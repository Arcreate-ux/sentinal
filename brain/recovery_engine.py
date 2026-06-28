"""
SENTINEL — Recovery Engine (brain/recovery_engine.py)

The Opportunity Engine. Finds productive fallback work when a block ends early,
when the user is fatigued, or when time is lost. Rescues lost productivity without increasing stress.
"""

import json
import logging

logger = logging.getLogger("sentinel.brain.recovery_engine")

class RecoveryEngine:
    def __init__(self, ai_engine, state_db, notion_client, event_store=None, event_bus=None):
        self.ai = ai_engine
        self.state = state_db
        self.notion = notion_client
        self.store = event_store
        self.bus = event_bus

    async def get_recovery_action(self, trigger_type: str, available_minutes: int, current_subject: str = None) -> dict:
        """
        Calculates the best recovery action based on the trigger:
        - "fatigue": Mentally exhausted, need low friction.
        - "early_finish": Reached coaching early, lunch ended early, block done early.
        - "impossible_task": Cannot do the planned task.
        """
        logger.info(f"Running Recovery Engine for {trigger_type} ({available_minutes} mins)...")

        # 1. Gather context
        unresolved_concepts = await self.state.get_unresolved_concepts(subject=current_subject)
        
        # A lightweight version of recent learning events to find "skipped for time" questions
        recent_summaries = await self.state.get_summaries_range("2020-01-01", "2099-01-01")[-3:] # Mocking dates for now to get recent
        
        context_payload = {
            "trigger_type": trigger_type,
            "available_minutes": available_minutes,
            "current_subject": current_subject,
            "unresolved_concepts": unresolved_concepts[-5:] if unresolved_concepts else []
        }

        prompt = f"""
        You are the Recovery Engine (The Opportunity Engine).
        The user has encountered a disruption ({trigger_type}) and has {available_minutes} free minutes.
        
        CONTEXT:
        {json.dumps(context_payload, indent=2)}
        
        YOUR JOB:
        Find the highest-value, lowest-friction task they can realistically do in {available_minutes} minutes.
        Do NOT create new work. Rescue lost time.
        - If 'fatigue': Recommend reviewing an old concept or looking at already attempted questions. No heavy new theory.
        - If 'early_finish': Recommend finishing questions that were skipped strictly due to lack of time yesterday, or reviewing faculty doubts.
        
        Output STRICT JSON matching this schema:
        {{
            "action_type": "<string>",
            "description": "<What they should do right now>",
            "reasoning": "<Why this is the perfect task for their current state>",
            "confidence": <float>
        }}
        """

        try:
            raw_response = await self.ai.call(
                task_type="fast_decision", # High speed
                prompt=prompt,
                system_prompt="You are an opportunity-cost optimizer. Output ONLY raw JSON.",
                force_provider="gemini",
                force_model="gemini-2.5-pro"
            )
            
            cleaned = raw_response.strip()
            if "```json" in cleaned: cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0]
            elif "```" in cleaned: cleaned = cleaned.split("```", 1)[1].split("```", 1)[0]
                
            action = json.loads(cleaned.strip())
            return action
            
        except Exception as e:
            logger.error(f"Recovery Engine failed: {e}")
            return {"error": str(e)}

    async def check_proactive_recovery(self) -> dict:
        """
        Runs in the background to proactively evaluate if the user is likely to hit fatigue soon based on timeline rules.
        """
        logger.info("Running Proactive Recovery Check...")
        if not self.store:
            return {"error": "No Event Store available."}
            
        rules = await self.store.get_events(event_type="ExperienceRuleDiscovered", limit=5)
        fatigue_rules = [r.get("payload", {}).get("rule") for r in rules if "fatigue" in r.get("payload", {}).get("rule", "").lower()]
        
        if not fatigue_rules:
            return {"status": "No fatigue patterns detected in Experience Engine."}
            
        prompt = f"""
        You are the Proactive Recovery Engine.
        Analyze the student's historical fatigue patterns and decide if we should intervene NOW before they start the next block.
        
        FATIGUE PATTERNS (Experience Rules):
        {json.dumps(fatigue_rules, indent=2)}
        
        YOUR JOB:
        If they are about to hit a known fatigue pattern, suggest an alternative "Recovery Action" proactively (e.g. "Switch to revision first").
        
        Output STRICT JSON:
        {{
            "intervene": <bool>,
            "message": "<What to tell the user proactively, or null>"
        }}
        """
        try:
            raw_response = await self.ai.call(
                task_type="fast_decision",
                prompt=prompt,
                system_prompt="You predict fatigue and proactively suggest recovery tasks.",
                max_tokens=150
            )
            cleaned = raw_response.strip()
            if "```json" in cleaned: cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0]
            elif "```" in cleaned: cleaned = cleaned.split("```", 1)[1].split("```", 1)[0]
            
            result = json.loads(cleaned.strip())
            
            if result.get("intervene") and self.bus:
                import time
                import uuid
                from sentinel.bot.events import RecoverySuggested
                event = RecoverySuggested(
                    event_id=str(uuid.uuid4()),
                    timestamp=time.time(),
                    payload=result
                )
                await self.bus.publish(event)
                
            return result
        except Exception as e:
            logger.error(f"Proactive recovery failed: {e}")
            return {"error": str(e)}
