"""
SENTINEL — Reflection Engine (brain/reflection_engine.py)

The student finishes a block and dumps their raw thoughts into Telegram.
SENTINEL already knows the block context (subject, chapter, exercise, t_q).
The student NEVER has to repeat themselves.

What this engine does:
1. Pulls the active block from DB — gets subject, chapter, exercise automatically.
2. Pulls past unresolved errors for that subject — checks for recurring mistakes.
3. Sends the full context + user dump to AI.
4. AI extracts: errors, key_points, faculty_doubts, recurring_mistakes, short_note.
5. Saves everything to MongoDB under the chapter name for later /chapter lookup.
"""

import logging
import json
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("sentinel.brain.reflection_engine")


class ReflectionEngine:
    def __init__(self, ai_engine, state_db, notion_client, event_bus=None):
        self.ai = ai_engine
        self.state = state_db
        self.notion = notion_client
        self.bus = event_bus

    # ─────────────────────────────────────────────────────────────────────
    # MAIN: Process a block brain-dump.
    # Called by the orchestrator after the student selects a block in /done.
    # block_data already has subject, chapter, exercise_type from the plan.
    # ─────────────────────────────────────────────────────────────────────
    async def process_block_reflection(
        self, block_data: dict, history_context: list, user_message: str
    ) -> dict[str, Any]:
        """
        Parse the student's raw brain-dump.
        block_data contains everything we need: subject, chapter, exercise_type.
        Student NEVER needs to say what they were doing.
        """
        from sentinel.brain.prompts import BLOCK_BRAIN_DUMP_PROMPT

        subject = block_data.get("subject", "Physics")
        chapter = block_data.get("chapter", "Current Chapter")
        exercise_type = block_data.get("exercise_type", "Ex 1A")
        block_label = block_data.get("block_label") or block_data.get("label", "Block")
        question_count = block_data.get("question_count") or block_data.get("expected_questions", 0)
        target_time = block_data.get("target_time") or block_data.get("estimated_minutes", 0)

        # Pull recent unresolved errors for this subject from DB
        past_errors = []
        try:
            unresolved = await self.state.get_unresolved_concepts(subject=subject)
            past_errors = [
                {"concept": c.get("concept_name"), "last_seen": c.get("updated_at", "?")}
                for c in (unresolved or [])[-5:]
            ]
        except Exception:
            pass

        prompt = BLOCK_BRAIN_DUMP_PROMPT.format(
            block_label=block_label,
            subject=subject,
            chapter=chapter,
            exercise_type=exercise_type,
            question_count=question_count,
            target_time=target_time,
            past_errors=json.dumps(past_errors, indent=2) if past_errors else "None",
            user_message=user_message,
        )

        try:
            raw = await self.ai.call(
                task_type="parser",
                prompt=prompt,
                system_prompt="You are SENTINEL's block extractor. Return ONLY raw JSON.",
                max_tokens=500,
            )

            result = self._parse_json(raw)

            # If the AI needs a follow-up, return early
            if result.get("needs_followup") and result.get("followup_question"):
                return {
                    "needs_followup": True,
                    "followup_question": result["followup_question"],
                    "parsed_data": result,
                    "historical_insight": self._check_recurring(result, past_errors),
                }

            # Enrich with block context before returning
            result["subject"] = subject
            result["chapter"] = chapter
            result["exercise_type"] = exercise_type
            result["block_label"] = block_label

            # Save chapter-level data to DB for /chapter command
            await self._save_chapter_data(chapter, subject, result)

            return {
                "needs_followup": False,
                "followup_question": None,
                "parsed_data": result,
                "historical_insight": self._check_recurring(result, past_errors),
            }

        except Exception as e:
            logger.error("Block reflection parsing failed: %s", e)
            # Fallback: regex extract bare numbers from the dump
            numbers = re.findall(r"\d+", user_message)
            return {
                "needs_followup": False,
                "followup_question": None,
                "parsed_data": {
                    "attempted": int(numbers[0]) if len(numbers) >= 1 else 0,
                    "correct": int(numbers[1]) if len(numbers) >= 2 else 0,
                    "time_taken": int(numbers[2]) if len(numbers) >= 3 else 0,
                    "errors": [],
                    "key_points": [],
                    "faculty_doubts": [],
                    "recurring_mistakes": [],
                    "short_note": "Auto-extracted via regex fallback.",
                    "subject": subject,
                    "chapter": chapter,
                    "exercise_type": exercise_type,
                },
                "historical_insight": None,
            }

    # ─────────────────────────────────────────────────────────────────────
    # Save chapter-level errors/notes to MongoDB for /chapter command
    # ─────────────────────────────────────────────────────────────────────
    async def _save_chapter_data(self, chapter: str, subject: str, result: dict) -> None:
        """
        Appends this block's errors, key points, and faculty doubts to the
        chapter's cumulative record in MongoDB. This is what powers /chapter.
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            entry = {
                "timestamp": now,
                "block_label": result.get("block_label"),
                "exercise_type": result.get("exercise_type"),
                "errors": result.get("errors", []),
                "key_points": result.get("key_points", []),
                "faculty_doubts": result.get("faculty_doubts", []),
                "recurring_mistakes": result.get("recurring_mistakes", []),
                "short_note": result.get("short_note", ""),
                "attempted": result.get("attempted"),
                "correct": result.get("correct"),
            }
            db = self.state._get_db()
            await db.chapter_logs.update_one(
                {"chapter": chapter, "subject": subject},
                {
                    "$push": {"block_entries": entry},
                    "$set": {"chapter": chapter, "subject": subject, "last_updated": now},
                    "$inc": {"block_count": 1},
                },
                upsert=True,
            )
        except Exception as e:
            logger.warning("Failed to save chapter data: %s", e)

    # ─────────────────────────────────────────────────────────────────────
    # Generate chapter master summary for /chapter command
    # ─────────────────────────────────────────────────────────────────────
    async def generate_chapter_summary(self, chapter: str, subject: str | None = None) -> str:
        """
        Called by /chapter command.
        Pulls all logged errors/notes for a chapter and asks AI to synthesize.
        """
        from sentinel.brain.prompts import CHAPTER_SUMMARY_PROMPT

        try:
            db = self.state._get_db()
            query = {"chapter": {"$regex": chapter, "$options": "i"}}
            if subject:
                query["subject"] = subject

            doc = await db.chapter_logs.find_one(query, {"_id": 0})
            if not doc:
                return f"📭 No data logged yet for chapter '{chapter}'. Finish some blocks first."

            entries = doc.get("block_entries", [])
            if not entries:
                return f"📭 Chapter '{chapter}' found but no block entries logged yet."

            # Aggregate all data
            all_errors = []
            all_key_points = []
            all_faculty_doubts = []
            for e in entries:
                all_errors.extend(e.get("errors", []))
                all_key_points.extend(e.get("key_points", []))
                all_faculty_doubts.extend(e.get("faculty_doubts", []))

            block_count = doc.get("block_count", len(entries))
            first_date = entries[0].get("timestamp", "?")[:10] if entries else "?"
            last_date = entries[-1].get("timestamp", "?")[:10] if entries else "?"
            date_range = f"{first_date} to {last_date}"

            prompt = CHAPTER_SUMMARY_PROMPT.format(
                chapter=doc.get("chapter", chapter),
                subject=doc.get("subject", subject or "Unknown"),
                block_count=block_count,
                date_range=date_range,
                all_errors=json.dumps(all_errors, indent=2) if all_errors else "None logged.",
                all_key_points=json.dumps(all_key_points, indent=2) if all_key_points else "None logged.",
                faculty_doubts=json.dumps(all_faculty_doubts, indent=2) if all_faculty_doubts else "None logged.",
            )

            response = await self.ai.call(
                task_type="general_chat",
                prompt=prompt,
                system_prompt="You are SENTINEL's chapter diagnostics engine. Be precise and concise.",
                max_tokens=800,
            )
            return response.strip()

        except Exception as e:
            logger.error("Chapter summary generation failed: %s", e)
            return f"⚠️ Failed to generate chapter summary: {e}"

    # ─────────────────────────────────────────────────────────────────────
    # Evening Reflection (unchanged — runs at end of day automatically)
    # ─────────────────────────────────────────────────────────────────────
    async def run_evening_reflection(self, date_str: str) -> dict[str, Any]:
        """Runs the evening reflection, combining deterministic data with AI root-cause diagnosis."""
        from sentinel.brain.prompts import EVENING_REFLECTION_PROMPT
        from sentinel.brain.analyzer import PerformanceAnalyzer

        logger.info("Running Reflection Engine for %s...", date_str)
        analyzer = PerformanceAnalyzer(self.ai, self.notion, self.state)

        summary = await self.state.get_daily_summary(date_str)
        if not summary:
            summary = await analyzer._compute_summary_from_notion(date_str)
        if not summary:
            return {"error": f"No data recorded for {date_str}."}

        weak_subjects = await analyzer.identify_weak_subjects()
        payload_str = json.dumps(
            {"summary": summary, "weak_subjects": weak_subjects[:3] if weak_subjects else []},
            indent=2,
        )

        try:
            raw = await self.ai.call(
                task_type="evening_reflection",
                prompt=EVENING_REFLECTION_PROMPT.format(data_json=payload_str),
                system_prompt="You are an analytical AI diagnosing study bottlenecks. Return ONLY raw JSON.",
                max_tokens=300,
            )
            result = self._parse_json(raw)
            return result
        except Exception as e:
            logger.error("Reflection Engine failed: %s", e)
            return {"error": str(e), "summary": summary}

    # ─────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────
    def _parse_json(self, raw: str) -> dict:
        cleaned = raw.strip()
        if "```json" in cleaned:
            cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in cleaned:
            cleaned = cleaned.split("```", 1)[1].split("```", 1)[0]
        try:
            return json.loads(cleaned.strip())
        except json.JSONDecodeError:
            logger.warning("JSON parse failed on AI response: %s", cleaned[:200])
            return {}

    def _check_recurring(self, result: dict, past_errors: list) -> str | None:
        """Generate a historical insight message if recurring mistakes are detected."""
        recurring = result.get("recurring_mistakes", [])
        if recurring:
            return f"⚠️ Recurring mistake detected: {', '.join(recurring)}. This has appeared before. Flag for faculty."
        return None
