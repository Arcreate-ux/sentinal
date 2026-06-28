"""
SENTINEL — Knowledge Engine (brain/knowledge_engine.py)

Takes the parsed data from the ReflectionEngine (Adaptive Interview)
and commits it to the permanent ConceptAsset and ErrorProfile hierarchy in MongoDB.
"""

import logging
import json
import time

logger = logging.getLogger("sentinel.brain.knowledge_engine")

class KnowledgeEngine:
    def __init__(self, ai_engine, state_db, event_bus=None):
        self.ai = ai_engine
        self.state = state_db
        self.event_bus = event_bus

    async def extract_assets(self, block_context: dict, parsed_data: dict) -> dict:
        """
        Takes the parsed dictionary from the Adaptive Interview and turns it into
        structured LearningEvents and ConceptAssets.
        """
        logger.info("Extracting Concept Assets from parsed learning data...")
        from sentinel.brain.ontology import get_core_concepts
        subject = block_context.get("subject", "")
        core_concepts = get_core_concepts(subject) if subject else []

        prompt = f"""
        Extract structured concept assets and error profiles from the student's study block data.
        
        BLOCK CONTEXT:
        {json.dumps(block_context, indent=2)}
        
        PARSED INTERVIEW DATA:
        {json.dumps(parsed_data, indent=2)}
        
        CORE CONCEPTS FOR {subject} (Use these as anchors if applicable):
        {core_concepts}
        
        YOUR JOB:
        Create a list of ConceptAsset objects and ArchivedQuestion objects.
        For ConceptAssets:
        - Identify the core permanent concept.
        - Document the exact mistake/insight as a timeline revision on the Concept.
        - Propose `proposed_connections` (graph edges to other concepts).
        - Propose a `confidence_delta` (-0.2 to +0.2) based on performance.
        
        For ArchivedQuestions (Evidence):
        - Log each specific question encountered as cold evidence.
        - Classify 'mistake_type' as one of: [Concept, Formula, Calculation, Reading, Visualization, Silly, Time_Pressure].
        
        Return STRICT JSON matching this schema:
        {{
            "concept_assets": [
                {{
                    "concept_name": "Wedge Constraint",
                    "subject": "Physics",
                    "chapter": "COM",
                    "proposed_connections": ["Relative Motion"],
                    "confidence_delta": -0.1,
                    "faculty_needed": true,
                    "revisions": [
                        {{
                            "faculty_notes": "",
                            "current_understanding": "Knows FBD, doesn't know relative motion relation.",
                            "error_profiles": [
                                {{"mistake_type": "Concept", "description": "Couldn't derive equation"}}
                            ]
                        }}
                    ]
                }}
            ],
            "archived_questions": [
                {{
                    "question_id": "Q7",
                    "subject": "Physics",
                    "chapter": "COM",
                    "concept_label": "Wedge Constraint",
                    "mistake_type": "Concept",
                    "source_block": "{block_context.get('block_label', 'Unknown')}"
                }}
            ]
        }}
        """

        try:
            raw_response = await self.ai.call(
                task_type="parser",
                prompt=prompt,
                system_prompt="You are a data extraction engine. Output ONLY raw JSON.",
                max_tokens=500
            )
            
            cleaned = raw_response.strip()
            if "```json" in cleaned: cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0]
            elif "```" in cleaned: cleaned = cleaned.split("```", 1)[1].split("```", 1)[0]
                
            assets_payload = json.loads(cleaned.strip())
            
            # (Removed await state.save_learning_event, await state.upsert_concept_asset, await state.upsert_question_asset)
            # The LearningModelUpdater now handles these database mutations.
            
            learning_event = {
                "timestamp": time.time(),
                "subject": block_context.get("subject", "Unknown"),
                "chapter": block_context.get("chapter", "Unknown"),
                "exercise_type": block_context.get("exercise_type", "Unknown"),
                "attempted": parsed_data.get("attempted", 0),
                "correct": parsed_data.get("correct", 0),
                "questions_encountered": parsed_data.get("concept_doubts", []) + parsed_data.get("incomplete_questions", []),
                "reasons_for_skipping": {q: parsed_data.get("reason_skipped", "Unknown") for q in parsed_data.get("incomplete_questions", [])},
                "time_taken": block_context.get("target_time", 0)
            }
            
            concept_assets = assets_payload.get("concept_assets", [])
            for asset in concept_assets:
                for rev in asset.get("revisions", []):
                    rev["timestamp"] = time.time()
                    
            archived_questions = assets_payload.get("archived_questions", [])
            for asset in archived_questions:
                asset["timestamp"] = time.time()
                asset["archived"] = True

            # Emit KnowledgeExtracted Event
            event_bus = getattr(self, "event_bus", None)
            if event_bus:
                from sentinel.bot.events import KnowledgeExtracted
                import uuid
                event = KnowledgeExtracted(
                    event_id=str(uuid.uuid4()),
                    timestamp=time.time(),
                    payload={
                        "learning_event": learning_event,
                        "concept_assets": concept_assets,
                        "archived_questions": archived_questions
                    }
                )
                await event_bus.publish(event)
            
            return {"learning_event": learning_event, "concept_assets": concept_assets, "archived_questions": archived_questions}
            
        except Exception as e:
            logger.error(f"Knowledge Engine extraction failed: {e}")
            return {"error": str(e)}
