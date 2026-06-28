"""
SENTINEL — Event Bus (brain/event_bus.py)

In-memory async pub-sub bus that routes events to subscribers
and persists them to the EventStore.
"""

import asyncio
import logging
from typing import Callable, Dict, List, Any, Coroutine
from sentinel.bot.events import BaseEvent
from sentinel.brain.event_store import EventStore

logger = logging.getLogger("sentinel.brain.event_bus")

# Type alias for subscribers: takes a BaseEvent and returns an awaitable
SubscriberFunc = Callable[[BaseEvent], Coroutine[Any, Any, None]]

class EventBus:
    def __init__(self, store: EventStore):
        self.store = store
        self.subscribers: Dict[str, List[SubscriberFunc]] = {}
        
    def subscribe(self, event_type: str, handler: SubscriberFunc) -> None:
        """Register a handler for a specific event type."""
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append(handler)
        logger.debug(f"Subscribed {handler.__name__} to {event_type}")

    async def publish(self, event: BaseEvent) -> None:
        """Publish an event to subscribers and persist it."""
        logger.info(f"EventBus Publishing: {event.event_type} from {event.source}")
        
        # 1. Persist the event first
        try:
            await self.store.append(event)
        except Exception as e:
            logger.error(f"Failed to persist event {event.event_id}: {e}", exc_info=True)
            
        # 2. Dispatch to subscribers
        handlers = self.subscribers.get(event.event_type, [])
        if not handlers:
            logger.debug(f"No subscribers for {event.event_type}")
            return
            
        # Run handlers concurrently
        tasks = [asyncio.create_task(self._safe_execute(handler, event)) for handler in handlers]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_execute(self, handler: SubscriberFunc, event: BaseEvent) -> None:
        try:
            await handler(event)
        except Exception as e:
            logger.error(f"Subscriber {handler.__name__} failed on {event.event_type}: {e}", exc_info=True)
