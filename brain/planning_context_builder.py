"""
SENTINEL — Planning Context Builder (brain/planning_context_builder.py)
Fetches raw data from storage engines (Mongo/Notion) to build the typed PlanningContext.
"""

from datetime import datetime, timedelta
import json
import logging

from sentinel.brain.contracts import PlanningContext, YesterdaySummary, StreakInfo, RevisionItem, HomeworkItem

logger = logging.getLogger("sentinel.planning_context")

class PlanningContextBuilder:
    def __init__(self, state_db, notion_client):
        self.state = state_db
        self.notion = notion_client

    async def build_context(self, homework_list: list) -> PlanningContext:
        """
        Gathers raw data for the planner and returns a strongly-typed PlanningContext.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        
        # 1. Gather yesterday's summary
        summary_raw = await self.state.get_daily_summary(yesterday_date)
        if summary_raw:
            ys = YesterdaySummary(
                total_cy=summary_raw.get("total_cy", 0),
                physics_cy=summary_raw.get("physics_cy", 0),
                physics_ty=summary_raw.get("physics_ty", 0),
                chem_cy=summary_raw.get("chem_cy", 0),
                chem_ty=summary_raw.get("chem_ty", 0),
                maths_cy=summary_raw.get("maths_cy", 0),
                maths_ty=summary_raw.get("maths_ty", 0),
                blocks_completed=summary_raw.get("blocks_completed", 0),
                blocks_skipped=summary_raw.get("blocks_skipped", 0),
                raw_data=summary_raw
            )
        else:
            ys = YesterdaySummary()
        
        # 2. Gather streak
        streak_data = await self.state.get_streak("daily_target")
        if streak_data:
            streak = StreakInfo(current_count=streak_data.get("current_count", 0))
        else:
            streak = StreakInfo()
        
        # 3. Gather revision backlog
        revision_items = []
        try:
            backlog = await self.notion.get_revision_backlog()
            if backlog:
                for item in backlog:
                    revision_items.append(RevisionItem(
                        subject=item.get("subject", "?"),
                        chapter=item.get("chapter", "?"),
                        status=item.get("status", "?")
                    ))
        except Exception as e:
            logger.warning(f"Failed to fetch revision backlog: {e}")
            
        # 4. Parse Homework
        hw_items = []
        if homework_list:
            for hw in homework_list:
                hw_items.append(HomeworkItem(
                    subject=hw.get("subject", "?"),
                    chapter=hw.get("chapter", "?"),
                    exercise_type=hw.get("exercise_type", "?"),
                    questions=int(hw.get("questions", 0)),
                    range=hw.get("range")
                ))

        learning_level = 0
        if hasattr(self.state, "get_learning_confidence_level"):
            try:
                learning_level = await self.state.get_learning_confidence_level()
            except Exception as e:
                logger.warning(f"Failed to fetch learning confidence level: {e}")

        # 5. Date context
        day_type_raw = None
        if hasattr(self.state, "get_state"):
            try:
                day_type_raw = await self.state.get_state("day_type")
            except Exception:
                pass
        day_type = day_type_raw if day_type_raw else "self_study"

        # 6. JEE countdown
        days_to_jee = 0
        if hasattr(self.state, "get_state"):
            try:
                jee_raw = await self.state.get_state("days_to_jee")
                if jee_raw:
                    days_to_jee = int(jee_raw)
            except (ValueError, TypeError, Exception):
                pass

        # 7. Coaching exam countdown
        days_to_coaching_exam = 0
        if hasattr(self.state, "get_state"):
            try:
                coaching_days_raw = await self.state.get_state("days_to_coaching_exam")
                if coaching_days_raw:
                    days_to_coaching_exam = int(coaching_days_raw)
            except (ValueError, TypeError, Exception):
                pass

        coaching_exam_syllabus = ""
        if hasattr(self.state, "get_state"):
            try:
                coaching_exam_syllabus = await self.state.get_state("coaching_exam_syllabus") or ""
            except Exception:
                pass

        # 8. Circled questions (stored as JSON list in state)
        circled_questions = []
        if hasattr(self.state, "get_state"):
            try:
                circled_raw = await self.state.get_state("circled_questions")
                if circled_raw:
                    circled_questions = json.loads(circled_raw)
            except (json.JSONDecodeError, TypeError, Exception):
                pass

        # 9. Questions needing repetition (revision_count >= 3, < 5)
        questions_needing_repetition = []
        if hasattr(self.state, "get_questions_needing_repetition"):
            try:
                questions_needing_repetition = await self.state.get_questions_needing_repetition(threshold=3)
            except Exception as e:
                logger.warning(f"Failed to fetch questions needing repetition: {e}")

        # 10. Weak subjects (average accuracy < 50% this week)
        weak_subjects = []
        if hasattr(self.state, "get_blocks_range"):
            try:
                blocks_raw = await self.state.get_blocks_range(
                    (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
                    today
                )
                if blocks_raw:
                    subject_stats = {}
                    for b in blocks_raw:
                        subj = b.get("subject", "")
                        a = b.get("attempted") or 0
                        c = b.get("correct") or 0
                        if a > 0:
                            subject_stats.setdefault(subj, []).append(c / a)
                    for subj, accs in subject_stats.items():
                        avg = sum(accs) / len(accs) if accs else 0
                        if avg < 0.5:
                            weak_subjects.append(subj)
            except Exception as e:
                logger.warning(f"Failed to compute weak subjects: {e}")

        # 11. Yesterday completion percentage
        yesterday_completion_pct = 0.0
        if ys.blocks_completed > 0 or ys.blocks_skipped > 0:
            total = ys.blocks_completed + ys.blocks_skipped
            yesterday_completion_pct = round(ys.blocks_completed / total, 2) if total > 0 else 0.0

        # 12. 7-day rolling average CY
        average_cy = 0.0
        try:
            week_summaries = []
            for i in range(7):
                d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                s = await self.state.get_daily_summary(d)
                if s:
                    week_summaries.append(s.get("total_cy", 0))
            if week_summaries:
                average_cy = round(sum(week_summaries) / len(week_summaries), 1)
        except Exception as e:
            logger.warning(f"Failed to compute average CY: {e}")

        return PlanningContext(
            yesterday_summary=ys,
            streak=streak,
            revision_backlog=revision_items,
            homework=hw_items,
            learning_confidence_level=learning_level,
            date=today,
            day_type=day_type,
            days_to_jee=days_to_jee,
            days_to_coaching_exam=days_to_coaching_exam,
            coaching_exam_syllabus=coaching_exam_syllabus,
            circled_questions=circled_questions,
            questions_needing_repetition=questions_needing_repetition,
            weak_subjects=weak_subjects,
            yesterday_completion_pct=yesterday_completion_pct,
            average_cy=average_cy,
            pending_homework=len(hw_items),
        )
