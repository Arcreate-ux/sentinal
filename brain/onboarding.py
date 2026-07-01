"""
SENTINEL — Onboarding Engine (brain/onboarding.py)

First-run conversation that learns about the student.
Asks questions one at a time, saves answers, builds a complete student profile.
"""

import json
import logging
from typing import Any

logger = logging.getLogger("sentinel.brain.onboarding")

ONBOARDING_STEPS = [
    {
        "key": "name",
        "question": "👋 Hey! I'm SENTINEL — your AI study coach for JEE.\n\nBefore we start, I need to learn about you.\n\nWhat's your name?",
    },
    {
        "key": "jee_target",
        "question": "Are you targeting JEE Main (Jan 2028), JEE Advanced (Jun 2028), or both?",
    },
    {
        "key": "coaching_start",
        "question": "When did you start coaching? (e.g., March 2026)",
    },
    {
        "key": "coaching_days",
        "question": "What are your coaching days? (e.g., Mon Wed Fri)",
    },
    {
        "key": "faculty_physics",
        "question": "Who teaches Physics at your coaching? (name or 'skip')",
    },
    {
        "key": "faculty_chem",
        "question": "Who teaches Chemistry?",
    },
    {
        "key": "faculty_maths",
        "question": "Who teaches Maths?",
    },
    {
        "key": "current_chapters",
        "question": "What chapters are you currently doing?\n\nExample: Physics: COM, Chem: Equilibrium, Maths: Sequences",
    },
    {
        "key": "backlog_estimate",
        "question": "Roughly how many homework backlogs do you have right now? (just a number)",
    },
    {
        "key": "extra_notes",
        "question": "Anything else I should know about you? (type 'skip' if nothing)",
    },
]


class OnboardingEngine:
    """State machine for first-run student onboarding."""

    def __init__(self, state_db) -> None:
        self.state = state_db

    async def is_onboarded(self) -> bool:
        """Check if the student has completed onboarding."""
        profile = await self.state.get_student_profile()
        return profile is not None and profile.get("onboarded", False)

    async def get_first_question(self) -> str:
        """Start onboarding and return the first question."""
        await self.state.set_state("onboarding_step", "0")
        await self.state.set_state("onboarding_data", "{}")
        await self.state.set_state("conversation_state", "onboarding")
        return ONBOARDING_STEPS[0]["question"]

    async def handle_step(self, text: str) -> str:
        """Process the current step's answer and return the next question or finish."""
        step_raw = await self.state.get_state("onboarding_step")
        step = int(step_raw) if step_raw else 0

        # Load accumulated data
        data_raw = await self.state.get_state("onboarding_data")
        data = json.loads(data_raw) if data_raw else {}

        # Save current answer
        if step < len(ONBOARDING_STEPS):
            key = ONBOARDING_STEPS[step]["key"]
            answer = text.strip()
            if answer.lower() != "skip":
                data[key] = answer
            await self.state.set_state("onboarding_data", json.dumps(data))

        # Move to next step
        next_step = step + 1

        if next_step < len(ONBOARDING_STEPS):
            await self.state.set_state("onboarding_step", str(next_step))
            return ONBOARDING_STEPS[next_step]["question"]

        # All questions answered — finalize
        return await self._finalize(data)

    async def _finalize(self, data: dict[str, Any]) -> str:
        """Build and save the complete student profile."""
        # Parse coaching days
        coaching_days_raw = data.get("coaching_days", "")
        coaching_days = [d.strip()[:3].title() for d in coaching_days_raw.replace(",", " ").split() if d.strip()]

        # Parse JEE target dates
        jee_target = data.get("jee_target", "both").lower()
        jee_main_date = "2028-01-20"
        jee_advanced_date = "2028-06-01"

        # Parse chapters
        chapters = {"Physics": "", "Chem": "", "Maths": ""}
        chapters_raw = data.get("current_chapters", "")
        for part in chapters_raw.split(","):
            part = part.strip()
            for subj in ["Physics", "Chem", "Maths", "Chemistry", "Math"]:
                if subj.lower() in part.lower():
                    key = "Chem" if "chem" in subj.lower() else ("Maths" if "math" in subj.lower() else subj)
                    chapters[key] = part.split(":", 1)[-1].strip() if ":" in part else part
                    break

        # Parse backlog
        try:
            backlog = int("".join(c for c in data.get("backlog_estimate", "0") if c.isdigit()) or "0")
        except ValueError:
            backlog = 0

        profile = {
            "name": data.get("name", "Student"),
            "jee_target": "both" if "both" in jee_target else ("main" if "main" in jee_target else "advanced"),
            "jee_main_date": jee_main_date,
            "jee_advanced_date": jee_advanced_date,
            "coaching_start": data.get("coaching_start", ""),
            "coaching_days": coaching_days,
            "faculty": {
                "Physics": data.get("faculty_physics", ""),
                "Chem": data.get("faculty_chem", ""),
                "Maths": data.get("faculty_maths", ""),
            },
            "current_chapters": chapters,
            "backlog_estimate": backlog,
            "extra_notes": data.get("extra_notes", ""),
            "onboarded": True,
        }

        await self.state.save_student_profile(profile)

        # Save coaching days to state (used by planner)
        await self.state.set_state("coaching_days", json.dumps(coaching_days))

        # Save faculty as memories for contextual resolution
        for subj, name in profile["faculty"].items():
            if name and name.lower() not in ("skip", ""):
                await self.state.save_memory({
                    "raw_text": f"{name} is my {subj} teacher",
                    "entities": [name],
                    "resolved_subject": subj,
                    "resolved_type": "faculty",
                    "tags": ["faculty", subj.lower(), name.lower()],
                })

        # Clear onboarding state
        await self.state.set_state("conversation_state", "default")
        await self.state.delete_state("onboarding_step")
        await self.state.delete_state("onboarding_data")

        logger.info("Onboarding complete for %s", profile["name"])

        return (
            f"⚔️ SENTINEL ONLINE\n"
            f"{'━' * 24}\n"
            f"Welcome, {profile['name']}.\n\n"
            f"Target: IIT Bombay CS\n"
            f"JEE Main: {jee_main_date} | JEE Advanced: {jee_advanced_date}\n"
            f"Coaching days: {', '.join(coaching_days) if coaching_days else 'Not set'}\n"
            f"Backlogs: ~{backlog}\n\n"
            f"I know your faculty, your chapters, and your situation.\n"
            f"From now on, I learn everything about how you study.\n\n"
            f"Commands: /help\n"
            f"Let's get to work. 🔥"
        )
