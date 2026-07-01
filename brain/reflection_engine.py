"""
SENTINEL — Reflection Engine (brain/reflection_engine.py)

Answers: "Why did today go the way it did?"
Also handles the single-message Block Reflection (the Adaptive Interview).
"""

import logging
import json
from datetime import datetime, timezone
from typing import Any

from sentinel.bot.schemas import TaskProfile
from sentinel.brain.analyzer import PerformanceAnalyzer

logger = logging.getLogger("sentinel.brain.reflection_engine")

EVENING_REFLECTION_PROMPT = """\
Analyze today's study performance.

DATA:
{data_json}

YOUR JOB:
1. Identify the single biggest bottleneck (Root Cause). E.g., "Skipped Theory".
2. Provide explicit evidence.
3. Recommend exactly one actionable change for tomorrow.
4. Output your confidence in this diagnosis (0.0 to 1.0).

Format strictly as JSON:
{{
    "yield": <int>,
    "target_hit": <bool>,
    "root_cause": "<string>",
    "evidence": "<string>",
    "recommendation": "<string>",
    "confidence": <float>
}}
"""

BLOCK_REFLECTION_PROMPT = """\
You are SENTINEL's Adaptive Interview Engine.
The user just sent a raw brain-dump after finishing a study block.

BLOCK CONTEXT:
{context_json}

HISTORY CONTEXT:
{history_json}

USER MESSAGE:
"{user_message}"

YOUR JOB:
Extract the Learning Event details. The student's permanent understanding is tied to CONCEPTS, not questions.
If the user's message is too vague and missing critical information (e.g. they say "didn't understand Q7" but not WHAT concept Q7 is about), you should ask exactly ONE targeted follow-up question (e.g. "What was the core concept behind Q7?").
However, if they genuinely don't know the concept even after a follow-up, DO NOT force them. Simply log the concept_name as "Unresolved Concept" so it can be handled in a later faculty session.
Also, connect their current doubts to the HISTORY CONTEXT. If they are struggling with a concept they failed before, point it out in `historical_insight`.

If you have enough information (or if they genuinely don't know the concept), set "needs_followup" to false and provide the parsed LearningEvent data.

Format strictly as JSON:
{{
    "needs_followup": <bool>,
    "followup_question": "<string or null>",
    "historical_insight": "<string or null> (e.g. 'I noticed Q7 is about the same wedge-constraint concept you struggled with last Tuesday. I recommend asking Sir specifically about the derivation.')",
    "parsed_data": {{
        "attempted": <int>,
        "correct": <int>,
        "concept_doubts": ["<Q7: Reason>", ...],
        "incomplete_questions": ["<Q10>", ...],
        "reason_skipped": "<string>",
        "faculty_concepts": ["<string>"]
    }}
}}
"""

