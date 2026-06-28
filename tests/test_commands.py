import pytest
from unittest.mock import AsyncMock, MagicMock
from sentinel.bot.commands import cmd_week, cmd_status, cmd_scores
from sentinel.brain.contracts.planning import ExecutionPlan, PlanningContext, ExecutionBlock
from sentinel.bot.schemas import TestScores as ScoreModel

@pytest.mark.asyncio
async def test_cmd_week_no_args():
    update = MagicMock()
    update.message.text = "/week"
    context = MagicMock()
    
    mock_state = AsyncMock()
    mock_state.get_state.return_value = '["Mon", "Wed"]'
    context.bot_data = {"state_db": mock_state}
    
    with pytest.MonkeyPatch.context() as m:
        mock_reply = AsyncMock()
        m.setattr("sentinel.bot.commands._reply", mock_reply)
        await cmd_week(update, context)
        
        mock_reply.assert_called_once()
        assert "Mon, Wed" in mock_reply.call_args[0][1]

@pytest.mark.asyncio
async def test_cmd_status_no_plan():
    update = MagicMock()
    context = MagicMock()
    
    mock_state = AsyncMock()
    mock_state.get_state.return_value = None
    context.bot_data = {"state_db": mock_state}
    
    with pytest.MonkeyPatch.context() as m:
        mock_reply = AsyncMock()
        m.setattr("sentinel.bot.commands._reply", mock_reply)
        await cmd_status(update, context)
        
        mock_reply.assert_called_once()
        assert "No plan found" in mock_reply.call_args[0][1]

@pytest.mark.asyncio
async def test_regression_get_on_plan():
    # Bug: plan.get() caused crash because ExecutionPlan is a Pydantic object
    update = MagicMock()
    context = MagicMock()
    
    mock_state = AsyncMock()
    # Provide a valid mocked JSON representation of PlanningResult
    plan_json = '{"plan": {"date": "2026-06-28", "day_type": "normal", "blocks": [], "total_expected_cy": 150, "total_expected_time": 100}, "used_fallback": false, "ai_provider": "claude", "schema_version": "1.0"}'
    mock_state.get_state.return_value = plan_json
    mock_state.get_today_blocks.return_value = []
    
    context.bot_data = {"state_db": mock_state}
    
    with pytest.MonkeyPatch.context() as m:
        mock_reply = AsyncMock()
        m.setattr("sentinel.bot.commands._reply", mock_reply)
        # Should not raise AttributeError
        await cmd_status(update, context)
        mock_reply.assert_called_once()
        assert "CY: 0/150" in mock_reply.call_args[0][1]

@pytest.mark.asyncio
async def test_regression_save_test_score_await():
    # Bug: save_test_score was not awaited, causing data loss
    update = MagicMock()
    update.message.text = "/scores Physics 50/120"
    context = MagicMock()
    context.args = ["Physics", "50/120"]
    
    mock_state = AsyncMock()
    context.bot_data = {"state_db": mock_state}
    
    with pytest.MonkeyPatch.context() as m:
        mock_reply = AsyncMock()
        m.setattr("sentinel.bot.commands._reply", mock_reply)
        mock_parser = MagicMock()
        mock_parser.parse_test_scores = AsyncMock(return_value={"p_score": 50, "p_total": 120, "c_score": 0, "c_total": 120, "m_score": 0, "m_total": 120})
        m.setattr("sentinel.bot.commands._parser", MagicMock(return_value=mock_parser))
        
        await cmd_scores(update, context)
        
        # Verify save_test_score was actually awaited by AsyncMock
        mock_state.save_test_score.assert_called_once()

@pytest.mark.asyncio
async def test_cmd_scores_accepts_parser_model():
    # The real parser returns a TestScores model, not a dict.
    update = MagicMock()
    update.message.text = "/scores Physics 50/120"
    context = MagicMock()
    context.args = ["Physics", "50/120"]

    mock_state = AsyncMock()
    mock_roaster = MagicMock()
    mock_roaster.generate_test_recalibration = AsyncMock(return_value="recalibration")
    context.bot_data = {"state_db": mock_state, "roaster": mock_roaster}

    with pytest.MonkeyPatch.context() as m:
        mock_reply = AsyncMock()
        m.setattr("sentinel.bot.commands._reply", mock_reply)
        mock_parser = MagicMock()
        mock_parser.parse_test_scores = AsyncMock(
            return_value=ScoreModel(p_score=50, p_total=120)
        )
        m.setattr("sentinel.bot.commands._parser", MagicMock(return_value=mock_parser))

        await cmd_scores(update, context)

        mock_state.save_test_score.assert_called_once()
        kwargs = mock_state.save_test_score.call_args.kwargs
        assert "date" not in kwargs
        assert kwargs["test_date"]
        assert kwargs["p_score"] == 50
        mock_roaster.generate_test_recalibration.assert_awaited_once()
