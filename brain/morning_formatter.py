"""
SENTINEL — Morning Formatter (brain/morning_formatter.py)
Translates the final ExecutionPlan into a readable Telegram message.
"""

from sentinel.brain.contracts import ExecutionPlan

class MorningFormatter:
    def format_morning_briefing(self, plan: ExecutionPlan) -> str:
        """Format the daily plan into a morning briefing message for Telegram."""
        day_type_fmt = plan.day_type.replace('_', ' ').title()
        
        lines = [
            f"📅 DAY PLAN — {plan.date}",
            f"{'━' * 24}",
            f"Type: {day_type_fmt}",
            f"Target CY: {plan.total_expected_cy}",
            f"Target Time: {plan.total_expected_time} min\n"
        ]
        
        for idx, block in enumerate(plan.blocks):
            label = block.block_label
            subj = block.subject
            ex = block.exercise_type
            qs = block.question_count
            t = block.target_time
            cy = block.expected_cy
            lines.append(f"📦 {label} | {subj} {ex} ({qs}Q) | {t}m → {cy} CY")
            
        lines.append("\nTime to go to war with yesterday's you. ⚔️")
        return "\n".join(lines)
