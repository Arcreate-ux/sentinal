"""
SENTINEL — Telegram Bot Handler (bot/telegram_handler.py)

Wires up the python-telegram-bot Application, registers command and
message handlers, and provides an API for the scheduler to send proactive
messages (block prompts, timeouts, briefings, summaries).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from sentinel.bot.commands import (
    cmd_help,
    cmd_homework,
    cmd_plan,
    cmd_roast,
    cmd_scores,
    cmd_sick,
    cmd_skip,
    cmd_start,
    cmd_status,
    cmd_sync,
    cmd_week,
    cmd_done,
    cmd_doubts,
)
from sentinel.config import (
    BOT_NAME,
    DAILY_CY_TARGET,
    TELEGRAM_CHAT_ID,
    TIMEZONE,
)

logger = logging.getLogger("sentinel.bot")

class SentinelBot:
    """Central Telegram bot that ties together all SENTINEL subsystems."""

    def __init__(
        self,
        token: str,
        notion_client,
        ai_engine,
        state_db,
        health_monitor,
        planner,
        analyzer,
        roaster,
        parser,
    ) -> None:
        from sentinel.brain.action_planner import ActionPlanner
        from sentinel.brain.executor import ActionExecutor
        from sentinel.brain.reflection_engine import ReflectionEngine
        from sentinel.brain.knowledge_engine import KnowledgeEngine
        
        self.token = token
        self.notion = notion_client
        self.ai = ai_engine
        self.state = state_db
        self.health = health_monitor
        self.parser = parser
        self.planner = planner
        self.analyzer = analyzer
        self.roaster = roaster
        self.reflection_engine = None
        
        # Core Orchestrator Dependency
        self.orchestrator = None # Will be injected by main.py
        
        self.app: Application | None = None
        self._chat_id: str = TELEGRAM_CHAT_ID or ""

    # ── Setup ───────────────────────────────────────────────────────────────

    def setup(self) -> Application:
        """Build the Application, register handlers, inject shared services.
        
        Returns:
            The configured Application instance.
        """
        builder = Application.builder().token(self.token)
        self.app = builder.build()

        # Inject shared services into bot_data so handlers can access them
        self.app.bot_data["planner"] = self.planner
        self.app.bot_data["analyzer"] = self.analyzer
        self.app.bot_data["roaster"] = self.roaster
        self.app.bot_data["parser"] = self.parser
        self.app.bot_data["notion"] = self.notion
        self.app.bot_data["state_db"] = self.state
        self.app.bot_data["health"] = self.health
        self.app.bot_data["bot_ref"] = self  # For scheduler to reach send_message

        from telegram.ext import TypeHandler, ApplicationHandlerStop
        from sentinel.config import TELEGRAM_ALLOWED_USERS

        async def allowlist_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            user_id = None
            username = None
            if update.message and update.message.from_user:
                user_id = str(update.message.from_user.id)
                username = update.message.from_user.username
            elif update.callback_query and update.callback_query.from_user:
                user_id = str(update.callback_query.from_user.id)
                username = update.callback_query.from_user.username
                
            if TELEGRAM_ALLOWED_USERS and user_id:
                if user_id not in TELEGRAM_ALLOWED_USERS and (not username or username not in TELEGRAM_ALLOWED_USERS):
                    logger.warning(f"Blocked unauthorized access from user_id: {user_id}, username: {username}")
                    raise ApplicationHandlerStop

        self.app.add_handler(TypeHandler(Update, allowlist_check), group=-1)

        # Register command handlers dynamically
        from sentinel.bot.commands import COMMANDS
        for handler in COMMANDS:
            name = handler.__name__[4:]
            self.app.add_handler(CommandHandler(name, handler))

        # Register the generic message handler (non-command text)
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )

        # Error handler
        self.app.add_error_handler(self._error_handler)

        logger.info("SentinelBot setup complete — %d command handlers registered", len(COMMANDS))
        return self.app

    # ── Message handler ─────────────────────────────────────────────────────

    async def handle_message(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Adapter logic: Route non-command messages purely to the Orchestrator."""
        text = update.message.text.strip()
        if not text:
            return

        if not self.orchestrator:
            await update.message.reply_text("⚠️ Orchestrator not attached.")
            return

        async def reply_callback(msg: str):
            await update.message.reply_text(msg, parse_mode="Markdown")

        context_obj = {"update": update, "context": context}
        
        try:
            await self.orchestrator.handle(text, reply_callback, context_obj)
        except Exception as e:
            logger.error(f"Failed to route message to Orchestrator: {e}", exc_info=True)
            await reply_callback("⚠️ Critical system failure in the Brain.")

    async def _handle_mode(self, update: Update, context: ContextTypes.DEFAULT_TYPE, args: str) -> None:
        """Handle /mode [developer|study] to toggle system capabilities."""
        mode = args.strip().lower()
        if mode not in ["developer", "study"]:
            await update.message.reply_text("⚠️ Usage: /mode [developer|study]")
            return
            
        is_dev = (mode == "developer")
        await self.state.set_state("developer_mode", str(is_dev).lower())
        
        if is_dev:
            await update.message.reply_text("🔓 **Developer Mode Enabled**\nSystem-level tools and deep architecture operations unlocked.")
        else:
            await update.message.reply_text("🔒 **Study Mode Enabled**\nDistraction-free, strict JEE tracking mode.")

    # ── Scheduler API ───────────────────────────────────────────────────────

    async def send_message(self, text: str) -> None:
        """Send a message to the registered chat (used by scheduler)."""
        chat_id = await self._get_chat_id()
        if not chat_id:
            logger.warning("Tried to send message, but no chat_id registered.")
            return
            
        if not self.app or not self.app.bot:
            logger.warning("App or bot not initialized")
            return
            
        try:
            max_len = 4000
            if len(text) > max_len:
                text = text[:max_len] + "\n\n… (truncated)"
            
            # Simple retry loop for telegram messages
            import asyncio
            from telegram.error import TelegramError
            
            for attempt in range(3):
                try:
                    await self.app.bot.send_message(chat_id=chat_id, text=text)
                    return
                except TelegramError as e:
                    if attempt < 2:
                        await asyncio.sleep(1.5 ** attempt)
                    else:
                        raise e
        except Exception:
            logger.exception("Failed to send scheduled message")

    async def send_morning_briefing(self) -> None:
        """Send today's plan + intelligence, generating the plan first if needed."""
        from sentinel.brain.contracts import PlanningResult
        from sentinel.brain.morning_formatter import MorningFormatter
        from datetime import timedelta

        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        try:
            plan_date = await self.state.get_state("plan_date")
            raw = await self.state.get_state("current_plan")
            if plan_date == today and raw:
                result = PlanningResult.model_validate_json(raw)
            else:
                coaching_days_raw = await self.state.get_state("coaching_days")
                coaching_days = json.loads(coaching_days_raw) if coaching_days_raw else []
                weekday = datetime.now().strftime("%A")[:3]
                day_type = "coaching" if weekday in coaching_days else "self_study"
                homework_raw = await self.state.get_state("homework_pending")
                homework = json.loads(homework_raw) if homework_raw else []
                result = await self.planner.generate_daily_plan(day_type, coaching_days, homework)

            # Load extra context for rich briefing
            profile = await self.state.get_student_profile()
            yesterday_summary = await self.state.get_daily_summary(yesterday)
            streak = await self.state.get_streak("daily_target")
            unresolved = await self.state.get_unresolved_concepts()
            unresolved_count = len(unresolved) if unresolved else 0

            # Find weakest concept
            weakest_concept = None
            if unresolved:
                weakest_concept = unresolved[0].get("concept_name", "Unknown")

            # Homework count
            hw_raw = await self.state.get_state("homework_pending")
            homework_count = len(json.loads(hw_raw)) if hw_raw else 0

            msg = MorningFormatter().format_morning_briefing(
                plan=result.plan,
                profile=profile,
                yesterday_summary=yesterday_summary,
                streak=streak,
                unresolved_count=unresolved_count,
                homework_count=homework_count,
                weakest_concept=weakest_concept,
            )
            await self.send_message(msg)
        except Exception:
            logger.exception("Failed to send morning briefing")
            await self.send_message("⚠️ Morning briefing failed. Use /plan to generate it manually.")

    async def send_block_prompt(self, block) -> None:
        """Send a proactive prompt to start a block."""
        from sentinel.brain.prompts import BLOCK_PROMPT_TEMPLATE
        
        block_label = getattr(block, "block_label", "Block")
        subject = getattr(block, "subject", "?")
        ex_type = getattr(block, "exercise_type", "?")
        q_count = getattr(block, "expected_questions", 0)
        time_est = getattr(block, "expected_time_mins", 0)
        
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            completed = await self.state.get_today_blocks(today)
            cy_so_far = sum(b.get("actual_cy", 0) for b in completed)
            cy_remaining = max(0, DAILY_CY_TARGET - cy_so_far)
            
            prompt_text = BLOCK_PROMPT_TEMPLATE.format(
                block_label=block_label,
                block_name=block_label,
                subject=subject,
                exercise_type=ex_type,
                question_count=q_count,
                target_time=time_est,
                yesterday_cy_block=0,
                cy_so_far=cy_so_far,
                cy_remaining=cy_remaining,
            )
            
            # Get AI to personalise the prompt
            message = await self.ai.call(
                task_type="block_prompt",
                prompt=prompt_text,
                temperature=0.7,
                max_tokens=256,
            )
        except Exception:
            logger.warning("AI block prompt failed, using template")
            message = (
                f"⏱️ BLOCK START: {block_label}\n"
                f"{'━' * 24}\n"
                f"Subject: {subject}\n"
                f"Exercise: {ex_type}\n"
                f"Questions: {q_count}\n"
                f"Target time: {time_est} min\n\n"
                f"Clock's ticking. Go. 🔥"
            )
            
        await self.state.set_state("conversation_state", "awaiting_block_report")
        await self.state.set_state("block_start_time", datetime.now().isoformat())
        await self.send_message(message)

    async def send_timeout_ping(self, block, level: int) -> None:
        """Send an escalating timeout notification.
        
        Args:
            block: The current block (ExecutionBlock).
            level: Escalation level (1 = gentle, 2 = firm, 3 = aggressive).
        """
        from sentinel.brain.prompts import TIMEOUT_PING_TEMPLATE
        
        block_label = getattr(block, "block_label", "Block")
        subject = getattr(block, "subject", "?")
        minutes_late = level * 15
        cy_at_stake = getattr(block, "expected_cy", 0)
        
        try:
            template = TIMEOUT_PING_TEMPLATE.get(str(minutes_late), TIMEOUT_PING_TEMPLATE["45"])
            prompt_text = template.format(
                block_name=block_label,
                minutes_late=minutes_late,
                cy_at_stake=cy_at_stake,
            )
            message = await self.ai.call(
                task_type="timeout_ping",
                prompt=prompt_text,
                temperature=0.8,
                max_tokens=200,
            )
        except Exception:
            message = f"⚠️ You are {minutes_late} minutes late logging {block_label}."
            
        await self.send_message(message)

    async def send_daily_summary(self) -> None:
        """Calculate, log, and send the end-of-day summary."""
        today = datetime.now().strftime("%Y-%m-%d")
        completed = await self.state.get_today_blocks(today)
        
        skipped_raw = await self.state.get_state("blocks_skipped_today")
        skipped_count = int(skipped_raw) if skipped_raw else 0
        
        from sentinel.notion_client.formulas import (
            cognitive_yield,
            theory_yield,
        )
        
        totals = {
            "total_cy": 0,
            "physics_cy": 0, "physics_ty": 0,
            "chem_cy": 0, "chem_ty": 0,
            "maths_cy": 0, "maths_ty": 0,
        }
        subject_blocks = {"physics": 0, "chem": 0, "maths": 0}
        
        for b in completed:
            if str(b.get("status", "")).upper() == "SKIPPED":
                continue
            subj = b.get("subject", "")
            cy = b.get("actual_cy", 0)
            ex = b.get("exercise_type", "Ex 1A")
            A = b.get("A", 0)
            C = b.get("C", 0)
            T = b.get("T", 0)
            
            ty = theory_yield(T, A, C, ex, subj) if A else 0
            
            totals["total_cy"] += cy
            prefix = subj.lower() if subj.lower() in ("physics", "maths") else "chem"
            totals[f"{prefix}_cy"] += cy
            totals[f"{prefix}_ty"] += ty
            subject_blocks[prefix] += 1
            
        for p in ["physics", "chem", "maths"]:
            if subject_blocks[p] > 0:
                totals[f"{p}_ty"] = int(totals[f"{p}_ty"] / subject_blocks[p])
                
        blocks_done = sum(1 for b in completed if str(b.get("status", "")).upper() != "SKIPPED")
        day_type = await self.state.get_state("day_type") or "self_study"
        
        try:
            await self.state.save_daily_summary(
                target_date=today,
                total_cy=totals["total_cy"],
                physics_cy=totals["physics_cy"], physics_ty=totals["physics_ty"],
                chem_cy=totals["chem_cy"], chem_ty=totals["chem_ty"],
                maths_cy=totals["maths_cy"], maths_ty=totals["maths_ty"],
                blocks_completed=blocks_done,
                blocks_skipped=skipped_count,
                day_type=day_type,
            )

            if self.reflection_engine:
                try:
                    await self.reflection_engine.run_evening_reflection(today)
                except Exception:
                    logger.warning("Failed to append evening reflection telemetry", exc_info=True)
            
            # Update streak
            if totals["total_cy"] >= DAILY_CY_TARGET:
                await self.state.update_streak("daily_target", today)
                
            # Generate and send summary message
            summary_msg = await self.analyzer.generate_daily_summary(today)
            await self.send_message(summary_msg)
            logger.info("Daily summary sent for %s (CY=%d)", today, totals["total_cy"])
        except Exception:
            logger.exception("Failed to send daily summary")
            await self.send_message("⚠️ Daily summary generation failed.")

    # ── Internal ────────────────────────────────────────────────────────────

    async def _get_chat_id(self) -> str:
        """Resolve the chat ID from state or config."""
        stored = await self.state.get_state("chat_id")
        if stored:
            self._chat_id = stored
            return stored
        return self._chat_id

    @staticmethod
    async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Global error handler for the Telegram bot."""
        logger.error("Telegram handler error: %s", context.error, exc_info=context.error)
        if isinstance(update, Update) and update.message:
            try:
                await update.message.reply_text(
                    "⚠️ An internal error occurred. The system is still running."
                )
            except Exception:
                pass

    # ── Run ─────────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Start the bot (blocking). Use this for standalone testing.
        
        For production, the main.py entry point manages startup differently.
        """
        if not self.app:
            self.setup()
        logger.info("Starting SentinelBot polling…")
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)
