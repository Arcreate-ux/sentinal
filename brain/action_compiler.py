"""
SENTINEL — Action Compiler (brain/action_compiler.py)

Deterministic translation from the Planner's ExecutionPlan (Actions) 
into strict ToolCalls for the Execution Engine. 
No LLM is used here.
"""

import logging
from typing import List
from pydantic import BaseModel

from sentinel.brain.actions import Action, ActionType
from sentinel.brain.tool_registry import ToolRegistry, SendReplySchema, SwitchProviderSchema, UpdateNotionSchema

logger = logging.getLogger("sentinel.action_compiler")

class ToolCall(BaseModel):
    tool_name: str
    params: BaseModel

class ActionCompiler:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def compile(self, actions: List[Action]) -> List[ToolCall]:
        """
        Translates a list of abstract Actions into concrete ToolCalls.
        This provides a layer of indirection so one Action can map to multiple ToolCalls 
        if needed, and ensures strict type-safety before execution.
        """
        tool_calls = []
        
        for action in actions:
            try:
                calls = self._compile_action(action)
                tool_calls.extend(calls)
            except Exception as e:
                logger.error(f"Failed to compile action {action.action_type}: {e}")
                raise ValueError(f"Compilation failed for action {action.action_type}: {e}")
                
        return tool_calls

    def _compile_action(self, action: Action) -> List[ToolCall]:
        """Map a single abstract Action to one or more concrete ToolCalls."""
        if action.action_type == ActionType.SEND_REPLY:
            return [
                ToolCall(
                    tool_name="send_reply",
                    params=SendReplySchema(message=action.message)
                )
            ]
            
        elif action.action_type == ActionType.SWITCH_PROVIDER:
            return [
                ToolCall(
                    tool_name="switch_provider",
                    params=SwitchProviderSchema(provider=action.provider)
                )
            ]
            
        elif action.action_type == ActionType.UPDATE_NOTION:
            return [
                ToolCall(
                    tool_name="update_notion",
                    params=UpdateNotionSchema(
                        target_database=action.target_database,
                        payload=action.payload
                    )
                )
            ]
            
        # ── Future mappings (Phase 2/3) ──
        # Example: InsertBlock action might compile into multiple tool calls:
        # 1. Update DB2
        # 2. Update Timeline
        # 3. Notify Scheduler
        
        elif action.action_type == ActionType.INSERT_BLOCK:
            logger.warning("INSERT_BLOCK compiler logic stubbed.")
            # For now, just a dummy mapping
            return []
            
        elif action.action_type == ActionType.NOTIFY_SCHEDULER:
            logger.warning("NOTIFY_SCHEDULER compiler logic stubbed.")
            return []
            
        elif action.action_type == ActionType.QUERY_DATABASE:
            logger.warning("QUERY_DATABASE compiler logic stubbed.")
            return []
            
        elif action.action_type == ActionType.MOVE_FLEXIBLE:
            logger.warning("MOVE_FLEXIBLE compiler logic stubbed.")
            return []
            
        raise NotImplementedError(f"Action type {action.action_type} has no compiler mapping.")
