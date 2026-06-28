"""
SENTINEL — Scheduler Engine (scheduler/engine.py)
Manages background jobs and active block pacing for the study execution system.
Utilises APScheduler AsyncIOScheduler to run daily tasks (morning briefing,
daily summary, weekly roast), periodic health checks, and a self-healing polling
state machine to track current blocks and send timeout alerts.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, time as dt_time
import pytz
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from sentinel.config import (
    TIMEZONE,
    MORNING_BRIEFING_HOUR,
    BLOCK_TIMEOUT_MINUTES,
    API_HEALTH_CHECK_HOURS,
    NOTION_HEALTH_CHECK_HOURS,
)

logger = logging.getLogger("sentinel.scheduler")


class SentinelScheduler:
    """Central scheduling and pacing engine for SENTINEL."""

    def __init__(
        self,
        bot_ref: Any,
        state_db: Any,
        health_monitor: Any,
        roaster: Any,
    ) -> None:
        """
        Args:
            bot_ref: SentinelBot instance.
            state_db: StateDB instance.
            health_monitor: HealthMonitor instance.
            roaster: WeeklyRoaster instance.
        """
        self.bot = bot_ref
        self.state = state_db
        self.health = health_monitor
        self.roaster = roaster

        self.tz = pytz.timezone(TIMEZONE)
        self.scheduler = AsyncIOScheduler(timezone=self.tz)

        logger.info("SentinelScheduler initialized with timezone %s", TIMEZONE)

    # ── Lifecyle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background scheduler and schedule all jobs."""
        if self.scheduler.running:
            logger.warning("Scheduler is already running.")
            return

        self.schedule_all_jobs()
        self.scheduler.start()
        logger.info("SentinelScheduler started successfully.")

    def shutdown(self) -> None:
        """Shut down the background scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("SentinelScheduler shut down.")

    # ── Job Scheduling ──────────────────────────────────────────────────────

    def schedule_all_jobs(self) -> None:
        """Register all cron and periodic tasks with the scheduler."""
        # Clear existing jobs in case of restart/reschedule
        self.scheduler.remove_all_jobs()

        # 1. Morning Briefing: daily at MORNING_BRIEFING_HOUR:00
        self.scheduler.add_job(
            self.run_morning_briefing,
            trigger=CronTrigger(hour=MORNING_BRIEFING_HOUR, minute=0, timezone=self.tz),
            id="morning_briefing",
            name="Daily Morning Briefing",
            replace_existing=True,
        )

        # 2. Daily Summary: daily at 00:30 (half an hour before 1 AM hard stop)
        self.scheduler.add_job(
            self.run_daily_summary,
            trigger=CronTrigger(hour=0, minute=30, timezone=self.tz),
            id="daily_summary",
            name="Daily Performance Summary",
            replace_existing=True,
        )

        # 3. Weekly Roast: Sundays at 21:00 (9:00 PM)
        self.scheduler.add_job(
            self.run_weekly_roast,
            trigger=CronTrigger(day_of_week="sun", hour=21, minute=0, timezone=self.tz),
            id="weekly_roast",
            name="Weekly Performance Roast",
            replace_existing=True,
        )

        # 4. API Health Check: every API_HEALTH_CHECK_HOURS hours
        self.scheduler.add_job(
            self.health.check_api_health,
            trigger="interval",
            hours=API_HEALTH_CHECK_HOURS,
            id="api_health_check",
            name="API Health Check",
            replace_existing=True,
        )

        # 5. Notion Health Check: every NOTION_HEALTH_CHECK_HOURS hours
        self.scheduler.add_job(
            self.health.check_notion_health,
            trigger="interval",
            hours=NOTION_HEALTH_CHECK_HOURS,
            id="notion_health_check",
            name="Notion Health Check",
            replace_existing=True,
        )

        # 6. Active Block Pacing Poller: every 30 seconds
        self.scheduler.add_job(
            self.check_pacing_state_machine,
            trigger="interval",
            seconds=30,
            id="block_pacing",
            name="Active Block Pacing Poller",
            replace_existing=True,
        )

        logger.info("All Sentinel background jobs scheduled.")

    # ── Job Implementations ─────────────────────────────────────────────────

    async def run_morning_briefing(self) -> None:
        """Trigger morning briefing on the bot."""
        logger.info("Running daily morning briefing job...")
        await self.bot.send_morning_briefing()

    async def run_daily_summary(self) -> None:
        """Trigger daily summary on the bot."""
        logger.info("Running daily summary job...")
        await self.bot.send_daily_summary()

    async def run_weekly_roast(self) -> None:
        """Trigger weekly roast and send it to registered chat."""
        logger.info("Running weekly roast job...")
        today = datetime.now(self.tz)
        # Week range: Monday to Sunday
        week_start = (today - __import__("datetime").timedelta(days=today.weekday())).strftime("%Y-%m-%d")
        week_end = today.strftime("%Y-%m-%d")

        try:
            roast_text = await self.roaster.generate_weekly_roast(week_start, week_end)
            await self.bot.send_message(roast_text)
        except Exception:
            logger.exception("Failed to run scheduled weekly roast")
            await self.bot.send_message("❌ Weekly roast failed. Even the AI is disappointed in you.")

    # ── Active Block Pacing (Self-Healing State Machine) ───────────────────

    async def check_pacing_state_machine(self) -> None:
        """Polls the state DB to manage dynamic block pacing and timeouts.
        This is completely self-healing across bot restarts because all state
        is persisted in SQLite.
        """
        try:
            await self._run_pacing_loop()
        except Exception as e:
            logger.error("Unhandled exception in pacing state machine: %s", e, exc_info=True)

    async def _run_pacing_loop(self) -> None:
        # 1. Skip if on off_day
        day_type = await self.state.get_state("day_type")
        if day_type == "off_day":
            return

        # 2. Skip if no active plan for today
        plan_date = await self.state.get_state("plan_date")
        today_str = datetime.now(self.tz).strftime("%Y-%m-%d")
        if plan_date != today_str:
            return

        # 3. Read current block index
        current_idx_raw = await self.state.get_state("current_block_index")
        if current_idx_raw is None:
            return
            
        try:
            idx = int(current_idx_raw)
        except (ValueError, TypeError):
            logger.warning("Invalid current_block_index: %s. Resetting to 0.", current_idx_raw)
            await self.state.set_state("current_block_index", "0")
            idx = 0

        # 4. Load plan blocks
        plan_raw = await self.state.get_state("current_plan")
        if not plan_raw:
            return
            
        try:
            from sentinel.brain.contracts import PlanningResult
            result = PlanningResult.model_validate_json(plan_raw)
            plan = result.plan
        except Exception as e:
            logger.error(f"Failed to parse current plan JSON in scheduler: {e}")
            return
            
        blocks = plan.blocks
        if not blocks or idx >= len(blocks):
            # All blocks completed/skipped
            return
            
        block = blocks[idx]
        block_label = block.block_label

        # 5. Read block pacing state
        active_block_label = await self.state.get_state("active_block_label")
        block_start_time_raw = await self.state.get_state("block_start_time")

        # Case A: Block Transition (New block active)
        if active_block_label != block_label:
            logger.info("Pacing state machine: Transitioning from '%s' to '%s'", active_block_label, block_label)
            await self.state.set_state("active_block_label", block_label)
            await self.state.set_state("block_start_time", datetime.now(self.tz).isoformat())
            await self.state.set_state("timeout_level_sent", "0")
            
            # Prompt the user for this new block
            await self.bot.send_block_prompt(block)
            return

        # Case B: Currently in block execution
        if not block_start_time_raw:
            # Fallback if start time is missing
            await self.state.set_state("block_start_time", datetime.now(self.tz).isoformat())
            return
            
        try:
            start_time = datetime.fromisoformat(block_start_time_raw)
        except ValueError:
            logger.warning("Invalid block_start_time in state: %s", block_start_time_raw)
            await self.state.set_state("block_start_time", datetime.now(self.tz).isoformat())
            return

        # Parse timezone-aware or naive comparison safely
        if start_time.tzinfo is None:
            start_time = self.tz.localize(start_time)
            
        now = datetime.now(self.tz)
        elapsed_minutes = (now - start_time).total_seconds() / 60
        target_time = block.target_time or 60
        overdue_minutes = elapsed_minutes - target_time

        # Check timeouts
        if overdue_minutes >= BLOCK_TIMEOUT_MINUTES:
            timeout_level_raw = await self.state.get_state("timeout_level_sent") or "0"
            level = int(timeout_level_raw)
            
            # Level 1: Overdue by >= 15 min
            if level < 1 and overdue_minutes < BLOCK_TIMEOUT_MINUTES + 15:
                logger.warning("Block %s timeout Level 1 (overdue by %.1f min)", block_label, overdue_minutes)
                await self.state.set_state("timeout_level_sent", "1")
                await self.bot.send_timeout_ping(block, level=1)
                
            # Level 2: Overdue by >= 30 min
            elif level < 2 and BLOCK_TIMEOUT_MINUTES + 15 <= overdue_minutes < BLOCK_TIMEOUT_MINUTES + 30:
                logger.warning("Block %s timeout Level 2 (overdue by %.1f min)", block_label, overdue_minutes)
                await self.state.set_state("timeout_level_sent", "2")
                await self.bot.send_timeout_ping(block, level=2)
                
            # Level 3: Overdue by >= 45 min
            elif level < 3 and overdue_minutes >= BLOCK_TIMEOUT_MINUTES + 30:
                logger.warning("Block %s timeout Level 3 (overdue by %.1f min)", block_label, overdue_minutes)
                await self.state.set_state("timeout_level_sent", "3")
                await self.bot.send_timeout_ping(block, level=3)

    async def cancel_block_jobs(self) -> None:
        """Clear active block state to allow immediate transition or halt.
        Used by /skip and /sick command handlers to update pacing.
        """
        logger.info("Scheduler: Cancelling active block jobs state.")
        await self.state.set_state("active_block_label", "")
        await self.state.set_state("block_start_time", "")
        await self.state.set_state("timeout_level_sent", "0")
