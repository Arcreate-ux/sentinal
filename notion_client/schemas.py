"""
SENTINEL — Notion Schemas (notion_client/schemas.py)
Defines the property structures for Notion database rows.
"""
from __future__ import annotations

from typing import Any


def db1_row(
    task_name: str,
    subject: str,
    exercise_type: str,
    time_taken: float,
    attempted: int,
    correct: int,
    block: str,
    date_str: str,
    cy: float,
    ty: float,
) -> dict[str, Any]:
    """Schema for DB1: Daily Execution Ledger."""
    return {
        "Task (Actionable Verb + Exact Scope)": {"title": [{"text": {"content": task_name}}]},
        "Subject": {"select": {"name": subject}},
        "Exercise Type": {"select": {"name": exercise_type}},
        "Actual Time Spent (mins)": {"number": time_taken},
        "Questions Attempted": {"number": attempted},
        "Questions Correct": {"number": correct},
        "BLOCK": {"select": {"name": block}},
        "Date": {"date": {"start": date_str}},
    }


def db4_system_log(event: str, level: str, timestamp: str, details: str) -> dict[str, Any]:
    """Schema for DB4: System Log."""
    return {
        "Event": {"title": [{"text": {"content": event}}]},
        "Level": {"select": {"name": level}},
        "Date": {"date": {"start": timestamp}},
        "Details": {"rich_text": [{"text": {"content": details[:2000]}}]}
    }
