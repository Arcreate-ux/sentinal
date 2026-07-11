"""
SENTINEL — Onboarding Engine (brain/onboarding.py)

First-run conversation that learns about the student.
Asks questions one at a time, saves answers, builds a complete student profile.
"""

import json
import logging
from datetime import date
from typing import Any

logger = logging.getLogger("sentinel.brain.onboarding")

ONBOARDING_STEPS = [
    {
        "key": "name",
        "question": "👋 Hey! I'm SENTINEL — your AI study coach for JEE.\n\nBefore we start, I need to learn about you.\n\nWhat's your name?",
    },
    {
        "key": "jee_exam_date",
        "question": "When is your JEE Main exam? (YYYY-MM-DD)\n\nExample: 2027-01-25",
    },
    {
        "key": "jee_target",
        "question": "Are you targeting JEE Main only, JEE Advanced only, or both?",
    },
    {
        "key": "coaching_name",
        "question": "What's your coaching institute name?\n(Enter the name or 'skip' if not applicable)",
    },
    {
        "key": "coaching_start",
        "question": "When did you start coaching? (e.g., March 2026)",
    },
    {
        "key": "coaching_exam_cycle_days",
        "question": "How often are your coaching exams? (in days)\n\nExample: 21 for every 3 weeks, 14 for every 2 weeks",
    },
    {
        "key": "next_coaching_exam_date",
        "question": "When is your next coaching exam? (YYYY-MM-DD)\n\nExample: 2026-08-01",
    },
    {
        "key": "coaching_exam_syllabus",
        "question": "What's the syllabus for this coaching exam?\n(comma-separated topics or 'skip')\n\nExample: NLM, Rotational Motion, Quadratics, Electrochemistry",
    },
    {
        "key": "coaching_days",
        "question": "Which days do you have coaching? (e.g., Mon Wed Fri)",
    },
    {
        "key": "subjects",
        "question": "What subjects are you studying?\n(comma-separated or 'Physics, Chemistry, Mathematics')",
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
        "key": "daily_study_hours",
        "question": "How many hours can you study on a self-study day?\n(just a number, e.g. 8)",
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
        today = date.today()

        # Parse coaching days
        coaching_days_raw = data.get("coaching_days", "")
        coaching_days = [d.strip()[:3].title() for d in coaching_days_raw.replace(",", " ").split() if d.strip()]

        # Parse JEE exam date and compute days left
        jee_exam_date_str = data.get("jee_exam_date", "2028-01-20")
        try:
            jee_exam_date_parsed = date.fromisoformat(jee_exam_date_str)
            days_to_jee = (jee_exam_date_parsed - today).days
        except ValueError:
            days_to_jee = None

        jee_advanced_date = "2028-06-01"
        try:
            jee_advanced_parsed = date.fromisoformat(jee_advanced_date)
            days_to_jee_adv = (jee_advanced_parsed - today).days
        except ValueError:
            days_to_jee_adv = None

        # Parse JEE target
        jee_target = data.get("jee_target", "both").lower()

        # Parse subjects
        subjects_raw = data.get("subjects", "Physics, Chemistry, Mathematics")
        subjects = [s.strip() for s in subjects_raw.replace(",", " ").split() if s.strip()]

        # Parse coaching exam cycle and next exam
        coaching_exam_cycle_raw = data.get("coaching_exam_cycle_days", "")
        try:
            coaching_exam_cycle = int("".join(c for c in coaching_exam_cycle_raw if c.isdigit()) or "0")
        except ValueError:
            coaching_exam_cycle = 0

        next_coaching_exam_date_str = data.get("next_coaching_exam_date", "")
        days_to_coaching_exam = None
        if next_coaching_exam_date_str:
            try:
                next_coaching_parsed = date.fromisoformat(next_coaching_exam_date_str)
                days_to_coaching_exam = (next_coaching_parsed - today).days
            except ValueError:
                pass

        # Parse daily study hours
        daily_study_hours_raw = data.get("daily_study_hours", "")
        try:
            daily_study_hours = int("".join(c for c in daily_study_hours_raw if c.isdigit()) or "0")
        except ValueError:
            daily_study_hours = 0

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
            "jee_exam_date": jee_exam_date_str,
            "jee_advanced_date": jee_advanced_date,
            "days_to_jee": days_to_jee,
            "days_to_jee_advanced": days_to_jee_adv,
            "coaching_name": data.get("coaching_name", ""),
            "coaching_start": data.get("coaching_start", ""),
            "coaching_days": coaching_days,
            "coaching_exam_cycle_days": coaching_exam_cycle,
            "next_coaching_exam_date": next_coaching_exam_date_str,
            "coaching_exam_syllabus": data.get("coaching_exam_syllabus", ""),
            "subjects": subjects,
            "faculty": {
                "Physics": data.get("faculty_physics", ""),
                "Chem": data.get("faculty_chem", ""),
                "Maths": data.get("faculty_maths", ""),
            },
            "current_chapters": chapters,
            "daily_study_hours": daily_study_hours,
            "backlog_estimate": backlog,
            "extra_notes": data.get("extra_notes", ""),
            "onboarded": True,
        }

        await self.state.save_student_profile(profile)

        # Save coaching days to state (used by planner)
        await self.state.set_state("coaching_days", json.dumps(coaching_days))

        # Save all new onboarding fields individually for quick lookup
        await self.state.set_state("jee_exam_date", jee_exam_date_str)
        await self.state.set_state("days_to_jee", str(days_to_jee) if days_to_jee is not None else "")
        await self.state.set_state("coaching_name", data.get("coaching_name", ""))
        await self.state.set_state("coaching_exam_cycle_days", str(coaching_exam_cycle))
        await self.state.set_state("next_coaching_exam_date", next_coaching_exam_date_str)
        await self.state.set_state("coaching_exam_syllabus", data.get("coaching_exam_syllabus", ""))
        await self.state.set_state("subjects", json.dumps(subjects))
        await self.state.set_state("daily_study_hours", str(daily_study_hours))
        await self.state.set_state("days_to_coaching_exam", str(days_to_coaching_exam) if days_to_coaching_exam is not None else "")

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

        # Build completion message
        jee_days_str = f"{days_to_jee}d" if days_to_jee is not None else "?"
        exam_days_str = f"{days_to_coaching_exam}d" if days_to_coaching_exam is not None else "?"
        syllabus_preview = data.get("coaching_exam_syllabus", "")[:50]
        if syllabus_preview:
            syllabus_preview = syllabus_preview + "..." if len(data.get("coaching_exam_syllabus", "")) > 50 else syllabus_preview

        return (
            f"⚔️ SENTINEL ONLINE\n"
            f"{'━' * 24}\n"
            f"Welcome, {profile['name']}.\n\n"
            f"Target: IIT Bombay CS\n"
            f"JEE Main: {jee_exam_date_str} ({jee_days_str} away)\n"
            f"JEE Advanced: {jee_advanced_date} ({days_to_jee_adv}d away)\n"
            f"Coaching: {profile['coaching_name'] or 'Not set'} | {', '.join(coaching_days) if coaching_days else 'No days set'}\n"
            f"Coaching exam: {next_coaching_exam_date_str or 'Not set'} ({exam_days_str} away)\n"
            f"Syllabus: {syllabus_preview or 'Not set'}\n"
            f"Study hours/day: {daily_study_hours}h | Backlogs: ~{backlog}\n\n"
            f"I know your faculty, your chapters, and your situation.\n"
            f"From now on, I learn everything about how you study.\n\n"
            f"Commands: /help\n"
            f"Let's get to work. 🔥"
        )
