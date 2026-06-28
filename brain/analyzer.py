"""
SENTINEL — Performance Analyzer (brain/analyzer.py)

Computes CY/TY metrics, analyses per-block performance against plan,
generates daily summaries, detects multi-day trends, and estimates the
gap to the IIT Bombay CS target score.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from sentinel.config import (
    DAILY_CY_TARGET,
    SUBJECTS,
    TARGET_IIT,
    TARGET_BRANCH,
    TARGET_JEE_SCORE,
    TIMEZONE,
)

logger = logging.getLogger("sentinel.analyzer")

class PerformanceAnalyzer:
    """Crunches study performance data and surfaces actionable insights."""

    def __init__(self, ai_engine, notion_client, state_db) -> None:
        self.ai = ai_engine
        self.notion = notion_client
        self.state = state_db

    # ── Block-level analysis ────────────────────────────────────────────────

    async def analyze_block_result(
        self,
        subject: str,
        ex_type: str,
        A: int,
        C: int,
        T: int,
        block_plan: dict,
    ) -> str:
        """Analyse a single block's performance and return a rival-style message.
        
        Args:
            subject: "Physics" | "Chem" | "Maths"
            ex_type: Exercise type, e.g. "Ex 2A"
            A: Attempted questions.
            C: Correct questions.
            T: Time taken in minutes.
            block_plan: The planned block dict (with expected_cy, target_time, etc.)
            
        Returns:
            A short, punchy competitive-rival analysis string.
        """
        from sentinel.notion_client.formulas import (
            cognitive_yield,
            accuracy_ratio,
            theory_yield,
        )
        
        cy = cognitive_yield(T, A, C, ex_type, subject)
        ty = theory_yield(T, A, C, ex_type, subject)
        acc = accuracy_ratio(A, C)
        
        planned_cy = block_plan.get("expected_cy", 0)
        planned_time = block_plan.get("target_time", 0)
        
        # CY comparison
        cy_diff = cy - planned_cy
        cy_emoji = "🟢" if cy_diff >= 0 else "🔴"
        
        # Time comparison
        time_diff = T - planned_time
        time_emoji = "⚡" if time_diff <= 0 else "🐢"
        
        # Accuracy tier
        if acc >= 0.9:
            acc_comment = "Surgical precision 🎯"
        elif acc >= 0.75:
            acc_comment = "Solid, not perfect."
        elif acc >= 0.6:
            acc_comment = "Sloppy. Tighten up."
        else:
            acc_comment = "Accuracy is bleeding. Fix this. 🩸"
            
        lines = [
            f"{'─' * 20}",
            f"📊 BLOCK RESULT: {subject} · {ex_type}",
            f"{'─' * 20}",
            f"  A={A} | C={C} | T={T}min",
            f"  {cy_emoji} CY: {cy} (plan: {planned_cy}, diff: {cy_diff:+d})",
            f"  📈 TY: {ty}",
            f"  🎯 Accuracy: {acc:.0%} — {acc_comment}",
            f"  {time_emoji} Time: {T}min (plan: {planned_time}min, diff: {time_diff:+d}min)",
        ]

        if cy_diff >= 10:
            lines.append("\n💪 Beat the plan. Good. Now raise the bar tomorrow.")
        elif cy_diff >= 0:
            lines.append("\n✅ On target. Consistency wins championships.")
        elif cy_diff >= -10:
            lines.append("\n⚠️ Slightly under. Don't let the next block slip too.")
        else:
            lines.append("\n🔥 Significantly under target. What happened? Recover NOW.")
            
        return "\n".join(lines)

    # ── Daily summary ───────────────────────────────────────────────────────

    async def generate_daily_summary(self, date: str) -> str:
        """Aggregate all blocks for the given date and generate an end-of-day summary.
        
        Args:
            date: ISO date string, e.g. "2026-06-22"
            
        Returns:
            Formatted daily summary message.
        """
        summary = await self.state.get_daily_summary(date)
        if not summary:
            # Try to compute from Notion data
            summary = await self._compute_summary_from_notion(date)
            
        if not summary:
            return f"📭 No data recorded for {date}. Ghost day."

        total_cy = summary.get("total_cy", 0)
        target_hit = total_cy >= DAILY_CY_TARGET
        pct = (total_cy / DAILY_CY_TARGET * 100) if DAILY_CY_TARGET > 0 else 0
        
        # Streak info
        streak = await self.state.get_streak("daily_target")
        streak_count = streak.get("current_count", 0) if streak else 0

        lines = [
            f"{'━' * 24}",
            f"🌙 END-OF-DAY REPORT — {date}",
            f"{'━' * 24}",
            "",
            f"{'✅' if target_hit else '❌'} Total CY: {total_cy}/{DAILY_CY_TARGET} ({pct:.0f}%)",
            "",
            "📚 Subject Breakdown:",
        ]
        
        for subj, prefix in [("Physics", "physics"), ("Chem", "chem"), ("Maths", "maths")]:
            cy_val = summary.get(f"{prefix}_cy", 0)
            ty_val = summary.get(f"{prefix}_ty", 0)
            lines.append(f"  {subj}: CY={cy_val} | TY={ty_val}")
            
        blocks_done = summary.get("blocks_completed", 0)
        blocks_skip = summary.get("blocks_skipped", 0)
        
        lines.extend([
            "",
            f"📦 Blocks: {blocks_done} completed, {blocks_skip} skipped",
            f"🔥 Streak: {streak_count} day{'s' if streak_count != 1 else ''}",
        ])
        
        if target_hit:
            lines.append("\n🏆 Target hit. Yesterday's you just lost. Keep stacking Ws.")
        else:
            deficit = DAILY_CY_TARGET - total_cy
            lines.append(f"\n😤 Fell short by {deficit} CY. Tomorrow is redemption.")
            
        # Faculty Escalation Check
        try:
            weak_subjects = await self.identify_weak_subjects()
            for w in weak_subjects:
                if w.get("avg_ty", 100) < 40 and w.get("ty_trend") == "declining":
                    lines.append(f"\n🚨 FACULTY ESCALATION REQUIRED 🚨")
                    lines.append(f"Your TY in {w['subject']} has plummeted to {w['avg_ty']} and is declining.")
                    lines.append(f"Do NOT study this alone tomorrow. Contact a mentor or faculty immediately to fix your conceptual leaks.")
                    break # One escalation per day is enough
        except Exception as e:
            logger.warning(f"Failed to check for faculty escalation: {e}")
            
        return "\n".join(lines)

    # ── Trend detection ─────────────────────────────────────────────────────

    async def detect_trends(self, days: int = 7) -> dict:
        """Analyse multi-day trends in CY, TY, and accuracy per subject.
        
        Args:
            days: Number of days to look back.
            
        Returns:
            Dict with per-subject trend data and overall trajectory.
        """
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        summaries = await self.state.get_summaries_range(start, end)
        if len(summaries) < 2:
            return {"status": "insufficient_data", "message": "Need at least 2 days of data."}
            
        trends: dict[str, Any] = {"period_days": days, "subjects": {}}
        
        for subj, prefix in [("Physics", "physics"), ("Chem", "chem"), ("Maths", "maths")]:
            cy_values = [s.get(f"{prefix}_cy", 0) for s in summaries]
            ty_values = [s.get(f"{prefix}_ty", 0) for s in summaries]
            
            cy_trend = self._compute_trend(cy_values)
            ty_trend = self._compute_trend(ty_values)
            
            trends["subjects"][subj] = {
                "cy_values": cy_values,
                "ty_values": ty_values,
                "cy_avg": round(sum(cy_values) / len(cy_values), 1) if cy_values else 0,
                "ty_avg": round(sum(ty_values) / len(ty_values), 1) if ty_values else 0,
                "cy_trend": cy_trend,
                "ty_trend": ty_trend,
            }
            
        # Overall
        total_cys = [s.get("total_cy", 0) for s in summaries]
        trends["overall"] = {
            "total_cy_values": total_cys,
            "avg_daily_cy": round(sum(total_cys) / len(total_cys), 1) if total_cys else 0,
            "days_on_target": sum(1 for v in total_cys if v >= DAILY_CY_TARGET),
            "total_days": len(total_cys),
            "trend": self._compute_trend(total_cys),
        }
        
        return trends

    # ── Weak subject identification ─────────────────────────────────────────

    async def identify_weak_subjects(self) -> list[dict]:
        """Return subjects sorted by weakness (lowest average TY first).
        
        Returns:
            List of dicts with subject, avg_ty, avg_cy, and weakness_score.
        """
        trends = await self.detect_trends(days=7)
        if trends.get("status") == "insufficient_data":
            # Fallback: use just today
            trends = await self.detect_trends(days=30)
            if trends.get("status") == "insufficient_data":
                return []
                
        results = []
        for subj, data in trends.get("subjects", {}).items():
            avg_ty = data.get("ty_avg", 0)
            avg_cy = data.get("cy_avg", 0)
            ty_trend = data.get("ty_trend", "stable")
            
            # Weakness score: lower TY = weaker, declining trend = worse
            weakness = 100 - avg_ty  # Higher = weaker
            if ty_trend == "declining":
                weakness += 15
            elif ty_trend == "rising":
                weakness -= 10
                
            results.append({
                "subject": subj,
                "avg_ty": avg_ty,
                "avg_cy": avg_cy,
                "ty_trend": ty_trend,
                "weakness_score": round(weakness, 1),
            })
            
        results.sort(key=lambda x: x["weakness_score"], reverse=True)
        return results

    # ── IIT gap estimation ──────────────────────────────────────────────────

    async def compute_iit_gap(self) -> dict:
        """Estimate the gap between current projected JEE score and the IIT target.
        Uses a simplified projection based on recent accuracy and CY trends.
        
        Returns:
            Dict with projected_score, target_score, gap, subject_projections.
        """
        trends = await self.detect_trends(days=14)
        if trends.get("status") == "insufficient_data":
            return {
                "status": "insufficient_data",
                "message": "Need more daily data to project JEE score.",
                "target": TARGET_JEE_SCORE,
            }
            
        # Simplified projection: scale TY into marks
        # JEE Advanced: 54 questions total (~18 per subject), 360 marks total, ~120 per subject
        subject_projections: dict[str, dict] = {}
        total_projected = 0.0
        
        for subj, data in trends.get("subjects", {}).items():
            avg_ty = data.get("ty_avg", 0)
            
            # TY is a quality metric; map it to an expected fraction of marks
            # A TY of ~80+ is "excellent", ~60 is "good", below 40 is struggling
            projected_fraction = min(1.0, avg_ty / 90.0)
            subject_marks = round(120 * projected_fraction, 1)
            total_projected += subject_marks
            
            subject_projections[subj] = {
                "avg_ty": avg_ty,
                "ty_trend": data.get("ty_trend", "stable"),
                "projected_marks": subject_marks,
                "max_marks": 120,
            }
            
        gap = TARGET_JEE_SCORE - total_projected
        return {
            "status": "ok",
            "target_college": TARGET_IIT,
            "target_branch": TARGET_BRANCH,
            "target_score": TARGET_JEE_SCORE,
            "projected_score": round(total_projected, 1),
            "gap": round(gap, 1),
            "on_track": gap <= 0,
            "subjects": subject_projections,
        }

    # ── Private helpers ─────────────────────────────────────────────────────

    async def _compute_summary_from_notion(self, date: str) -> dict | None:
        """Attempt to compute daily summary from Notion DB1 rows."""
        try:
            rows = await self.notion.read_db1_rows(filters={"property": "Date", "date": {"equals": date}})
            if not rows:
                return None
                
            from sentinel.notion_client.formulas import (
                cognitive_yield,
                theory_yield,
            )
            
            totals: dict[str, Any] = {
                "total_cy": 0, "physics_cy": 0, "physics_ty": 0,
                "chem_cy": 0, "chem_ty": 0, "maths_cy": 0, "maths_ty": 0,
            }
            
            for row in rows:
                subj = row.get("subject", "")
                ex = row.get("exercise_type", "")
                T = row.get("time_taken", 0)
                A = row.get("attempted", 0)
                C = row.get("correct", 0)
                
                cy = cognitive_yield(T, A, C, ex, subj)
                ty = theory_yield(T, A, C, ex, subj)
                
                totals["total_cy"] += cy
                prefix = subj.lower() if subj.lower() in ("physics", "maths") else "chem"
                totals[f"{prefix}_cy"] = totals.get(f"{prefix}_cy", 0) + cy
                totals[f"{prefix}_ty"] = totals.get(f"{prefix}_ty", 0) + ty
                
            return totals
        except Exception:
            logger.warning("Failed to compute summary from Notion", exc_info=True)
            return None

    @staticmethod
    def _compute_trend(values: list[int | float]) -> str:
        """Simple trend detection: rising, declining, or stable.
        Uses linear slope over the value series.
        """
        if len(values) < 2:
            return "stable"
            
        n = len(values)
        x_mean = (n - 1) / 2
        y_mean = sum(values) / n
        
        numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        
        if denominator == 0:
            return "stable"
            
        slope = numerator / denominator
        
        # Normalise slope relative to mean
        if y_mean == 0:
            return "stable"
            
        relative_slope = slope / y_mean
        if relative_slope > 0.05:
            return "rising"
        elif relative_slope < -0.05:
            return "declining"
        return "stable"
