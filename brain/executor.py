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
                try:
                    import re
                    # Execute queries based on keywords or dates
                    dates = re.findall(r"\d{4}-\d{2}-\d{2}", action.query)
                    if len(dates) >= 2:
                        res = await self.state.get_blocks_range(dates[0], dates[1])
                        await update.message.reply_text(f"🔍 Found {len(res)} completed blocks from {dates[0]} to {dates[1]}.")
                    elif len(dates) == 1:
                        res = await self.state.get_today_blocks(dates[0])
                        await update.message.reply_text(f"🔍 Found {len(res)} completed blocks for {dates[0]}.")
                    else:
                        unresolved = await self.state.get_unresolved_concepts() or []
                        await update.message.reply_text(f"🔍 Database query processed. Unresolved concepts count: {len(unresolved)}")
                    return ActionResult(success=True)
                except Exception as e:
                    return ActionResult(success=False, reason=str(e))
                
            elif action.action_type == ActionType.UPDATE_NOTION:
                if action.target_database not in ["db1", "db2", "db3"]:
                    return ActionResult(success=False, reason="Invalid target database", retry=False)
                try:
                    if action.target_database == "db1":
                        await self.notion.create_db1_row(**action.payload)
                    else:
                        await self.notion.update_db2_db3(action.payload)
                    return ActionResult(success=True)
                except Exception as e:
                    return ActionResult(success=False, reason=f"Notion update failed: {e}", rollback_needed=True)
                
            elif action.action_type == ActionType.NOTIFY_SCHEDULER:
                scheduler = context.bot_data.get("scheduler")
                if scheduler:
                    # Let the scheduler know about changes
                    logger.info(f"Notifying scheduler: {action.message}")
                    await scheduler.cancel_block_jobs()
                return ActionResult(success=True)
                
            elif action.action_type == ActionType.INSERT_BLOCK:
                import uuid
                plan_raw = await self.state.get_state("current_plan")
                if not plan_raw:
                    return ActionResult(success=False, reason="No active plan to insert block into.")
                try:
                    from sentinel.brain.contracts import PlanningResult, ExecutionBlock
                    result = PlanningResult.model_validate_json(plan_raw)
                    plan = result.plan
                    
                    new_idx = len(plan.blocks) + 1
                    block_id = f"block-{uuid.uuid4().hex[:8]}"
                    new_block = ExecutionBlock(
                        decision_id=plan.decision_id,
                        block_id=block_id,
                        date=plan.date,
                        block_label=f"EB-{new_idx}",
                        subject=action.subject,
                        exercise_type="Ex 1A",
                        question_count=10,
                        target_time=action.duration_mins,
                        expected_cy=int(action.duration_mins * 1.5),
                        block_type=action.block_type or "homework",
                        status="PLANNED"
                    )
                    plan.blocks.append(new_block)
                    
                    await self.state.set_state("current_plan", result.model_dump_json())
                    await self.state.save_study_blocks(plan.date, [b.model_dump() for b in plan.blocks])
                    
                    scheduler = context.bot_data.get("scheduler")
                    if scheduler:
                        await scheduler.cancel_block_jobs()
                        
                    await update.message.reply_text(f"➕ Inserted block: {action.subject} ({action.duration_mins}m)")
                    return ActionResult(success=True)
                except Exception as e:
                    logger.error(f"INSERT_BLOCK failed: {e}")
                    return ActionResult(success=False, reason=str(e))
                    
            elif action.action_type == ActionType.MOVE_FLEXIBLE:
                plan_raw = await self.state.get_state("current_plan")
                if not plan_raw:
                    return ActionResult(success=False, reason="No active plan to shift.")
                try:
                    from datetime import datetime, timedelta
                    from sentinel.brain.contracts import PlanningResult
                    result = PlanningResult.model_validate_json(plan_raw)
                    plan = result.plan
                    
                    shift = timedelta(hours=action.hours_shifted)
                    shifted_count = 0
                    for block in plan.blocks:
                        if block.status == "PLANNED":
                            if block.start_time:
                                try:
                                    t = datetime.strptime(block.start_time, "%H:%M")
                                    block.start_time = (t + shift).strftime("%H:%M")
                                    shifted_count += 1
                                except ValueError:
                                    pass
                            if block.end_time:
                                try:
                                    t = datetime.strptime(block.end_time, "%H:%M")
                                    block.end_time = (t + shift).strftime("%H:%M")
                                except ValueError:
                                    pass
                                    
                    if shifted_count > 0:
                        await self.state.set_state("current_plan", result.model_dump_json())
                        await self.state.save_study_blocks(plan.date, [b.model_dump() for b in plan.blocks])
                        
                    scheduler = context.bot_data.get("scheduler")
                    if scheduler:
                        await scheduler.cancel_block_jobs()
                        
                    await update.message.reply_text(f"⏳ Shifted schedule by {action.hours_shifted} hours ({shifted_count} blocks adjusted).")
                    return ActionResult(success=True)
                except Exception as e:
                    logger.error(f"MOVE_FLEXIBLE failed: {e}")
                    return ActionResult(success=False, reason=str(e))
            
            return ActionResult(
                success=False, 
                reason=f"Action type '{action.action_type}' is not yet supported by the Executor."
            )
            
        except Exception as e:
            logger.exception(f"Unhandled exception executing {action.action_type}")
            return ActionResult(success=False, reason=str(e), retry=False, rollback_needed=True)
