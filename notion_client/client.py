"""
SENTINEL — Notion API Client (notion_client/client.py)
Handles async communication with the Notion API.
"""
from __future__ import annotations

import logging
from typing import Any
from datetime import datetime, timedelta

import httpx
import asyncio

from sentinel import config
from sentinel.notion_client import schemas
from sentinel.notion_client import formulas

def async_retry(max_retries=3, base_delay=1.0):
    def decorator(func):
        async def wrapper(*args, **kwargs):
            delay = base_delay
            last_exc = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except httpx.HTTPError as e:
                    last_exc = e
                    if attempt < max_retries - 1:
                        await asyncio.sleep(delay)
                        delay *= 2
            raise last_exc
        return wrapper
    return decorator

logger = logging.getLogger("sentinel.notion")


class NotionClient:
    def __init__(self) -> None:
        self.headers = {
            "Authorization": f"Bearer {config.NOTION_API_KEY}",
            "Notion-Version": config.NOTION_VERSION,
            "Content-Type": "application/json"
        }
        self.client: httpx.AsyncClient | None = None
        
    async def __aenter__(self) -> NotionClient:
        if not self.client:
            self.client = httpx.AsyncClient(base_url="https://api.notion.com/v1", headers=self.headers, timeout=15.0)
        return self
        
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self.client:
            await self.client.aclose()
            self.client = None
            
    @async_retry(max_retries=2, base_delay=1.0)
    async def check_health(self) -> bool:
        if not self.client or not config.NOTION_API_KEY:
            return False
        try:
            # Query users endpoint as a simple health check
            resp = await self.client.get("/users")
            return resp.status_code == 200
        except Exception:
            return False

    async def create_db4_if_not_exists(self) -> str:
        """Create or return the DB4 ID for System Logs."""
        if config.NOTION_DB4_ID:
            return config.NOTION_DB4_ID
        logger.warning("DB4 not configured. Placeholder returned.")
        return "placeholder_db4_id"

    @async_retry(max_retries=3, base_delay=1.5)
    async def create_db1_row(
        self,
        task_name: str,
        subject: str,
        exercise_type: str,
        time_taken: float,
        attempted: int,
        correct: int,
        block: str,
        date_str: str,
    ) -> None:
        """Log a study block to Notion DB1."""
        if not self.client or not config.NOTION_API_KEY:
            logger.info("Skipping Notion logging (API key missing or client not initialized).")
            return
            
        cy = formulas.cognitive_yield(time_taken, attempted, correct, exercise_type, subject)
        ty = formulas.theory_yield(time_taken, attempted, correct, exercise_type, subject)
        props = schemas.db1_row(task_name, subject, exercise_type, time_taken, attempted, correct, block, date_str, cy, ty)
        
        try:
            resp = await self.client.post("/pages", json={
                "parent": {"database_id": config.NOTION_DB1_ID},
                "properties": props
            })
            resp.raise_for_status()
        except Exception as exc:
            logger.error("Failed to log to Notion DB1: %s", exc)
            raise exc

    @async_retry(max_retries=3, base_delay=1.5)
    async def update_db2_db3(self, report: Any, assets: list = None, conceptual_mistake: bool = False) -> None:
        """Update DB2 (Revision Backlog) and DB3 (Error Log) based on a report."""
        if not self.client or not config.NOTION_API_KEY:
            return
            
        attempted = getattr(report, "attempted", 0) if not isinstance(report, dict) else report.get("attempted", 0)
        correct = getattr(report, "correct", 0) if not isinstance(report, dict) else report.get("correct", 0)
        subject = getattr(report, "subject", "Unknown") if not isinstance(report, dict) else report.get("subject", "Unknown")
        ex_type = getattr(report, "exercise_type", "Unknown") if not isinstance(report, dict) else report.get("exercise_type", "Unknown")
        
        accuracy = correct / attempted if attempted > 0 else 0
        needs_revision = accuracy < 0.7 and attempted > 0
        
        if needs_revision:
            # Need revision, log to DB2
            try:
                await self.client.post("/pages", json={
                    "parent": {"database_id": config.NOTION_DB2_ID},
                    "properties": {
                        "Chapter / Module": {"title": [{"text": {"content": f"{subject} {ex_type}"}}]},
                        "Status": {"select": {"name": "Pending"}},
                        "Total circled questions (manual)": {"number": max(attempted - correct, 0)},
                        "Double-Circled (Faculty Intervention Req.)": {"number": 1 if accuracy < 0.5 else 0},
                        "Is Short notes Completed?": {"checkbox": False},
                        "Next Execution Date": {
                            "date": {"start": (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")}
                        },
                    }
                })
            except Exception as e:
                logger.error(f"Failed to log to DB2: {e}")
                
        # DB3 (Error Log) Logic
        has_assets = assets is not None and len(assets) > 0
        if conceptual_mistake or has_assets or needs_revision:
            if config.NOTION_DB3_ID:
                try:
                    title = f"Error Log: {subject} {ex_type}"
                    if has_assets:
                        title += f" ({len(assets)} assets)"
                    await self.client.post("/pages", json={
                        "parent": {"database_id": config.NOTION_DB3_ID},
                        "properties": {
                            "Core Concept / Root Bug": {"title": [{"text": {"content": title}}]},
                            "Status": {"select": {"name": "Unresolved"}},
                            "Failure Type": {"select": {"name": "Concept" if conceptual_mistake or has_assets else "Calculation"}},
                            "Concept Deficit / Failure Reason": {
                                "rich_text": [{
                                    "text": {
                                        "content": f"Accuracy {accuracy:.0%}; {max(attempted - correct, 0)} circled questions."
                                    }
                                }]
                            },
                        }
                    })
                except Exception as e:
                    logger.error(f"Failed to log to DB3: {e}")

    @async_retry(max_retries=3, base_delay=1.0)
    async def create_db4_row(self, action_type: str, decision: str, reasoning: str, data_snapshot: str) -> None:
        """Log a system action to DB4 (Audit / Policy Log)."""
        if not self.client or not config.NOTION_DB4_ID:
            return
            
        try:
            await self.client.post("/pages", json={
                "parent": {"database_id": config.NOTION_DB4_ID},
                "properties": {
                    "Action Type": {"title": [{"text": {"content": action_type}}]},
                    "Decision": {"rich_text": [{"text": {"content": decision}}]},
                    "Reasoning": {"rich_text": [{"text": {"content": reasoning}}]},
                    "Data Snapshot": {"rich_text": [{"text": {"content": data_snapshot[:2000]}}]} # limit length
                }
            })
        except Exception as e:
            logger.error(f"Failed to create DB4 row: {e}")
            raise e
            
    @async_retry(max_retries=2, base_delay=1.0)
    async def get_daily_stats(self, date_str: str) -> dict:
        """Fetch CY statistics directly from Notion DB1 for the given date."""
        if not self.client or not config.NOTION_DB1_ID:
            return {"cy": 0}
            
        try:
            resp = await self.client.post(f"/databases/{config.NOTION_DB1_ID}/query", json={
                "filter": {
                    "property": "Date",
                    "date": {
                        "equals": date_str
                    }
                }
            })
            resp.raise_for_status()
            results = resp.json().get("results", [])
            
            total_cy = 0
            for page in results:
                props = page.get("properties", {})
                cy_prop = props.get("Cognitive Yield", {})
                if cy_prop.get("type") == "formula":
                    total_cy += cy_prop.get("formula", {}).get("number", 0) or 0
                    
            return {"cy": total_cy}
        except Exception as e:
            logger.error(f"Failed to get daily stats: {e}")
            return {"cy": 0}

    @async_retry(max_retries=2, base_delay=1.0)
    async def get_revision_backlog(self) -> list[dict]:
        """Fetch pending revision items from DB2."""
        if not self.client or not config.NOTION_DB2_ID:
            return []
            
        try:
            resp = await self.client.post(f"/databases/{config.NOTION_DB2_ID}/query", json={
                "filter": {
                    "property": "Status",
                    "select": {
                        "equals": "Pending"
                    }
                }
            })
            resp.raise_for_status()
            results = resp.json().get("results", [])
            
            backlog = []
            for page in results:
                props = page.get("properties", {})
                title_prop = props.get("Chapter / Module", {})
                if title_prop.get("title") and len(title_prop["title"]) > 0:
                    text = title_prop["title"][0].get("text", {}).get("content", "")
                    
                    # Split subject and chapter (assumes format "Subject Chapter")
                    parts = text.split(" ", 1)
                    subj = parts[0] if len(parts) > 0 else "Unknown"
                    chap = parts[1] if len(parts) > 1 else "Unknown"
                    
                    backlog.append({
                        "subject": subj,
                        "chapter": chap,
                        "status": "Pending"
                    })
            return backlog
        except Exception as e:
            logger.error(f"Failed to get revision backlog: {e}")
            return []

    @async_retry(max_retries=2, base_delay=1.0)
    async def read_db1_rows(self, filters: dict) -> list[dict]:
        """Read rows from DB1 matching a filter."""
        if not self.client or not config.NOTION_DB1_ID:
            return []
            
        try:
            resp = await self.client.post(f"/databases/{config.NOTION_DB1_ID}/query", json={
                "filter": filters
            })
            resp.raise_for_status()
            results = resp.json().get("results", [])
            
            rows = []
            for page in results:
                props = page.get("properties", {})
                row = {}
                row["subject"] = props.get("Subject", {}).get("select", {}).get("name", "")
                row["exercise_type"] = props.get("Exercise Type", {}).get("select", {}).get("name", "")
                row["time_taken"] = props.get("Actual Time Spent (mins)", {}).get("number", 0)
                row["attempted"] = props.get("Questions Attempted", {}).get("number", 0)
                row["correct"] = props.get("Questions Correct", {}).get("number", 0)
                rows.append(row)
            return rows
        except Exception as e:
            logger.error(f"Failed to read db1 rows: {e}")
            return []
