"""Read-only Notion schema snapshot used by the local fake databases.

Source: Notion retrieve-database calls made on 2026-06-28.
The snapshot stores database property contracts, not real page data.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def _select(*names: str) -> dict[str, Any]:
    return {"options": [{"name": name} for name in names]}


SCHEMA_SNAPSHOT: dict[str, dict[str, Any]] = {
    "db1": {
        "source_database_id": "36dbc6be-f0c2-81db-9da5-f2d1856408ae",
        "local_database_id": "local_fake_db1_daily_execution_ledger",
        "title": "1. Daily Execution Ledger (The 80% Output)",
        "properties": {
            "Max Time (min)": {"id": "%3D%7BXc", "type": "rich_text"},
            "Questions Correct": {"id": "%3ERRD", "type": "number", "number": {"format": "number"}},
            "Cognitive Yield ": {"id": "D%3EuK", "type": "formula", "formula": {"expression": "extracted_not_evaluated_locally"}},
            "Id": {"id": "KJYt", "type": "unique_id", "unique_id": {"prefix": "TASK"}},
            "Theory Yield ": {"id": "P_MW", "type": "formula", "formula": {"expression": "extracted_not_evaluated_locally"}},
            "Logged Errors": {
                "id": "QKbP",
                "type": "relation",
                "relation": {"database_id": "36dbc6be-f0c2-81ba-a6bd-f3e39886eb50"},
            },
            "Questions Attempted": {"id": "TGPh", "type": "number", "number": {"format": "number"}},
            "Actual Time Spent (mins)": {"id": "UMr%5D", "type": "number", "number": {"format": "number"}},
            "Accuracy Ratio": {"id": "U%5Ddv", "type": "formula", "formula": {"expression": "correct / attempted"}},
            "Tickbox": {"id": "VkD_", "type": "checkbox"},
            "Mins per Question": {"id": "ce%60b", "type": "formula", "formula": {"expression": "time / attempted"}},
            "Alternative": {"id": "cxrf", "type": "rich_text"},
            "Calculated Circled Qs": {"id": "hzb%7C", "type": "formula", "formula": {"expression": "attempted - correct"}},
            "Cognitive Yield (Task)": {"id": "rnpe", "type": "formula", "formula": {"expression": "same_as_cognitive_yield"}},
            "Subject": {"id": "v%5CAX", "type": "select", "select": _select("Physics", "Chem", "Maths", "All")},
            "Exercise Type": {
                "id": "v%5EPT",
                "type": "select",
                "select": _select(
                    "MLE",
                    "Ex 1A",
                    "Ex 1B",
                    "Ex 2A",
                    "Ex 2B",
                    "Ex 3A",
                    "Ex 3B",
                    "Ex 4A",
                    "Ex 4B",
                    "JMYL",
                    "JAYL",
                    "PYQs",
                    "Revision",
                ),
            },
            "Target Chapter/Module": {
                "id": "xSCz",
                "type": "relation",
                "relation": {"database_id": "36dbc6be-f0c2-81fe-a1d9-ee8def93d63e"},
            },
            "BLOCK": {
                "id": "zS_P",
                "type": "select",
                "select": _select("EB-3", "EB-1", "EB-C", "EB - A", "EB - B", "EB-2", "RB", "TA", "ADV.", "AB"),
            },
            "Date": {"id": "~zcP", "type": "date"},
            "Task (Actionable Verb + Exact Scope)": {"id": "title", "type": "title"},
        },
    },
    "db2": {
        "source_database_id": "36dbc6be-f0c2-81fe-a1d9-ee8def93d63e",
        "local_database_id": "local_fake_db2_revision_backlog",
        "title": "3. Revision Backlog (Off-Day Execution)",
        "properties": {
            "Double-Circled (Faculty Intervention Req.)": {"id": "%3Fv%3Dk", "type": "number", "number": {"format": "number"}},
            "Is Short notes Completed?": {"id": "GRkv", "type": "checkbox"},
            "Status": {"id": "SLuC", "type": "select", "select": _select("Pending", "Completed")},
            "Related to 1. Daily Execution Ledger (The 80% Output) (Target Chapter/Module)": {
                "id": "Tq%60q",
                "type": "relation",
                "relation": {"database_id": "36dbc6be-f0c2-81db-9da5-f2d1856408ae"},
            },
            "TOTAL CIRCLED QUESTIONS ": {"id": "W%5DhV", "type": "formula", "formula": {"expression": "manual_total_or_rollup"}},
            "Total Circled Qs": {"id": "bJy%5C", "type": "rollup", "rollup": {"function": "sum"}},
            "Total circled questions (manual)": {"id": "pNDI", "type": "number", "number": {"format": "number"}},
            "Next Execution Date": {"id": "%7C%3AsD", "type": "date"},
            "Chapter / Module": {"id": "title", "type": "title"},
        },
    },
    "db3": {
        "source_database_id": "36dbc6be-f0c2-81ba-a6bd-f3e39886eb50",
        "local_database_id": "local_fake_db3_precision_error_log",
        "title": "2. Precision Concept & Error Log (The 20% Acquisition)",
        "properties": {
            "Status": {"id": "%40%3DLk", "type": "select", "select": _select("Unresolved", "Resolved")},
            "Failure Type": {"id": "aT%3CD", "type": "select", "select": _select("Omission", "Time Management", "Concept", "Calculation")},
            "Concept Deficit / Failure Reason": {"id": "hlgS", "type": "rich_text"},
            "Subject": {"id": "jcSP", "type": "rollup", "rollup": {"function": "show_original"}},
            "Related to 1. Daily Execution Ledger (The 80% Output) (Logged Errors)": {
                "id": "sSHI",
                "type": "relation",
                "relation": {"database_id": "36dbc6be-f0c2-81db-9da5-f2d1856408ae"},
            },
            "Core Concept / Root Bug": {"id": "title", "type": "title"},
        },
    },
    "db4": {
        "source_database_id": "",
        "local_database_id": "local_fake_db4_system_log",
        "title": "4. System Log (Local Test Contract)",
        "properties": {
            "Action Type": {"id": "title", "type": "title"},
            "Decision": {"id": "decision", "type": "rich_text"},
            "Reasoning": {"id": "reasoning", "type": "rich_text"},
            "Data Snapshot": {"id": "data_snapshot", "type": "rich_text"},
            "Timestamp": {"id": "timestamp", "type": "date"},
            "Level": {"id": "level", "type": "select", "select": _select("INFO", "WARNING", "ERROR")},
        },
    },
}


def get_schema_snapshot() -> dict[str, dict[str, Any]]:
    return deepcopy(SCHEMA_SNAPSHOT)

