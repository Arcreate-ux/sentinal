from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sentinel.brain.contracts import ExecutionBlock, ExecutionPlan


QUESTION_BLOCK_TYPES = {"homework", "revision", "test"}


class StudyBlockEngine:
    """Normalizes permanent study blocks used by planning and reflection.

    The older planner contract used execution fields such as `block_label`,
    `exercise_type`, `question_count`, and `target_time`. Phase 1 needs the
    richer study-block shape while keeping existing commands and tests intact.
    """

    @staticmethod
    def normalize_plan(plan: ExecutionPlan, target_date: str | None = None) -> ExecutionPlan:
        date_str = target_date or plan.date or datetime.now().strftime("%Y-%m-%d")
        decision_id = getattr(plan, "decision_id", "")
        blocks = [
            StudyBlockEngine.normalize_block(block, date_str, idx + 1)
            for idx, block in enumerate(plan.blocks)
        ]
        for block in blocks:
            if decision_id and not block.decision_id:
                block.decision_id = decision_id
        return ExecutionPlan(
            schema_version=plan.schema_version,
            decision_id=decision_id,
            date=date_str,
            day_type=plan.day_type,
            blocks=blocks,
            total_expected_cy=sum(block.expected_cy for block in blocks),
            total_expected_time=sum(block.estimated_minutes or block.target_time for block in blocks),
            prediction=getattr(plan, "prediction", None) or {},
            is_fallback=plan.is_fallback,
        )

    @staticmethod
    def normalize_block(block: ExecutionBlock | dict[str, Any], target_date: str, ordinal: int) -> ExecutionBlock:
        raw = block.model_dump() if hasattr(block, "model_dump") else dict(block)
        label = str(raw.get("label") or raw.get("block_label") or f"Block-{ordinal}").strip()
        subject = str(raw.get("subject") or "Physics").strip()
        exercise_type = str(raw.get("exercise_type") or raw.get("exercise") or "Ex 1A").strip()
        chapter = str(raw.get("chapter") or "?").strip()
        expected_questions = int(raw.get("expected_questions") or raw.get("question_count") or 0)
        estimated_minutes = int(raw.get("estimated_minutes") or raw.get("target_time") or 0)
        questions = str(raw.get("questions") or StudyBlockEngine._questions_label(expected_questions)).strip()
        block_type = str(raw.get("block_type") or StudyBlockEngine.infer_block_type(label, exercise_type)).strip()
        status = str(raw.get("status") or "PLANNED").strip().upper()
        block_id = str(raw.get("block_id") or StudyBlockEngine.make_block_id(target_date, label, ordinal)).strip()

        return ExecutionBlock(
            schema_version=raw.get("schema_version", "1.0"),
            decision_id=str(raw.get("decision_id") or ""),
            block_id=block_id,
            date=str(raw.get("date") or target_date),
            label=label,
            block_label=label,
            subject=subject,
            chapter=chapter,
            exercise=raw.get("exercise") or exercise_type,
            exercise_type=exercise_type,
            questions=questions,
            block_type=block_type,
            estimated_minutes=estimated_minutes,
            expected_questions=expected_questions,
            question_count=int(raw.get("question_count") or expected_questions),
            target_time=int(raw.get("target_time") or estimated_minutes),
            expected_cy=int(raw.get("expected_cy") or 0),
            difficulty=str(raw.get("difficulty") or StudyBlockEngine.infer_difficulty(exercise_type, expected_questions)),
            start_time=str(raw.get("start_time") or ""),
            end_time=str(raw.get("end_time") or ""),
            actual_cy=int(raw.get("actual_cy") or 0),
            status=status,
        )

    @staticmethod
    def make_block_id(target_date: str, label: str, ordinal: int) -> str:
        safe_label = re.sub(r"[^A-Za-z0-9]+", "-", label.strip()).strip("-").upper() or "BLOCK"
        return f"{target_date}-{safe_label}-{ordinal:03d}"

    @staticmethod
    def infer_block_type(label: str, exercise_type: str) -> str:
        lower = f"{label} {exercise_type}".lower()
        if "test" in lower or label.upper().startswith(("TA", "ADV", "AB")):
            return "test"
        if "faculty" in lower:
            return "faculty_session"
        if "theory" in lower or exercise_type.lower() in {"concept", "lecture"}:
            return "theory"
        if "revision" in lower or label.upper().startswith("RB"):
            return "revision"
        return "homework"

    @staticmethod
    def infer_difficulty(exercise_type: str, expected_questions: int) -> str:
        lower = exercise_type.lower()
        if any(token in lower for token in ("2b", "3", "4", "pyq", "jayl")) or expected_questions > 25:
            return "Hard"
        if any(token in lower for token in ("2a", "jmyl", "revision")) or expected_questions > 12:
            return "Medium"
        return "Easy"

    @staticmethod
    def prompt_for_block(block: dict[str, Any]) -> str:
        block_type = str(block.get("block_type") or "homework").lower()
        label = block.get("label") or block.get("block_label") or block.get("block_id")
        subject = block.get("subject", "?")
        chapter = block.get("chapter", "?")
        exercise = block.get("exercise") or block.get("exercise_type", "?")
        if block_type == "theory":
            return f"Report {label}: confidence, confusing concepts, and what did not click for {subject} {chapter}."
        if block_type == "revision":
            return f"Report {label}: retention, forgotten topics, confidence, and any questions that still feel weak."
        if block_type == "test":
            return f"Report {label}: marks, mistakes, time pressure, and questions to archive."
        if block_type == "faculty_session":
            return f"Report {label}: doubts resolved, new homework assigned, and new concepts from faculty."
        return f"Report {label}: attempted, correct, skipped/incomplete questions, and doubts for {subject} {chapter} {exercise}."

    @staticmethod
    def describe_block(block: dict[str, Any], index: int | None = None) -> str:
        prefix = f"{index}. " if index is not None else ""
        label = block.get("label") or block.get("block_label") or "Block"
        subject = block.get("subject", "?")
        chapter = block.get("chapter", "?")
        exercise = block.get("exercise") or block.get("exercise_type", "?")
        questions = block.get("questions") or StudyBlockEngine._questions_label(int(block.get("expected_questions") or 0))
        status = block.get("status", "PLANNED")
        return f"{prefix}{label} - {subject} {chapter} {exercise} {questions} [{status}]"

    @staticmethod
    def find_block(blocks: list[dict[str, Any]], selector: str) -> dict[str, Any] | None:
        cleaned = selector.strip()
        if not cleaned:
            return None
        if cleaned.isdigit():
            idx = int(cleaned) - 1
            if 0 <= idx < len(blocks):
                return blocks[idx]
        lowered = cleaned.lower()
        for block in blocks:
            aliases = {
                str(block.get("block_id", "")).lower(),
                str(block.get("label", "")).lower(),
                str(block.get("block_label", "")).lower(),
            }
            if lowered in aliases:
                return block
        return None

    @staticmethod
    def _questions_label(expected_questions: int) -> str:
        return f"{expected_questions}Q" if expected_questions else ""