class ReflectionEngine:
    def __init__(self, ai_engine, state_db, notion_client, event_bus=None):
        self.ai = ai_engine
        self.state = state_db
        self.notion = notion_client
        self.bus = event_bus
        self.analyzer = PerformanceAnalyzer(ai_engine, notion_client, state_db)

    async def run_evening_reflection(self, date_str: str) -> dict[str, Any]:
        """Runs the evening reflection, combining deterministic data with AI root-cause diagnosis."""
        logger.info(f"Running Reflection Engine for {date_str}...")
        
        summary = await self.state.get_daily_summary(date_str)
        if not summary:
            summary = await self.analyzer._compute_summary_from_notion(date_str)
            
        if not summary:
            return {"error": f"No data recorded for {date_str}."}

        weak_subjects = await self.analyzer.identify_weak_subjects()
        telemetry_actual = await self._append_planner_actual(date_str, summary)
        payload_str = json.dumps({"summary": summary, "weak_subjects": weak_subjects[:3] if weak_subjects else []}, indent=2)

        try:
            raw_response = await self.ai.call(
                task_type="evening_reflection",
                prompt=EVENING_REFLECTION_PROMPT.format(data_json=payload_str),
                system_prompt="You are an analytical AI diagnosing study bottlenecks. Return ONLY raw JSON.",
                max_tokens=300
            )
            
            cleaned = raw_response.strip()
            if "```json" in cleaned: cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0]
            elif "```" in cleaned: cleaned = cleaned.split("```", 1)[1].split("```", 1)[0]

            try:
                result = json.loads(cleaned.strip())
                if telemetry_actual:
                    result["telemetry_actual"] = telemetry_actual.get("actual")
                    result["prediction_error"] = telemetry_actual.get("prediction_error")
                return result
            except json.JSONDecodeError:
                logger.warning("Evening reflection JSON parse failed, returning raw summary")
                result = {"yield": 0, "target_hit": False, "root_cause": "Parse error", "evidence": cleaned[:200], "recommendation": "Review manually", "confidence": 0.0}
                if telemetry_actual:
                    result["telemetry_actual"] = telemetry_actual.get("actual")
                    result["prediction_error"] = telemetry_actual.get("prediction_error")
                return result
        except Exception as e:
            logger.error(f"Reflection Engine failed to diagnose: {e}")
            result = {"error": str(e), "summary": summary}
            if telemetry_actual:
                result["telemetry_actual"] = telemetry_actual.get("actual")
                result["prediction_error"] = telemetry_actual.get("prediction_error")
            return result

    async def _append_planner_actual(self, date_str: str, summary: dict[str, Any]) -> dict[str, Any] | None:
        if not hasattr(self.state, "append_planner_actual"):
            return None

        completed_blocks = []
        if hasattr(self.state, "get_today_blocks"):
            completed_blocks = await self.state.get_today_blocks(date_str)

        planned_blocks = []
        if hasattr(self.state, "get_study_blocks"):
            planned_blocks = await self.state.get_study_blocks(date_str)

        completed_count = int(summary.get("blocks_completed") or 0)
        if not completed_count:
            completed_count = sum(1 for block in completed_blocks if str(block.get("status", "")).upper() != "SKIPPED")
        skipped_count = int(summary.get("blocks_skipped") or 0)
        if not skipped_count:
            skipped_count = sum(1 for block in completed_blocks if str(block.get("status", "")).upper() == "SKIPPED")

        planned_count = len(planned_blocks) or completed_count + skipped_count
        actual_duration = sum(self._duration_from_block(block) for block in completed_blocks)
        actual_completion = (completed_count / planned_count) if planned_count else None
        decision_id = self._decision_id_from_blocks(planned_blocks) or await self._decision_id_from_state(date_str)
        actual_fatigue = await self._actual_fatigue(summary)

        actual = {
            "date": date_str,
            "decision_id": decision_id,
            "actual_cy": summary.get("total_cy", 0),
            "actual_duration": actual_duration,
            "actual_completion": actual_completion,
            "actual_fatigue": actual_fatigue,
            "blocks_completed": completed_count,
            "blocks_skipped": skipped_count,
            "planned_blocks": planned_count,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }
        return await self.state.append_planner_actual(date_str, actual)

    @staticmethod
    def _duration_from_block(block: dict[str, Any]) -> float:
        for key in ("T", "time_taken", "actual_duration", "duration", "target_time"):
            value = block.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return 0.0

    @staticmethod
    def _decision_id_from_blocks(blocks: list[dict[str, Any]]) -> str | None:
        for block in blocks:
            decision_id = block.get("decision_id")
            if decision_id:
                return str(decision_id)
        return None

    async def _decision_id_from_state(self, date_str: str) -> str | None:
        if hasattr(self.state, "get_latest_planner_decision_for_date"):
            decision = await self.state.get_latest_planner_decision_for_date(date_str)
            if decision and decision.get("decision_id"):
                return str(decision["decision_id"])

        if not hasattr(self.state, "get_state"):
            return None
        current_decision_id = await self.state.get_state("current_decision_id")
        if current_decision_id:
            return current_decision_id

        raw_plan = await self.state.get_state("current_plan")
        if not raw_plan:
            return None
        try:
            parsed = json.loads(raw_plan)
        except json.JSONDecodeError:
            return None
        return parsed.get("decision_id") or parsed.get("plan", {}).get("decision_id")

    async def _actual_fatigue(self, summary: dict[str, Any]) -> float | None:
        for key in ("fatigue", "actual_fatigue", "fatigue_level"):
            if summary.get(key) is not None:
                return self._coerce_float(summary.get(key))

        if not hasattr(self.state, "get_student_profile"):
            return None
        profile = await self.state.get_student_profile()
        if not profile:
            return None
        for key in ("fatigue", "current_fatigue", "fatigue_level"):
            if profile.get(key) is not None:
                return self._coerce_float(profile.get(key))
        return None

    @staticmethod
    def _coerce_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    async def process_block_reflection(self, block_context: dict, history_context: list, user_message: str) -> dict[str, Any]:
        """Parses a single brain-dump message into a Learning Event, or asks a follow-up."""
        logger.info("Processing block reflection with history...")
        
        try:
            raw_response = await self.ai.call(
                task_type="parser", 
                prompt=BLOCK_REFLECTION_PROMPT.format(
                    context_json=json.dumps(block_context, indent=2), 
                    history_json=json.dumps(history_context, indent=2),
                    user_message=user_message
                ),
                system_prompt="You are the Adaptive Interview Engine. Return ONLY raw JSON.",
                max_tokens=400
            )
            
            cleaned = raw_response.strip()
            if "```json" in cleaned: cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0]
            elif "```" in cleaned: cleaned = cleaned.split("```", 1)[1].split("```", 1)[0]

            try:
                result = json.loads(cleaned.strip())
            except json.JSONDecodeError:
                logger.warning("Block reflection JSON parse failed, using regex fallback")
                # Regex fallback: try to extract A/C/T numbers from user message
                import re
                numbers = re.findall(r'\d+', user_message)
                attempted = int(numbers[0]) if len(numbers) >= 1 else 0
                correct = int(numbers[1]) if len(numbers) >= 2 else 0
                result = {
                    "needs_followup": False,
                    "followup_question": None,
                    "historical_insight": None,
                    "parsed_data": {
                        "attempted": attempted,
                        "correct": correct,
                        "concept_doubts": [],
                        "incomplete_questions": [],
                        "reason_skipped": "AI parse failed, raw numbers extracted",
                        "faculty_concepts": []
                    }
                }
            
            if not result.get("needs_followup") and self.bus:
                import time
                import uuid
                from sentinel.bot.events import ReflectionCompleted
                event = ReflectionCompleted(
                    event_id=str(uuid.uuid4()),
                    timestamp=time.time(),
                    payload=result.get("parsed_data", {})
                )
                await self.bus.publish(event)
                
            return result
        except Exception as e:
            logger.error(f"Block reflection parsing failed: {e}")
            return {"needs_followup": False, "parsed_data": {"attempted": 0, "correct": 0, "concept_doubts": [], "incomplete_questions": [], "reason_skipped": str(e), "faculty_concepts": []}}
