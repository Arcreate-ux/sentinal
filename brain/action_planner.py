from __future__ import annotations
import json
import logging
from sentinel.bot.schemas import IntentClassification
from sentinel.brain.actions import (
    AssistantRequest, ActionType,
    InsertBlock, MoveFlexibleBlocks, UpdateNotion,
    NotifyScheduler, SendReply, SwitchProvider, QueryDatabase
)

logger = logging.getLogger("sentinel.action_planner")

class ActionPlanner:
    """Translates high-level Intents into a sequence of concrete Actions."""
    
    def __init__(self, ai_engine, state_db, notion_client):
        self.ai = ai_engine
        self.state = state_db
        self.notion = notion_client

    async def plan_actions(self, text: str, intent_data: IntentClassification) -> AssistantRequest:
        """Evaluate context and intent to generate an execution plan."""
        intent = intent_data.intent
        tier = intent_data.complexity_tier
        
        # 1. Deterministic Rule-Based Actions (Fast path)
        if intent == "general":
            return AssistantRequest(
                intent=intent,
                reasoning="Rule-based fast path for general chat.",
                confidence="high",
                actions=[]
            )
            
        if intent == "reschedule":
            # For a reschedule, we might want the AI to plan the actions if it's complex,
            # or just emit deterministic actions if it's simple.
            # Let's ask the AI to generate the action plan for complex tasks.
            
            schema = AssistantRequest.model_json_schema()
            prompt = (
                f"The user wants to reschedule or adjust their plan.\n"
                f"Message: {text}\n"
                f"Generate a sequence of system actions to fulfill this request.\n"
                f"You MUST return a JSON object adhering exactly to this schema:\n{json.dumps(schema)}"
            )
            
            try:
                raw = await self.ai.call(
                    task_type="think",
                    prompt=prompt,
                    temperature=0.1,
                    max_tokens=512
                )
                # Quick clean JSON
                if "```json" in raw:
                    raw = raw.split("```json")[1].split("```")[0].strip()
                elif "```" in raw:
                    raw = raw.split("```")[1].strip()
                    
                request = AssistantRequest.model_validate_json(raw)
                return request
            except Exception as e:
                logger.error(f"Action planning failed: {e}", exc_info=True)
                return AssistantRequest(
                    intent="reschedule",
                    reasoning=f"LLM planner failed: {e}",
                    confidence="low",
                    actions=[SendReply(message="I encountered an error while planning the reschedule. Falling back to simple mode.")]
                )
                
        if intent == "system_command":
            entities = intent_data.get_system_entities()
            if entities.provider:
                return AssistantRequest(
                    intent=intent,
                    reasoning="Rule-based fast path for provider switch.",
                    confidence="high",
                    actions=[
                        SwitchProvider(provider=entities.provider),
                        SendReply(message=f"Switched provider to {entities.provider}.")
                    ]
                )
                
        # Fallback for unhandled intents
        return AssistantRequest(
            intent=intent,
            reasoning="Fallback action plan for unhandled intent.",
            confidence="low",
            actions=[]
        )
