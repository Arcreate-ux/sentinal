"""
SENTINEL — Slim Orchestrator (brain/orchestrator.py)

Dispatcher pattern:
  1. State machine handles in-progress conversations (awaiting_*)
  2. AI classifies intent for free-text messages
  3. Known system flows get dedicated handlers
  4. Everything else goes to the dynamic agent with full context
"""

import json
import logging
from typing import Callable, Awaitable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

_IST = ZoneInfo("Asia/Kolkata")

from sentinel.brain.study_blocks import StudyBlockEngine

logger = logging.getLogger("sentinel.brain.orchestrator")


def _state_supports(state, method_name: str) -> bool:
    return callable(getattr(type(state), method_name, None))


# ── AI Intent Classification ───────────────────────────────────────────────

class IntentClassification(BaseModel):
    model_config = {"extra": "forbid"}
    intent: str = Field(description="block_done, analyze_weakness, chapter_summary, or dynamic for anything else")
    confidence: float = Field(default=0.0)
    extracted_entities: dict = Field(default_factory=dict, description="Useful entities: chapter names, times, dates")


async def _classify_intent_ai(text: str, ai_engine) -> IntentClassification:
    """Classify message intent using AI. Falls back to 'dynamic' on any error."""
    prompt = (
        f"Analyze this student's message. Is it a core system flow (block_done, analyze_weakness, chapter_summary) "
        f"or something else entirely? Message: '{text}'\n"
        f"Output strictly valid JSON matching this schema: {IntentClassification.model_json_schema()}"
    )
    try:
        raw = await ai_engine.call("fast", prompt)
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        return IntentClassification.model_validate_json(raw)
    except Exception:
        return IntentClassification(intent="dynamic", confidence=0.0)


