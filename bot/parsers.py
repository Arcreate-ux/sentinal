"""
SENTINEL — Message Parsers (bot/parsers.py)

Robust multi-strategy parsing for performance reports, homework,
test scores, week schedules, and commands.  Tries regex first,
falls back to AI when natural language is too ambiguous.
"""

from __future__ import annotations

import logging
import json
import re
from typing import Any
from pydantic import ValidationError

from sentinel.config import SUBJECTS, EXERCISE_TYPES
from sentinel.bot.schemas import (
    PerformanceReport,
    HomeworkEntry,
    HomeworkList,
    TestScores,
    IntentClassification,
)

logger = logging.getLogger("sentinel.parsers")

# ── Pre-compiled regex patterns ────────────────────────────────────────────

# Structured: A=15 C=12 T=50  (any order, case-insensitive)
_STRUCTURED_PATTERN = re.compile(
    r"""
    (?:^|\s)A\s*[=:]\s*(?P<A>\d+)  |
    (?:^|\s)C\s*[=:]\s*(?P<C>\d+)  |
    (?:^|\s)T\s*[=:]\s*(?P<T>\d+)
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Natural: "did 15 got 12 in 50 mins"
_NATURAL_PATTERN = re.compile(
    r"(?:did|attempted|solved)\s+(\d+).*?(?:got|correct|right)\s+(\d+).*?(?:in|took)\s+(\d+)\s*(?:min|m)?",
    re.IGNORECASE,
)

# Compact: "15/12/50" (A/C/T)
_COMPACT_PATTERN = re.compile(r"(\d+)\s*/\s*(\d+)\s*/\s*(\d+)")

# Test scores: "Physics 45/120" or "P: 45/120"
_TEST_SCORE_PATTERN = re.compile(
    r"(?P<subj>Physics|Phys|Phy|P|Chemistry|Chem|C|Mathematics|Maths|Math|M)"
    r"\s*[:\-]?\s*(?P<score>\d+)\s*/\s*(?P<total>\d+)",
    re.IGNORECASE,
)

# Homework: "Physics Ch.5 Ex2A Q1-20"
_HOMEWORK_PATTERN = re.compile(
    r"(?P<subject>Physics|Chem(?:istry)?|Maths?)\s+"
    r"(?:Ch\.?\s*(?P<chapter>\d+\S*))?\s*"
    r"(?P<exercise_type>Ex\s*\d+[AB]?|MLE|PYQs?|JMYL|JAYL)\s+"
    r"(?:Q\s*)?(?P<start>\d+)\s*[-–]\s*(?P<end>\d+)",
    re.IGNORECASE,
)

# Coaching days: "coaching Mon Wed Fri"
_DAYS_PATTERN = re.compile(
    r"(Mon(?:day)?|Tue(?:sday)?|Wed(?:nesday)?|Thu(?:rsday)?|Fri(?:day)?|Sat(?:urday)?|Sun(?:day)?)",
    re.IGNORECASE,
)

_DAY_NORMALISE: dict[str, str] = {
    "mon": "Mon", "monday": "Mon",
    "tue": "Tue", "tuesday": "Tue",
    "wed": "Wed", "wednesday": "Wed",
    "thu": "Thu", "thursday": "Thu",
    "fri": "Fri", "friday": "Fri",
    "sat": "Sat", "saturday": "Sat",
    "sun": "Sun", "sunday": "Sun",
}

_SUBJECT_NORMALISE: dict[str, str] = {
    "physics": "Physics", "phys": "Physics", "phy": "Physics", "p": "Physics",
    "chemistry": "Chem", "chem": "Chem", "c": "Chem",
    "mathematics": "Maths", "maths": "Maths", "math": "Maths", "m": "Maths",
}

class MessageParser:
    """Parses user messages into structured data, regex-first with AI fallback."""

    def __init__(self, ai_engine) -> None:
        self.ai = ai_engine

    # ── Performance report ──────────────────────────────────────────────────

    async def parse_performance_report(self, text: str) -> PerformanceReport | None:
        """Parse a block performance report from text.
        
        Tries regex patterns first, falls back to AI.
        
        Returns:
            PerformanceReport or None if unparseable.
        """
        result = self._try_regex_performance(text)
        if result:
            return result
        # AI fallback
        return await self._ai_parse_performance(text)

    def _try_regex_performance(self, text: str) -> PerformanceReport | None:
        """Attempt to parse performance data using regex patterns."""
        # Strategy 1: Structured A=X C=Y T=Z
        matches = {k: None for k in ("A", "C", "T")}
        for m in _STRUCTURED_PATTERN.finditer(text):
            for key in ("A", "C", "T"):
                val = m.group(key)
                if val is not None:
                    matches[key] = int(val)

        if all(v is not None for v in matches.values()):
            return self._build_perf_result(
                matches["A"], matches["C"], matches["T"], text,
            )

        # Strategy 2: Natural language
        m = _NATURAL_PATTERN.search(text)
        if m:
            return self._build_perf_result(
                int(m.group(1)), int(m.group(2)), int(m.group(3)), text,
            )

        # Strategy 3: Compact A/C/T
        m = _COMPACT_PATTERN.search(text)
        if m:
            return self._build_perf_result(
                int(m.group(1)), int(m.group(2)), int(m.group(3)), text,
            )

        return None

    def _build_perf_result(
        self, A: int, C: int, T: int, text: str,
    ) -> PerformanceReport:
        """Build the result dict, extracting optional subject/type from context."""
        subject = self._extract_subject(text)
        exercise_type = self._extract_exercise_type(text)
        return PerformanceReport(
            attempted=A,
            correct=C,
            time_taken=T,
            subject=subject,
            exercise_type=exercise_type,
            is_report=True,
        )

    async def _ai_parse_performance(self, text: str) -> PerformanceReport | None:
        """Use AI to parse a free-form performance report."""
        from sentinel.brain.prompts import MESSAGE_PARSE_PROMPT

        schema = PerformanceReport.model_json_schema()
        prompt = MESSAGE_PARSE_PROMPT.format(user_message=text)
        prompt += f"\n\nYou MUST return a JSON object adhering exactly to this schema:\n{json.dumps(schema)}"

        try:
            raw = await self.ai.call(
                task_type="parse_message",
                prompt=prompt,
                temperature=0.1,
                max_tokens=256,
            )
            cleaned = self._clean_json(raw)
            parsed = PerformanceReport.model_validate_json(cleaned)
            if not parsed.is_report:
                return None
            return parsed
        except (ValidationError, json.JSONDecodeError) as e:
            logger.warning(f"AI performance parse failed due to bad structure: {e}")
            return None
        except Exception as e:
            logger.error(f"AI performance parse failed due to network/engine error: {e}", exc_info=True)
            return None

    # ── Homework ────────────────────────────────────────────────────────────

    async def parse_homework(self, text: str) -> list[HomeworkEntry]:
        """Parse homework entries from text.
        
        Expected input: "Homework: Physics Ch.5 Ex2A Q1-20, Chem Ch.3 MLE Q1-15"
        
        Returns:
            List of HomeworkEntry models.
        """
        results = []
        for m in _HOMEWORK_PATTERN.finditer(text):
            subj = self._normalise_subject(m.group("subject"))
            chapter = m.group("chapter") or "?"
            ex_type = self._normalise_exercise_type(m.group("exercise_type"))
            start = int(m.group("start"))
            end = int(m.group("end"))
            
            results.append(HomeworkEntry(
                subject=subj,
                chapter=chapter,
                exercise_type=ex_type,
                questions=end - start + 1,
                range=f"Q{start}-{end}",
            ))

        if results:
            return results

        # AI fallback for non-standard formats
        try:
            schema = HomeworkList.model_json_schema()
            from sentinel.brain.prompts import HOMEWORK_PARSE_PROMPT
            prompt = HOMEWORK_PARSE_PROMPT.format(
                subjects=', '.join(SUBJECTS),
                exercise_types=', '.join(EXERCISE_TYPES),
                text=text,
                schema=json.dumps(schema)
            )
            raw = await self.ai.call(
                task_type="parse_message", prompt=prompt,
                temperature=0.1, max_tokens=512,
            )
            cleaned = self._clean_json(raw)
            parsed = HomeworkList.model_validate_json(cleaned)
            return parsed.entries
        except (ValidationError, json.JSONDecodeError) as e:
            logger.warning(f"AI homework parse failed due to bad structure: {e}")
            return []
        except Exception as e:
            logger.error(f"AI homework parse failed due to network/engine error: {e}", exc_info=True)
            return []

    # ── Test scores ─────────────────────────────────────────────────────────

    async def parse_test_scores(self, text: str) -> TestScores:
        """Parse coaching test scores from text.
        
        Expected: "Physics 45/120, Chem 62/120, Maths 55/120"
        
        Returns:
            TestScores model.
        """
        result: dict[str, int] = {}
        for m in _TEST_SCORE_PATTERN.finditer(text):
            subj_raw = m.group("subj").lower()
            score = int(m.group("score"))
            total = int(m.group("total"))
            
            subj = self._normalise_subject(subj_raw)
            if subj == "Physics":
                result["p_score"] = score
                result["p_total"] = total
            elif subj == "Chem":
                result["c_score"] = score
                result["c_total"] = total
            elif subj == "Maths":
                result["m_score"] = score
                result["m_total"] = total
                
        return TestScores.model_validate(result)

    # ── Week schedule ───────────────────────────────────────────────────────

    async def parse_week_schedule(self, text: str) -> list[str]:
        """Parse coaching days from text.
        
        Expected: "coaching Mon Wed Fri" or "Monday, Wednesday, Friday"
        
        Returns:
            List of normalised day abbreviations, e.g. ["Mon", "Wed", "Fri"].
        """
        days = []
        for m in _DAYS_PATTERN.finditer(text):
            normalised = _DAY_NORMALISE.get(m.group(1).lower())
            if normalised and normalised not in days:
                days.append(normalised)
        return days

    # ── Command parsing ─────────────────────────────────────────────────────

    @staticmethod
    def parse_command(text: str) -> tuple[str, str]:
        """Extract command name and arguments from a /command message.
        
        Args:
            text: Raw message text, e.g. "/homework Physics Ch.5 Ex2A Q1-20"
            
        Returns:
            Tuple of (command, args_text). command is lowercase without slash.
            If not a command, returns ("", text).
        """
        text = text.strip()
        if not text.startswith("/"):
            return ("", text)
            
        parts = text.split(None, 1)
        cmd = parts[0][1:].lower().split("@")[0]  # Strip bot username suffix
        args = parts[1] if len(parts) > 1 else ""
        return (cmd, args)

    # ── Intent Classification ───────────────────────────────────────────────

    async def classify_intent(self, text: str) -> IntentClassification:
        """Classify the user's natural language intent with a Rule Engine first, then AI fallback.
        
        Returns:
            IntentClassification model.
        """
        # 1. Rule Engine for fast deterministic routing
        lower_text = text.lower().strip()
        
        # Greetings / Simple Chatter
        if lower_text in ("hello", "hi", "hey", "yo", "sup", "status"):
            return IntentClassification(intent="general", complexity_tier="fast", entities={})
            
        # Commands (handled by explicit intents)
        if lower_text.startswith(("/plan", "reschedule", "adjust plan")):
            return IntentClassification(intent="reschedule", complexity_tier="fast", entities={})
            
        if lower_text.startswith(("/status", "/history", "trend")):
            return IntentClassification(intent="analyze_history", complexity_tier="fast", entities={})
            
        # 2. AI Fallback for ambiguous or complex intents
        schema = IntentClassification.model_json_schema()
        from sentinel.brain.prompts import INTENT_CLASSIFICATION_PROMPT
        prompt = INTENT_CLASSIFICATION_PROMPT.format(text=text, schema=json.dumps(schema))
        try:
            raw = await self.ai.call(
                task_type="parse_message",
                prompt=prompt,
                temperature=0.0,
                max_tokens=150,
            )
            cleaned = self._clean_json(raw)
            return IntentClassification.model_validate_json(cleaned)
        except (ValidationError, json.JSONDecodeError) as e:
            logger.warning(f"Intent classification failed due to bad structure: {e}")
            return IntentClassification(intent="general", complexity_tier="fast", entities={})
        except Exception as e:
            logger.error(f"Intent classification failed due to network/engine error: {e}", exc_info=True)
            return IntentClassification(intent="general", complexity_tier="fast", entities={})

    # ── Private helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _extract_subject(text: str) -> str | None:
        """Try to find a subject mention in the text."""
        lower = text.lower()
        for pattern, normalised in _SUBJECT_NORMALISE.items():
            # Match as whole word to avoid false positives ("p" in "kept")
            if re.search(rf"\b{re.escape(pattern)}\b", lower):
                return normalised
        return None

    @staticmethod
    def _extract_exercise_type(text: str) -> str | None:
        """Try to find an exercise type in the text."""
        for ex in EXERCISE_TYPES:
            if ex.lower() in text.lower():
                return ex
            # Also match without spaces: "Ex2A" -> "Ex 2A"
            compact = ex.replace(" ", "")
            if compact.lower() in text.lower().replace(" ", ""):
                return ex
        return None

    @staticmethod
    def _normalise_subject(raw: str) -> str:
        """Normalise a raw subject string to canonical form."""
        return _SUBJECT_NORMALISE.get(raw.lower().strip(), raw.strip())

    @staticmethod
    def _normalise_exercise_type(raw: str) -> str:
        """Normalise exercise type string (add spaces if needed)."""
        raw = raw.strip()
        for ex in EXERCISE_TYPES:
            if raw.lower().replace(" ", "") == ex.lower().replace(" ", ""):
                return ex
        return raw

    @staticmethod
    def _clean_json(raw: str) -> str:
        """Remove markdown wrappers from LLM JSON responses."""
        cleaned = raw.strip()
        if "```json" in cleaned:
            cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in cleaned:
            cleaned = cleaned.split("```", 1)[1].split("```", 1)[0]
        return cleaned.strip()
