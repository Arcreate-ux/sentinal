"""
SENTINEL — Planning Engine (brain/planning_engine.py)

Implements the Midnight Optimization Role-Based AI Committee.
- Historian (Python): Fetches recent recommendations and their tested outcomes.
- Planner (GPT-4o): Proposes an optimized strategy.
- Critic (Gemini 2.5 Pro): Finds flaws and hidden risks.
- Coach (Local/Command R): Evaluates psychological sustainability.
- Policy Verifier (Python): Rejects impossible schedules (e.g. out of time).
- Final Reviewer (Gemini 2.5 Pro): Synthesizes the final Battle Plan and Briefing.
"""

import json
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger("sentinel.brain.planning_engine")

class PlanningEngine:
    """The Midnight Optimization Committee."""

    def __init__(self, ai_engine, notion_client, state_db, event_store=None, event_bus=None, memory_engine=None):
        self.ai = ai_engine
        self.notion = notion_client
        self.state = state_db
        self.store = event_store
        self.bus = event_bus
        self.memory = memory_engine

    async def run_midnight_optimization(self, manual_notion_plan: str, today_diagnosis: dict, available_time_mins: int = 240) -> dict:
        """
        Runs the full Role-Based AI Committee pipeline.
        Returns the final optimized Battle Plan dict.
        """
        logger.info("Starting Midnight Optimization Committee...")

        # 0. The Historian (Python Retrieval)
        recent_recs = await self.state.get_recent_recommendations(limit=5)
        historian_context = []
        for r in recent_recs:
            if r.get("applied") is True:
                historian_context.append(f"Tested: '{r['recommendation_text']}'. Effectiveness: {r.get('effectiveness_score')}.")
            elif r.get("applied") is False:
                historian_context.append(f"Ignored: '{r['recommendation_text']}'. Reason: {r.get('reason_ignored')}.")
                
        # Historian Prediction Tracking
        prediction_feedback = "No previous prediction data available."
        if self.store:
            past_plans = await self.store.get_events(event_type="BattlePlanGenerated", limit=1)
            if past_plans:
                last_plan = past_plans[0].get("payload", {})
                predicted_cy = last_plan.get("predicted_total_cy")
                if predicted_cy:
                    actual_cy = today_diagnosis.get("summary", {}).get("total_cy", 0)
                    variance = actual_cy - predicted_cy
                    if variance < 0:
                        prediction_feedback = f"Yesterday you predicted {predicted_cy} CY, but reality was {actual_cy} CY (Error: {variance}). You are overestimating capacity. Adjust time estimates downward."
                    else:
                        prediction_feedback = f"Yesterday you predicted {predicted_cy} CY, and reality was {actual_cy} CY. Good calibration."

        # Memory Engine (The Librarian) Context
        librarian_context = {}
        if self.memory:
            # Try to get the weakest subject from today to fetch relevant deep memory
            target_subject = today_diagnosis.get("weak_subjects", ["Physics"])[0]
            librarian_context = await self.memory.retrieve_context_bundle(subject=target_subject)
            
            # Compute a data-driven historical multiplier for the prompt
            profiles = librarian_context.get("relevant_concept_profiles", [])
            if profiles:
                # E.g. if average confidence is 0.4, we might need 1.5x time
                avg_conf = sum(p.get("confidence_score", 0.5) for p in profiles) / len(profiles)
                historical_multiplier = round(1.0 + (1.0 - avg_conf), 2)
                librarian_context["historical_multiplier"] = historical_multiplier

        # Context package
        context = {
            "user_draft_plan": manual_notion_plan,
            "today_diagnosis": today_diagnosis,
            "historian_memory": historian_context,
            "prediction_feedback": prediction_feedback,
            "librarian_memory": librarian_context,
            "available_time_mins": available_time_mins,
            "date": datetime.now().strftime("%Y-%m-%d")
        }
        context_str = json.dumps(context, indent=2)

        # 1. The Planner (GPT-4o or fastest high-tier model)
        planner_prompt = f"""
        You are the STRICT PLANNER.
        Look at the user's drafted Notion plan, today's diagnosis, the Historian's memory, and the Librarian's deep memory bundle.
        Produce a hyper-optimized schedule for tomorrow. 
        Focus strictly on fixing the root cause from today's diagnosis.
        If the Librarian provides a 'historical_multiplier' > 1.0 for a weak concept, MULTIPLY the estimated time block duration for that subject by that factor.
        CONTEXT: {context_str}
        
        Output a detailed strategic proposal.
        """
        logger.info("  -> Calling Planner...")
        planner_draft = await self.ai.call(
            task_type="daily_plan",
            prompt=planner_prompt,
            system_prompt="You are an expert strategic planner.",
            force_provider="g4f_pro",
            force_model="gpt-4o"
        )

        # 2. The Critic (Gemini Pro)
        critic_prompt = f"""
        You are the CRITIC.
        Review the PLANNER's draft. Find flaws, impossible assumptions, and hidden risks.
        
        PLANNER'S DRAFT:
        {planner_draft}
        
        CONTEXT:
        {context_str}
        
        Output your harsh critique.
        """
        logger.info("  -> Calling Critic...")
        critic_feedback = await self.ai.call(
            task_type="daily_plan",
            prompt=critic_prompt,
            system_prompt="You are a ruthless critic. Find the weaknesses.",
            force_provider="gemini",
            force_model="gemini-2.5-pro"
        )

        # 3. The Coach (Fallback/Fast model)
        coach_prompt = f"""
        You are the COACH.
        Review the PLANNER's draft and the CRITIC's feedback.
        Is this psychologically sustainable? Will it cause burnout?
        
        PLANNER: {planner_draft}
        CRITIC: {critic_feedback}
        
        Output your assessment on sustainability.
        """
        logger.info("  -> Calling Coach...")
        coach_feedback = await self.ai.call(
            task_type="daily_plan",
            prompt=coach_prompt,
            system_prompt="You are a psychological coach ensuring long-term sustainability.",
            force_provider="g4f_pro",
            force_model="gpt-4o"
        )

        # 4. Python Verification (Policy Check)
        logger.info("  -> Policy Verification Layer...")
        # Since we don't have the final JSON yet, we ask a strict JSON parser to just extract the TOTAL TIME proposed
        time_check_prompt = f"From this plan, what is the total proposed study time in minutes? Reply ONLY with an integer. PLAN: {planner_draft}"
        try:
            time_str = await self.ai.call("parser", time_check_prompt, max_tokens=10)
            proposed_time = int(time_str.strip())
            if proposed_time > available_time_mins + 30: # 30 min grace
                logger.warning(f"Policy Violation: Proposed {proposed_time}m, Available {available_time_mins}m")
                planner_draft += f"\n\n[POLICY ENGINE INJECTION: Your plan requires {proposed_time}m but only {available_time_mins}m is available. The Reviewer must cut tasks to fit this limit.]"
        except Exception:
            logger.warning("Policy Engine failed to extract time, skipping hard check.")

        # 5. Final Reviewer (Gemini Pro) -> Output JSON
        final_prompt = f"""
        You are the FINAL REVIEWER.
        Synthesize the committee's work into the final JSON Battle Plan.
        Pay extreme attention to any [POLICY ENGINE INJECTION] notes.
        
        PLANNER: {planner_draft}
        CRITIC: {critic_feedback}
        COACH: {coach_feedback}
        
        Output STRICT JSON matching this schema:
        {{
            "date": "{context['date']}",
            "predicted_total_cy": <float estimated Cognitive Yield for tomorrow>,
            "briefing_message": "<The Telegram message the user wakes up to>",
            "blocks": [
                {{"block_label": "EB-1", "subject": "Chem", "exercise_type": "Theory", "target_time": 45}}
            ]
        }}
        """
        logger.info("  -> Calling Final Reviewer...")
        final_json_str = await self.ai.call(
            task_type="daily_plan",
            prompt=final_prompt,
            system_prompt="You are the executive reviewer. Output ONLY valid JSON.",
            force_provider="gemini",
            force_model="gemini-2.5-pro"
        )

        # 6. The Scheduler (Python Deterministic Parsing)
        try:
            cleaned = final_json_str.strip()
            if "```json" in cleaned: cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0]
            elif "```" in cleaned: cleaned = cleaned.split("```", 1)[1].split("```", 1)[0]
                
            battle_plan = json.loads(cleaned.strip())
            
            await self.state.set_state("plan_date", battle_plan.get("date"))
            await self.state.set_state("current_plan", json.dumps(battle_plan))
            
            if self.bus:
                import time
                import uuid
                from sentinel.bot.events import BattlePlanGenerated
                event = BattlePlanGenerated(
                    event_id=str(uuid.uuid4()),
                    timestamp=time.time(),
                    payload=battle_plan
                )
                await self.bus.publish(event)
            
            logger.info("Midnight Optimization complete.")
            return battle_plan
            
        except Exception as e:
            logger.error(f"Scheduler failed to parse final JSON: {e}")
            return {"error": str(e), "fallback_triggered": True}
