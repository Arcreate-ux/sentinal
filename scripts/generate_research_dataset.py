from __future__ import annotations

import argparse
import asyncio
import csv
import json
from pathlib import Path
from typing import Any

from sentinel.state.database import StateDB


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _metric(source: dict[str, Any] | None, key: str) -> Any:
    if not source:
        return None
    return source.get(key)


def build_research_row(decision: dict[str, Any]) -> dict[str, Any]:
    prediction = decision.get("prediction") or {}
    actual = decision.get("actual") or {}
    error = decision.get("prediction_error") or {}
    plan = decision.get("plan") or {}
    inputs = decision.get("inputs") or {}

    return {
        "decision_id": decision.get("decision_id"),
        "version": decision.get("version"),
        "date": decision.get("date"),
        "timestamp": decision.get("timestamp") or decision.get("generated_at"),
        "day_type": decision.get("day_type") or plan.get("day_type"),
        "used_fallback": decision.get("used_fallback"),
        "learning_confidence_level": decision.get("learning_confidence_level"),
        "planned_blocks": len(plan.get("blocks") or []),
        "expected_cy": _metric(prediction, "expected_cy"),
        "expected_duration": _metric(prediction, "expected_duration"),
        "expected_completion": _metric(prediction, "expected_completion"),
        "expected_fatigue": _metric(prediction, "expected_fatigue"),
        "actual_cy": _metric(actual, "actual_cy"),
        "actual_duration": _metric(actual, "actual_duration"),
        "actual_completion": _metric(actual, "actual_completion"),
        "actual_fatigue": _metric(actual, "actual_fatigue"),
        "error_cy": _metric(error, "cy"),
        "error_duration": _metric(error, "duration"),
        "error_completion": _metric(error, "completion"),
        "error_fatigue": _metric(error, "fatigue"),
        "blocks_completed": _metric(actual, "blocks_completed"),
        "blocks_skipped": _metric(actual, "blocks_skipped"),
        "input_backlog_count": _extract_backlog_count(inputs),
        "inputs_json": _json_dump(inputs),
        "prediction_json": _json_dump(prediction),
        "actual_json": _json_dump(actual),
        "prediction_error_json": _json_dump(error),
        "plan_json": _json_dump(plan),
        "planner_reasoning_json": _json_dump(decision.get("planner_reasoning") or {}),
    }


def _extract_backlog_count(inputs: dict[str, Any]) -> int | None:
    context = inputs.get("planning_context") or {}
    revision_backlog = context.get("revision_backlog")
    if isinstance(revision_backlog, list):
        return len(revision_backlog)
    return None


async def export_dataset(output_dir: Path) -> tuple[Path, Path, int]:
    db = StateDB()
    mongo = db._get_db()
    cursor = mongo.planner_decisions.find({}, {"_id": 0}).sort("date", 1)
    decisions = await cursor.to_list(length=None)
    rows = [build_research_row(decision) for decision in decisions]

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "sentinel_research_dataset.json"
    csv_path = output_dir / "sentinel_research_dataset.csv"

    json_path.write_text(_json_dump(rows) + "\n", encoding="utf-8")
    fieldnames = list(rows[0].keys()) if rows else list(build_research_row({}).keys())
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    db.close()
    return json_path, csv_path, len(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export SENTINEL Phase 8 planner decisions as CSV and JSON.")
    parser.add_argument(
        "--output-dir",
        default="data/research",
        help="Directory for sentinel_research_dataset.csv/json.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    json_path, csv_path, count = asyncio.run(export_dataset(Path(args.output_dir)))
    print(f"Exported {count} decisions")
    print(f"JSON: {json_path}")
    print(f"CSV: {csv_path}")


if __name__ == "__main__":
    main()
