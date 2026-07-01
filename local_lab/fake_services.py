from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from sentinel import config
from sentinel.brain.study_blocks import StudyBlockEngine
from sentinel.notion_client.formulas import cognitive_yield, theory_yield

from local_lab.schema_snapshot import get_schema_snapshot


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def local_today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


class AuditLogger:
    def __init__(self, runtime_dir: Path) -> None:
        self.runtime_dir = runtime_dir
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.path = runtime_dir / "audit.jsonl"

    def log(self, event_type: str, **payload: Any) -> dict[str, Any]:
        event = {
            "event_id": str(uuid.uuid4()),
            "timestamp": utc_now(),
            "event_type": event_type,
            **payload,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        return event

    def tail(self, limit: int = 80) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()[-limit:]
        events = []
        for line in lines:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return events

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


class FakeStateDB:
    """JSON-backed async stand-in for StateDB.

    The layout is intentionally close to the Mongo collections used by the real
    app, but every write stays under local_lab/runtime.
    """

    def __init__(self, runtime_dir: Path, audit: AuditLogger) -> None:
        self.path = runtime_dir / "fake_state.json"
        self.audit = audit
        self.data = _read_json(
            self.path,
            {
                "system_state": {},
                "completed_blocks": [],
                "daily_summary": [],
                "test_scores": [],
                "api_health": {},
                "streaks": {},
                "chat_history": [],
                "learning_events": [],
                "concept_assets": [],
                "archived_questions": [],
                "skill_assets": [],
                "recommendation_history": [],
                "study_blocks": [],
                "learning_model": {},
                "experience_rules": [],
                "timeline": [],
                "recovery_history": [],
                "faculty_history": [],
                "prediction_history": [],
                "planner_decisions": [],
                "snapshots": [],
            },
        )
        for key, default in {
            "system_state": {},
            "completed_blocks": [],
            "daily_summary": [],
            "test_scores": [],
            "api_health": {},
            "streaks": {},
            "chat_history": [],
            "learning_events": [],
            "concept_assets": [],
            "archived_questions": [],
            "skill_assets": [],
            "recommendation_history": [],
            "study_blocks": [],
            "learning_model": {},
            "experience_rules": [],
            "timeline": [],
            "recovery_history": [],
            "faculty_history": [],
            "prediction_history": [],
            "planner_decisions": [],
            "snapshots": [],
        }.items():
            self.data.setdefault(key, default)

    async def init_db(self) -> None:
        self._save()
        self.audit.log("state.init", database="fake_state", path=str(self.path))

    def close(self) -> None:
        self._save()

    def _save(self) -> None:
        _write_json(self.path, self.data)

    async def get_state(self, key: str, default: str | None = None) -> str | None:
        if key == "completed_blocks":
            raise ValueError("Access to raw completed_blocks is prohibited in local lab too.")
        value = self.data["system_state"].get(key, {}).get("value", default)
        self.audit.log("state.get", key=key, hit=key in self.data["system_state"])
        return value

    async def set_state(self, key: str, value: str) -> None:
        if key == "completed_blocks":
            raise ValueError("Writing raw completed_blocks is prohibited in local lab too.")
        self.data["system_state"][key] = {"value": value, "updated_at": utc_now()}
        self._save()
        self.audit.log("state.set", key=key, value_preview=str(value)[:240])

    async def delete_state(self, key: str) -> None:
        self.data["system_state"].pop(key, None)
        self._save()
        self.audit.log("state.delete", key=key)

    async def save_completed_block(self, target_date: str, block_data: dict[str, Any]) -> None:
        block = dict(block_data)
        block["date"] = target_date
        block["saved_at"] = utc_now()
        self.data["completed_blocks"].append(block)
        counter = f"completed_count:{target_date}"
        current = int(self.data["system_state"].get(counter, {}).get("value", 0))
        self.data["system_state"][counter] = {"value": str(current + 1), "updated_at": utc_now()}
        self._save()
        self.audit.log(
            "state.completed_block.saved",
            date=target_date,
            subject=block.get("subject"),
            block_label=block.get("block_label"),
            actual_cy=block.get("actual_cy"),
        )
        await self.record_timeline_event(
            "completed_block.saved",
            {
                "date": target_date,
                "block_id": block.get("block_id"),
                "label": block.get("label") or block.get("block_label"),
                "subject": block.get("subject"),
                "actual_cy": block.get("actual_cy"),
            },
        )

    async def get_today_blocks(self, target_date: str) -> list[dict[str, Any]]:
        blocks = [dict(b) for b in self.data["completed_blocks"] if b.get("date") == target_date]
        self.audit.log("state.completed_block.read_today", date=target_date, count=len(blocks))
        return blocks

    async def get_blocks_range(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        rows = [
            dict(b)
            for b in self.data["completed_blocks"]
            if start_date <= b.get("date", "") <= end_date
        ]
        rows.sort(key=lambda row: row.get("date", ""))
        self.audit.log("state.completed_block.read_range", start_date=start_date, end_date=end_date, count=len(rows))
        return rows

    async def save_daily_summary(
        self,
        target_date: str,
        total_cy: float,
        physics_cy: float,
        physics_ty: float,
        chem_cy: float,
        chem_ty: float,
        maths_cy: float,
        maths_ty: float,
        blocks_completed: int,
        blocks_skipped: int,
        day_type: str = "normal",
    ) -> None:
        doc = {
            "date": target_date,
            "total_cy": total_cy,
            "physics_cy": physics_cy,
            "physics_ty": physics_ty,
            "chem_cy": chem_cy,
            "chem_ty": chem_ty,
            "maths_cy": maths_cy,
            "maths_ty": maths_ty,
            "blocks_completed": blocks_completed,
            "blocks_skipped": blocks_skipped,
            "day_type": day_type,
            "updated_at": utc_now(),
        }
        self.data["daily_summary"] = [d for d in self.data["daily_summary"] if d.get("date") != target_date]
        self.data["daily_summary"].append(doc)
        self._save()
        self.audit.log("state.daily_summary.saved", date=target_date, total_cy=total_cy)
        await self.record_timeline_event(
            "daily_summary.saved",
            {
                "date": target_date,
                "total_cy": total_cy,
                "blocks_completed": blocks_completed,
                "blocks_skipped": blocks_skipped,
                "day_type": day_type,
            },
        )
        await self.get_learning_confidence_level()

    async def get_daily_summary(self, target_date: str) -> dict[str, Any] | None:
        for row in self.data["daily_summary"]:
            if row.get("date") == target_date:
                return dict(row)
        return None

    async def get_summaries_range(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        rows = [dict(d) for d in self.data["daily_summary"] if start_date <= d.get("date", "") <= end_date]
        rows.sort(key=lambda row: row.get("date", ""))
        return rows

    async def save_test_score(
        self,
        test_date: str,
        p_score: float,
        p_total: float,
        c_score: float,
        c_total: float,
        m_score: float,
        m_total: float,
        notes: str = "",
    ) -> int:
        doc = {
            "id": len(self.data["test_scores"]) + 1,
            "date": test_date,
            "p_score": p_score,
            "p_total": p_total,
            "c_score": c_score,
            "c_total": c_total,
            "m_score": m_score,
            "m_total": m_total,
            "notes": notes,
            "created_at": utc_now(),
        }
        self.data["test_scores"].append(doc)
        self._save()
        self.audit.log("state.test_score.saved", date=test_date, total=p_score + c_score + m_score)
        return int(doc["id"])

    async def get_latest_test_score(self) -> dict[str, Any] | None:
        if not self.data["test_scores"]:
            return None
        return dict(sorted(self.data["test_scores"], key=lambda row: row.get("date", ""))[-1])

    async def get_test_scores_range(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        rows = [dict(d) for d in self.data["test_scores"] if start_date <= d.get("date", "") <= end_date]
        rows.sort(key=lambda row: row.get("date", ""))
        return rows

    async def update_api_health(self, provider: str, success: bool, latency_ms: float) -> None:
        row = self.data["api_health"].setdefault(
            provider,
            {"provider": provider, "success_count": 0, "failure_count": 0, "avg_latency_ms": 0, "total_calls": 0},
        )
        row["total_calls"] += 1
        row["success_count"] += 1 if success else 0
        row["failure_count"] += 0 if success else 1
        total = row["total_calls"]
        row["avg_latency_ms"] = round(((row["avg_latency_ms"] * (total - 1)) + latency_ms) / total, 2)
        row["updated_at"] = utc_now()
        self._save()

    async def get_healthy_providers(self) -> list[dict[str, Any]]:
        rows = []
        for row in self.data["api_health"].values():
            total = row.get("total_calls", 0)
            if not total:
                continue
            item = dict(row)
            item["success_rate"] = round(row.get("success_count", 0) / total, 3)
            rows.append(item)
        rows.sort(key=lambda row: (-row["success_rate"], row["avg_latency_ms"]))
        return rows

    async def update_streak(self, streak_type: str, target_date: str) -> dict[str, Any]:
        existing = self.data["streaks"].get(streak_type)
        if not existing:
            existing = {"streak_type": streak_type, "current_count": 1, "best_count": 1, "last_date": target_date}
        elif existing.get("last_date") != target_date:
            try:
                delta = (date.fromisoformat(target_date) - date.fromisoformat(existing.get("last_date", target_date))).days
            except ValueError:
                delta = 999
            existing["current_count"] = existing.get("current_count", 0) + 1 if delta == 1 else 1
            existing["best_count"] = max(existing.get("best_count", 0), existing["current_count"])
            existing["last_date"] = target_date
        existing["updated_at"] = utc_now()
        self.data["streaks"][streak_type] = existing
        self._save()
        self.audit.log("state.streak.updated", streak_type=streak_type, current_count=existing["current_count"])
        return dict(existing)

    async def get_streak(self, streak_type: str) -> dict[str, Any] | None:
        row = self.data["streaks"].get(streak_type)
        return dict(row) if row else None

    async def get_all_streaks(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.data["streaks"].values()]

    async def log_event(self, event_type: str, data: dict[str, Any], timestamp: str) -> None:
        self.audit.log(f"state.event.{event_type}", timestamp=timestamp, data=data)

    async def save_chat_message(self, role: str, content: str) -> None:
        self.data["chat_history"].append({"role": role, "content": content, "timestamp": utc_now()})
        self._save()

    async def get_recent_chat_history(self, limit: int = 10) -> list[dict[str, Any]]:
        return [dict(row) for row in self.data["chat_history"][-limit:]]

    async def get_db_stats(self) -> dict[str, Any]:
        return {
            "storage": "local_json",
            "collections": {key: len(value) if isinstance(value, list) else len(value) for key, value in self.data.items()},
            "path": str(self.path),
        }

    async def save_study_blocks(self, target_date: str, blocks: list[dict[str, Any]]) -> None:
        normalized = [
            StudyBlockEngine.normalize_block(block, target_date, idx + 1).model_dump()
            for idx, block in enumerate(blocks)
        ]
        existing_other_days = [block for block in self.data["study_blocks"] if block.get("date") != target_date]
        self.data["study_blocks"] = existing_other_days + normalized
        self._save()
        await self.record_timeline_event(
            "study_blocks.planned",
            {
                "date": target_date,
                "block_ids": [block["block_id"] for block in normalized],
                "count": len(normalized),
            },
        )
        self.audit.log("state.study_blocks.saved", date=target_date, count=len(normalized))

    async def get_study_blocks(self, target_date: str | None = None, include_completed: bool = True) -> list[dict[str, Any]]:
        rows = [dict(block) for block in self.data["study_blocks"]]
        if target_date:
            rows = [block for block in rows if block.get("date") == target_date]
        if not include_completed:
            rows = [block for block in rows if str(block.get("status", "")).upper() not in {"COMPLETED", "SKIPPED"}]
        rows.sort(key=lambda block: block.get("block_id", ""))
        self.audit.log("state.study_blocks.read", date=target_date, count=len(rows))
        return rows

    async def get_study_block_by_identifier(self, identifier: str, target_date: str | None = None) -> dict[str, Any] | None:
        blocks = await self.get_study_blocks(target_date=target_date)
        found = StudyBlockEngine.find_block(blocks, identifier)
        self.audit.log(
            "state.study_block.selected",
            identifier=identifier,
            date=target_date,
            found=bool(found),
            block_id=found.get("block_id") if found else None,
        )
        return dict(found) if found else None

    async def update_study_block(self, block_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        for idx, block in enumerate(self.data["study_blocks"]):
            if block.get("block_id") == block_id:
                updated = dict(block)
                updated.update(updates)
                updated["updated_at"] = utc_now()
                self.data["study_blocks"][idx] = updated
                self._save()
                await self.record_timeline_event(
                    "study_block.updated",
                    {
                        "block_id": block_id,
                        "status": updated.get("status"),
                        "updates": {key: updates.get(key) for key in sorted(updates)},
                    },
                )
                self.audit.log("state.study_block.updated", block_id=block_id, status=updated.get("status"))
                return dict(updated)
        self.audit.log("state.study_block.update_missed", block_id=block_id, updates=updates)
        return None

    async def complete_study_block(self, block_id: str, actual: dict[str, Any]) -> dict[str, Any]:
        block = next((row for row in self.data["study_blocks"] if row.get("block_id") == block_id), None)
        if not block:
            raise ValueError(f"Unknown study block: {block_id}")
        if str(block.get("status", "")).upper() == "COMPLETED":
            self.audit.log("state.study_block.duplicate_completion", block_id=block_id)
            return {"ok": False, "duplicate": True, "block": dict(block)}
        updates = dict(actual)
        updates["status"] = "COMPLETED"
        updated = await self.update_study_block(block_id, updates)
        return {"ok": True, "duplicate": False, "block": updated}

    async def skip_study_block(self, block_id: str, reason: str = "") -> dict[str, Any] | None:
        return await self.update_study_block(
            block_id,
            {
                "status": "SKIPPED",
                "skip_reason": reason,
                "actual_cy": 0,
            },
        )

    async def record_timeline_event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        event = {
            "event_id": str(uuid.uuid4()),
            "timestamp": utc_now(),
            "event_type": event_type,
            "payload": payload,
        }
        self.data["timeline"].append(event)
        self._save()
        self.audit.log("state.timeline.event", timeline_event_type=event_type, payload_preview=str(payload)[:500])
        return event

    async def save_planner_decision(self, decision: dict[str, Any]) -> None:
        row = dict(decision)
        row.setdefault("timestamp", utc_now())
        decision_id = row.get("decision_id")
        if decision_id:
            self.data["planner_decisions"] = [
                existing for existing in self.data["planner_decisions"]
                if existing.get("decision_id") != decision_id
            ]
        self.data["planner_decisions"].append(row)
        self._save()
        await self.record_timeline_event("planner.decision", row)

    async def get_planner_decision(self, decision_id: str) -> dict[str, Any] | None:
        row = next((row for row in self.data["planner_decisions"] if row.get("decision_id") == decision_id), None)
        return dict(row) if row else None

    async def get_latest_planner_decision_for_date(self, target_date: str) -> dict[str, Any] | None:
        rows = [row for row in self.data["planner_decisions"] if row.get("date") == target_date]
        if not rows:
            return None
        rows.sort(key=lambda row: row.get("timestamp", ""), reverse=True)
        return dict(rows[0])

    async def append_planner_actual(self, target_date: str, actual: dict[str, Any]) -> dict[str, Any] | None:
        actual_row = dict(actual)
        actual_row.setdefault("date", target_date)
        actual_row.setdefault("computed_at", utc_now())
        decision_id = actual_row.get("decision_id")

        index = None
        for idx, row in enumerate(self.data["planner_decisions"]):
            if decision_id and row.get("decision_id") == decision_id:
                index = idx
                break
        if index is None:
            dated = [
                (idx, row)
                for idx, row in enumerate(self.data["planner_decisions"])
                if row.get("date") == target_date
            ]
            if not dated:
                return None
            dated.sort(key=lambda item: item[1].get("timestamp", ""), reverse=True)
            index, row = dated[0]
            decision_id = row.get("decision_id")
            actual_row["decision_id"] = decision_id

        decision = self.data["planner_decisions"][index]
        error = self._compute_prediction_error(decision.get("prediction") or {}, actual_row)
        decision["actual"] = actual_row
        decision["prediction_error"] = error
        decision["actual_updated_at"] = utc_now()
        decision.setdefault("actual_history", []).append(actual_row)
        self._save()
        payload = {
            "decision_id": decision_id,
            "date": target_date,
            "actual": actual_row,
            "prediction_error": error,
        }
        await self.record_timeline_event("planner.actual_appended", payload)
        return payload

    async def save_daily_snapshot(self, snapshot: dict[str, Any]) -> None:
        row = dict(snapshot)
        row.setdefault("timestamp", utc_now())
        self.data["snapshots"] = [
            existing for existing in self.data["snapshots"]
            if existing.get("date") != row.get("date")
        ]
        self.data["snapshots"].append(row)
        self._save()
        await self.record_timeline_event("snapshot.daily", row)

    @staticmethod
    def _compute_prediction_error(prediction: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
        pairs = {
            "cy": ("expected_cy", "actual_cy"),
            "duration": ("expected_duration", "actual_duration"),
            "completion": ("expected_completion", "actual_completion"),
            "fatigue": ("expected_fatigue", "actual_fatigue"),
        }
        errors = {}
        for label, (pred_key, actual_key) in pairs.items():
            predicted = prediction.get(pred_key)
            observed = actual.get(actual_key)
            if predicted is None or observed is None:
                continue
            try:
                errors[label] = float(predicted) - float(observed)
            except (TypeError, ValueError):
                continue
        return errors

    async def save_recovery_event(self, event_data: dict[str, Any]) -> None:
        row = dict(event_data)
        row.setdefault("timestamp", utc_now())
        self.data["recovery_history"].append(row)
        self._save()
        await self.record_timeline_event("recovery.event", row)

    async def save_faculty_event(self, event_data: dict[str, Any]) -> None:
        row = dict(event_data)
        row.setdefault("timestamp", utc_now())
        self.data["faculty_history"].append(row)
        self._save()
        await self.record_timeline_event("faculty.event", row)

    async def save_prediction(self, prediction_data: dict[str, Any]) -> None:
        row = dict(prediction_data)
        row.setdefault("timestamp", utc_now())
        self.data["prediction_history"].append(row)
        self._save()
        await self.record_timeline_event("prediction.event", row)

    async def get_learning_confidence_level(self) -> int:
        day_count = len({row.get("date") for row in self.data["daily_summary"] if row.get("date")})
        evidence_count = len(self.data["learning_events"]) + len(self.data["completed_blocks"])
        if day_count >= 365 or evidence_count >= 900:
            level = 4
        elif day_count >= 180 or evidence_count >= 450:
            level = 3
        elif day_count >= 30 or evidence_count >= 90:
            level = 2
        elif day_count >= 7 or evidence_count >= 20:
            level = 1
        else:
            level = 0
        self.data["learning_model"]["confidence_level"] = {
            "level": level,
            "day_count": day_count,
            "evidence_count": evidence_count,
            "updated_at": utc_now(),
        }
        self._save()
        self.audit.log("state.learning_confidence.level", level=level, day_count=day_count, evidence_count=evidence_count)
        return level

    async def update_learning_model(self, block_context: dict[str, Any], parsed_data: dict[str, Any]) -> dict[str, Any]:
        subject = str(block_context.get("subject") or "Unknown")
        chapter = str(block_context.get("chapter") or "Unknown")
        attempted = int(parsed_data.get("attempted") or 0)
        correct = int(parsed_data.get("correct") or 0)
        model = self.data["learning_model"].setdefault("subjects", {})
        subject_model = model.setdefault(
            subject,
            {
                "blocks_seen": 0,
                "attempted": 0,
                "correct": 0,
                "chapters": {},
                "last_updated": utc_now(),
            },
        )
        chapter_model = subject_model["chapters"].setdefault(
            chapter,
            {"blocks_seen": 0, "attempted": 0, "correct": 0, "confidence": 0.0},
        )
        for row in (subject_model, chapter_model):
            row["blocks_seen"] = int(row.get("blocks_seen", 0)) + 1
            row["attempted"] = int(row.get("attempted", 0)) + attempted
            row["correct"] = int(row.get("correct", 0)) + correct
            row["confidence"] = round(row["correct"] / row["attempted"], 3) if row["attempted"] else 0.0
        subject_model["last_updated"] = utc_now()
        await self.get_learning_confidence_level()
        self._save()
        await self.record_timeline_event(
            "learning_model.updated",
            {
                "subject": subject,
                "chapter": chapter,
                "attempted": attempted,
                "correct": correct,
                "confidence": chapter_model["confidence"],
            },
        )
        return dict(chapter_model)

    async def save_learning_event(self, event_data: dict[str, Any]) -> None:
        event = dict(event_data)
        event.setdefault("timestamp", time.time())
        self.data["learning_events"].append(event)
        self._save()
        self.audit.log("state.learning_event.saved", subject=event.get("subject"), attempted=event.get("attempted"))
        await self.record_timeline_event("learning_event.saved", event)
        await self.get_learning_confidence_level()

    async def upsert_concept_asset(self, concept_data: dict[str, Any]) -> None:
        concept_name = concept_data.get("concept_name")
        if not concept_name:
            return
        existing = next((row for row in self.data["concept_assets"] if row.get("concept_name") == concept_name), None)
        if existing:
            existing["times_encountered"] = existing.get("times_encountered", 0) + concept_data.get("times_encountered", 1)
            existing["last_seen"] = concept_data.get("last_seen", time.time())
            existing.setdefault("revisions", []).extend(concept_data.get("revisions", []))
            existing["current_understanding"] = concept_data.get("current_understanding", existing.get("current_understanding", ""))
            existing["resolved"] = concept_data.get("resolved", existing.get("resolved", False))
            existing["updated_at"] = utc_now()
        else:
            row = dict(concept_data)
            row.setdefault("times_encountered", 1)
            row.setdefault("first_seen", time.time())
            row.setdefault("last_seen", row["first_seen"])
            row.setdefault("resolved", False)
            row["updated_at"] = utc_now()
            self.data["concept_assets"].append(row)
        self._save()
        self.audit.log("state.concept_asset.upserted", concept_name=concept_name, subject=concept_data.get("subject"))

    async def save_archived_questions(self, archived_questions: list[dict[str, Any]]) -> None:
        self.data["archived_questions"].extend(dict(row) for row in archived_questions)
        self._save()
        self.audit.log("state.archived_questions.saved", count=len(archived_questions))

    async def get_concept_asset(self, concept_name: str) -> dict[str, Any] | None:
        row = next((row for row in self.data["concept_assets"] if row.get("concept_name") == concept_name), None)
        return dict(row) if row else None

    async def get_unresolved_concepts(self, subject: str | None = None) -> list[dict[str, Any]]:
        rows = [row for row in self.data["concept_assets"] if not row.get("resolved", False)]
        if subject:
            rows = [row for row in rows if str(row.get("subject", "")).lower() == subject.lower()]
        return [dict(row) for row in rows]

    async def save_recommendation(self, rec_data: dict[str, Any]) -> None:
        self.data["recommendation_history"].append(dict(rec_data))
        self._save()

    async def update_recommendation_outcome(self, rec_timestamp: float, applied: bool, reason: str, effectiveness: float) -> None:
        for row in self.data["recommendation_history"]:
            if row.get("timestamp") == rec_timestamp:
                row.update({"applied": applied, "reason_ignored": reason, "effectiveness_score": effectiveness})
        self._save()

    async def get_recent_recommendations(self, limit: int = 10) -> list[dict[str, Any]]:
        return [dict(row) for row in self.data["recommendation_history"][-limit:]]


class LocalNotionClient:
    """Schema-validating fake Notion client with four local databases."""

    def __init__(self, runtime_dir: Path, audit: AuditLogger) -> None:
        self.path = runtime_dir / "fake_notion.json"
        self.audit = audit
        self.schemas = get_schema_snapshot()
        self.data = _read_json(
            self.path,
            {
                "schemas": self.schemas,
                "rows": {"db1": [], "db2": [], "db3": [], "db4": []},
            },
        )
        self.data["schemas"] = self.schemas
        self._save()

    async def __aenter__(self) -> "LocalNotionClient":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self._save()

    def _save(self) -> None:
        _write_json(self.path, self.data)

    def _validate_properties(self, db_key: str, properties: dict[str, Any]) -> None:
        allowed = set(self.schemas[db_key]["properties"])
        unknown = sorted(set(properties) - allowed)
        if unknown:
            raise ValueError(f"Fake {db_key} write contains properties absent from real schema: {unknown}")

    def _append_row(self, db_key: str, properties: dict[str, Any], normalized: dict[str, Any]) -> dict[str, Any]:
        self._validate_properties(db_key, properties)
        row = {
            "id": f"{db_key}_{len(self.data['rows'][db_key]) + 1:05d}",
            "created_time": utc_now(),
            "database_id": self.schemas[db_key]["local_database_id"],
            "properties": properties,
            "normalized": normalized,
        }
        self.data["rows"][db_key].append(row)
        self._save()
        self.audit.log(
            "fake_notion.row.created",
            database=db_key,
            database_title=self.schemas[db_key]["title"],
            row_id=row["id"],
            properties=list(properties),
            normalized=normalized,
        )
        return row

    async def check_health(self) -> bool:
        self.audit.log("fake_notion.health", status="online")
        return True

    async def create_db4_if_not_exists(self) -> str:
        return self.schemas["db4"]["local_database_id"]

    async def create_db1_row(
        self,
        task_name: str,
        subject: str,
        exercise_type: str,
        time_taken: float,
        attempted: int,
        correct: int,
        block: str,
        date_str: str,
    ) -> None:
        cy = cognitive_yield(time_taken, attempted, correct, exercise_type, subject)
        ty = theory_yield(time_taken, attempted, correct, exercise_type, subject)
        accuracy = correct / attempted if attempted else 0
        mins_per_question = time_taken / attempted if attempted else 0
        circled = max(attempted - correct, 0)
        properties = {
            "Task (Actionable Verb + Exact Scope)": {"title": [{"text": {"content": task_name}}]},
            "Subject": {"select": {"name": subject}},
            "Exercise Type": {"select": {"name": exercise_type}},
            "Actual Time Spent (mins)": {"number": time_taken},
            "Questions Attempted": {"number": attempted},
            "Questions Correct": {"number": correct},
            "BLOCK": {"select": {"name": block}},
            "Date": {"date": {"start": date_str}},
            "Cognitive Yield ": {"formula": {"number": cy}},
            "Theory Yield ": {"formula": {"number": ty}},
            "Accuracy Ratio": {"formula": {"number": accuracy}},
            "Mins per Question": {"formula": {"number": mins_per_question}},
            "Calculated Circled Qs": {"formula": {"number": circled}},
            "Cognitive Yield (Task)": {"formula": {"number": cy}},
            "Tickbox": {"checkbox": False},
            "Max Time (min)": {"rich_text": []},
            "Alternative": {"rich_text": []},
            "Logged Errors": {"relation": []},
            "Target Chapter/Module": {"relation": []},
        }
        self._append_row(
            "db1",
            properties,
            {
                "task_name": task_name,
                "subject": subject,
                "exercise_type": exercise_type,
                "time_taken": time_taken,
                "attempted": attempted,
                "correct": correct,
                "block": block,
                "date": date_str,
                "cognitive_yield": cy,
                "theory_yield": ty,
                "accuracy": accuracy,
                "circled_questions": circled,
            },
        )

    async def update_db2_db3(self, report: Any, assets: list | None = None, conceptual_mistake: bool = False) -> None:
        attempted = getattr(report, "attempted", 0) if not isinstance(report, dict) else report.get("attempted", 0)
        correct = getattr(report, "correct", 0) if not isinstance(report, dict) else report.get("correct", 0)
        subject = getattr(report, "subject", None) if not isinstance(report, dict) else report.get("subject")
        subject = subject or "Unknown"
        ex_type = getattr(report, "exercise_type", None) if not isinstance(report, dict) else report.get("exercise_type")
        ex_type = ex_type or "Unknown"
        accuracy = correct / attempted if attempted else 0
        needs_revision = attempted > 0 and accuracy < 0.7
        has_assets = bool(assets)

        if needs_revision:
            self._append_row(
                "db2",
                {
                    "Chapter / Module": {"title": [{"text": {"content": f"{subject} {ex_type}"}}]},
                    "Status": {"select": {"name": "Pending"}},
                    "Total circled questions (manual)": {"number": max(attempted - correct, 0)},
                    "TOTAL CIRCLED QUESTIONS ": {"formula": {"number": max(attempted - correct, 0)}},
                    "Double-Circled (Faculty Intervention Req.)": {"number": 1 if accuracy < 0.5 else 0},
                    "Is Short notes Completed?": {"checkbox": False},
                    "Next Execution Date": {"date": {"start": (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")}},
                    "Related to 1. Daily Execution Ledger (The 80% Output) (Target Chapter/Module)": {"relation": []},
                    "Total Circled Qs": {"rollup": {"number": max(attempted - correct, 0)}},
                },
                {
                    "subject": subject,
                    "chapter": ex_type,
                    "status": "Pending",
                    "circled_questions": max(attempted - correct, 0),
                    "source": "low_accuracy_block",
                },
            )

        if conceptual_mistake or has_assets or needs_revision:
            failure_type = "Concept" if conceptual_mistake or has_assets else "Calculation"
            self._append_row(
                "db3",
                {
                    "Core Concept / Root Bug": {"title": [{"text": {"content": f"{subject} {ex_type} accuracy leak"}}]},
                    "Status": {"select": {"name": "Unresolved"}},
                    "Failure Type": {"select": {"name": failure_type}},
                    "Concept Deficit / Failure Reason": {
                        "rich_text": [{"text": {"content": f"Accuracy {accuracy:.0%}; {attempted - correct} circled questions."}}],
                    },
                    "Subject": {"rollup": {"array": [{"select": {"name": subject}}]}},
                    "Related to 1. Daily Execution Ledger (The 80% Output) (Logged Errors)": {"relation": []},
                },
                {
                    "concept_name": f"{subject} {ex_type} accuracy leak",
                    "subject": subject,
                    "failure_type": failure_type,
                    "status": "Unresolved",
                },
            )

    async def create_db4_row(self, action_type: str, decision: str, reasoning: str, data_snapshot: str) -> None:
        self._append_row(
            "db4",
            {
                "Action Type": {"title": [{"text": {"content": action_type}}]},
                "Decision": {"rich_text": [{"text": {"content": decision}}]},
                "Reasoning": {"rich_text": [{"text": {"content": reasoning}}]},
                "Data Snapshot": {"rich_text": [{"text": {"content": data_snapshot[:2000]}}]},
                "Timestamp": {"date": {"start": utc_now()}},
                "Level": {"select": {"name": "INFO"}},
            },
            {
                "action_type": action_type,
                "decision": decision,
                "reasoning": reasoning,
            },
        )

    async def create_db3_concept_asset(self, asset: dict[str, Any], source_block: dict[str, Any]) -> None:
        concept = asset.get("concept_name", "Unresolved Concept")
        subject = asset.get("subject") or source_block.get("subject") or "Unknown"
        revision = ""
        if asset.get("revisions"):
            revision = asset["revisions"][-1].get("current_understanding", "")
        self._append_row(
            "db3",
            {
                "Core Concept / Root Bug": {"title": [{"text": {"content": concept}}]},
                "Status": {"select": {"name": "Unresolved"}},
                "Failure Type": {"select": {"name": "Concept"}},
                "Concept Deficit / Failure Reason": {"rich_text": [{"text": {"content": revision or "Captured from /done reflection."}}]},
                "Subject": {"rollup": {"array": [{"select": {"name": subject}}]}},
                "Related to 1. Daily Execution Ledger (The 80% Output) (Logged Errors)": {"relation": []},
            },
            {
                "concept_name": concept,
                "subject": subject,
                "failure_type": "Concept",
                "status": "Unresolved",
                "source_block": source_block.get("block_label"),
            },
        )

    async def get_daily_stats(self, date_str: str) -> dict[str, Any]:
        rows = [row for row in self.data["rows"]["db1"] if row["normalized"].get("date") == date_str]
        return {
            "cy": sum(row["normalized"].get("cognitive_yield", 0) for row in rows),
            "rows": len(rows),
            "source": "fake_notion_db1",
        }

    async def get_revision_backlog(self) -> list[dict[str, Any]]:
        rows = []
        for row in self.data["rows"]["db2"]:
            norm = row.get("normalized", {})
            if norm.get("status") == "Pending":
                rows.append({"subject": norm.get("subject", "?"), "chapter": norm.get("chapter", "?"), "status": "Pending"})
        return rows

    async def read_db1_rows(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        rows = list(self.data["rows"]["db1"])
        date_filter = (((filters or {}).get("date") or {}).get("equals")) if filters else None
        if not date_filter and filters:
            date_filter = (((filters.get("filter") or {}).get("date") or {}).get("equals"))
        if date_filter:
            rows = [row for row in rows if row.get("normalized", {}).get("date") == date_filter]
        return [dict(row) for row in rows]

    def counts(self) -> dict[str, int]:
        return {key: len(value) for key, value in self.data["rows"].items()}

    def export(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.data))


class LocalAIEngine:
    """Deterministic provider router and response generator.

    It does not call any live model. It simulates routing, fallback, and model
    outputs so the rest of the app can be tested repeatedly offline.
    """

    def __init__(self, audit: AuditLogger, state_db: FakeStateDB | None = None) -> None:
        self.audit = audit
        self.state_db = state_db
        self.last_provider_used: str | None = None
        self._developer_force_provider: str | None = None
        self.failure_once: dict[str, set[str]] = {
            "daily_plan": {"g4f_pro"},
            "think": {"g4f_pro"},
            "evening_reflection": {"g4f_pro"},
            "test_recalibration": {"g4f_pro"},
            "weekly_roast": {"g4f_pro"},
        }
        self._failed: set[tuple[str, str]] = set()

    def switch_provider(self, provider: str) -> None:
        self._developer_force_provider = provider.lower()
        self.audit.log("ai.switch_provider", provider=provider.lower())

    async def close(self) -> None:
        self.audit.log("ai.close")

    async def health_check_all(self) -> dict[str, bool]:
        result = {provider: True for provider in config.FALLBACK_CHAIN}
        self.audit.log("ai.health_check_all", result=result)
        return result

    async def call(
        self,
        task_type: str,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        force_provider: str | None = None,
        force_model: str | None = None,
    ) -> str:
        provider_chain = self._providers_for_task(task_type, force_provider)
        trace = []
        selected = provider_chain[-1]
        for provider in provider_chain:
            should_fail = provider in self.failure_once.get(task_type, set()) and (task_type, provider) not in self._failed
            if should_fail:
                self._failed.add((task_type, provider))
                trace.append({"provider": provider, "status": "failed", "reason": "simulated local timeout"})
                if self.state_db:
                    await self.state_db.update_api_health(provider, False, 2000)
                continue
            selected = provider
            trace.append({"provider": provider, "status": "success", "reason": "local deterministic response"})
            if self.state_db:
                await self.state_db.update_api_health(provider, True, 40)
            break

        self.last_provider_used = selected
        response = self._generate_response(task_type, prompt)
        self.audit.log(
            "ai.call",
            task_type=task_type,
            selected_provider=selected,
            forced_provider=force_provider or self._developer_force_provider,
            forced_model=force_model,
            max_tokens=max_tokens,
            temperature=temperature,
            route_trace=trace,
            system_prompt_preview=(system_prompt or "")[:500],
            prompt_preview=prompt[:1200],
            response_preview=response[:1200],
        )
        return response

    def _providers_for_task(self, task_type: str, force_provider: str | None) -> list[str]:
        forced = (force_provider or self._developer_force_provider or "").lower()
        if forced:
            return [forced] + [provider for provider in config.FALLBACK_CHAIN if provider != forced]
        if task_type in {"parse_message", "parser", "fast", "general_chat", "block_prompt", "timeout_ping"}:
            preferred = config.FAST_PROVIDERS
        else:
            preferred = config.THINK_PROVIDERS
        return preferred + [provider for provider in config.FALLBACK_CHAIN if provider not in preferred]

    def _generate_response(self, task_type: str, prompt: str) -> str:
        if "Classify the intent of this student message" in prompt:
            return json.dumps(self._classify_intent(prompt))
        if "Generate today's battle plan" in prompt or "Build today's block schedule" in prompt:
            return json.dumps(self._daily_plan())
        if "Adaptive Interview Engine" in prompt:
            return json.dumps(self._block_reflection(prompt))
        if "Extract structured concept assets" in prompt:
            return json.dumps(self._concept_assets(prompt))
        if "Analyze today's study performance" in prompt:
            return json.dumps(
                {
                    "yield": 0,
                    "target_hit": False,
                    "root_cause": "Insufficient completed blocks or low theory conversion.",
                    "evidence": "Local fake reflection saw missing/low CY data.",
                    "recommendation": "Tomorrow: one theory block before problem blocks, then log doubts immediately.",
                    "confidence": 0.72,
                }
            )
        if "The user wants to analyze their history" in prompt:
            return "Need at least 2 logged days for a real trend. Today, focus on generating clean block data."
        return "Local model response: logged, routed, and stored in the fake audit trail."

    def _classify_intent(self, prompt: str) -> dict[str, Any]:
        match = re.search(r"Message:\s*(.*?)\nYou MUST", prompt, flags=re.S)
        text = match.group(1).strip() if match else prompt
        lower = text.lower()
        report_like = bool(re.search(r"\b(a|attempted)\s*[=:]?\s*\d+.*\b(c|correct)\s*[=:]?\s*\d+", lower))
        compact_report = bool(re.search(r"\b\d+\s*/\s*\d+\s*/\s*\d+\b", lower))
        if report_like or compact_report or ("attempted" in lower and "correct" in lower):
            return {"intent": "report", "complexity_tier": "fast", "entities": {}}
        if any(word in lower for word in ["trend", "history", "past", "analyze", "compare"]):
            return {"intent": "analyze_history", "complexity_tier": "think", "entities": {}}
        if "switch" in lower and ("provider" in lower or "model" in lower):
            provider = next((p for p in config.FALLBACK_CHAIN if p in lower), None)
            return {"intent": "system_command", "complexity_tier": "fast", "entities": {"provider": provider}}
        if any(word in lower for word in ["why", "how", "doubt", "explain", "jee"]):
            return {"intent": "query", "complexity_tier": "think", "entities": {}}
        return {"intent": "general", "complexity_tier": "fast", "entities": {}}

    def _daily_plan(self) -> dict[str, Any]:
        blocks = [
            {"schema_version": "1.0", "block_label": "EB-1", "subject": "Physics", "exercise_type": "Ex 2A", "question_count": 12, "target_time": 54, "expected_cy": 60},
            {"schema_version": "1.0", "block_label": "EB-2", "subject": "Chem", "exercise_type": "JMYL", "question_count": 20, "target_time": 80, "expected_cy": 60},
            {"schema_version": "1.0", "block_label": "EB-3", "subject": "Maths", "exercise_type": "Ex 1A", "question_count": 10, "target_time": 45, "expected_cy": 60},
            {"schema_version": "1.0", "block_label": "RB", "subject": "Physics", "exercise_type": "Revision", "question_count": 8, "target_time": 32, "expected_cy": 60},
        ]
        return {"blocks": blocks}

    def _block_reflection(self, prompt: str) -> dict[str, Any]:
        user_match = re.search(r'USER MESSAGE:\s*"(.*?)"', prompt, flags=re.S)
        text = user_match.group(1) if user_match else prompt
        lower = text.lower()
        nums = [int(n) for n in re.findall(r"\b\d+\b", text)]
        attempted = nums[0] if nums else 0
        correct = nums[1] if len(nums) > 1 else max(0, attempted - 2)
        q_ids = [f"Q{q}" for q in re.findall(r"\bq\s*(\d+)\b", lower)]
        concepts = self._extract_concepts(lower)
        vague = bool(q_ids) and not concepts and "don't know" not in lower and "dont know" not in lower
        if vague:
            return {
                "needs_followup": True,
                "followup_question": f"What was the core concept behind {q_ids[0]}? If you do not know, say 'don't know'.",
                "historical_insight": None,
                "parsed_data": {"attempted": attempted, "correct": correct, "concept_doubts": q_ids, "incomplete_questions": [], "reason_skipped": "", "faculty_concepts": []},
            }
        if not concepts and ("don't know" in lower or "dont know" in lower or q_ids):
            concepts = ["Unresolved Concept"]
        return {
            "needs_followup": False,
            "followup_question": None,
            "historical_insight": "Local memory will surface this in /doubts until it is resolved.",
            "parsed_data": {
                "attempted": attempted,
                "correct": correct,
                "concept_doubts": [f"{qid}: {concepts[0] if concepts else 'unclear'}" for qid in q_ids],
                "incomplete_questions": [],
                "reason_skipped": "stuck" if "stuck" in lower else "",
                "faculty_concepts": concepts,
            },
        }

    def _concept_assets(self, prompt: str) -> dict[str, Any]:
        concepts = self._extract_json_list(prompt, "faculty_concepts") or ["Unresolved Concept"]
        subject_match = re.search(r'"subject":\s*"([^"]+)"', prompt)
        chapter_match = re.search(r'"chapter":\s*"([^"]+)"', prompt)
        block_match = re.search(r'"block_label":\s*"([^"]+)"', prompt)
        subject = subject_match.group(1) if subject_match else "Unknown"
        chapter = chapter_match.group(1) if chapter_match else "Unknown"
        block = block_match.group(1) if block_match else "Unknown"
        assets = []
        archived = []
        for concept in concepts:
            assets.append(
                {
                    "concept_name": concept,
                    "subject": subject,
                    "chapter": chapter,
                    "proposed_connections": [],
                    "confidence_delta": -0.08,
                    "faculty_needed": concept == "Unresolved Concept",
                    "revisions": [
                        {
                            "faculty_notes": "",
                            "current_understanding": f"Captured locally from block reflection: {concept}",
                            "error_profiles": [{"mistake_type": "Concept", "description": "Needs targeted revision or faculty clarification."}],
                        }
                    ],
                }
            )
            archived.append(
                {
                    "question_id": "Q?",
                    "subject": subject,
                    "chapter": chapter,
                    "concept_label": concept,
                    "mistake_type": "Concept",
                    "source_block": block,
                }
            )
        return {"concept_assets": assets, "archived_questions": archived}

    @staticmethod
    def _extract_json_list(prompt: str, key: str) -> list[str]:
        match = re.search(rf'"{re.escape(key)}":\s*(\[[^\]]*\])', prompt)
        if not match:
            return []
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return []
        return [str(item) for item in payload if str(item).strip()]

    @staticmethod
    def _extract_concepts(lower_text: str) -> list[str]:
        concepts = {
            "circular": "Circular Motion",
            "rotation": "Rotational Motion",
            "friction": "Friction",
            "wedge": "Wedge Constraint",
            "constraint": "Constraint Relation",
            "mole": "Mole Concept",
            "equilibrium": "Chemical Equilibrium",
            "integration": "Integration",
            "sequence": "Sequences and Series",
            "binomial": "Binomial Theorem",
        }
        found = []
        for needle, concept in concepts.items():
            if needle in lower_text and concept not in found:
                found.append(concept)
        return found


class LocalKnowledgeEngine:
    def __init__(self, ai_engine: LocalAIEngine, state_db: FakeStateDB, notion_client: LocalNotionClient, audit: AuditLogger) -> None:
        self.ai = ai_engine
        self.state = state_db
        self.notion = notion_client
        self.audit = audit

    async def extract_assets(self, block_context: dict[str, Any], parsed_data: dict[str, Any]) -> dict[str, Any]:
        prompt = (
            "Extract structured concept assets and error profiles from the student's study block data.\n\n"
            f"BLOCK CONTEXT:\n{json.dumps(block_context, indent=2)}\n\n"
            f"PARSED INTERVIEW DATA:\n{json.dumps(parsed_data, indent=2)}\n"
        )
        raw = await self.ai.call("parser", prompt, system_prompt="Return ONLY raw JSON.", max_tokens=500)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            return {"error": f"Local knowledge JSON parse failed: {exc}"}

        learning_event = {
            "timestamp": time.time(),
            "subject": block_context.get("subject", "Unknown"),
            "chapter": block_context.get("chapter", "Unknown"),
            "exercise_type": block_context.get("exercise_type", "Unknown"),
            "attempted": parsed_data.get("attempted", 0),
            "correct": parsed_data.get("correct", 0),
            "questions_encountered": parsed_data.get("concept_doubts", []) + parsed_data.get("incomplete_questions", []),
            "reasons_for_skipping": {q: parsed_data.get("reason_skipped", "Unknown") for q in parsed_data.get("incomplete_questions", [])},
            "time_taken": block_context.get("target_time", 0),
        }
        await self.state.save_learning_event(learning_event)
        if hasattr(self.state, "update_learning_model"):
            await self.state.update_learning_model(block_context, parsed_data)

        concept_assets = payload.get("concept_assets", [])
        now = time.time()
        for asset in concept_assets:
            for revision in asset.get("revisions", []):
                revision["timestamp"] = now
            state_asset = {
                "concept_name": asset.get("concept_name", "Unresolved Concept"),
                "subject": asset.get("subject") or block_context.get("subject", "Unknown"),
                "chapter": asset.get("chapter") or block_context.get("chapter", "Unknown"),
                "connected_to": asset.get("proposed_connections", []),
                "revisions": asset.get("revisions", []),
                "faculty_dependency": 1 if asset.get("faculty_needed") else 0,
                "mastery_stage": "Struggling",
                "confidence_score": max(0.0, 0.4 + float(asset.get("confidence_delta", 0))),
                "resolved": False,
                "last_seen": now,
            }
            await self.state.upsert_concept_asset(state_asset)
            await self.notion.create_db3_concept_asset(state_asset, block_context)

        archived = payload.get("archived_questions", [])
        for row in archived:
            row["timestamp"] = now
            row["archived"] = True
        await self.state.save_archived_questions(archived)

        self.audit.log(
            "knowledge.assets.extracted",
            concepts=[asset.get("concept_name") for asset in concept_assets],
            archived_questions=len(archived),
        )
        return {"learning_event": learning_event, "concept_assets": concept_assets, "archived_questions": archived}


class LocalRoaster:
    def __init__(self, state_db: FakeStateDB, audit: AuditLogger) -> None:
        self.state = state_db
        self.audit = audit

    async def generate_block_roast(self, block_entry: dict[str, Any], plan: dict[str, Any]) -> str:
        attempted = block_entry.get("A", 0)
        correct = block_entry.get("C", 0)
        accuracy = correct / attempted if attempted else 0
        cy = block_entry.get("actual_cy", 0)
        target = block_entry.get("expected_cy", 0)
        verdict = "on track" if cy >= target else "behind"
        self.audit.log("roaster.block", block=block_entry.get("block_label"), cy=cy, target=target)
        return (
            f"✅ Logged {block_entry.get('block_label', 'Block')}.\n"
            f"A={attempted} C={correct} Accuracy={accuracy:.0%} CY={cy}/{target}.\n"
            f"Verdict: {verdict}. Next block needs clean logging, not staring."
        )

    async def generate_test_recalibration(self, scores: dict[str, Any]) -> str:
        total = scores.get("p_score", 0) + scores.get("c_score", 0) + scores.get("m_score", 0)
        max_total = scores.get("p_total", 120) + scores.get("c_total", 120) + scores.get("m_total", 120)
        pct = total / max_total if max_total else 0
        weak = min(
            [("Physics", scores.get("p_score", 0)), ("Chem", scores.get("c_score", 0)), ("Maths", scores.get("m_score", 0))],
            key=lambda item: item[1],
        )[0]
        self.audit.log("roaster.test_recalibration", total=total, max_total=max_total, weak_subject=weak)
        return f"📉 Test recalibration: {total}/{max_total} ({pct:.0%}). Weakest subject: {weak}. Next 3 days: theory repair before PYQs."

    async def generate_weekly_roast(self, week_start: str, week_end: str) -> str:
        summaries = await self.state.get_summaries_range(week_start, week_end)
        total = sum(row.get("total_cy", 0) for row in summaries)
        self.audit.log("roaster.weekly", week_start=week_start, week_end=week_end, total_cy=total)
        return f"🔥 Weekly local roast {week_start} to {week_end}: {len(summaries)} logged days, {total} CY. Missing days are the real enemy."


class LocalHealthMonitor:
    def __init__(self, ai_engine: LocalAIEngine, notion_client: LocalNotionClient, state_db: FakeStateDB) -> None:
        self.ai = ai_engine
        self.notion = notion_client
        self.state = state_db

    async def get_system_status(self) -> dict[str, Any]:
        return {"ai": "offline-simulated", "notion": "fake-online", "state_db": "fake-online"}

    async def check_notion_health(self) -> None:
        await self.notion.check_health()


@dataclass
class FakeChat:
    id: str = "local-chat"


class FakeMessage:
    def __init__(self, text: str, replies: list[str]) -> None:
        self.text = text
        self.replies = replies
        self.from_user = None

    async def reply_text(self, text: str, *args: Any, **kwargs: Any) -> None:
        self.replies.append(text)


class FakeUpdate:
    def __init__(self, text: str, replies: list[str]) -> None:
        self.message = FakeMessage(text, replies)
        self.effective_chat = FakeChat()
        self.callback_query = None


class FakeContext:
    def __init__(self, bot_data: dict[str, Any], args: list[str] | None = None) -> None:
        self.bot_data = bot_data
        self.args = args or []
