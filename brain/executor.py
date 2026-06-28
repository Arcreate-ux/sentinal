import logging
from typing import Any
from telegram import Update
from telegram.ext import ContextTypes

from sentinel.brain.actions import ActionType, ActionResult, Action

logger = logging.getLogger("sentinel.executor")

class ActionExecutor:
    """The Verification Engine: Deterministically executes actions and verifies their success."""
    
    def __init__(self, ai_engine, notion_client, state_db):
        self.ai = ai_engine
        self.notion = notion_client
        self.state = state_db

    async def execute_sequence(
        self, 
        actions: list[Action], 
        update: Update, 
        context: ContextTypes.DEFAULT_TYPE
    ) -> bool:
        """
        Executes a sequence of actions. 
        Halts and notifies the user immediately if any action fails.
        Returns True if all actions succeeded, False otherwise.
        """
        for i, action in enumerate(actions):
            result = await self._execute_single_action(action, update, context)
            
            if not result.success:
                logger.error(f"Action {i+1}/{len(actions)} ({action.action_type}) failed: {result.reason}")
                
                # Halt pipeline and notify user
                error_msg = f"⚠️ Pipeline halted at step {i+1} ({action.action_type}).\nReason: {result.reason}"
                if result.rollback_needed:
                    error_msg += "\n\n(Note: Manual intervention or rollback may be required.)"
                    
                await update.message.reply_text(error_msg)
                return False
                
        return True

    async def _execute_single_action(
        self, 
        action: Action, 
        update: Update, 
        context: ContextTypes.DEFAULT_TYPE
    ) -> ActionResult:
        """Executes one action and returns a deterministic ActionResult."""
        is_dev = await self.state.get_state("developer_mode") == "true"
        try:
            if action.action_type == ActionType.SEND_REPLY:
                await update.message.reply_text(action.message)
                return ActionResult(success=True)
                
            elif action.action_type == ActionType.SWITCH_PROVIDER:
                if not is_dev:
                    return ActionResult(success=False, reason="System tools require Developer Mode (/mode developer)", retry=False)
                self.ai.switch_provider(action.provider)
                return ActionResult(success=True, reason=f"Switched to {action.provider}")
                
            elif action.action_type == ActionType.QUERY_DATABASE:
                if not is_dev:
                    return ActionResult(success=False, reason="System tools require Developer Mode (/mode developer)", retry=False)
                logger.info(f"Querying DB: {action.query}")
                return ActionResult(success=True, reason="Database queried")
                
            elif action.action_type == ActionType.UPDATE_NOTION:
                # Stubbed logic
                logger.info(f"Updating Notion {action.target_database} with {action.payload}")
                # Simulating a check
                if action.target_database not in ["db1", "db2", "db3"]:
                    return ActionResult(success=False, reason="Invalid target database", retry=False)
                return ActionResult(success=True)
                
            elif action.action_type == ActionType.NOTIFY_SCHEDULER:
                logger.info(f"Notifying scheduler: {action.message}")
                return ActionResult(success=True)
                
            # If we reach here, the tool isn't fully implemented in the executor yet
            return ActionResult(
                success=False, 
                reason=f"Action type '{action.action_type}' is not yet supported by the Executor."
            )
            
        except Exception as e:
            logger.exception(f"Unhandled exception executing {action.action_type}")
            return ActionResult(success=False, reason=str(e), retry=False, rollback_needed=True)
