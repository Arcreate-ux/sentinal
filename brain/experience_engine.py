"""
SENTINEL — Experience Engine (brain/experience_engine.py)

Runs periodically to analyze the immutable timeline and extract permanent
Personal Rules and Learning DNA. Emits ExperienceRuleDiscovered events.
"""

import logging
import json
import time
from typing import Any
from sentinel.bot.events import ExperienceRuleDiscovered
import uuid

logger = logging.getLogger("sentinel.brain.experience_engine")

class ExperienceEngine:
    def __init__(self, ai_engine, event_store, event_bus):
        self.ai = ai_engine
        self.store = event_store
        self.bus = event_bus

    async def analyze_timeline(self, days_back: int = 7) -> dict[str, Any]:
        """Analyzes the timeline for repeated patterns and emits rules."""
        logger.info(f"Running Experience Engine on last {days_back} days of timeline...")
        
        # Fetch reflection and recovery events
        reflections = await self.store.get_events(event_type="ReflectionCompleted", limit=50)
        recoveries = await self.store.get_events(event_type="RecoverySuggested", limit=50)
        
        if not reflections:
            return {"error": "Not enough timeline data to extract experience rules."}
            
        payload = {
            "recent_reflections": [r.get("payload", {}) for r in reflections],
            "recent_recoveries": [r.get("payload", {}) for r in recoveries]
        }
        
        prompt = f"""
        Analyze the student's recent timeline events to find ONE highly confident behavioral or learning rule.
        A rule is a permanent constraint or preference the Planner must respect (e.g. "Always start Chemistry with theory", "Homework > 90 mins causes fatigue").
        
        TIMELINE DATA:
        {json.dumps(payload, indent=2)}
        
        YOUR JOB:
        Identify a strong pattern. If none exists with high confidence, return null.
        
        Format strictly as JSON:
        {{
            "rule": "<The rule text or null>",
            "confidence": <float 0.0-1.0>,
            "evidence": "<Explanation based on the data>"
        }}
        """
        
        try:
            raw_response = await self.ai.call(
                task_type="parser",
                prompt=prompt,
                system_prompt="You are the Experience Engine. Output ONLY raw JSON.",
                max_tokens=400
            )
            
            cleaned = raw_response.strip()
            if "```json" in cleaned: cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0]
            elif "```" in cleaned: cleaned = cleaned.split("```", 1)[1].split("```", 1)[0]
                
            result = json.loads(cleaned.strip())
            
            if result.get("rule") and result.get("confidence", 0.0) >= 0.8:
                # Store it globally or emit an event
                event = ExperienceRuleDiscovered(
                    event_id=str(uuid.uuid4()),
                    timestamp=time.time(),
                    payload=result
                )
                await self.bus.publish(event)
                logger.info(f"Discovered new experience rule: {result['rule']}")
                
            return result
        except Exception as e:
            logger.error(f"Experience Engine failed: {e}")
            return {"error": str(e)}
