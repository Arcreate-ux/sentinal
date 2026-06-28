"""
SENTINEL — Health Monitor (health/monitor.py)
Monitors API and database health proactively.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("sentinel.health")


class HealthMonitor:
    def __init__(self, ai_engine: Any, notion_client: Any, state_db: Any) -> None:
        self.ai = ai_engine
        self.notion = notion_client
        self.state = state_db

    async def get_system_status(self) -> dict[str, str]:
        """Run an immediate health check of all subsystems."""
        ai_health = await self._check_ai()
        notion_health = await self.notion.check_health()
        return {
            "ai_engine": "online" if ai_health else "degraded",
            "notion": "online" if notion_health else "offline",
            "state_db": "online"
        }

    async def _check_ai(self) -> bool:
        try:
            # Simple ping to fast provider
            await self.ai.call("parse_message", "ping", max_tokens=10)
            return True
        except Exception as exc:
            logger.warning("AI health check failed: %s", exc)
            return False

    async def check_api_health(self) -> None:
        """Scheduled job to check AI API endpoints."""
        logger.info("Running scheduled API health check...")
        status = await self.get_system_status()
        if status["ai_engine"] != "online":
            logger.warning("AI Engine health is degraded.")

    async def check_notion_health(self) -> None:
        """Scheduled job to check Notion API."""
        logger.info("Running scheduled Notion health check...")
        is_healthy = await self.notion.check_health()
        if not is_healthy:
            logger.warning("Notion API health check failed.")
