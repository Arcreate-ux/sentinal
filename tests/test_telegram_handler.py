import pytest
from unittest.mock import AsyncMock, MagicMock
from sentinel.bot.telegram_handler import SentinelBot
from telegram import Update, Poll
from sentinel.brain.contracts import ExecutionBlock, ExecutionPlan, PlanningResult

@pytest.mark.asyncio
async def test_regression_allowlist_poll():
    # Bug: username = update.message.from_user.username caused crash on Poll updates
    bot = SentinelBot(
        token="mock", notion_client=MagicMock(), ai_engine=MagicMock(),
        state_db=AsyncMock(), health_monitor=MagicMock(), planner=MagicMock(),
        analyzer=MagicMock(), roaster=MagicMock(), parser=MagicMock()
    )
    
    app = bot.setup()
    
    # Get the allowlist_check TypeHandler
    handlers = app.handlers[-1] # Group -1
    allowlist_handler = handlers[0]
    
    update = MagicMock(spec=Update)
    update.message = None
    update.callback_query = None
    update.poll = MagicMock(spec=Poll)
    
    context = MagicMock()
    
    # Should not raise UnboundLocalError for 'username'
    await allowlist_handler.callback(update, context)

@pytest.mark.asyncio
async def test_regression_daily_summary_blocks():
    # Bug: send_daily_summary read raw JSON instead of using get_today_blocks
    bot = SentinelBot(
        token="mock", notion_client=MagicMock(), ai_engine=MagicMock(),
        state_db=AsyncMock(), health_monitor=MagicMock(), planner=MagicMock(),
        analyzer=MagicMock(), roaster=MagicMock(), parser=MagicMock()
    )
    
    # Mock get_today_blocks to return a single block
    mock_block = {"subject": "Physics", "actual_cy": 50}
    bot.state.get_today_blocks.return_value = [mock_block]
    bot.state.get_state.return_value = "0" # blocks_skipped_today
    bot.analyzer.generate_daily_summary = AsyncMock(return_value="Total CY: 50")
    
    with pytest.MonkeyPatch.context() as m:
        mock_send = AsyncMock()
        m.setattr(bot, "send_message", mock_send)
        
        await bot.send_daily_summary()
        
        # Verify get_today_blocks was used
        bot.state.get_today_blocks.assert_called_once()
        
        # Verify the CY sum was correctly parsed
        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][0]
        assert "Total CY: 50" in sent_text

@pytest.mark.asyncio
async def test_send_morning_briefing_uses_existing_plan():
    bot = SentinelBot(
        token="mock", notion_client=MagicMock(), ai_engine=MagicMock(),
        state_db=AsyncMock(), health_monitor=MagicMock(), planner=MagicMock(),
        analyzer=MagicMock(), roaster=MagicMock(), parser=MagicMock()
    )
    today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    plan = PlanningResult(
        plan=ExecutionPlan(
            date=today,
            day_type="self_study",
            blocks=[
                ExecutionBlock(
                    block_label="EB-1",
                    subject="Physics",
                    exercise_type="JMYL",
                    question_count=10,
                    target_time=40,
                    expected_cy=60,
                )
            ],
            total_expected_cy=60,
            total_expected_time=40,
        ),
        used_fallback=False,
    )
    bot.state.get_state.side_effect = lambda key, default=None: {
        "plan_date": today,
        "current_plan": plan.model_dump_json(),
    }.get(key, default)

    with pytest.MonkeyPatch.context() as m:
        mock_send = AsyncMock()
        m.setattr(bot, "send_message", mock_send)

        await bot.send_morning_briefing()

        mock_send.assert_awaited_once()
        assert "DAY PLAN" in mock_send.call_args.args[0]
        assert "Physics JMYL" in mock_send.call_args.args[0]
