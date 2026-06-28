"""
SENTINEL — Reflection Engine (brain/reflection_engine.py)

Answers: "Why did today go the way it did?"
Also handles the single-message Block Reflection (the Adaptive Interview).
"""

import logging
import json
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
                
            return json.loads(cleaned.strip())
        except Exception as e:
            logger.error(f"Reflection Engine failed to diagnose: {e}")
            return {"error": str(e), "summary": summary}

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
                
            result = json.loads(cleaned.strip())
            
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
            return {"error": str(e)}
