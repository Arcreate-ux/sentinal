"""
SENTINEL — Learning Model Updater (brain/learning_updater.py)

The ONLY engine allowed to modify the Learning Model in MongoDB.
Subscribes to KnowledgeExtracted events to merge evidence, 
recalculate confidence, and evolve mastery_stage.
"""

import logging
from sentinel.bot.events import BaseEvent, KnowledgeExtracted
from datetime import datetime, timezone

logger = logging.getLogger("sentinel.brain.learning_updater")

class LearningModelUpdater:
    def __init__(self, state_db):
        self.state = state_db

    async def handle_knowledge_extracted(self, event: BaseEvent) -> None:
        if not isinstance(event, KnowledgeExtracted):
            return
            
        payload = event.payload
        learning_event = payload.get("learning_event")
        concept_assets = payload.get("concept_assets", [])
        archived_questions = payload.get("archived_questions", [])

        # 1. Save Learning Event
        if learning_event:
            await self.state.save_learning_event(learning_event)
            
        # 2. Mutate Concept Assets
        for asset in concept_assets:
            concept_name = asset.get("concept_name")
            if not concept_name:
                continue
                
            db = self.state._get_db()
            existing = db.concept_assets.find_one({"concept_name": concept_name})
            
            now = datetime.now(timezone.utc).isoformat()
            
            if existing:
                revisions = existing.get("revisions", [])
                revisions.extend(asset.get("revisions", []))
                
                times = existing.get("times_encountered", 0) + 1
                faculty_dependency = existing.get("faculty_dependency", 0)
                
                # Check if faculty was needed in this block
                if asset.get("faculty_needed", False) or any(r.get("faculty_notes") for r in asset.get("revisions", [])):
                    faculty_dependency += 1
                else:
                    faculty_dependency = max(0, faculty_dependency - 1)
                
                # Update graph connections (only add new unique connections)
                connected_to = set(existing.get("connected_to", []))
                proposed = asset.get("proposed_connections", [])
                for p in proposed:
                    connected_to.add(p)
                
                # Deterministic Confidence Evolvement
                conf = existing.get("confidence_score", 0.0)
                delta = asset.get("confidence_delta", 0.0)
                # Cap the delta impact based on how many times encountered to prevent volatility
                actual_delta = max(-0.2, min(0.2, delta)) 
                
                # Faculty penalty
                if faculty_dependency > 0:
                    actual_delta -= 0.1
                    
                conf = max(0.0, min(1.0, conf + actual_delta))
                
                # Evolve Mastery Stage deterministically
                if faculty_dependency > 0 and conf < 0.6:
                    mastery = "Struggling"
                elif conf > 0.8:
                    mastery = "Mastered"
                elif conf > 0.4:
                    mastery = "Improving"
                else:
                    mastery = "Novice"
                
                db.concept_assets.update_one(
                    {"concept_name": concept_name},
                    {"$set": {
                        "revisions": revisions,
                        "connected_to": list(connected_to),
                        "last_seen": now,
                        "times_encountered": times,
                        "faculty_dependency": faculty_dependency,
                        "mastery_stage": mastery,
                        "confidence_score": conf,
                        "updated_at": now
                    }}
                )
            else:
                asset["first_seen"] = now
                asset["last_seen"] = now
                asset["times_encountered"] = 1
                
                conf = max(0.0, min(1.0, asset.get("confidence_delta", 0.0)))
                asset["confidence_score"] = conf
                asset["faculty_dependency"] = 1 if asset.get("faculty_needed") else 0
                asset["mastery_stage"] = "Novice"
                asset["connected_to"] = asset.get("proposed_connections", [])
                asset["updated_at"] = now
                
                db.concept_assets.insert_one(asset)
                
        # 3. Aggregate up to Skills
        await self._aggregate_skills(concept_assets)
                
        # 4. Cold Archive Questions
        db = self.state._get_db()
        if archived_questions:
            db.archived_questions.insert_many(archived_questions)
            
        logger.info(f"Learning Model updated: {len(concept_assets)} concepts modified, {len(archived_questions)} questions archived.")

    async def _aggregate_skills(self, concept_assets: list) -> None:
        """Roll up confidence from concepts to skills."""
        db = self.state._get_db()
        from sentinel.brain.ontology import SEED_ONTOLOGY
        
        updated_skills = set()
        
        # Find which skills these concepts belong to
        for asset in concept_assets:
            concept_name = asset.get("concept_name")
            subject = asset.get("subject")
            if not subject or not concept_name:
                continue
                
            subj_data = SEED_ONTOLOGY.get(subject, {})
            for category_name, category_data in subj_data.items():
                if concept_name in category_data.get("core_concepts", []):
                    # We flag all skills in this category for recalculation
                    for skill in category_data.get("skills", []):
                        updated_skills.add((subject, skill))
        
        now = datetime.now(timezone.utc).isoformat()
        # Recalculate confidence for flagged skills
        for subject, skill_name in updated_skills:
            # Find all concepts under the skill's category
            subj_data = SEED_ONTOLOGY.get(subject, {})
            category_concepts = []
            for cat_data in subj_data.values():
                if skill_name in cat_data.get("skills", []):
                    category_concepts.extend(cat_data.get("core_concepts", []))
            
            if not category_concepts:
                continue
                
            # Fetch all concepts in the DB for this category
            cursor = db.concept_assets.find({"concept_name": {"$in": category_concepts}})
            stored_concepts = list(cursor)
            
            if not stored_concepts:
                continue
                
            avg_confidence = sum(c.get("confidence_score", 0.0) for c in stored_concepts) / len(stored_concepts)
            
            db.skill_assets.update_one(
                {"skill_name": skill_name, "subject": subject},
                {"$set": {
                    "confidence_score": avg_confidence,
                    "last_updated": now,
                    "child_concepts": category_concepts
                }},
                upsert=True
            )
            
        logger.info(f"Learning Model updated with {len(concept_assets)} concepts.")
