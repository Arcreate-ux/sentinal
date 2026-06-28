"""
SENTINEL — Context Builder (brain/context_builder.py)

Builds the unified context bundle (World State) required by the Brain and Runtime.
Replaces the scattered context aggregation in the Orchestrator.
"""

import logging
from typing import Any, Dict
from datetime import datetime, timezone
import json

logger = logging.getLogger("sentinel.brain.context_builder")

class ContextBuilder:
    def __init__(self, state_db, notion_client, event_store):
        self.state = state_db
        self.notion = notion_client
        self.store = event_store

    async def build_context(self, user_message: str, intent_data: Any = None) -> Dict[str, Any]:
        """Assembles the immutable World State bundle."""
        logger.debug("Building unified context bundle...")
        
        # 1. World State (Core Environment)
        world_state = {
            "current_time_utc": datetime.now(timezone.utc).isoformat(),
            "mode": await self.state.get_state("mode", "study"),
            "conversation_state": await self.state.get_state("conversation_state", "idle")
        }
        
        # 2. Working Memory (Current session / active plan)
        raw_plan = await self.state.get_state("current_plan")
        working_memory = {
            "active_plan": json.loads(raw_plan) if raw_plan else None,
            "current_block_index": int(await self.state.get_state("current_block_index") or 0)
        }
        
        # 3. Long-term Memory (Recent Timeline Events)
        recent_events = await self.store.get_events(limit=10)
        long_term_memory = {
            "recent_timeline": [
                {"type": e.get("event_type"), "timestamp": e.get("timestamp")} for e in recent_events
            ]
        }
        
        # 4. Capabilities (Healthy Providers)
        capabilities = {
            "healthy_providers": await self.state.get_healthy_providers()
        }
        
        # 5. Prediction (Experience Rules & Historian)
        # Fetching rules from the DB (assuming we save ExperienceRules somewhere, for now we just fetch recent rule events)
        rule_events = await self.store.get_events(event_type="ExperienceRuleDiscovered", limit=5)
        predictions = {
            "active_rules": [r.get("payload", {}).get("rule") for r in rule_events]
        }
        
        bundle = {
            "user_objective": user_message,
            "world_state": world_state,
            "working_memory": working_memory,
            "long_term_memory": long_term_memory,
            "capabilities": capabilities,
            "predictions": predictions
        }
        
        return bundle
