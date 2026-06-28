import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from sentinel.bot.commands import cmd_done, cmd_homework
from sentinel.bot.parsers import MessageParser
from sentinel.bot.schemas import PerformanceReport
from sentinel.brain.contracts import ExecutionBlock, ExecutionPlan, PlanningResult
from sentinel.brain.orchestrator import Orchestrator
from sentinel.brain.planner import DailyPlanner


class DummyAI:
    async def call(self, **kwargs):
        raise RuntimeError("AI unavailable")


class NoRawCompletedState:
    def __init__(self):
        self.values = {}
        self.saved_blocks = []

    async def get_daily_summary(self, target_date):
        return None

    async def get_streak(self, streak_type):
        return None

    async def set_state(self, key, value):
        if key == "completed_blocks":
            raise AssertionError("raw completed_blocks state must not be written")
        self.values[key] = value


class EmptyNotion:
    async def get_revision_backlog(self):
        return []


class ParserAI:
    async def call(self, **kwargs):
        return "{}"


def _one_block_plan_json():
    block = ExecutionBlock(
        block_label="EB-1",
        subject="Physics",
        exercise_type="JMYL",
        question_count=10,
        target_time=40,
        expected_cy=60,
    )
    result = PlanningResult(
        plan=ExecutionPlan(
            date="2026-06-28",
            day_type="self_study",
            blocks=[block],
            total_expected_cy=60,
            total_expected_time=40,
        ),
        used_fallback=False,
    )
    return result.model_dump_json()


@pytest.mark.asyncio
async def test_cmd_homework_stores_json_dicts():
    update = MagicMock()
    update.message.text = "/homework Physics Ch.5 Ex2A Q1-20"
    state = AsyncMock()
    state.get_state.return_value = None
    context = MagicMock()
    context.bot_data = {
        "state_db": state,
        "parser": MessageParser(ParserAI()),
    }

    with pytest.MonkeyPatch.context() as m:
        m.setattr("sentinel.bot.commands._reply", AsyncMock())
        await cmd_homework(update, context)

    state.set_state.assert_awaited_once()
    key, raw_value = state.set_state.call_args.args
    assert key == "homework_pending"
    stored = json.loads(raw_value)
    assert stored[0]["subject"] == "Physics"
    assert stored[0]["questions"] == 20


@pytest.mark.asyncio
async def test_generate_daily_plan_does_not_write_raw_completed_blocks():
    state = NoRawCompletedState()
    planner = DailyPlanner(DummyAI(), EmptyNotion(), state)

    result = await planner.generate_daily_plan(
        "self_study",
        [],
        [{"subject": "Physics", "chapter": "Ch.5", "exercise_type": "JMYL", "questions": 10}],
    )

    assert result.used_fallback is True
    assert state.values["current_block_index"] == "0"
    assert "completed_blocks" not in state.values


@pytest.mark.asyncio
async def test_cmd_done_saves_block_with_cy_and_assets():
    update = MagicMock()
    update.message.text = "/done attempted 10 correct 8, Q7 was circular motion"
    state = AsyncMock()
    state.get_state.side_effect = lambda key, default=None: {
        "current_plan": _one_block_plan_json(),
        "current_block_index": "0",
    }.get(key, default)
    state.get_unresolved_concepts.return_value = []

    reflection_engine = MagicMock()
    reflection_engine.process_block_reflection = AsyncMock(
        return_value={
            "needs_followup": False,
            "historical_insight": "Same concept appeared before.",
            "parsed_data": {
                "attempted": 10,
                "correct": 8,
                "concept_doubts": ["Q7: circular motion"],
                "incomplete_questions": [],
                "faculty_concepts": ["circular motion"],
            },
        }
    )
    knowledge_engine = MagicMock()
    knowledge_engine.extract_assets = AsyncMock(
        return_value={"concept_assets": [{"concept_name": "Circular Motion"}]}
    )
    context = MagicMock()
    context.bot_data = {
        "state_db": state,
        "reflection_engine": reflection_engine,
        "knowledge_engine": knowledge_engine,
    }

    with pytest.MonkeyPatch.context() as m:
        m.setattr("sentinel.bot.commands._reply", AsyncMock())
        await cmd_done(update, context)

    state.save_completed_block.assert_awaited_once()
    saved_block = state.save_completed_block.call_args.args[1]
    assert saved_block["actual_cy"] > 0
    assert saved_block["A"] == 10
    assert saved_block["C"] == 8
    knowledge_engine.extract_assets.assert_awaited_once()


@pytest.mark.asyncio
async def test_orchestrator_block_report_uses_completed_block_collection():
    state = AsyncMock()

    def get_state(key, default=None):
        if key == "completed_blocks":
            raise AssertionError("raw completed_blocks state must not be read")
        return {
            "current_plan": _one_block_plan_json(),
            "current_block_index": "0",
        }.get(key, default)

    state.get_state.side_effect = get_state

    orchestrator = Orchestrator(
        state_db=state,
        context_builder=None,
        memory_engine=None,
        parser=None,
        action_planner=None,
        executor=None,
        reflection_engine=None,
        knowledge_engine=None,
        analyzer=object(),
        notion_client=None,
    )
    replies = []

    async def reply(message):
        replies.append(message)

    await orchestrator._log_block_result(
        PerformanceReport(attempted=10, correct=8, time_taken=40),
        reply,
        context_obj=None,
    )

    state.save_completed_block.assert_awaited_once()
    saved_block = state.save_completed_block.call_args.args[1]
    assert saved_block["actual_cy"] > 0
    assert replies
