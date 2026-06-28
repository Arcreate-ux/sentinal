"""
SENTINEL — MongoDB State Database.
Provides persistent, thread-safe, asynchronous storage for state that doesn't belong
in Notion: daily summary caches, test scores, API health tracking, streak
counters, and arbitrary key-value state.
Uses PyMongo Async API to ensure non-blocking event loops.
"""
from __future__ import annotations
import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from pymongo import AsyncMongoClient
from pymongo.errors import ConnectionFailure

from sentinel import config

logger = logging.getLogger(__name__)

class StateDB:
    """Async MongoDB state manager for SENTINEL."""
    
    def __init__(self) -> None:
        self.uri = config.MONGODB_URI or "mongodb://localhost:27017/"
        self.db_name = config.MONGODB_DB_NAME or "sentinel_brain"
        self._client: AsyncMongoClient | None = None
        self._db = None

    def _get_db(self):
        """Return the MongoDB database, connecting if needed."""
        if self._client is None:
            self._client = AsyncMongoClient(self.uri)
            self._db = self._client[self.db_name]
        return self._db

    def close(self) -> None:
        """Close the database connection."""
        if self._client:
            self._client.close()
            self._client = None

    async def init_db(self) -> None:
        """Initialize indexes if needed. In MongoDB, collections are created on first write."""
        db = self._get_db()
        try:
            await self._client.admin.command("ping")
            logger.info("MongoDB connection verified.")
        except ConnectionFailure as e:
            logger.critical(f"MongoDB unreachable at {self.uri}: {e}")
            raise
            
        try:
            await db.system_state.create_index("key", unique=True)
            await db.daily_summary.create_index("date", unique=True)
            await db.api_health.create_index("provider", unique=True)
            await db.streaks.create_index("streak_type", unique=True)
            await db.chat_history.create_index("timestamp")
            await db.completed_blocks.create_index("date")
            await db.archived_questions.create_index("timestamp")
            await db.concept_assets.create_index("concept_name", unique=True)
            await db.skill_assets.create_index([("skill_name", 1), ("subject", 1)], unique=True)
            logger.info(f"MongoDB initialized at {self.uri} (DB: {self.db_name})")
        except ConnectionFailure as e:
            logger.error(f"Failed to connect to MongoDB: {e}")

    # ─────────────────────────────────────────────────────────────────────
    # SYSTEM STATE
    # ─────────────────────────────────────────────────────────────────────
    async def get_state(self, key: str, default: str | None = None) -> str | None:
        if key == "completed_blocks":
            raise ValueError("Access to raw 'completed_blocks' state is prohibited. Use get_today_blocks() instead.")
            
        db = self._get_db()
        doc = await db.system_state.find_one({"key": key})
        if doc is None:
            return default
        return doc.get("value")

    async def set_state(self, key: str, value: str) -> None:
        if key == "completed_blocks":
            raise ValueError("Writing to raw 'completed_blocks' state is prohibited. Use save_completed_block() instead.")
            
        db = self._get_db()
        await db.system_state.update_one(
            {"key": key},
            {"$set": {"value": value, "updated_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True
        )

    async def delete_state(self, key: str) -> None:
        db = self._get_db()
        await db.system_state.delete_one({"key": key})
        
    # ─────────────────────────────────────────────────────────────────────
    # COMPLETED BLOCKS
    # ─────────────────────────────────────────────────────────────────────
    async def save_completed_block(self, date: str, block_data: dict[str, Any]) -> None:
        """Save a completed/skipped block to a dated collection."""
        db = self._get_db()
        block_data["date"] = date
        block_data["saved_at"] = datetime.now(timezone.utc).isoformat()
        await db.completed_blocks.insert_one(block_data)
        
        # Also keep a fast index for "today's blocks"
        await db.system_state.update_one(
            {"key": f"completed_count:{date}"},
            {"$inc": {"value": 1}},
            upsert=True
        )

    async def get_today_blocks(self, date: str) -> list[dict[str, Any]]:
        """Get only today's completed blocks."""
        db = self._get_db()
        cursor = db.completed_blocks.find(
            {"date": date},
            {"_id": 0}
        )
        return await cursor.to_list(length=None)

    async def get_blocks_range(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        """Get blocks across a date range for weekly/monthly analysis."""
        db = self._get_db()
        cursor = db.completed_blocks.find(
            {"date": {"$gte": start_date, "$lte": end_date}},
            {"_id": 0}
        ).sort("date", 1)
        return await cursor.to_list(length=None)

    # ─────────────────────────────────────────────────────────────────────
    # STUDY BLOCKS (FIRST-CLASS OBJECTS)
    # ─────────────────────────────────────────────────────────────────────
    async def save_study_blocks(self, target_date: str, blocks: list[dict[str, Any]]) -> None:
        """Save normalized study blocks to the database."""
        db = self._get_db()
        # Delete any existing blocks for this date so we can safely replace them
        await db.study_blocks.delete_many({"date": target_date})
        
        if blocks:
            # Add updated timestamp to all blocks
            for b in blocks:
                b["updated_at"] = datetime.now(timezone.utc).isoformat()
            await db.study_blocks.insert_many(blocks)
            
        await self.record_timeline_event(
            "study_blocks.planned",
            {
                "date": target_date,
                "block_ids": [block.get("block_id") for block in blocks],
                "count": len(blocks),
            },
        )

    async def get_study_blocks(self, target_date: str | None = None, include_completed: bool = True) -> list[dict[str, Any]]:
        """Fetch study blocks, optionally filtered by date and completion status."""
        db = self._get_db()
        query = {}
        if target_date:
            query["date"] = target_date
        
        cursor = db.study_blocks.find(query, {"_id": 0})
        rows = await cursor.to_list(length=None)
        
        if not include_completed:
            rows = [b for b in rows if str(b.get("status", "")).upper() not in {"COMPLETED", "SKIPPED"}]
            
        rows.sort(key=lambda block: block.get("block_id", ""))
        return rows

    async def get_study_block_by_identifier(self, identifier: str, target_date: str | None = None) -> dict[str, Any] | None:
        """Fetch a specific study block by its ID or human-readable label."""
        db = self._get_db()
        query = {"$or": [{"block_id": identifier}, {"label": identifier}, {"block_label": identifier}]}
        if target_date:
            query["date"] = target_date
            
        return await db.study_blocks.find_one(query, {"_id": 0})

    async def update_study_block(self, block_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        """Update a specific study block."""
        db = self._get_db()
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        
        result = await db.study_blocks.find_one_and_update(
            {"block_id": block_id},
            {"$set": updates},
            return_document=True,
            projection={"_id": 0}
        )
        if result:
            await self.record_timeline_event("study_block.updated", {"block_id": block_id, "updates": list(updates.keys())})
        return result

    async def complete_study_block(self, block_id: str, actual: dict[str, Any]) -> dict[str, Any]:
        """Mark a block as completed with actual metrics."""
        db = self._get_db()
        
        updates = {
            "status": "COMPLETED",
            "actual_time": actual.get("actual_time", 0),
            "actual_attempted": actual.get("attempted", 0),
            "actual_correct": actual.get("correct", 0),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        result = await db.study_blocks.find_one_and_update(
            {"block_id": block_id},
            {"$set": updates},
            return_document=True,
            projection={"_id": 0}
        )
        if result:
            await self.record_timeline_event("study_block.completed", {"block_id": block_id, "metrics": actual})
        return result or {}

    async def skip_study_block(self, block_id: str, reason: str = "") -> dict[str, Any] | None:
        """Mark a block as skipped."""
        db = self._get_db()
        updates = {
            "status": "SKIPPED",
            "reason_skipped": reason,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        result = await db.study_blocks.find_one_and_update(
            {"block_id": block_id},
            {"$set": updates},
            return_document=True,
            projection={"_id": 0}
        )
        if result:
            await self.record_timeline_event("study_block.skipped", {"block_id": block_id, "reason": reason})
        return result

    # ─────────────────────────────────────────────────────────────────────
    # TIMELINE & PLANNER DECISIONS
    # ─────────────────────────────────────────────────────────────────────
    async def record_timeline_event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        db = self._get_db()
        import uuid
        event = {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload
        }
        await db.timeline.insert_one(dict(event))
        event.pop("_id", None)
        return event

    async def save_planner_decision(self, decision: dict[str, Any]) -> None:
        db = self._get_db()
        decision["timestamp"] = datetime.now(timezone.utc).isoformat()
        await db.planner_decisions.insert_one(decision)

    # ─────────────────────────────────────────────────────────────────────
    # DAILY SUMMARY
    # ─────────────────────────────────────────────────────────────────────
    async def save_daily_summary(
        self, target_date: str, total_cy: float, physics_cy: float, physics_ty: float,
        chem_cy: float, chem_ty: float, maths_cy: float, maths_ty: float,
        blocks_completed: int, blocks_skipped: int, day_type: str = "normal",
    ) -> None:
        db = self._get_db()
        doc = {
            "date": target_date,
            "total_cy": total_cy,
            "physics_cy": physics_cy, "physics_ty": physics_ty,
            "chem_cy": chem_cy, "chem_ty": chem_ty,
            "maths_cy": maths_cy, "maths_ty": maths_ty,
            "blocks_completed": blocks_completed,
            "blocks_skipped": blocks_skipped,
            "day_type": day_type,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        await db.daily_summary.update_one({"date": target_date}, {"$set": doc}, upsert=True)

    async def get_daily_summary(self, target_date: str) -> dict[str, Any] | None:
        db = self._get_db()
        return await db.daily_summary.find_one({"date": target_date}, {"_id": 0})

    async def get_summaries_range(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        db = self._get_db()
        cursor = db.daily_summary.find(
            {"date": {"$gte": start_date, "$lte": end_date}},
            {"_id": 0}
        ).sort("date", 1)
        return await cursor.to_list(length=None)

    # ─────────────────────────────────────────────────────────────────────
    # TEST SCORES
    # ─────────────────────────────────────────────────────────────────────
    async def save_test_score(
        self, test_date: str, p_score: float, p_total: float, c_score: float, c_total: float,
        m_score: float, m_total: float, notes: str = "",
    ) -> int:
        db = self._get_db()
        doc = {
            "date": test_date,
            "p_score": p_score, "p_total": p_total,
            "c_score": c_score, "c_total": c_total,
            "m_score": m_score, "m_total": m_total,
            "notes": notes,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.test_scores.insert_one(doc)
        return 1  # Mocking ROWID for compatibility

    async def get_latest_test_score(self) -> dict[str, Any] | None:
        db = self._get_db()
        return await db.test_scores.find_one({}, sort=[("date", -1)], projection={"_id": 0})

    async def get_test_scores_range(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        db = self._get_db()
        cursor = db.test_scores.find(
            {"date": {"$gte": start_date, "$lte": end_date}},
            {"_id": 0}
        ).sort("date", 1)
        return await cursor.to_list(length=None)

    # ─────────────────────────────────────────────────────────────────────
    # API HEALTH
    # ─────────────────────────────────────────────────────────────────────
    async def update_api_health(self, provider: str, success: bool, latency_ms: float) -> None:
        db = self._get_db()
        now = datetime.now(timezone.utc).isoformat()
        existing = await db.api_health.find_one({"provider": provider})
        
        if not existing:
            doc = {
                "provider": provider,
                "last_success": now if success else None,
                "last_failure": None if success else now,
                "success_count": 1 if success else 0,
                "failure_count": 0 if success else 1,
                "avg_latency_ms": latency_ms,
                "total_calls": 1,
                "updated_at": now
            }
            await db.api_health.insert_one(doc)
        else:
            total = existing.get("total_calls", 0) + 1
            new_avg = ((existing.get("avg_latency_ms", 0) * existing.get("total_calls", 0)) + latency_ms) / total
            
            updates = {
                "success_count": existing.get("success_count", 0) + (1 if success else 0),
                "failure_count": existing.get("failure_count", 0) + (0 if success else 1),
                "avg_latency_ms": round(new_avg, 2),
                "total_calls": total,
                "updated_at": now
            }
            if success:
                updates["last_success"] = now
            else:
                updates["last_failure"] = now
                
            await db.api_health.update_one({"provider": provider}, {"$set": updates})

    async def get_healthy_providers(self) -> list[dict[str, Any]]:
        db = self._get_db()
        cursor = db.api_health.find({}, {"_id": 0})
        providers = []
        for r in await cursor.to_list(length=None):
            total = r.get("total_calls", 0)
            if total > 0:
                sr = r.get("success_count", 0) / total
                if sr > 0.5:
                    r["success_rate"] = round(sr, 3)
                    providers.append(r)
        
        providers.sort(key=lambda x: (-x["success_rate"], x["avg_latency_ms"]))
        return providers

    # ─────────────────────────────────────────────────────────────────────
    # STREAKS
    # ─────────────────────────────────────────────────────────────────────
    async def update_streak(self, streak_type: str, target_date: str) -> dict[str, Any]:
        db = self._get_db()
        existing = await db.streaks.find_one({"streak_type": streak_type})
        
        if not existing:
            doc = {
                "streak_type": streak_type,
                "current_count": 1,
                "best_count": 1,
                "last_date": target_date,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            await db.streaks.insert_one(doc)
            del doc["_id"]
            return doc
            
        last_date_str = existing.get("last_date", "")
        if last_date_str == target_date:
            del existing["_id"]
            return existing
            
        try:
            last_dt = date.fromisoformat(last_date_str)
            target_dt = date.fromisoformat(target_date)
            delta = (target_dt - last_dt).days
        except (ValueError, TypeError):
            delta = 999
            
        if delta == 1:
            new_count = existing.get("current_count", 0) + 1
        elif delta > 1:
            new_count = 1
        else:
            del existing["_id"]
            return existing
            
        new_best = max(existing.get("best_count", 0), new_count)
        
        updates = {
            "current_count": new_count,
            "best_count": new_best,
            "last_date": target_date,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        await db.streaks.update_one({"streak_type": streak_type}, {"$set": updates})
        
        return {
            "streak_type": streak_type,
            "current_count": new_count,
            "best_count": new_best,
            "last_date": target_date
        }

    async def get_streak(self, streak_type: str) -> dict[str, Any] | None:
        db = self._get_db()
        return await db.streaks.find_one({"streak_type": streak_type}, {"_id": 0})

    async def get_all_streaks(self) -> list[dict[str, Any]]:
        db = self._get_db()
        cursor = db.streaks.find({}, {"_id": 0}).sort("streak_type", 1)
        return await cursor.to_list(length=None)

    # ─────────────────────────────────────────────────────────────────────
    # LOGGING & CHAT HISTORY
    # ─────────────────────────────────────────────────────────────────────
    async def log_event(self, event_type: str, data: dict[str, Any], timestamp: str) -> None:
        key = f"event_{event_type}_{timestamp}"
        await self.set_state(key, json.dumps(data))

    async def save_chat_message(self, role: str, content: str) -> None:
        """Save a chat message to history."""
        db = self._get_db()
        doc = {
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        await db.chat_history.insert_one(doc)
        
    async def get_recent_chat_history(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get the most recent chat messages, chronologically ordered."""
        db = self._get_db()
        cursor = db.chat_history.find({}, {"_id": 0}).sort("timestamp", -1).limit(limit)
        history = await cursor.to_list(length=limit)
        # Reverse to get chronological order (oldest to newest among the recent ones)
        return history[::-1]

    async def get_db_stats(self) -> dict[str, Any]:
        """Get MongoDB database stats (memory, objects, data size)."""
        db = self._get_db()
        try:
            return await db.command("dbstats")
        except Exception as e:
            logger.error(f"Failed to get dbstats: {e}")
            return {"error": str(e)}

    # ─────────────────────────────────────────────────────────────────────
    # KNOWLEDGE ENGINE (PERMANENT HIERARCHY)
    # ─────────────────────────────────────────────────────────────────────
    
    async def save_learning_event(self, event_data: dict[str, Any]) -> None:
        """Save a transient learning event to MongoDB."""
        db = self._get_db()
        await db.learning_events.insert_one(event_data)

    async def upsert_concept_asset(self, concept_data: dict[str, Any]) -> None:
        """Create or update a concept asset by appending to its revisions."""
        db = self._get_db()
        concept_name = concept_data.get("concept_name")
        if not concept_name:
            return
            
        existing = await db.concept_assets.find_one({"concept_name": concept_name})
        if existing:
            # Append revisions
            revisions = existing.get("revisions", [])
            new_revisions = concept_data.get("revisions", [])
            revisions.extend(new_revisions)
            
            await db.concept_assets.update_one(
                {"concept_name": concept_name},
                {"$set": {
                    "revisions": revisions,
                    "resolved": concept_data.get("resolved", existing.get("resolved")),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }}
            )
        else:
            concept_data["updated_at"] = datetime.now(timezone.utc).isoformat()
            await db.concept_assets.insert_one(concept_data)



    async def get_concept_asset(self, concept_name: str) -> dict[str, Any] | None:
        db = self._get_db()
        return await db.concept_assets.find_one({"concept_name": concept_name}, {"_id": 0})

    async def get_unresolved_concepts(self, subject: str = None) -> list[dict[str, Any]]:
        db = self._get_db()
        query = {"resolved": False}
        if subject:
            query["subject"] = subject
        cursor = db.concept_assets.find(query, {"_id": 0})
        return await cursor.to_list(length=None)

    # ─────────────────────────────────────────────────────────────────────
    # PLANNING ENGINE (RECOMMENDATION MEMORY)
    # ─────────────────────────────────────────────────────────────────────
    
    async def save_recommendation(self, rec_data: dict[str, Any]) -> None:
        db = self._get_db()
        await db.recommendation_history.insert_one(rec_data)

    async def update_recommendation_outcome(self, rec_timestamp: float, applied: bool, reason: str, effectiveness: float) -> None:
        db = self._get_db()
        await db.recommendation_history.update_one(
            {"timestamp": rec_timestamp},
            {"$set": {
                "applied": applied,
                "reason_ignored": reason,
                "effectiveness_score": effectiveness
            }}
        )

    async def get_recent_recommendations(self, limit: int = 10) -> list[dict[str, Any]]:
        db = self._get_db()
        cursor = db.recommendation_history.find({}, {"_id": 0}).sort("timestamp", -1).limit(limit)
        return await cursor.to_list(length=limit)
