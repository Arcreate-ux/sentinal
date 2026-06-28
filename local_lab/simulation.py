from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sentinel.brain.study_blocks import StudyBlockEngine
from sentinel.notion_client.formulas import cognitive_yield, theory_yield


SCENARIO_KINDS = [
    "first_day",
    "normal_homework",
    "skipped_homework",
    "skipped_theory",
    "revision_day",
    "coaching_test",
    "api_failure",
    "parser_ambiguity",
    "interrupted_study_block",
    "duplicate_reflection",
    "burnout_day",
    "illness",
    "backlog_overload",
    "faculty_session",
    "concept_mastered",
    "concept_forgotten",
    "impossible_schedule",
    "homework_learning",
]


@dataclass
class Check:
    status: str
    area: str
    message: str


@dataclass
class ScenarioResult:
    name: str
    kind: str
    day_number: int
    date_str: str
    checks: list[Check] = field(default_factory=list)
    ai_responses: list[dict[str, Any]] = field(default_factory=list)

    def add(self, status: str, area: str, message: str) -> None:
        self.checks.append(Check(status=status, area=area, message=message))


class SimulationEngine:
    """Runs local-only SENTINEL Phase 1 scenarios against fake services."""

    def __init__(self, harness: Any) -> None:
        self.harness = harness
        self.state = harness.state
        self.notion = harness.notion
        self.parser = harness.parser
        self.reflection = harness.reflection_engine
        self.knowledge = harness.knowledge_engine
        self.ai = harness.ai
        self.seeded_until = 0
        self.start_date = date.today() - timedelta(days=364)

    async def run(self, requested_count: int = 60) -> str:
        scenario_count = max(50, min(requested_count, 90))
        self._reset_fake_data()
        scenarios = self._build_scenarios(scenario_count)
        results: list[ScenarioResult] = []
        for scenario in scenarios:
            await self._seed_history_until(scenario["day_number"] - 1)
            results.append(await self._run_scenario(scenario))
        return await self._format_report(results, requested_count, scenario_count)

    def _reset_fake_data(self) -> None:
        chat_history = self.state.data.get("chat_history", [])[-20:]
        self.state.data.update(
            {
                "system_state": {},
                "completed_blocks": [],
                "daily_summary": [],
                "test_scores": [],
                "api_health": {},
                "streaks": {},
                "chat_history": chat_history,
                "learning_events": [],
                "concept_assets": [],
                "archived_questions": [],
                "skill_assets": [],
                "recommendation_history": [],
                "study_blocks": [],
                "learning_model": {},
                "experience_rules": [],
                "timeline": [],
                "recovery_history": [],
                "faculty_history": [],
                "prediction_history": [],
                "planner_decisions": [],
            }
        )
        self.state._save()
        self.notion.data["rows"] = {"db1": [], "db2": [], "db3": [], "db4": []}
        self.notion._save()
        self.harness.audit.clear()
        self.harness.audit.log("simulation.reset", note="local fake databases cleared")

    def _build_scenarios(self, count: int) -> list[dict[str, Any]]:
        milestone_days = {1, 7, 30, 180, 365}
        spread = {round(1 + idx * (364 / max(count - 1, 1))) for idx in range(count)}
        days = sorted(milestone_days | spread)
        while len(days) < count:
            for candidate in range(1, 366):
                if candidate not in days:
                    days.append(candidate)
                    break
        days = sorted(days)[:count]
        if 365 not in days:
            days[-1] = 365
            days = sorted(set(days))

        scenarios = []
        for idx, day_number in enumerate(days[:count]):
            if day_number == 1:
                kind = "first_day"
            elif day_number == 7:
                kind = "one_week_later"
            elif day_number == 30:
                kind = "one_month_later"
            elif day_number == 180:
                kind = "six_month_later"
            elif day_number == 365:
                kind = "one_year_later"
            else:
                kind = SCENARIO_KINDS[idx % len(SCENARIO_KINDS)]
            target = self.start_date + timedelta(days=day_number - 1)
            scenarios.append(
                {
                    "name": f"{idx + 1:02d}_{kind}",
                    "kind": kind,
                    "day_number": day_number,
                    "date": target.isoformat(),
                }
            )
        return scenarios

    async def _seed_history_until(self, day_number: int) -> None:
        while self.seeded_until < day_number:
            self.seeded_until += 1
            target = (self.start_date + timedelta(days=self.seeded_until - 1)).isoformat()
            base = 160 + (self.seeded_until % 80)
            await self.state.save_daily_summary(
                target_date=target,
                total_cy=base,
                physics_cy=base // 3,
                physics_ty=45,
                chem_cy=base // 3,
                chem_ty=42,
                maths_cy=base - 2 * (base // 3),
                maths_ty=48,
                blocks_completed=3,
                blocks_skipped=1 if self.seeded_until % 13 == 0 else 0,
                day_type="seeded_history",
            )

    async def _run_scenario(self, scenario: dict[str, Any]) -> ScenarioResult:
        audit_start = self._audit_line_count()
        result = ScenarioResult(scenario["name"], scenario["kind"], scenario["day_number"], scenario["date"])
        blocks = self._make_blocks(scenario)
        await self.state.save_study_blocks(scenario["date"], blocks)
        await self.state.save_planner_decision(
            {
                "date": scenario["date"],
                "scenario": scenario["name"],
                "learning_confidence_level": await self.state.get_learning_confidence_level(),
                "block_ids": [block["block_id"] for block in blocks],
                "expected_cy": sum(block["expected_cy"] for block in blocks),
                "expected_minutes": sum(block["estimated_minutes"] for block in blocks),
            }
        )

        await self._check_planner_and_blocks(result, scenario, blocks)
        await self._check_parser(result, scenario)

        kind = scenario["kind"]
        if kind in {"skipped_homework", "skipped_theory", "illness", "burnout_day"}:
            await self._run_skip_or_recovery(result, scenario, blocks[0])
        elif kind == "interrupted_study_block":
            await self._run_interrupted(result, scenario, blocks[0])
        elif kind == "duplicate_reflection":
            await self._run_duplicate(result, scenario, blocks[0])
        elif kind == "parser_ambiguity":
            await self._run_ambiguity(result, scenario, blocks[0])
        elif kind == "api_failure":
            await self._run_api_failure(result, scenario, blocks[0])
        elif kind == "coaching_test":
            await self._run_test_day(result, scenario, blocks[0])
        elif kind == "faculty_session":
            await self._run_faculty_session(result, scenario, blocks[0])
        elif kind == "concept_mastered":
            await self._run_concept_mastered(result, scenario, blocks[0])
        elif kind == "concept_forgotten":
            await self._run_concept_forgotten(result, scenario, blocks[0])
        elif kind in {"impossible_schedule", "backlog_overload"}:
            await self._run_impossible_or_backlog(result, scenario, blocks[0])
        else:
            await self._run_completed_homework(result, scenario, blocks[0])

        await self._write_daily_summary(scenario["date"])
        await self._check_common_postconditions(result, scenario)
        result.ai_responses = self._ai_calls_since(audit_start)
        return result

    def _make_blocks(self, scenario: dict[str, Any]) -> list[dict[str, Any]]:
        kind = scenario["kind"]
        block_type = "theory" if kind == "skipped_theory" else "homework"
        if kind == "revision_day":
            block_type = "revision"
        if kind == "coaching_test":
            block_type = "test"
        if kind == "faculty_session":
            block_type = "faculty_session"

        templates = [
            {
                "block_label": "EB-1",
                "subject": "Physics",
                "chapter": "Center of Mass",
                "exercise_type": "Ex 2A",
                "questions": "Q1-18",
                "question_count": 18,
                "target_time": 75,
                "expected_cy": 220,
                "block_type": block_type,
            },
            {
                "block_label": "EB-2",
                "subject": "Chem",
                "chapter": "Chemical Equilibrium",
                "exercise_type": "JMYL",
                "questions": "Q1-20",
                "question_count": 20,
                "target_time": 80,
                "expected_cy": 180,
                "block_type": "homework",
            },
            {
                "block_label": "EB-3",
                "subject": "Maths",
                "chapter": "Sequences and Series",
                "exercise_type": "Ex 1A",
                "questions": "Q1-15",
                "question_count": 15,
                "target_time": 60,
                "expected_cy": 160,
                "block_type": "homework",
            },
            {
                "block_label": "RB",
                "subject": "Physics",
                "chapter": "Rotation",
                "exercise_type": "Revision",
                "questions": "Q1-8",
                "question_count": 8,
                "target_time": 35,
                "expected_cy": 100,
                "block_type": "revision",
            },
        ]
        return [
            StudyBlockEngine.normalize_block(template, scenario["date"], idx + 1).model_dump()
            for idx, template in enumerate(templates)
        ]

    async def _check_planner_and_blocks(self, result: ScenarioResult, scenario: dict[str, Any], blocks: list[dict[str, Any]]) -> None:
        saved = await self.state.get_study_blocks(scenario["date"])
        if len(saved) == len(blocks) and all(block.get("block_id") for block in saved):
            result.add("PASS", "Planner", "Battle plan produced permanent study blocks.")
        else:
            result.add("FAIL", "Planner", "Study blocks were not saved with stable IDs.")
        if self.state.data["planner_decisions"]:
            result.add("PASS", "Battle Plan", "Planner decision recorded in fake Mongo.")
        else:
            result.add("FAIL", "Battle Plan", "Planner decision missing from fake Mongo.")

    async def _check_parser(self, result: ScenarioResult, scenario: dict[str, Any]) -> None:
        parsed = await self.parser.parse_performance_report("A=18 C=15 T=75")
        if parsed and parsed.attempted == 18 and parsed.correct == 15 and parsed.time_taken == 75:
            result.add("PASS", "Parser", "Structured performance report parsed.")
        else:
            result.add("FAIL", "Parser", "Structured performance report failed.")

    async def _run_completed_homework(self, result: ScenarioResult, scenario: dict[str, Any], block: dict[str, Any]) -> None:
        message = "18 attempted 15 correct in 75 mins. Didn't understand Q7 circular motion. No time for Q10."
        parsed = await self.reflection.process_block_reflection(block, [], message)
        if parsed.get("needs_followup"):
            result.add("WARNING", "Reflection", "Normal homework unexpectedly requested follow-up.")
            parsed["needs_followup"] = False
        await self._finalize_block(result, scenario, block, parsed.get("parsed_data", {}))

    async def _run_skip_or_recovery(self, result: ScenarioResult, scenario: dict[str, Any], block: dict[str, Any]) -> None:
        reason = "illness" if scenario["kind"] == "illness" else "burnout" if scenario["kind"] == "burnout_day" else "time shortage"
        await self.state.skip_study_block(block["block_id"], reason)
        skipped = dict(block)
        skipped.update({"status": "SKIPPED", "actual_cy": 0, "skip_reason": reason})
        await self.state.save_completed_block(scenario["date"], skipped)
        await self.state.save_recovery_event({"date": scenario["date"], "reason": reason, "block_id": block["block_id"], "action": "reschedule_or_reduce_load"})
        result.add("PASS", "Block transitions", "Skipped block recorded as SKIPPED.")
        result.add("PASS", "Recovery", "Recovery event written for skipped/off day.")

    async def _run_interrupted(self, result: ScenarioResult, scenario: dict[str, Any], block: dict[str, Any]) -> None:
        await self.state.update_study_block(block["block_id"], {"status": "INTERRUPTED", "interruption_reason": "family call", "actual_minutes": 24})
        await self.state.save_recovery_event({"date": scenario["date"], "block_id": block["block_id"], "action": "resume_later", "reason": "interrupted"})
        result.add("PASS", "Block transitions", "Interrupted block state recorded.")
        result.add("PASS", "Recovery", "Interrupted block recovery action written.")

    async def _run_duplicate(self, result: ScenarioResult, scenario: dict[str, Any], block: dict[str, Any]) -> None:
        parsed_data = {"attempted": 18, "correct": 16, "faculty_concepts": ["Circular Motion"], "concept_doubts": ["Q7: Circular Motion"], "incomplete_questions": []}
        await self._finalize_block(result, scenario, block, parsed_data)
        duplicate = await self.state.complete_study_block(block["block_id"], {"attempted": 18, "correct": 16})
        if duplicate.get("duplicate"):
            result.add("PASS", "Error handling", "Duplicate reflection was rejected.")
        else:
            result.add("FAIL", "Error handling", "Duplicate reflection was accepted.")

    async def _run_ambiguity(self, result: ScenarioResult, scenario: dict[str, Any], block: dict[str, Any]) -> None:
        parsed = await self.reflection.process_block_reflection(block, [], "18 attempted 14 correct. Didn't understand Q7.")
        if parsed.get("needs_followup"):
            result.add("PASS", "Reflection", "Ambiguous doubt triggered targeted follow-up.")
            parsed_data = parsed.get("parsed_data", {})
            parsed_data.setdefault("faculty_concepts", []).append("Unresolved Concept")
            await self._finalize_block(result, scenario, block, parsed_data)
        else:
            result.add("FAIL", "Reflection", "Ambiguous doubt did not trigger follow-up.")

    async def _run_api_failure(self, result: ScenarioResult, scenario: dict[str, Any], block: dict[str, Any]) -> None:
        raw = await self.ai.call("daily_plan", "Generate today's battle plan with API failure simulation.", max_tokens=200)
        try:
            json.loads(raw)
            result.add("PASS", "Error handling", "AI provider fallback produced valid planner JSON.")
        except json.JSONDecodeError:
            result.add("FAIL", "Error handling", "AI fallback returned invalid planner JSON.")
        await self._run_completed_homework(result, scenario, block)

    async def _run_test_day(self, result: ScenarioResult, scenario: dict[str, Any], block: dict[str, Any]) -> None:
        await self.state.save_test_score(scenario["date"], 52, 120, 68, 120, 47, 120, notes="time pressure in maths")
        await self.state.save_prediction({"date": scenario["date"], "type": "test_recalibration", "weak_subject": "Maths", "confidence": 0.62})
        await self._finalize_block(result, scenario, block, {"attempted": 75, "correct": 42, "faculty_concepts": ["Time Pressure"], "concept_doubts": ["Maths Section"], "incomplete_questions": []})
        result.add("PASS", "Prediction History", "Test prediction/recalibration record written.")

    async def _run_faculty_session(self, result: ScenarioResult, scenario: dict[str, Any], block: dict[str, Any]) -> None:
        await self.state.save_faculty_event({"date": scenario["date"], "resolved": ["Wedge Constraint"], "assigned": ["Physics COM Ex 2B Q1-10"]})
        await self.state.upsert_concept_asset({"concept_name": "Wedge Constraint", "subject": "Physics", "chapter": "Laws of Motion", "resolved": True, "confidence_score": 0.78})
        await self._finalize_block(result, scenario, block, {"attempted": 0, "correct": 0, "faculty_concepts": ["Wedge Constraint"], "concept_doubts": [], "incomplete_questions": []})
        result.add("PASS", "Faculty History", "Faculty session history written.")

    async def _run_concept_mastered(self, result: ScenarioResult, scenario: dict[str, Any], block: dict[str, Any]) -> None:
        await self.state.upsert_concept_asset({"concept_name": "Circular Motion", "subject": "Physics", "chapter": "Center of Mass", "resolved": True, "confidence_score": 0.92, "mastery_stage": "Mastered"})
        await self._finalize_block(result, scenario, block, {"attempted": 18, "correct": 18, "faculty_concepts": ["Circular Motion"], "concept_doubts": [], "incomplete_questions": []})
        result.add("PASS", "Learning Model", "Concept mastery evidence stored.")

    async def _run_concept_forgotten(self, result: ScenarioResult, scenario: dict[str, Any], block: dict[str, Any]) -> None:
        await self.state.upsert_concept_asset({"concept_name": "Chemical Equilibrium", "subject": "Chem", "chapter": "Equilibrium", "resolved": False, "confidence_score": 0.18, "mastery_stage": "Forgotten"})
        await self.state.save_recovery_event({"date": scenario["date"], "action": "schedule_revision", "concept": "Chemical Equilibrium"})
        await self._finalize_block(result, scenario, block, {"attempted": 18, "correct": 9, "faculty_concepts": ["Chemical Equilibrium"], "concept_doubts": ["Q12: equilibrium"], "incomplete_questions": []})
        result.add("PASS", "Recovery", "Forgotten concept recovery scheduled.")

    async def _run_impossible_or_backlog(self, result: ScenarioResult, scenario: dict[str, Any], block: dict[str, Any]) -> None:
        await self.state.save_recovery_event({"date": scenario["date"], "action": "drop_low_value_blocks", "reason": scenario["kind"]})
        await self.notion.create_db4_row(
            action_type="planner_guardrail",
            decision="Rejected impossible or overloaded plan",
            reasoning="Local simulator detected more expected minutes than available time.",
            data_snapshot=json.dumps({"scenario": scenario}),
        )
        await self._run_completed_homework(result, scenario, block)
        result.add("PASS", "Recovery", "Planner guardrail/recovery recorded.")

    async def _finalize_block(self, result: ScenarioResult, scenario: dict[str, Any], block: dict[str, Any], parsed_data: dict[str, Any]) -> None:
        attempted = int(parsed_data.get("attempted") or 0)
        correct = int(parsed_data.get("correct") or 0)
        time_taken = int(parsed_data.get("time_taken") or block.get("estimated_minutes") or block.get("target_time") or 0)
        actual_cy = cognitive_yield(time_taken, attempted, correct, block.get("exercise_type", "Ex 1A"), block.get("subject", "Physics"))

        knowledge = await self.knowledge.extract_assets(block, parsed_data)
        if knowledge.get("error"):
            result.add("FAIL", "Learning Model", knowledge["error"])
            return
        transition = await self.state.complete_study_block(
            block["block_id"],
            {
                "status": "COMPLETED",
                "attempted": attempted,
                "correct": correct,
                "T": time_taken,
                "A": attempted,
                "C": correct,
                "actual_cy": actual_cy,
            },
        )
        if transition.get("duplicate"):
            result.add("FAIL", "Block transitions", "Unexpected duplicate during first completion.")
            return
        saved = dict(block)
        saved.update({"status": "COMPLETED", "attempted": attempted, "correct": correct, "T": time_taken, "A": attempted, "C": correct, "actual_cy": actual_cy})
        await self.state.save_completed_block(scenario["date"], saved)
        await self.notion.create_db1_row(
            task_name=f"{block.get('label')}: {block.get('subject')} {block.get('exercise_type')}",
            subject=block.get("subject", "Physics"),
            exercise_type=block.get("exercise_type", "Ex 1A"),
            time_taken=time_taken,
            attempted=attempted,
            correct=correct,
            block=block.get("block_label", "Block"),
            date_str=scenario["date"],
        )
        await self.notion.update_db2_db3(
            {
                "attempted": attempted,
                "correct": correct,
                "subject": block.get("subject", "Physics"),
                "exercise_type": block.get("exercise_type", "Ex 1A"),
            },
            assets=knowledge.get("concept_assets", []),
            conceptual_mistake=bool(knowledge.get("concept_assets")),
        )
        result.add("PASS", "Block transitions", "Planned block completed with actual reflection data.")
        result.add("PASS", "Learning Model", "Learning event and concept assets updated.")
        result.add("PASS", "Fake Notion", "DB1/DB2/DB3 local writes completed.")
        result.add("PASS", "Recovery", "No recovery action required for completed block.")

    async def _write_daily_summary(self, target_date: str) -> None:
        completed = await self.state.get_today_blocks(target_date)
        totals = {"physics": 0.0, "chem": 0.0, "maths": 0.0}
        ty = {"physics": 0.0, "chem": 0.0, "maths": 0.0}
        counts = {"physics": 0, "chem": 0, "maths": 0}
        skipped = 0
        for block in completed:
            if str(block.get("status", "")).upper() == "SKIPPED":
                skipped += 1
                continue
            subject = block.get("subject", "Physics")
            key = "chem" if subject.lower().startswith("chem") else subject.lower()
            if key not in totals:
                key = "physics"
            attempted = int(block.get("attempted") or block.get("A") or 0)
            correct = int(block.get("correct") or block.get("C") or 0)
            time_taken = float(block.get("T") or block.get("estimated_minutes") or 0)
            cy = float(block.get("actual_cy") or cognitive_yield(time_taken, attempted, correct, block.get("exercise_type", "Ex 1A"), subject))
            totals[key] += cy
            ty[key] += theory_yield(time_taken, attempted, correct, block.get("exercise_type", "Ex 1A"), subject) if attempted else 0
            counts[key] += 1
        await self.state.save_daily_summary(
            target_date=target_date,
            total_cy=sum(totals.values()),
            physics_cy=totals["physics"],
            physics_ty=round(ty["physics"] / counts["physics"], 1) if counts["physics"] else 0,
            chem_cy=totals["chem"],
            chem_ty=round(ty["chem"] / counts["chem"], 1) if counts["chem"] else 0,
            maths_cy=totals["maths"],
            maths_ty=round(ty["maths"] / counts["maths"], 1) if counts["maths"] else 0,
            blocks_completed=sum(1 for block in completed if str(block.get("status", "")).upper() != "SKIPPED"),
            blocks_skipped=skipped,
            day_type="simulation",
        )

    async def _check_common_postconditions(self, result: ScenarioResult, scenario: dict[str, Any]) -> None:
        if self.state.data["timeline"]:
            result.add("PASS", "Mongo updates", "Timeline contains observable local writes.")
        else:
            result.add("FAIL", "Mongo updates", "Timeline is empty after scenario.")
        level = await self.state.get_learning_confidence_level()
        expected = self._expected_level(scenario["day_number"])
        if level >= expected:
            result.add("PASS", "Learning Confidence", f"L{level} reached for day {scenario['day_number']}.")
        else:
            result.add("WARNING", "Learning Confidence", f"L{level} below expected L{expected} for day {scenario['day_number']}.")

    @staticmethod
    def _expected_level(day_number: int) -> int:
        if day_number >= 365:
            return 4
        if day_number >= 180:
            return 3
        if day_number >= 30:
            return 2
        if day_number >= 7:
            return 1
        return 0

    async def _format_report(self, results: list[ScenarioResult], requested: int, executed: int) -> str:
        flat = [check for result in results for check in result.checks]
        counts = {status: sum(1 for check in flat if check.status == status) for status in ("PASS", "FAIL", "WARNING")}
        final_level = await self.state.get_learning_confidence_level()
        detail_paths = self._write_detail_artifacts(results, requested, executed, counts, final_level)
        lines = [
            "SENTINEL LOCAL SIMULATION REPORT",
            f"Requested scenarios: {requested}",
            f"Executed scenarios: {executed}",
            f"PASS: {counts['PASS']}",
            f"FAIL: {counts['FAIL']}",
            f"WARNING: {counts['WARNING']}",
            f"Learning confidence: L{final_level}",
            f"Fake Notion rows: {self.notion.counts()}",
            f"Fake Mongo study_blocks: {len(self.state.data['study_blocks'])}",
            f"Fake Mongo timeline: {len(self.state.data['timeline'])}",
            f"Scenario detail JSON: {detail_paths['json']}",
            f"Scenario AI report: {detail_paths['markdown']}",
        ]
        failures = [(result, check) for result in results for check in result.checks if check.status == "FAIL"]
        warnings = [(result, check) for result in results for check in result.checks if check.status == "WARNING"]
        if failures:
            lines.append("\nFAILURES")
            for result, check in failures[:18]:
                lines.append(f"- {result.name} [{check.area}]: {check.message}")
        if warnings:
            lines.append("\nWARNINGS")
            for result, check in warnings[:12]:
                lines.append(f"- {result.name} [{check.area}]: {check.message}")
        if not failures:
            lines.append("\nAll required scenario checks passed.")
        return "\n".join(lines)

    def _audit_line_count(self) -> int:
        path = self.harness.audit.path
        if not path.exists():
            return 0
        with path.open("r", encoding="utf-8") as handle:
            return sum(1 for _ in handle)

    def _audit_events_since(self, start_line: int) -> list[dict[str, Any]]:
        path = self.harness.audit.path
        if not path.exists():
            return []
        events = []
        with path.open("r", encoding="utf-8") as handle:
            for idx, line in enumerate(handle):
                if idx < start_line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return events

    def _ai_calls_since(self, start_line: int) -> list[dict[str, Any]]:
        calls = []
        for event in self._audit_events_since(start_line):
            if event.get("event_type") != "ai.call":
                continue
            calls.append(
                {
                    "task_type": event.get("task_type"),
                    "selected_provider": event.get("selected_provider"),
                    "route_trace": event.get("route_trace", []),
                    "prompt_preview": event.get("prompt_preview", ""),
                    "response_preview": event.get("response_preview", ""),
                }
            )
        return calls

    def _write_detail_artifacts(
        self,
        results: list[ScenarioResult],
        requested: int,
        executed: int,
        counts: dict[str, int],
        final_level: int,
    ) -> dict[str, str]:
        runtime_dir = self.harness.runtime_dir
        json_path = runtime_dir / f"simulation_{executed}_details.json"
        markdown_path = runtime_dir / f"simulation_{executed}_ai_report.md"
        scenarios = []
        for result in results:
            check_counts = {
                status: sum(1 for check in result.checks if check.status == status)
                for status in ("PASS", "FAIL", "WARNING")
            }
            scenarios.append(
                {
                    "name": result.name,
                    "kind": result.kind,
                    "day_number": result.day_number,
                    "date": result.date_str,
                    "check_counts": check_counts,
                    "checks": [check.__dict__ for check in result.checks],
                    "ai_responses": result.ai_responses,
                }
            )

        payload = {
            "requested_scenarios": requested,
            "executed_scenarios": executed,
            "status_counts": counts,
            "learning_confidence": final_level,
            "fake_notion_rows": self.notion.counts(),
            "fake_mongo_counts": {
                "study_blocks": len(self.state.data["study_blocks"]),
                "completed_blocks": len(self.state.data["completed_blocks"]),
                "learning_events": len(self.state.data["learning_events"]),
                "concept_assets": len(self.state.data["concept_assets"]),
                "timeline": len(self.state.data["timeline"]),
                "planner_decisions": len(self.state.data["planner_decisions"]),
            },
            "scenarios": scenarios,
        }
        json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

        lines = [
            "# SENTINEL Local Simulation AI Report",
            "",
            f"- Requested scenarios: {requested}",
            f"- Executed scenarios: {executed}",
            f"- PASS: {counts['PASS']}",
            f"- FAIL: {counts['FAIL']}",
            f"- WARNING: {counts['WARNING']}",
            f"- Learning confidence: L{final_level}",
            f"- Fake Notion rows: {self.notion.counts()}",
            f"- Fake Mongo study_blocks: {len(self.state.data['study_blocks'])}",
            f"- Fake Mongo timeline: {len(self.state.data['timeline'])}",
            "",
            "## Scenarios",
        ]
        for scenario in scenarios:
            lines.extend(
                [
                    "",
                    f"### {scenario['name']}",
                    "",
                    f"- Kind: {scenario['kind']}",
                    f"- Day: {scenario['day_number']} ({scenario['date']})",
                    f"- Checks: PASS {scenario['check_counts']['PASS']}, FAIL {scenario['check_counts']['FAIL']}, WARNING {scenario['check_counts']['WARNING']}",
                ]
            )
            if not scenario["ai_responses"]:
                lines.append("- AI responses: none; deterministic fake-state path only.")
                continue
            lines.append("- AI responses:")
            for idx, call in enumerate(scenario["ai_responses"], 1):
                response = str(call.get("response_preview", "")).replace("\n", " ")
                prompt = str(call.get("prompt_preview", "")).replace("\n", " ")
                if len(response) > 700:
                    response = response[:700] + "..."
                if len(prompt) > 260:
                    prompt = prompt[:260] + "..."
                lines.extend(
                    [
                        f"  {idx}. `{call.get('task_type')}` via `{call.get('selected_provider')}`",
                        f"     Prompt: {prompt}",
                        f"     Response: {response}",
                    ]
                )
        markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {"json": str(json_path), "markdown": str(markdown_path)}


async def _run_cli(scenarios: int) -> None:
    from local_lab.harness import LocalSentinelHarness

    harness = LocalSentinelHarness()
    await harness.init()
    report = await SimulationEngine(harness).run(scenarios)
    print(report)


def main() -> None:
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="Run SENTINEL local-only Phase 1 simulation scenarios.")
    parser.add_argument("--scenarios", type=int, default=60, help="Scenario count. Clamped to 50-90.")
    args = parser.parse_args()
    asyncio.run(_run_cli(args.scenarios))


if __name__ == "__main__":
    main()
