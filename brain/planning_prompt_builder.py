"""
SENTINEL — Planning Prompt Builder (brain/planning_prompt_builder.py)
Serializes typed models into JSON and assembles the LLM prompt.
"""

from datetime import datetime
from sentinel.brain.prompts import DAILY_PLAN_PROMPT_TEMPLATE
from sentinel.brain.contracts import PlanningContext
from sentinel.brain.protocol.snapshot import ProtocolSnapshot

class PlanningPromptBuilder:
    def build_daily_prompt(
        self,
        context: PlanningContext,
        protocol: ProtocolSnapshot,
        day_type: str,
        coaching_days: list
    ) -> str:
        """
        Serializes context and protocol objects and injects them into the prompt.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        weekday = datetime.now().strftime("%A")

        # 1. Format Yesterday's Summary
        if context.yesterday_summary.raw_data:
            yesterday_cy = context.yesterday_summary.total_cy
            yesterday_ty = (
                context.yesterday_summary.physics_ty +
                context.yesterday_summary.chem_ty +
                context.yesterday_summary.maths_ty
            )
            yesterday_str = context.yesterday_summary.model_dump_json(indent=2)
        else:
            yesterday_cy = 0
            yesterday_ty = 0
            yesterday_str = '{"error": "No data for yesterday"}'

        # 2. Format Streak
        streak_status = f"{context.streak.current_count} days"

        # 3. Format Revision Backlog
        if context.revision_backlog:
            # We only show top 10 items in the prompt to save tokens
            items_dump = [item.model_dump() for item in context.revision_backlog[:10]]
            backlog_payload = {
                "count": len(context.revision_backlog),
                "items": items_dump
            }
            import json
            revision_backlog_str = json.dumps(backlog_payload, indent=2)
        else:
            revision_backlog_str = '{"count": 0, "items": []}'

        # 4. Format Homework
        if context.homework:
            homework_str = "[" + ",\n".join(hw.model_dump_json() for hw in context.homework) + "]"
        else:
            homework_str = '{"count": 0, "items": []}'

        # Build prompt using Protocol Snapshot
        import json
        prompt = DAILY_PLAN_PROMPT_TEMPLATE.format(
            today_date=today,
            weekday=weekday,
            day_type=day_type,
            coaching_schedule=", ".join(coaching_days) if coaching_days else "None set",
            yesterday_summary=yesterday_str,
            yesterday_cy=yesterday_cy,
            yesterday_ty=yesterday_ty,
            streak_status=streak_status,
            revision_backlog=revision_backlog_str,
            coaching_homework=homework_str,
            learning_confidence_level=context.learning_confidence_level,
            daily_cy_target=protocol.daily_cy_target,
            hard_stop_hour=protocol.hard_stop_hour,
            subjects=", ".join(protocol.subjects),
            exercise_types=", ".join(protocol.exercise_types),
            block_types=", ".join(protocol.block_types),
            tq_table=json.dumps(protocol.t_q_table, indent=2),
        )
        return prompt