class Orchestrator:
    def __init__(self, state_db, context_builder, memory_engine, parser,
                 action_planner, executor, reflection_engine, knowledge_engine,
                 analyzer, notion_client, personal_memory=None, ai_engine=None):
        self.state = state_db
        self.context = context_builder
        self.memory = memory_engine
        self.parser = parser
        self.action_planner = action_planner
        self.executor = executor
        self.reflection_engine = reflection_engine
        self.knowledge_engine = knowledge_engine
        self.analyzer = analyzer
        self.notion = notion_client
        self.personal_memory = personal_memory
        self.ai = ai_engine

    async def handle(self, message: str, reply_callback: Callable[[str], Awaitable[None]], context_obj=None) -> None:
        """Main entry point. State machine → AI intent → handler dispatch."""
        text = message.strip()
        if not text:
            return

        state_key = await self.state.get_state("conversation_state")

        try:
            # ── State machine first ────────────────────────────────────────
            if state_key == "onboarding":
                return await self._route_onboarding(text, reply_callback)
            if state_key and state_key.startswith("awaiting_"):
                return await self._handle_state(state_key, text, reply_callback, context_obj)

            # ── AI intent classification ───────────────────────────────────
            classification = await _classify_intent_ai(text, self.ai)
            intent = classification.intent
            logger.debug("Intent: %s (conf=%.2f) for: %s", intent, classification.confidence, text[:50])

            # ── Dispatch to handler ────────────────────────────────────────
            handler = getattr(self, f"_handle_{intent}", self._handle_dynamic)
            await handler(text, reply_callback, context_obj)

        except Exception as e:
            logger.error(f"Orchestrator error: {e}", exc_info=True)
            await reply_callback("⚠️ An error occurred while processing your message.")

    # ── Routing helpers ────────────────────────────────────────────────────

    async def _route_onboarding(self, text, reply):
        from sentinel.brain.onboarding import OnboardingEngine
        onboarding = OnboardingEngine(self.state)
        response = await onboarding.handle_step(text)
        await reply(response)

    async def _handle_state(self, state_key, text, reply, context_obj):
        handlers = {
            "awaiting_block_report": lambda: self._handle_block_report(text, reply, context_obj),
            "awaiting_done_block_selection": lambda: self._handle_done_block_selection(text, reply),
            "awaiting_done_reflection": lambda: self._handle_done_reflection(text, reply),
            "awaiting_homework": lambda: self._handle_homework_input(text, reply),
            "awaiting_done_followup": lambda: self._handle_done_followup(text, reply, context_obj),
        }
        handler = handlers.get(state_key)
        if handler:
            await handler()

    # ── Known system flow handlers (≤30 lines each) ────────────────────────

    async def _handle_block_done(self, text, reply, context_obj):
        """Parse block completion report → confirm flow."""
        result = await self.parser.parse_performance_report(text)
        if result and result.attempted and result.time_taken:
            await self.state.set_state("conversation_state", "confirming_report")
            await self.state.set_state("pending_report", result.model_dump_json())
            await reply(f"📋 Confirm: {result.subject or '?'} {result.exercise_type or '?'} — "
                        f"{result.attempted}A/{result.correct}C/{result.time_taken}m?\nReply 'yes'.")
        else:
            await reply("🤔 Couldn't parse. Try:\n• done EB-1 18/20 45 min\n• A=15 C=12 T=50")

    async def _handle_analyze_weakness(self, text, reply, context_obj):
        """Pull 6-month deep data, AI gives brutal diagnosis."""
        await reply("📊 Pulling your full history...")
        try:
            data = await self.analyzer.get_weak_points_deep(months=6)
            from sentinel.brain.prompts import SYSTEM_PROMPT_COMPETITIVE_RIVAL
            prompt = (
                f"Student asked: '{text}'\n\n"
                f"REAL data ({data['total_blocks_analyzed']} blocks, {data['period_months']} months):\n"
                f"Subject accuracy: {json.dumps(data['subject_accuracy'])}\n"
                f"Weakest exercise types: {json.dumps(data['weakest_exercise_types'])}\n"
                f"Chapters with most errors: {json.dumps(data['weakest_chapters'])}\n"
                f"Recurring unresolved: {json.dumps(data['recurring_unresolved_concepts'])}\n"
                f"Give brutal, specific diagnosis with 3 concrete actions for next 7 days."
            )
            res = await self.analyzer.ai.call("general_chat", prompt,
                                              system_prompt=SYSTEM_PROMPT_COMPETITIVE_RIVAL, max_tokens=600)
            await reply(res)
        except Exception as e:
            logger.error("Weak points analysis failed: %s", e)
            await reply("⚠️ Failed to run deep analysis.")

    async def _handle_chapter_summary(self, text, reply, context_obj):
        """Aggregate chapter data → AI summary."""
        chapter_name = text.lower().replace("chapter", "").strip()
        if not chapter_name:
            await reply("Usage: chapter <chapter_name>")
            return
        if self.reflection_engine:
            summary = await self.reflection_engine.generate_chapter_summary(chapter_name)
            await reply(summary)
        else:
            await reply("⚠️ Reflection engine not available.")

    # ── Dynamic agent (catch-all for everything else) ───────────────────────

    async def _handle_dynamic(self, text, reply, context_obj):
        """Full-context AI agent for rescheduling, queries, chat, and anything unknown."""
        # Short/simple messages get a fast reply, no AI
        if len(text) < 20 and "?" not in text:
            quick = {"hi", "hello", "hey", "ok", "thanks", "yes", "no", "sure", "yep", "nope"}
            if text.lower().strip() in quick:
                await reply("⚡ Back to work.")
                return

        # Doubt detection gate — refuse to solve faculty material
        if self.ai and await self._is_faculty_doubt(text):
            return await self._log_doubt_and_refuse(text, reply)

        # Full context AI call
        await self._call_dynamic_agent(text, reply)

    async def _is_faculty_doubt(self, text) -> bool:
        """Quick AI check: is this a physics/chem/math doubt?"""
        if not self.ai:
            return False
        try:
            from sentinel.brain.prompts import DOUBT_DETECTION_PROMPT
            res = await self.ai.call("fast", DOUBT_DETECTION_PROMPT.format(text=text),
                                     max_tokens=5, temperature=0.0)
            return res.strip().upper().startswith("YES")
        except Exception:
            return False

    async def _log_doubt_and_refuse(self, text, reply):
        """Log doubt to faculty list and refuse to solve."""
        try:
            await self.state.upsert_concept_asset({
                "concept_name": text[:120], "subject": "Unknown", "chapter": "Unknown",
                "resolved": False, "failure_type": "faculty_doubt",
                "revisions": [], "current_understanding": "Needs faculty clarification",
                "linked_questions": [],
            })
        except Exception:
            pass
        await reply("❌ Not my job. Your faculty solves doubts.\n📋 Logged to /faculty list.\nGo back to work.")

    async def _call_dynamic_agent(self, text, reply):
        """Call AI with full student context for dynamic requests."""
        if not self.ai:
            await reply("⚠️ AI not available.")
            return
        try:
            ctx = await self._build_student_context()
            from sentinel.brain.prompts import SYSTEM_PROMPT_COMPETITIVE_RIVAL
            prompt = f"CONTEXT:\n{ctx}\n\nSTUDENT MESSAGE: {text}"
            response = await self.ai.call("general_chat", prompt,
                                          system_prompt=SYSTEM_PROMPT_COMPETITIVE_RIVAL,
                                          max_tokens=400, temperature=0.5)
            await reply(response.strip())
        except Exception as e:
            logger.error("Dynamic agent failed: %s", e)
            await reply("⚠️ Couldn't process that right now.")

    async def _build_student_context(self) -> str:
        """Assemble full student context for the dynamic agent."""
        parts = []
        now_str = datetime.now(_IST).strftime("%Y-%m-%d %H:%M %Z")
        parts.append(f"DATE/TIME: {now_str}")

        if self.personal_memory:
            try:
                mem = await self.personal_memory.get_context_for_ai("")
                profile = mem.get("student_profile", {})
                if profile:
                    parts.append(f"Student: {profile.get('name', '?')}")
                    parts.append(f"Faculty: {json.dumps(profile.get('faculty', {}))}")
            except Exception:
                pass

        yesterday = (datetime.now(_IST) - timedelta(days=1)).strftime("%Y-%m-%d")
        try:
            ys = await self.state.get_daily_summary(yesterday)
            if ys:
                parts.append(f"Yesterday CY: {ys.get('total_cy', 'N/A')}")
        except Exception:
            pass

        try:
            raw_plan = await self.state.get_state("current_plan")
            if raw_plan:
                from sentinel.brain.contracts import PlanningResult
                r = PlanningResult.model_validate_json(raw_plan)
                blocks_str = ", ".join(f"{b.block_label}({b.subject})" for b in r.plan.blocks)
                parts.append(f"Today plan: {blocks_str}")
        except Exception:
            pass

        try:
            unresolved = await self.state.get_unresolved_concepts()
            if unresolved:
                parts.append(f"Open doubts: {len(unresolved)}")
        except Exception:
            pass

        return "\n".join(parts) if parts else "No context available."

    # ── State machine handlers ─────────────────────────────────────────────

    async def _handle_block_report(self, text, reply, context_obj):
        if text.lower() in ("yes", "y", "confirm", "ok"):
            raw = await self.state.get_state("pending_report")
            if raw:
                from sentinel.bot.schemas import PerformanceReport
                return await self._log_block_result(PerformanceReport.model_validate_json(raw), reply, context_obj)
        result = await self.parser.parse_performance_report(text)
        if not result:
            await reply("🤔 Couldn't parse. Try: A=15 C=12 T=50")
            return
        await self.state.set_state("pending_report", result.model_dump_json())
        await self.state.set_state("conversation_state", "confirming_report")
        await reply(f"📋 Confirm: {result.subject or '?'} {result.exercise_type or '?'} — "
                    f"{result.attempted}A/{result.correct}C/{result.time_taken}m?\nReply 'yes'.")

    async def _handle_homework_input(self, text, reply):
        parsed = await self.parser.parse_homework(text)
        if not parsed:
            await reply("⚠️ Couldn't parse. Try: Physics Ch.5 Ex2A Q1-20")
            return
        existing_raw = await self.state.get_state("homework_pending")
        existing = json.loads(existing_raw) if existing_raw else []
        existing.extend(hw.model_dump() if hasattr(hw, "model_dump") else dict(hw) for hw in parsed)
        await self.state.set_state("homework_pending", json.dumps(existing))
        await self.state.set_state("conversation_state", "default")
        lines = ["✅ Homework added:"] + [f"  • {hw.subject}: {hw.exercise_type} ({hw.questions}Q)" for hw in parsed]
        await reply("\n".join(lines))

    async def _handle_done_block_selection(self, text, reply):
        today = datetime.now(_IST).strftime("%Y-%m-%d")
        block = None
        if _state_supports(self.state, "get_study_block_by_identifier"):
            block = await self.state.get_study_block_by_identifier(text.strip(), today)
        if not block:
            blocks = await self._planned_blocks(today)
            block = StudyBlockEngine.find_block(blocks, text.strip())
        if not block:
            await reply("Couldn't find that block. Reply with number, label, or block_id.")
            return
        if str(block.get("status", "")).upper() == "COMPLETED":
            await self.state.set_state("conversation_state", "default")
            await reply(f"{block.get('block_label', '?')} is already completed.")
            return
        await self.state.set_state("pending_done_block", json.dumps(block))
        await self.state.set_state("conversation_state", "awaiting_done_reflection")
        await reply(StudyBlockEngine.prompt_for_block(block))

    async def _handle_done_reflection(self, text, reply):
        raw_block = await self.state.get_state("pending_done_block")
        if not raw_block:
            await self.state.set_state("conversation_state", "default")
            await reply("Session expired. Use /done again.")
            return
        block_data = json.loads(raw_block)
        history = await self._get_history_context(block_data.get("subject"))
        parsed = await self.reflection_engine.process_block_reflection(block_data, history, text)
        if parsed.get("error"):
            await reply(f"Failed to parse: {parsed['error']}")
            return
        if parsed.get("needs_followup") and parsed.get("followup_question"):
            await self.state.set_state("conversation_state", "awaiting_done_followup")
            await self.state.set_state("pending_done_data", json.dumps(parsed.get("parsed_data", {})))
            await self.state.set_state("pending_done_insight", parsed.get("historical_insight", ""))
            await reply(f"🤔 {parsed['followup_question']}")
            return
        await self._finalize_done_data(block_data, parsed.get("parsed_data", {}),
                                       parsed.get("historical_insight", ""), reply)

    async def _handle_done_followup(self, text, reply, context_obj):
        raw_data = await self.state.get_state("pending_done_data")
        if not raw_data:
            await self.state.set_state("conversation_state", "idle")
            await reply("Session expired. Use /done again.")
            return
        parsed_data = json.loads(raw_data)
        parsed_data.setdefault("faculty_concepts", []).append(f"Follow-up: {text}")
        insight = await self.state.get_state("pending_done_insight") or ""
        await self.state.set_state("conversation_state", "idle")
        await self.state.set_state("pending_done_data", "")
        raw_block = await self.state.get_state("pending_done_block")
        if raw_block:
            await self._finalize_done_data(json.loads(raw_block), parsed_data, insight, reply)
        else:
            await reply("✅ Follow-up logged.")

    # ── Core helpers ───────────────────────────────────────────────────────

    async def _get_history_context(self, subject):
        if not _state_supports(self.state, "get_unresolved_concepts"):
            return []
        unresolved = await self.state.get_unresolved_concepts(subject=subject)
        return [{"concept": c.get("concept_name"), "questions": c.get("linked_questions", []),
                 "understanding": c.get("current_understanding", "")} for c in (unresolved or [])[-5:]]

    async def _planned_blocks(self, today):
        if _state_supports(self.state, "get_study_blocks"):
            blocks = await self.state.get_study_blocks(today)
            if blocks:
                return blocks
        raw = await self.state.get_state("current_plan")
        if not raw:
            return []
        try:
            from sentinel.brain.contracts import PlanningResult
            result = PlanningResult.model_validate_json(raw)
            return [StudyBlockEngine.normalize_block(b, today, i + 1).model_dump()
                    for i, b in enumerate(result.plan.blocks)]
        except Exception:
            return []

    async def _finalize_done_data(self, block_data, parsed_data, insight, reply):
        """Compute CY → save DB → revision tracking → Notion → advance index."""
        from sentinel.notion_client.formulas import cognitive_yield

        today = datetime.now(_IST).strftime("%Y-%m-%d")
        A = parsed_data.get("attempted", 0)
        C = parsed_data.get("correct", 0)
        T = parsed_data.get("time_taken") or block_data.get("target_time", 0)
        cy = cognitive_yield(T=T, A=A, C=C,
                             exercise_type=block_data.get("exercise_type", "Ex 1A"),
                             subject=block_data.get("subject", "Physics"))
        block_data.update({"status": "COMPLETED", "attempted": A, "correct": C,
                           "T": T, "A": A, "C": C, "actual_cy": cy})

        if _state_supports(self.state, "complete_study_block") and block_data.get("block_id"):
            t = await self.state.complete_study_block(block_data["block_id"], block_data)
            if t.get("duplicate"):
                await self.state.set_state("conversation_state", "default")
                await reply(f"Duplicate ignored: {block_data.get('block_label', '?')}")
                return

        await self.state.save_completed_block(today, block_data)
        await self._update_revision_tracking(block_data, parsed_data)
        await self._sync_to_notion(block_data, parsed_data, cy, today)
        await self._advance_block_index(reply, block_data, cy, A, C, insight)

    async def _update_revision_tracking(self, block_data, parsed_data):
        try:
            for concept in parsed_data.get("recurring_mistakes", []):
                if hasattr(self.state, "increment_revision_count"):
                    await self.state.increment_revision_count(block_data.get("subject", ""), concept)
            errors = parsed_data.get("errors", [])
            if errors:
                raw = await self.state.get_state("circled_questions")
                circled = json.loads(raw) if raw else []
                for err in errors[:3]:
                    circled.append({"subject": block_data.get("subject", ""),
                                    "chapter": block_data.get("chapter", "?"), "error": err})
                await self.state.set_state("circled_questions", json.dumps(circled[-20:]))
        except Exception:
            logger.debug("Revision tracking failed (non-fatal)", exc_info=True)

    async def _sync_to_notion(self, block_data, parsed_data, cy, today):
        if not self.notion:
            return
        try:
            A = parsed_data.get("attempted", 0)
            C = parsed_data.get("correct", 0)
            T = parsed_data.get("time_taken") or block_data.get("target_time", 0)
            await self.notion.create_db1_row(
                task_name=f"{block_data.get('block_label', '?')}: {block_data.get('subject', '?')} {block_data.get('exercise_type', '?')}",
                subject=block_data.get("subject", "Physics"),
                exercise_type=block_data.get("exercise_type", "Ex 1A"),
                time_taken=T, attempted=A, correct=C,
                block=block_data.get("block_label", "Block"), date_str=today,
            )
            await self.notion.update_db2_db3(
                {"attempted": A, "correct": C, "subject": block_data.get("subject", "?"),
                 "exercise_type": block_data.get("exercise_type", "?")},
                assets=[], conceptual_mistake=False,
            )
        except Exception:
            logger.warning("Notion sync failed", exc_info=True)

    async def _advance_block_index(self, reply, block_data, cy, A, C, insight):
        idx_raw = await self.state.get_state("current_block_index")
        idx = int(idx_raw) if idx_raw else 0
        await self.state.set_state("current_block_index", str(idx + 1))
        await self.state.set_state("pending_done_block", "")
        await self.state.set_state("conversation_state", "default")
        insight_msg = f"\n💡 {insight}\n" if insight else ""
        await reply(f"✅ Block Complete: {block_data.get('block_label', '?')}\n"
                    f"Stats: {C}/{A} correct. CY: {cy}{insight_msg}")

    async def _log_block_result(self, report, reply, context_obj):
        from sentinel.notion_client.formulas import cognitive_yield
        A, C, T = report.attempted, report.correct, report.time_taken
        subject = report.subject or "Physics"
        ex_type = report.exercise_type or "Ex 1A"
        today = datetime.now(_IST).strftime("%Y-%m-%d")
        idx_raw = await self.state.get_state("current_block_index")
        idx = int(idx_raw) if idx_raw else 0
        cy = cognitive_yield(T, A, C, ex_type, subject)
        block_entry = {"status": "COMPLETED", "actual_cy": cy, "T": T, "A": A, "C": C,
                       "subject": subject, "exercise_type": ex_type, "block_label": f"Block-{idx+1}"}
        await self.state.save_completed_block(today, block_entry)
        await self.state.set_state("current_block_index", str(idx + 1))
        await self.state.set_state("conversation_state", "default")
        await self.state.set_state("pending_report", "")
        await reply(f"✅ Logged. CY: {cy}")
