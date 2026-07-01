"""
SENTINEL — Main Entry Point (main.py)

Boots and coordinates all SENTINEL subsystems:
1. Validates configuration and environment variables.
2. Initializes SQLite State DB.
3. Performs Notion DB4 (System Log) auto-creation/registration.
4. Spawns and injects all modules (AI Engine, Notion Client, Health Monitor,
   Planner, Analyzer, Roaster, Parser, Telegram Bot, Scheduler).
5. Registers graceful shutdown handlers for OS signals.
"""

from __future__ import annotations

# IPv4 Monkeypatch: Fixes IPv6 blackhole timeouts on Hugging Face Spaces
import socket
_orig_getaddrinfo = socket.getaddrinfo
def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = getaddrinfo_ipv4

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any

import telegram

from sentinel import config
from sentinel.state.database import StateDB
from sentinel.notion_client.client import NotionClient
from sentinel.brain.ai_engine import AIEngine
from sentinel.health.monitor import HealthMonitor
from sentinel.brain.planner import DailyPlanner
from sentinel.brain.analyzer import PerformanceAnalyzer
from sentinel.brain.roaster import WeeklyRoaster
from sentinel.bot.parsers import MessageParser
from sentinel.bot.telegram_handler import SentinelBot
from sentinel.scheduler.engine import SentinelScheduler

from sentinel.brain.orchestrator import Orchestrator
from sentinel.brain.context_builder import ContextBuilder
from sentinel.brain.memory_engine import MemoryEngine
from sentinel.brain.action_planner import ActionPlanner
from sentinel.brain.executor import ActionExecutor
from sentinel.brain.reflection_engine import ReflectionEngine
from sentinel.brain.event_store import EventStore
from sentinel.brain.event_bus import EventBus
from sentinel.brain.experience_engine import ExperienceEngine
from sentinel.brain.recovery_engine import RecoveryEngine
from sentinel.brain.coaching_engine import CoachingEngine
from sentinel.brain.learning_updater import LearningModelUpdater
from sentinel.brain.knowledge_engine import KnowledgeEngine
from sentinel.brain.personal_memory import PersonalMemory
from sentinel.bot.events import KnowledgeExtracted

# Configure logging
config.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.LOG_PATH, encoding="utf-8"),
    ],
)
logger = logging.getLogger("sentinel.main")


# update_env_file removed for 12-factor cloud compatibility


