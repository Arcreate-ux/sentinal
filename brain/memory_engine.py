"""
SENTINEL — Memory Engine (brain/memory_engine.py)

The Librarian. A strictly deterministic retrieval system.
Given a subject/chapter context, it retrieves and ranks relevant ConceptAssets, 
ErrorProfiles, and LearningEvents to build a ContextBundle. No LLM calls.
"""

import logging
from typing import Any, Dict, List
from datetime import datetime, timezone

logger = logging.getLogger("sentinel.brain.memory_engine")

class MemoryEngine:
    def __init__(self, state_db, event_store):
        self.state = state_db
        self.store = event_store

    async def retrieve_context_bundle(self, subject: str, chapter: str = None) -> Dict[str, Any]:
        """
        Retrieves and ranks historical information relevant to the current block.
        """
        logger.info(f"Memory Engine retrieving context for {subject} - {chapter}")
        db = self.state._get_db()
        
        # 1. Retrieve Core Concepts for this context
        from sentinel.brain.ontology import get_core_concepts, SEED_ONTOLOGY
        
        # If chapter is provided, try to find concepts specifically under that chapter/category
        # Otherwise get all core concepts for the subject
        anchor_concepts = []
        if subject in SEED_ONTOLOGY:
            if chapter and chapter in SEED_ONTOLOGY[subject]:
                anchor_concepts.extend(SEED_ONTOLOGY[subject][chapter].get("core_concepts", []))
            else:
                anchor_concepts = get_core_concepts(subject)
        
        # 2. Graph Traversal Retrieval (Depth 2)
        # First layer: anchors
        cursor = db.concept_assets.find({
            "$or": [
                {"subject": subject, "chapter": chapter} if chapter else {"subject": subject},
                {"concept_name": {"$in": anchor_concepts}}
            ]
        }, {"_id": 0})
        
        level_1 = list(cursor)
        
        # Collect edges to traverse
        l2_targets = set()
        for c in level_1:
            for edge in c.get("connected_to", []):
                l2_targets.add(edge)
                
        # Remove already fetched concepts
        for c in level_1:
            l2_targets.discard(c.get("concept_name"))
            
        level_2 = []
        if l2_targets:
            cursor2 = db.concept_assets.find({"concept_name": {"$in": list(l2_targets)}}, {"_id": 0})
            level_2 = list(cursor2)
            
        all_concepts = level_1 + level_2
        
        # 3. Aggressive Culling & Ranking
        # Rules: Throw out anything with confidence > 0.9 UNLESS faculty dependency > 0
        filtered_concepts = []
        for c in all_concepts:
            conf = c.get("confidence_score", 0.0)
            fac_dep = c.get("faculty_dependency", 0)
            mastery = c.get("mastery_stage", "Novice")
            
            if conf >= 0.90 and fac_dep == 0 and mastery == "Mastered":
                continue # Completely mastered, ignore
            filtered_concepts.append(c)
            
        # Ranking factors: Struggling > High Faculty Dependency > Low Confidence
        def rank_concept(c: dict) -> float:
            score = 0.0
            if c.get("mastery_stage") == "Struggling":
                score += 50.0
            score += (1.0 - c.get("confidence_score", 1.0)) * 30.0
            score += c.get("faculty_dependency", 0) * 10.0
            # Give a slight boost if it was recently modified (within last 7 days)
            last_seen = c.get("last_seen")
            if last_seen:
                try:
                    dt = datetime.fromisoformat(last_seen)
                    if (datetime.now(timezone.utc) - dt).days < 7:
                        score += 5.0
                except:
                    pass
            return score
            
        filtered_concepts.sort(key=rank_concept, reverse=True)
        top_concepts = filtered_concepts[:15] # Strict cap at 15 to prevent context bloat
        
        # 4. Fetch Skill Summaries (Higher level guidance)
        skill_cursor = db.skill_assets.find({"subject": subject}, {"_id": 0})
        skills = list(skill_cursor)
        skills.sort(key=lambda s: s.get("confidence_score", 1.0))
        top_skills = skills[:5] # Send the 5 weakest skills as guidance
        
        # 3. Retrieve Recent Learning Events
        recent_events = await self.store.get_events(event_type="ReflectionCompleted", limit=3)
        
        # 4. Retrieve Active Experience Rules (Constraints)
        rule_events = await self.store.get_events(event_type="ExperienceRuleDiscovered", limit=5)
        active_rules = [r.get("payload", {}).get("rule") for r in rule_events]
        
        # 5. Active Recommendations (Historian context)
        recent_recs = await self.state.get_recent_recommendations(limit=3)
        
        bundle = {
            "target_subject": subject,
            "target_chapter": chapter,
            "relevant_skills": top_skills,
            "relevant_concept_profiles": top_concepts,
            "recent_learning_events": [e.get("payload", {}) for e in recent_events],
            "active_recommendations": recent_recs,
            "planner_constraints": active_rules
        }
        
        return bundle
