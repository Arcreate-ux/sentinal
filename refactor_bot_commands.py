import re

def refactor_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    # Import PlanningResult
    if "from sentinel.brain.contracts import PlanningResult" not in content:
        # insert after "from sentinel.config import ("
        content = content.replace(
            "from sentinel.config import (", 
            "from sentinel.brain.contracts import PlanningResult, ExecutionPlan\nfrom sentinel.brain.morning_formatter import MorningFormatter\nfrom sentinel.config import ("
        )

    # In cmd_plan
    # Find:
    #             plan = json.loads(raw)
    #             msg = await _planner(context).format_morning_briefing(plan)
    # Replace with:
    #             result = PlanningResult.model_validate_json(raw)
    #             msg = MorningFormatter().format_morning_briefing(result.plan)
    
    content = content.replace(
        "            plan = json.loads(raw)\n            msg = await _planner(context).format_morning_briefing(plan)",
        "            result = PlanningResult.model_validate_json(raw)\n            msg = MorningFormatter().format_morning_briefing(result.plan)"
    )

    content = content.replace(
        "        plan = await _planner(context).generate_daily_plan(day_type, coaching_days, homework)\n        msg = await _planner(context).format_morning_briefing(plan)",
        "        result = await _planner(context).generate_daily_plan(day_type, coaching_days, homework)\n        msg = MorningFormatter().format_morning_briefing(result.plan)"
    )

    # In cmd_status, cmd_skip, cmd_done, cmd_reschedule
    # Find:
    #     plan = json.loads(raw) (or json.loads(raw_plan))
    # Replace with:
    #     result = PlanningResult.model_validate_json(raw)
    #     plan = result.plan
    content = re.sub(
        r'([ \t]+)(\w+) = json\.loads\(raw(_plan)?\)',
        r'\1_result = PlanningResult.model_validate_json(raw\3)\n\1\2 = _result.plan',
        content
    )
    
    # We also need to fix plan accesses, e.g. plan.get("blocks", []) -> plan.blocks
    # plan.get("date", "?") -> plan.date
    content = content.replace('plan.get("blocks", [])', 'plan.blocks')
    content = content.replace('plan.get("date", "?")', 'plan.date')
    content = content.replace('plan.get("date")', 'plan.date')
    content = content.replace('b.get("actual_cy", 0)', 'b.get("actual_cy", 0)') # Wait, 'completed' is a list of dicts stored in state. We should ideally update that too, but let's keep it minimal for now.
    
    # Specifically for block access:
    # skipped = blocks[idx] -> reason... skipped.get("block_label") -> skipped.block_label
    content = content.replace('skipped.get("block_label", "Block")', 'skipped.block_label')
    content = content.replace('skipped.get("subject", "?")', 'skipped.subject')
    
    # For cmd_done block access:
    # block = blocks[idx]
    # block_label = block.get("block_label", "B") -> block.block_label
    # expected_cy = block.get("expected_cy", 0) -> block.expected_cy
    content = content.replace('block.get("block_label", "B")', 'block.block_label')
    content = content.replace('block.get("expected_cy", 0)', 'block.expected_cy')
    content = content.replace('block.get("subject", "?")', 'block.subject')
    content = content.replace('block.get("exercise_type", "?")', 'block.exercise_type')
    content = content.replace('block.get("question_count", 0)', 'block.question_count')
    content = content.replace('block.get("target_time", 0)', 'block.target_time')
    content = content.replace('block["actual_cy"]', 'block.actual_cy')

    # Also updating `json.dumps(plan)` to `_result.model_dump_json()` inside cmd_reschedule
    # Wait, in cmd_reschedule, it calls `_planner(context).adapt_plan()`
    # Let's check `bot/commands.py` for `adapt_plan`.
    
    with open(filepath, 'w') as f:
        f.write(content)

refactor_file('/home/yat/Documents/sentinal/bot/commands.py')
