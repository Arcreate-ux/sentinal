"""
SENTINEL — Weekly Roaster (brain/roaster.py)
Generates brutal, motivating performance roasts based on weekly stats and daily blocks.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sentinel.brain.prompts import DEBRIEF_PROMPT_TEMPLATE, WEEKLY_ROAST_TEMPLATE
from sentinel.config import DAILY_CY_TARGET

logger = logging.getLogger("sentinel.roaster")


class WeeklyRoaster:
    """Analyzes performance and generates AI roasts/debriefs."""

    def __init__(self, ai_engine, notion_client, state_db):
        self.ai = ai_engine
        self.notion = notion_client
        self.state = state_db

    async def generate_block_roast(self, block_entry: dict[str, Any], plan: dict[str, Any]) -> str:
        """Generates an immediate roast/debrief for a single block."""
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            completed = await self.state.get_today_blocks(today)
            cy_so_far = sum(b.get("actual_cy", 0) for b in completed)
            cy_remaining = max(0, DAILY_CY_TARGET - cy_so_far)
            
            A = block_entry.get("A", 0)
            C = block_entry.get("C", 0)
            T = block_entry.get("T", 0)
            
            accuracy_pct = (C / A * 100) if A > 0 else 0.0
            time_per_q = (T / A) if A > 0 else 0.0
            
            prompt = DEBRIEF_PROMPT_TEMPLATE.format(
                block_name=block_entry.get("block_label", "Block"),
                subject=block_entry.get("subject", "Unknown"),
                exercise_type=block_entry.get("exercise_type", "Unknown"),
                attempted=A,
                correct=C,
                time_taken=T,
                total_questions=block_entry.get("expected_questions", A),
                target_time=block_entry.get("target_time", T),
                accuracy_pct=accuracy_pct,
                time_per_q=time_per_q,
                expected_tq=block_entry.get("expected_tq", 4.0),
                cy_earned=block_entry.get("actual_cy", 0),
                cy_today_total=cy_so_far,
                cy_remaining=cy_remaining,
                yesterday_accuracy=accuracy_pct, # Mocked for now
                yesterday_tq=time_per_q # Mocked for now
            )
            return await self.ai.call("weekly_roast", prompt, max_tokens=150)
        except Exception as exc:
            logger.error("Failed to generate block roast: %s", exc)
            return f"✅ Block completed. CY Earned: {block_entry.get('actual_cy', 0)}"

    async def generate_weekly_roast(self, start_date: str, end_date: str) -> str:
        """Generates the main weekly roast comparing against targets."""
        summaries = await self.state.get_summaries_range(start_date, end_date)
        if not summaries:
            return "💀 No data logged this week. Are you even trying for IIT Bombay?"
            
        total_cy = sum(s.get("total_cy", 0) for s in summaries)
        target_cy = DAILY_CY_TARGET * 7
        
        try:
            prompt = WEEKLY_ROAST_TEMPLATE.format(
                week_number=1,
                daily_cy_data=json.dumps(summaries),
                total_cy_week=total_cy,
                total_cy_target=target_cy,
                cy_hit_pct=(total_cy / target_cy * 100) if target_cy > 0 else 0,
                cy_hit_rate=50.0,
                best_day="Unknown",
                worst_day="Unknown",
                subject_breakdown="N/A",
                accuracy_trend="N/A",
                revision_compliance=0.0,
                weakest_topics="N/A",
                coaching_test_score="N/A",
                week_start=start_date,
                week_end=end_date,
                data_snapshot=json.dumps(summaries[:2]),
                daily_cy_target=DAILY_CY_TARGET,
                target_jee_score=320,
                subjects="Physics, Chem, Maths"
            )
            return await self.ai.call("weekly_roast", prompt, max_tokens=500)
        except Exception:
            logger.error("Failed to generate weekly roast via AI")
            if total_cy >= target_cy:
                return f"🔥 WEEKLY REPORT: {total_cy}/{target_cy} CY. Excellent work. IIT Bombay is watching."
            else:
                return f"💀 WEEKLY REPORT: {total_cy}/{target_cy} CY. Pathetic. This won't get you to IIT Bombay."
