"""
SENTINEL — Planning Context Builder (brain/planning_context_builder.py)
Fetches raw data from storage engines (Mongo/Notion) to build the typed PlanningContext.
"""

from datetime import datetime, timedelta
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

        return PlanningContext(
            yesterday_summary=ys,
            streak=streak,
            revision_backlog=revision_items,
            homework=hw_items,
            learning_confidence_level=learning_level,
        )
