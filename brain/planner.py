"""
SENTINEL — Daily Planner (brain/planner.py)
Orchestrates the generation of adaptive daily study plans using AI and returns PlanningResult.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sentinel.brain.protocol.snapshot import ProtocolSnapshot
from sentinel.brain.contracts import PlanningResult, ExecutionPlan
from sentinel.brain.planning_context_builder import PlanningContextBuilder
from sentinel.brain.planning_prompt_builder import PlanningPromptBuilder
from sentinel.brain.planning_parser import PlanningParser
from sentinel.brain.planning_fallback import FallbackPlanner
from sentinel.brain.study_blocks import StudyBlockEngine

logger = logging.getLogger("sentinel.planner")


class DailyPlanner:
    """Orchestrates the creation and adaptation of daily study execution plans."""

    def __init__(self, ai_engine, notion_client, state_db) -> None:
        """
        Args:
            ai_engine: AIEngine instance for calling LLMs.
            notion_client: NotionClient for reading Notion databases.
            state_db: StateDB for persisting plan state.
        """
        self.ai = ai_engine
        self.state = state_db
        
        # Initialize the single-responsibility modules
        self.context_builder = PlanningContextBuilder(state_db, notion_client)
        self.prompt_builder = PlanningPromptBuilder()
        self.parser = PlanningParser()
        self.fallback = FallbackPlanner()
        
        # Load the immutable ProtocolSnapshot once
        self.protocol = ProtocolSnapshot()

    # ── Public API ──────────────────────────────────────────────────────────

    async def generate_daily_plan(
        self,
        day_type: str,
        coaching_days: list[str],
        homework: list[dict],
    ) -> PlanningResult:
        """Generate the daily study execution plan via AI.
        
        Args:
            day_type: "coaching" | "self_study" | "off_day"
            coaching_days: e.g. ["Mon", "Wed", "Fri"]
            homework: List of homework dicts.
            
        Returns:
            PlanningResult containing the ExecutionPlan.
        """
        today = datetime.now().strftime("%Y-%m-%d")

        # 1. Build Context
        context = await self.context_builder.build_context(homework)
        
        # 2. Build Prompt
        prompt = self.prompt_builder.build_daily_prompt(
            context=context,
            protocol=self.protocol,
            day_type=day_type,
            coaching_days=coaching_days
        )

        plan: ExecutionPlan
        used_fallback = False
        warnings = []
        ai_provider = None
        model = None

        try:
            # 3. Call AI
            raw_response = await self.ai.call(
                task_type="daily_plan",
                prompt=prompt,
                temperature=0.7,
                max_tokens=1024,
            )
            # The AI engine in this architecture doesn't return the exact provider in raw call easily, 
            # but we can try to get it if available, else omit.
            # 4. Parse AI Response
            plan = self.parser.parse_plan_response(raw_response, today, day_type)
            
        except Exception as e:
            logger.exception(f"Failed to generate daily plan via AI: {e}")
            warnings.append(f"AI generation failed: {e}")
            # 5. Fallback if AI or parsing fails
            plan = self.fallback.generate_fallback_plan(today, day_type, context.homework, self.protocol)
            used_fallback = True

        plan = StudyBlockEngine.normalize_plan(plan, today)

        # Wrap in PlanningResult
        result = PlanningResult(
            plan=plan,
            used_fallback=used_fallback,
            ai_provider=ai_provider,
            model=model,
            warnings=warnings
        )

        # Schedule block timeouts
        now = datetime.now()
        if now.hour < 12:
            stop = now.replace(hour=self.protocol.hard_stop_hour, minute=0, second=0)
        else:
            stop = (now + timedelta(days=1)).replace(
                hour=self.protocol.hard_stop_hour, minute=0, second=0
            )
        minutes_left = int((stop - now).total_seconds() / 60)
        logger.info("Generated plan. Hard stop in %d minutes", minutes_left)
        
        # Save state (Serialize Pydantic models to JSON)
        await self.state.set_state("plan_date", today)
        await self.state.set_state("current_plan", result.model_dump_json())
        await self.state.set_state("current_block_index", "0")
        await self.state.set_state("blocks_skipped_today", "0")
        await self.state.set_state("day_type", day_type)
        if hasattr(self.state, "save_study_blocks"):
            await self.state.save_study_blocks(today, [block.model_dump() for block in plan.blocks])
        if hasattr(self.state, "save_planner_decision"):
            level = await self.state.get_learning_confidence_level() if hasattr(self.state, "get_learning_confidence_level") else 0
            await self.state.save_planner_decision(
                {
                    "date": today,
                    "day_type": day_type,
                    "learning_confidence_level": level,
                    "used_fallback": used_fallback,
                    "block_ids": [block.block_id for block in plan.blocks],
                    "expected_cy": plan.total_expected_cy,
                    "expected_minutes": plan.total_expected_time,
                    "warnings": warnings,
                }
            )
        
        return result

    async def adapt_plan(self, user_request: str) -> PlanningResult:
        """Adapt the existing daily plan based on a user request."""
        current_plan_raw = await self.state.get_state("current_plan")
        if not current_plan_raw:
            raise ValueError("No active plan to adapt.")
            
        # Deserialize state to PlanningResult
        current_result = PlanningResult.model_validate_json(current_plan_raw)
        current_plan = current_result.plan
        
        prompt = (
            f"You are an expert, uncompromising study scheduler and strict mentor.\\n"
            f"The user has requested to change today's plan: '{user_request}'\\n\\n"
            f"CURRENT PLAN:\\n{current_plan.model_dump_json(indent=2)}\\n\\n"
            f"RULES:\\n"
            f"1. Preserve all mandatory 'EB' blocks if possible.\\n"
            f"2. Add actual 'start_time' and 'end_time' (HH:MM format) to every block.\\n"
            f"3. Ensure blocks do not overlap.\\n"
            f"4. Respect the hard stop hour of 01:00 AM.\\n"
            f"5. **CRITICAL CONSTRAINT:** If the user's request introduces an unreasonably long break (e.g., 4 or 5 hours) or breaks the hard-stop limit, you MUST REJECT IT.\\n"
            f"   If rejecting, return a JSON with exactly this structure: {{\"error\": \"true\", \"message\": \"[Your punchy, strict explanation of why this is unacceptable]\"}}\\n"
            f"6. If the request is reasonable, return ONLY valid JSON representing the new plan (same structure, but with start_time and end_time).\\n\\n"
            f"Return ONLY valid JSON."
        )
        
        try:
            import json
            raw_response = await self.ai.call(
                task_type="daily_plan",
                prompt=prompt,
                temperature=0.3,
                max_tokens=1024,
            )
            try:
                cleaned = raw_response.strip()
                if "```json" in cleaned:
                    cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0]
                elif "```" in cleaned:
                    cleaned = cleaned.split("```", 1)[1].split("```", 1)[0]
                cleaned = cleaned.strip()
                
                parsed_raw = json.loads(cleaned)
                if parsed_raw.get("error") == "true" or parsed_raw.get("error") is True:
                    raise ValueError(parsed_raw.get("message", "Request rejected by AI constraints."))
            except json.JSONDecodeError:
                pass

            today = datetime.now().strftime("%Y-%m-%d")
            # Reuse the parser for the adapted plan
            new_plan = self.parser.parse_plan_response(raw_response, today, current_plan.day_type)
            
            new_result = PlanningResult(
                plan=new_plan,
                used_fallback=False
            )
            
            # Save the new adapted plan
            await self.state.set_state("current_plan", new_result.model_dump_json())
            
            return new_result
        except Exception as e:
            logger.exception("Failed to adapt plan")
            raise e
