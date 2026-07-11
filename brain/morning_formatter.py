"""
SENTINEL — Morning Formatter (brain/morning_formatter.py)
Translates the final ExecutionPlan + context into a rich morning briefing.
"""

import json
from datetime import date

from sentinel.brain.contracts import ExecutionPlan


class MorningFormatter:
    def _build_morning_header(self, profile: dict | None) -> list[str]:
        """Build the morning header with date, JEE countdown, and coaching exam countdown."""
        today = date.today()
        lines = []

        # Date line
        date_str = today.strftime("%A, %d %B %Y")
        lines.append(f"📅 {date_str}")

        # JEE countdown
        jee_date_str = profile.get("jee_exam_date") if profile else None
        if not jee_date_str:
            jee_date_str = profile.get("jee_main_date") if profile else None
        if jee_date_str:
            try:
                jee_days = (date.fromisoformat(jee_date_str) - today).days
                lines.append(f"⏳ JEE Main: {jee_days} days left")
            except ValueError:
                lines.append(f"⏳ JEE Main: ? days left")
        jee_adv_str = profile.get("jee_advanced_date") if profile else None
        if jee_adv_str:
            try:
                adv_days = (date.fromisoformat(jee_adv_str) - today).days
                lines.append(f"🚀 JEE Advanced: {adv_days} days left")
            except ValueError:
                pass

        # Coaching exam countdown
        coaching_date_str = profile.get("next_coaching_exam_date") if profile else None
        if coaching_date_str:
            try:
                coaching_days = (date.fromisoformat(coaching_date_str) - today).days
                if coaching_days >= 0:
                    lines.append(f"📝 Coaching Exam: {coaching_days} days left")
                else:
                    lines.append(f"📝 Coaching Exam: OVERDUE by {-coaching_days} days")
            except ValueError:
                lines.append(f"📝 Coaching Exam: ? days left")

        # Coaching exam syllabus
        syllabus = profile.get("coaching_exam_syllabus", "") if profile else ""
        if syllabus:
            syllabus_short = syllabus[:60] + "..." if len(syllabus) > 60 else syllabus
            lines.append(f"📚 Syllabus: {syllabus_short}")

        return lines

    def format_morning_briefing(
        self,
        plan: ExecutionPlan,
        profile: dict | None = None,
        yesterday_summary: dict | None = None,
        streak: dict | None = None,
        unresolved_count: int = 0,
        homework_count: int = 0,
        weakest_concept: str | None = None,
    ) -> str:
        """Format the daily plan + intelligence into a rich morning briefing for Telegram."""
        name = profile.get("name", "Soldier") if profile else "Soldier"
        day_type_fmt = plan.day_type.replace("_", " ").title()
        today = date.today()

        lines = [f"Good Morning, {name}.", ""]

        # Morning header with countdowns
        header_lines = self._build_morning_header(profile)
        if header_lines:
            lines.append(f"{'━' * 26}")
            for hl in header_lines:
                lines.append(hl)
            lines.append(f"{'━' * 26}")
            lines.append("")

        # Yesterday's performance
        if yesterday_summary:
            ycy = yesterday_summary.get("total_cy", 0)
            target = 240
            hit = "✅" if ycy >= target else "❌"
            lines.append(f"📊 YESTERDAY: CY {ycy}/{target} {hit}")
            skipped = yesterday_summary.get("blocks_skipped", 0)
            if skipped > 0:
                lines.append(f"⚠️ Skipped {skipped} block(s) yesterday")
            lines.append("")

        # Streak
        if streak:
            streak_count = streak.get("current_count", 0)
            best = streak.get("best_count", 0)
            lines.append(f"🔥 Streak: {streak_count} days (best: {best})")
        lines.append("")

        # Pending work summary
        if homework_count > 0 or unresolved_count > 0 or weakest_concept:
            lines.append("📋 PENDING")
            if homework_count > 0:
                lines.append(f"  Homework: {homework_count} items")
            if unresolved_count > 0:
                lines.append(f"  Unresolved doubts: {unresolved_count}")
            if weakest_concept:
                lines.append(f"  Weakest: {weakest_concept}")
            lines.append("")

        # Burnout risk detection
        if yesterday_summary:
            ycy = yesterday_summary.get("total_cy", 0)
            skipped = yesterday_summary.get("blocks_skipped", 0)
            if ycy < 120 or skipped >= 2:
                lines.append("⚠️ LOW ENERGY DETECTED — Yesterday was rough.")
                lines.append("Today's plan accounts for recovery. Don't beat yourself up.")
                lines.append("")

        # Plan blocks
        lines.append(f"━━━ TODAY'S BATTLE PLAN ({day_type_fmt}) ━━━")
        for block in plan.blocks:
            label = block.block_label
            subj = block.subject
            ex = block.exercise_type
            qs = block.question_count
            t = block.target_time
            cy = block.expected_cy
            lines.append(f"📦 {label} | {subj} {ex} ({qs}Q) | {t}m → {cy} CY")

        lines.append("")
        lines.append(f"Target: {plan.total_expected_cy} CY | {plan.total_expected_time} min")
        lines.append("Hard stop: 01:00 AM")
        lines.append("")
        lines.append("Time to go to war with yesterday's you. ⚔️")
        return "\n".join(lines)