class SentinelApplication:
    """Manages the startup, orchestration, and teardown of Project SENTINEL."""

    def __init__(self) -> None:
        self.state_db: StateDB | None = None
        self.ai_engine: AIEngine | None = None
        self.notion_client: NotionClient | None = None
        self.health_monitor: HealthMonitor | None = None
        self.planner: DailyPlanner | None = None
        self.analyzer: PerformanceAnalyzer | None = None
        self.roaster: WeeklyRoaster | None = None
        self.parser: MessageParser | None = None
        self.orchestrator: Orchestrator | None = None
        self.bot: SentinelBot | None = None
        self.scheduler: SentinelScheduler | None = None
        self.reflection_engine: ReflectionEngine | None = None
        self.knowledge_engine: KnowledgeEngine | None = None
        self.personal_memory: PersonalMemory | None = None
        
        self.is_shutting_down = False

    async def boot(self) -> None:
        """Run the startup sequence for all subsystems."""
        logger.info("⚙️ Booting Project SENTINEL...")
        
        # 1. Validate Config
        errors = config.validate_config()
        if errors:
            logger.critical("❌ Boot configuration validation failed:")
            for err in errors:
                logger.critical("   - %s", err)
            logger.critical("Please check your .env configuration. Exiting.")
            sys.exit(1)

        # 2. Init MongoDB State Database
        logger.info("Initializing State Database...")
        self.state_db = StateDB()
        await self.state_db.init_db()

        # 3. Create/Connect Notion Client
        logger.info("Connecting to Notion integration...")
        self.notion_client = NotionClient()
        await self.notion_client.__aenter__()

        # Handle DB4 (System Log) Auto-creation
        if not config.NOTION_DB4_ID:
            logger.info("NOTION_DB4_ID not found. Checking Notion workspace for existing System Log...")
            try:
                db4_id = await self.notion_client.create_db4_if_not_exists()
                logger.info("📌 Auto-resolved NOTION_DB4_ID: %s", db4_id)
                config.NOTION_DB4_ID = db4_id
            except Exception as exc:
                logger.critical("❌ Failed to resolve or create Notion DB4 (System Log): %s", exc)
                sys.exit(1)

        # 4. Instantiate Services
        self.ai_engine = AIEngine(state_db=self.state_db)
        
        # Core Events Layer
        self.event_store = EventStore(self.state_db)
        self.event_bus = EventBus(self.event_store)
        
        # Sub-Engines
        self.knowledge_engine = KnowledgeEngine(self.ai_engine, self.state_db, event_bus=self.event_bus)
        self.experience_engine = ExperienceEngine(self.ai_engine, self.event_store, self.event_bus)
        self.recovery_engine = RecoveryEngine(self.ai_engine, self.state_db, self.notion_client, self.event_store, self.event_bus)
        self.coaching_engine = CoachingEngine(self.ai_engine, self.state_db, self.notion_client)
        self.learning_updater = LearningModelUpdater(self.state_db)
        self.reflection_engine = ReflectionEngine(self.ai_engine, self.state_db, self.notion_client)
        self.personal_memory = PersonalMemory(self.ai_engine, self.state_db)
        
        # Wiring Event Subscriptions
        self.event_bus.subscribe("KnowledgeExtracted", self.learning_updater.handle_knowledge_extracted)
        
        self.health_monitor = HealthMonitor(
            ai_engine=self.ai_engine,
            notion_client=self.notion_client,
            state_db=self.state_db,
        )
        
        self.planner = DailyPlanner(
            ai_engine=self.ai_engine,
            notion_client=self.notion_client,
            state_db=self.state_db,
        )
        
        self.analyzer = PerformanceAnalyzer(
            ai_engine=self.ai_engine,
            notion_client=self.notion_client,
            state_db=self.state_db,
        )
        
        self.roaster = WeeklyRoaster(
            ai_engine=self.ai_engine,
            notion_client=self.notion_client,
            state_db=self.state_db,
        )
        
        self.parser = MessageParser(
            ai_engine=self.ai_engine,
        )
        
        logger.info("Initializing Orchestrator Core...")
        self.orchestrator = Orchestrator(
            state_db=self.state_db,
            context_builder=ContextBuilder(self.state_db, self.notion_client, self.event_store),
            memory_engine=MemoryEngine(self.state_db, self.notion_client),
            parser=self.parser,
            action_planner=ActionPlanner(self.ai_engine, self.state_db, self.notion_client),
            executor=ActionExecutor(self.ai_engine, self.notion_client, self.state_db),
            reflection_engine=self.reflection_engine,
            knowledge_engine=self.knowledge_engine,
            analyzer=self.analyzer,
            notion_client=self.notion_client,
            personal_memory=self.personal_memory,
            ai_engine=self.ai_engine,
        )

        # 5. Initialize Telegram Bot
        logger.info("Initializing Telegram Bot...")
        self.bot = SentinelBot(
            token=config.TELEGRAM_BOT_TOKEN,
            notion_client=self.notion_client,
            ai_engine=self.ai_engine,
            state_db=self.state_db,
            health_monitor=self.health_monitor,
            planner=self.planner,
            analyzer=self.analyzer,
            roaster=self.roaster,
            parser=self.parser,
        )
        self.bot.orchestrator = self.orchestrator
        self.bot.reflection_engine = self.reflection_engine
        bot_app = self.bot.setup()

        # 6. Initialize Scheduler
        logger.info("Initializing Scheduler Engine...")
        self.scheduler = SentinelScheduler(
            bot_ref=self.bot,
            state_db=self.state_db,
            health_monitor=self.health_monitor,
            roaster=self.roaster,
        )
        
        # Cross-inject scheduler into Telegram bot_data so command handlers can access it
        bot_app.bot_data["scheduler"] = self.scheduler
        bot_app.bot_data["reflection_engine"] = self.reflection_engine
        bot_app.bot_data["knowledge_engine"] = self.knowledge_engine
        bot_app.bot_data["personal_memory"] = self.personal_memory

        # 7. Start Scheduler
        self.scheduler.start()

        # 8. Start Telegram Bot Polling (This will run in its own event loops/tasks)
        logger.info("⚔️ SENTINEL ONLINE AND RUNNING.")
        
        # Trigger an initial health check on startup
        asyncio.create_task(self.health_monitor.get_system_status())
        
        # Start bot polling in a non-blocking way using python-telegram-bot's initialization flow
        await bot_app.initialize()
        await bot_app.start()
        await bot_app.updater.start_polling(allowed_updates=telegram.Update.ALL_TYPES if hasattr(telegram, "Update") else None)

        # 9. Start a lightweight HTTP Health Check Server (required for free hosts like Render/Koyeb)
        port = int(os.environ.get("PORT", "8080"))
        logger.info("Starting HTTP health check server on port %d...", port)
        from http.server import SimpleHTTPRequestHandler, HTTPServer
        import threading
        
        class HealthCheckHandler(SimpleHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(b"SENTINEL is active.")
                
            def log_message(self, format, *args):
                # Suppress flood of access logs in the console
                return
                
        httpd = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        server_thread.start()

        # Keep running until cancelled
        while not self.is_shutting_down:
            await asyncio.sleep(1.0)
            
        # Clean shutdown sequence
        logger.info("Initiating graceful shutdown sequence...")
        
        # Stop HTTP Server
        logger.info("Stopping HTTP health check server...")
        httpd.shutdown()
        httpd.server_close()
        
        # Stop Bot
        logger.info("Stopping Telegram Bot...")
        await bot_app.updater.stop()
        await bot_app.stop()
        await bot_app.shutdown()
        
        # Stop Scheduler
        logger.info("Stopping Scheduler...")
        self.scheduler.shutdown()
        
        # Close clients
        logger.info("Closing API connections...")
        await self.ai_engine.close()
        await self.notion_client.__aexit__(None, None, None)
        self.state_db.close()
        
        logger.info("💀 SENTINEL OFFLINE.")

    def shutdown(self, signum: int, frame: Any) -> None:
        """OS Signal handler to set shutdown flag."""
        logger.info("Received signal %d. Shutting down...", signum)
        self.is_shutting_down = True


def main() -> None:
    """Main execution block."""
    app = SentinelApplication()
    
    # Register OS signals
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, app.shutdown)
        except ValueError:
            # Signal library might fail on some platforms if not on main thread
            pass
            
    try:
        asyncio.run(app.boot())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown initiated by keyboard interrupt or exit.")
    except Exception as exc:
        logger.critical("Fatal crash during main execution", exc_info=exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
