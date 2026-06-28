"""
SENTINEL — Event Store (brain/event_store.py)

Appends immutable events to the timeline in MongoDB.
Provides replay and query functionality.
"""

import logging
from typing import List, Optional
from sentinel.bot.events import BaseEvent
from pymongo.collection import Collection

logger = logging.getLogger("sentinel.brain.event_store")

class EventStore:
    def __init__(self, state_db):
        self.state_db = state_db
        # We rely on StateDB providing a direct motor collection if we had motor, 
        # but since StateDB abstracts it, we will use StateDB to store events.
        
    async def append(self, event: BaseEvent) -> None:
        """Append an event to the immutable ledger."""
        logger.debug(f"Appending event to store: {event.event_type} ({event.event_id})")
        # Ensure collection exists or use the abstraction in state_db
        try:
            db = self.state_db._get_db()
            collection = db.timeline_events
            doc = event.model_dump()
            await collection.insert_one(doc)
        except Exception as e:
            logger.warning(f"Failed to append to EventStore: {e}")

    async def get_events(self, event_type: Optional[str] = None, limit: int = 100) -> List[dict]:
        """Fetch historical events."""
        try:
            db = self.state_db._get_db()
            collection = db.timeline_events
            query = {"event_type": event_type} if event_type else {}
            cursor = collection.find(query).sort("timestamp", -1).limit(limit)
            return await cursor.to_list(length=limit)
        except Exception as e:
            logger.warning(f"Failed to fetch from EventStore: {e}")
            return []

    async def replay(self) -> None:
        """Replay events (stub for future use)."""
        logger.info("Replaying events from Timeline...")
        # Implementation for replaying state changes
        pass
