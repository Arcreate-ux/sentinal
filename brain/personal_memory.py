"""
SENTINEL — Personal Memory (brain/personal_memory.py)

"Remember Shantanu sir is my chemistry teacher."
Saves facts, preferences, and rules. Resolves names to subjects contextually.
"""

import json
import logging
from typing import Any

logger = logging.getLogger("sentinel.brain.personal_memory")

MEMORY_EXTRACTION_PROMPT = """\
Extract structured data from this personal memory the student wants to save.

Input: "{raw_text}"

Classify the memory type:
- "faculty" — about a teacher/sir/maam
- "study_rule" — a rule about how they want to study (e.g. "do 2 hours PYQs daily")
- "preference" — a like/dislike/preference
- "fact" — any other fact about the student
- "schedule" — about timing, routine, events

Extract:
- entities: names, subjects, or key terms mentioned
- resolved_subject: if a JEE subject is mentioned or implied, one of "Physics", "Chem", "Maths", or null
- tags: lowercase searchable keywords

Return ONLY JSON:
{{
    "entities": ["..."],
    "resolved_subject": "..." or null,
    "resolved_type": "faculty|study_rule|preference|fact|schedule",
    "tags": ["..."],
    "summary": "one-line summary of what to remember"
}}
"""


class PersonalMemory:
    """Manages the student's personal memory — facts, preferences, rules, people."""

    def __init__(self, ai_engine, state_db) -> None:
        self.ai = ai_engine
        self.state = state_db

    async def save(self, raw_text: str) -> dict[str, Any]:
        """Extract entities from text and save as a memory."""
        # Try AI extraction
        extracted = await self._extract(raw_text)

        memory = {
            "raw_text": raw_text,
            "entities": extracted.get("entities", []),
            "resolved_subject": extracted.get("resolved_subject"),
            "resolved_type": extracted.get("resolved_type", "fact"),
            "tags": extracted.get("tags", []),
            "summary": extracted.get("summary", raw_text),
        }

        await self.state.save_memory(memory)
        logger.info("Saved memory: %s", memory.get("summary", raw_text))
        return memory

    async def search(self, query: str) -> list[dict[str, Any]]:
        """Search memories by text, tags, entities."""
        return await self.state.search_memories(query)

    async def resolve_subject(self, query: str) -> str | None:
        """Given a name or reference, resolve to a subject using memories + profile.

        Example: "Shantanu" → search memories → find faculty entry → return "Chem"
        """
        # 1. Search memories
        results = await self.search(query)
        for mem in results:
            if mem.get("resolved_subject"):
                return mem["resolved_subject"]

        # 2. Check student profile faculty
        profile = await self.state.get_student_profile()
        if profile:
            faculty = profile.get("faculty", {})
            query_lower = query.lower()
            for subj, name in faculty.items():
                if name and query_lower in name.lower():
                    return subj

        return None

    async def get_study_rules(self) -> list[dict[str, Any]]:
        """Get all memories that are study rules (e.g. '2 hours PYQs daily')."""
        return await self.state.get_study_rules()

    async def get_context_for_ai(self, query: str = "") -> dict[str, Any]:
        """Build a memory context bundle for the AI handler.

        Returns profile + relevant memories + study rules.
        """
        profile = await self.state.get_student_profile()

        # Get study rules (always relevant)
        rules = await self.get_study_rules()

        # Search for query-relevant memories
        relevant = []
        if query:
            relevant = await self.search(query)

        return {
            "student_profile": profile,
            "study_rules": [{"rule": r.get("summary", r.get("raw_text")), "since": r.get("created_at")} for r in rules],
            "relevant_memories": [{"memory": m.get("summary", m.get("raw_text")), "type": m.get("resolved_type")} for m in relevant[:5]],
        }

    async def _extract(self, raw_text: str) -> dict[str, Any]:
        """Use AI to extract structured data from raw memory text."""
        try:
            raw = await self.ai.call(
                task_type="fast",
                prompt=MEMORY_EXTRACTION_PROMPT.format(raw_text=raw_text),
                system_prompt="You are a data extraction engine. Return ONLY valid JSON.",
                max_tokens=200,
                temperature=0.1,
            )

            cleaned = raw.strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0]
            elif "```" in cleaned:
                cleaned = cleaned.split("```", 1)[1].split("```", 1)[0]

            return json.loads(cleaned.strip())
        except Exception as e:
            logger.warning("Memory extraction failed, using raw text: %s", e)
            # Fallback: simple keyword extraction
            tags = [w.lower() for w in raw_text.split() if len(w) > 2]
            return {
                "entities": [],
                "resolved_subject": None,
                "resolved_type": "fact",
                "tags": tags[:10],
                "summary": raw_text,
            }
