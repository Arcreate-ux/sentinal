"""
SENTINEL — Coaching Engine (brain/coaching_engine.py)

Runs weekly. Analyzes up to 30 days of data to find the macro habit
or pattern that is causing the most damage (e.g. consistently failing
Chem theory before exams) and proposes a major schedule adjustment.
"""

import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("sentinel.brain.coaching_engine")

class CoachingEngine:
    def __init__(self, ai_engine, state_db, notion_client):
        self.ai = ai_engine
        self.state = state_db
        self.notion = notion_client

    async def run_weekly_coaching(self) -> dict:
        """
        Extracts the last 30 days of performance and knowledge assets,
        and generates a brutal coaching diagnosis.
        """
        logger.info("Starting Weekly Coaching Engine (Macro Analysis)...")
        
        # 1. Gather 30-day data
        end = datetime.now()
        start = end - timedelta(days=30)
        
        summaries = await self.state.get_summaries_range(
            start.strftime("%Y-%m-%d"), 
            end.strftime("%Y-%m-%d")
        )
        
        knowledge_assets = await self.state.get_unresolved_concepts()
        
        data_payload = {
            "days_analyzed": len(summaries),
            "summaries_sample": summaries[-7:] if summaries else [], # Last 7 days for detail
            "total_knowledge_assets": len(knowledge_assets),
            "recent_doubts": [
                a.get("concept_name", "Unknown Concept") 
                for a in knowledge_assets[-5:]
            ]
        }
        
        prompt = f"""
        You are a world-class, uncompromising JEE advanced coach.
        Review the student's last 30 days of study data and their recent knowledge gaps.
        
        DATA:
        {json.dumps(data_payload, indent=2)}
        
        YOUR JOB:
        1. Identify the SINGLE most damaging habit or pattern over the last month.
        2. Explain brutally why this habit will cost them their IIT Bombay CS goal.
        3. Propose a macro-schedule adjustment for next week to destroy this habit.
        
        Output STRICT JSON matching this schema:
        {{
            "damaging_habit": "<string>",
            "harsh_truth": "<string>",
            "macro_adjustment": "<string>"
        }}
        """
        
        try:
            raw_response = await self.ai.call(
                task_type="weekly_roast",
                prompt=prompt,
                system_prompt="You are an elite academic coach. Output ONLY raw JSON.",
                max_tokens=600
            )
            
            cleaned = raw_response.strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0]
            elif "```" in cleaned:
                cleaned = cleaned.split("```", 1)[1].split("```", 1)[0]
                
            coaching_report = json.loads(cleaned.strip())
            
            # Save the coaching report
            await self.state.set_state(f"coaching_report_{end.strftime('%Y_%W')}", json.dumps(coaching_report))
            return coaching_report
            
        except Exception as e:
            logger.error(f"Coaching Engine failed: {e}")
            return {"error": str(e)}
