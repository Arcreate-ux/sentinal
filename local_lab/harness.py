from __future__ import annotations

import json
import os
import re
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable

from sentinel.bot.commands import COMMANDS, cmd_doubts
from sentinel.bot.parsers import MessageParser
from sentinel.brain.action_planner import ActionPlanner
from sentinel.brain.analyzer import PerformanceAnalyzer
from sentinel.brain.executor import ActionExecutor
from sentinel.brain.orchestrator import Orchestrator
from sentinel.brain.planner import DailyPlanner
from sentinel.brain.reflection_engine import ReflectionEngine
from sentinel.config import DAILY_CY_TARGET
from sentinel.notion_client.formulas import cognitive_yield, theory_yield

from local_lab.fake_services import (
    AuditLogger,
    FakeContext,
    FakeStateDB,
    FakeUpdate,
    LocalAIEngine,
    LocalHealthMonitor,
    LocalKnowledgeEngine,
    LocalNotionClient,
    LocalRoaster,
    local_today,
)
from local_lab.simulation import SimulationEngine


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUNTIME_DIR = PROJECT_ROOT / "local_lab" / "runtime"


class LocalSentinelHarness:
    """Telegram-like local harness that never touches production services."""

    def __init__(self, runtime_dir: Path | None = None) -> None:
        self.runtime_dir = runtime_dir or DEFAULT_RUNTIME_DIR
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.audit = AuditLogger(self.runtime_dir)
        self.state = FakeStateDB(self.runtime_dir, self.audit)
        self.notion = LocalNotionClient(self.runtime_dir, self.audit)
        self.ai = LocalAIEngine(self.audit, self.state)
        self.parser = MessageParser(self.ai)
        self.health = LocalHealthMonitor(self.ai, self.notion, self.state)
        self.planner = DailyPlanner(self.ai, self.notion, self.state)
        self.analyzer = PerformanceAnalyzer(self.ai, self.notion, self.state)
        self.roaster = LocalRoaster(self.state, self.audit)
        self.analyzer.roaster = self.roaster
        self.reflection_engine = ReflectionEngine(self.ai, self.state, self.notion)
        self.knowledge_engine = LocalKnowledgeEngine(self.ai, self.state, self.notion, self.audit)
        self.action_planner = ActionPlanner(self.ai, self.state, self.notion)
        self.executor = ActionExecutor(self.ai, self.notion, self.state)
        self.orchestrator = Orchestrator(
            state_db=self.state,
            context_builder=None,
            memory_engine=None,
            parser=self.parser,
            action_planner=self.action_planner,
            executor=self.executor,
            reflection_engine=self.reflection_engine,
            knowledge_engine=self.knowledge_engine,
            analyzer=self.analyzer,
            notion_client=self.notion,
        )
        self.command_handlers = {handler.__name__[4:]: handler for handler in COMMANDS}
        self.bot_data = {
            "planner": self.planner,
            "analyzer": self.analyzer,
            "roaster": self.roaster,
            "parser": self.parser,
            "notion": self.notion,
            "state_db": self.state,
            "health": self.health,
            "scheduler": None,
            "reflection_engine": self.reflection_engine,
            "knowledge_engine": self.knowledge_engine,
            "bot_ref": None,
        }

    async def init(self) -> None:
        await self.state.init_db()
        self.audit.log(
            "local_lab.ready",
            runtime_dir=str(self.runtime_dir),
            fake_database_ids={key: value["local_database_id"] for key, value in self.notion.schemas.items()},
        )

    async def handle_message(self, text: str) -> dict[str, Any]:
        text = text.strip()
        if not text:
            return self._response([], note="empty")

        await self.state.save_chat_message("user", text)
        self.audit.log("chat.incoming", text=text)

        replies: list[str] = []
        lower = text.lower()
        if lower.startswith("/start"):
            await self.state.set_state("chat_id", "local-chat")
            replies.append(
                "SENTINEL LOCAL LAB ONLINE\n"
                "Real Notion, MongoDB, Telegram, and AI providers are disabled.\n"
                "Use /plan, /homework, /done, /doubts, /status, /night, or /simulate 30."
            )
        elif lower.startswith("/night"):
            replies.append(await self.run_night_cycle())
        elif lower.startswith("/db"):
            replies.append(self.format_fake_db_summary())
        elif lower.startswith("/audit"):
            replies.append(self.format_audit_tail())
        elif lower.startswith("/simulate"):
            replies.append(await self.simulate_days(self._parse_days(text, default=14)))
        elif "days left" in lower and "jee" in lower:
            replies.append(self.days_left_for_jee())
        elif "list" in lower and "doubt" in lower:
            replies.extend(await self._run_command("/doubts"))
        elif text.startswith("/"):
            replies.extend(await self._run_command(text))
        else:
            replies.extend(await self._run_orchestrator(text))

        for reply in replies:
            await self.state.save_chat_message("assistant", reply)
        self.audit.log("chat.outgoing", reply_count=len(replies), replies=[reply[:500] for reply in replies])
        return self._response(replies)

    async def _run_command(self, text: str) -> list[str]:
        cmd, args_text = self.parser.parse_command(text)
        handler = self.command_handlers.get(cmd)
        replies: list[str] = []
        if not handler:
            return [f"Unknown local command: /{cmd}. Try /help."]
        update = FakeUpdate(text, replies)
        context = FakeContext(self.bot_data, args=args_text.split() if args_text else [])
        self.audit.log("command.dispatch", command=cmd, args=args_text)
        await handler(update, context)
        return replies

    async def _run_orchestrator(self, text: str) -> list[str]:
        replies: list[str] = []
        update = FakeUpdate(text, replies)
        context = FakeContext(self.bot_data)

        async def reply_callback(message: str) -> None:
            replies.append(message)

        await self.orchestrator.handle(text, reply_callback, {"update": update, "context": context})
        return replies

    async def run_night_cycle(self) -> str:
        today = local_today()
        completed = await self.state.get_today_blocks(today)
        skipped_raw = await self.state.get_state("blocks_skipped_today")
        skipped = int(skipped_raw) if skipped_raw else 0
        totals = {
            "total_cy": 0,
            "physics_cy": 0,
            "physics_ty": 0,
            "chem_cy": 0,
            "chem_ty": 0,
            "maths_cy": 0,
            "maths_ty": 0,
        }
        subject_counts = {"physics": 0, "chem": 0, "maths": 0}
        for block in completed:
            if str(block.get("status", "")).upper() == "SKIPPED":
                continue
            subject = block.get("subject", "Physics")
            ex_type = block.get("exercise_type", "Ex 1A")
            attempted = int(block.get("A") or block.get("attempted") or 0)
            correct = int(block.get("C") or block.get("correct") or 0)
            time_taken = float(block.get("T") or block.get("time_taken") or 0)
            cy = float(block.get("actual_cy") or cognitive_yield(time_taken, attempted, correct, ex_type, subject))
            ty = float(theory_yield(time_taken, attempted, correct, ex_type, subject)) if attempted else 0
            prefix = "chem" if subject.lower().startswith("chem") else subject.lower()
            if prefix not in subject_counts:
                prefix = "physics"
            totals["total_cy"] += cy
            totals[f"{prefix}_cy"] += cy
            totals[f"{prefix}_ty"] += ty
            subject_counts[prefix] += 1
        for prefix, count in subject_counts.items():
            if count:
                totals[f"{prefix}_ty"] = round(totals[f"{prefix}_ty"] / count, 1)

        blocks_done = sum(1 for block in completed if str(block.get("status", "")).upper() != "SKIPPED")
        day_type = await self.state.get_state("day_type") or "self_study"
        await self.state.save_daily_summary(
            target_date=today,
            total_cy=totals["total_cy"],
            physics_cy=totals["physics_cy"],
            physics_ty=totals["physics_ty"],
            chem_cy=totals["chem_cy"],
            chem_ty=totals["chem_ty"],
            maths_cy=totals["maths_cy"],
            maths_ty=totals["maths_ty"],
            blocks_completed=blocks_done,
            blocks_skipped=skipped,
            day_type=day_type,
        )
        if totals["total_cy"] >= DAILY_CY_TARGET:
            await self.state.update_streak("daily_target", today)
        summary = await self.analyzer.generate_daily_summary(today)
        reflection = await self.reflection_engine.run_evening_reflection(today)
        await self.notion.create_db4_row(
            action_type="night_cycle",
            decision="Generated local night summary and reflection",
            reasoning=json.dumps(reflection)[:1000],
            data_snapshot=json.dumps({"date": today, "totals": totals}),
        )
        self.audit.log("night_cycle.completed", date=today, totals=totals, reflection=reflection)
        return f"{summary}\n\n🧠 Reflection: {json.dumps(reflection, indent=2)}"

    async def simulate_days(self, days: int) -> str:
        return await SimulationEngine(self).run(days)

    def days_left_for_jee(self) -> str:
        target_raw = os.environ.get("JEE_TARGET_DATE", "2028-05-21")
        try:
            target = date.fromisoformat(target_raw)
        except ValueError:
            target = date(2028, 5, 21)
        today = date.today()
        days = (target - today).days
        return (
            f"JEE target date configured: {target.isoformat()}.\n"
            f"Days left from {today.isoformat()}: {days}.\n"
            "Set JEE_TARGET_DATE to change this local countdown."
        )

    def format_fake_db_summary(self) -> str:
        counts = self.notion.counts()
        schema_lines = [
            f"{key.upper()} {schema['title']}: {counts.get(key, 0)} rows, {len(schema['properties'])} properties"
            for key, schema in self.notion.schemas.items()
        ]
        mongo_counts = {
            key: len(value) if isinstance(value, list) else len(value)
            for key, value in self.state.data.items()
        }
        mongo_lines = [
            f"{key}: {mongo_counts[key]}"
            for key in (
                "study_blocks",
                "learning_events",
                "concept_assets",
                "timeline",
                "planner_decisions",
                "recovery_history",
                "faculty_history",
                "prediction_history",
            )
        ]
        return "📦 LOCAL FAKE DATABASES\n" + "\n".join(schema_lines) + "\n\nFake Mongo:\n" + "\n".join(mongo_lines)

    def format_audit_tail(self, limit: int = 12) -> str:
        events = self.audit.tail(limit)
        if not events:
            return "Audit log is empty."
        lines = ["🧾 AUDIT TAIL"]
        for event in events:
            lines.append(f"- {event['timestamp']} {event['event_type']}")
        return "\n".join(lines)

    def state_snapshot(self) -> dict[str, Any]:
        return {
            "fake_db_counts": self.notion.counts(),
            "schemas": {
                key: {
                    "title": schema["title"],
                    "local_database_id": schema["local_database_id"],
                    "source_database_id": schema["source_database_id"],
                    "property_count": len(schema["properties"]),
                    "properties": list(schema["properties"]),
                }
                for key, schema in self.notion.schemas.items()
            },
            "recent_chat": self.state.data["chat_history"][-20:],
            "study_blocks_today": self.state.data.get("study_blocks", [])[-8:],
            "learning_confidence": self.state.data.get("learning_model", {}).get("confidence_level", {}),
            "audit_tail": self.audit.tail(40),
            "runtime_dir": str(self.runtime_dir),
        }

    def export_fake_notion(self) -> dict[str, Any]:
        return self.notion.export()

    def reset(self) -> None:
        if self.runtime_dir.exists():
            shutil.rmtree(self.runtime_dir)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.__init__(self.runtime_dir)

    def _response(self, replies: list[str], note: str = "ok") -> dict[str, Any]:
        return {
            "note": note,
            "replies": replies,
            "state": self.state_snapshot(),
        }

    @staticmethod
    def _parse_days(text: str, default: int) -> int:
        match = re.search(r"\b(\d{1,3})\b", text)
        if not match:
            return default
        return int(match.group(1))
