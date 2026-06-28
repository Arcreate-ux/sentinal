import sys
from pydantic import ValidationError
from datetime import datetime

from sentinel.brain.contracts import (
    ExecutionPlan, ExecutionBlock, PlanningResult, PlanningContext,
    HomeworkItem, YesterdaySummary, StreakInfo
)
from sentinel.brain.protocol.snapshot import ProtocolSnapshot
from sentinel.brain.planning_fallback import FallbackPlanner

def run_tests():
    print("=== Contract Verification Tests ===\n")
    passed = 0
    failed = 0

    def assert_test(name, condition, error_msg=""):
        nonlocal passed, failed
        if condition:
            print(f"✅ {name}")
            passed += 1
        else:
            print(f"❌ {name} (Failed: {error_msg})")
            failed += 1

    # Setup base objects
    block = ExecutionBlock(
        block_label="EB-1", subject="Physics", exercise_type="Ex 1A",
        question_count=10, target_time=45, expected_cy=60
    )
    plan = ExecutionPlan(
        date="2026-06-28", day_type="self_study", blocks=[block],
        total_expected_cy=60, total_expected_time=45
    )
    result = PlanningResult(
        plan=plan, used_fallback=False, ai_provider="g4f_pro", model="gpt-4o"
    )
    context = PlanningContext(
        yesterday_summary=YesterdaySummary(total_cy=240),
        streak=StreakInfo(current_count=5),
        revision_backlog=[],
        homework=[HomeworkItem(subject="Maths", chapter="Calculus", exercise_type="Ex 1A", questions=20)]
    )

    # Test 1: ExecutionPlan round-trip
    plan_json = plan.model_dump_json()
    restored_plan = ExecutionPlan.model_validate_json(plan_json)
    assert_test("ExecutionPlan round-trip", plan == restored_plan)

    # Test 2: PlanningResult round-trip
    result_json = result.model_dump_json()
    restored_result = PlanningResult.model_validate_json(result_json)
    assert_test("PlanningResult round-trip", result == restored_result)

    # Test 3: PlanningContext round-trip
    context_json = context.model_dump_json()
    restored_context = PlanningContext.model_validate_json(context_json)
    assert_test("PlanningContext round-trip", context == restored_context)

    # Test 4: Invalid JSON rejected
    try:
        ExecutionPlan.model_validate_json('{"date": "2026-06-28", "blocks": [{"subject": "Maths"}]}')
        assert_test("Invalid JSON rejected", False, "Should have raised ValidationError")
    except ValidationError:
        assert_test("Invalid JSON rejected", True)

    # Test 5: Nested contract validation
    try:
        HomeworkItem(subject=123)
        assert_test("Nested contract validation", False, "Should have rejected int for str")
    except ValidationError:
        assert_test("Nested contract validation", True)

    # Test 6: Unknown fields rejected
    try:
        ExecutionPlan.model_validate_json('{"schema_version": "1.0", "date": "2026-06-28", "day_type": "self_study", "blocks": [], "unknown_field": "bad"}')
        assert_test("Unknown fields rejected", False, "Should have forbidden extra field")
    except ValidationError:
        assert_test("Unknown fields rejected", True)

    # Test 7: Schema version valid
    assert_test("Schema version valid", plan.schema_version == "1.0")

    # Test 8: Schema version mismatch rejected
    try:
        ExecutionPlan.model_validate_json('{"schema_version": "0.9", "date": "2026-06-28", "day_type": "self_study", "blocks": []}')
        assert_test("Schema version mismatch rejected", False, "Should have rejected 0.9 schema_version")
    except ValidationError:
        assert_test("Schema version mismatch rejected", True)

    # Test 9: Protocol immutable
    protocol = ProtocolSnapshot()
    try:
        protocol.hard_stop_hour = 2
        assert_test("Protocol immutable", False, "Should have raised ValidationError")
    except ValidationError:
        assert_test("Protocol immutable", True)

    # Test 10: Fallback returns ExecutionPlan
    fallback = FallbackPlanner()
    fallback_plan = fallback.generate_fallback_plan("2026-06-28", "self_study", [], protocol)
    assert_test("Fallback returns ExecutionPlan", isinstance(fallback_plan, ExecutionPlan))

    print(f"\n{passed}/{passed+failed} tests passed")
    if failed > 0:
        sys.exit(1)

if __name__ == "__main__":
    run_tests()
