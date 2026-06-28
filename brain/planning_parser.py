"""
SENTINEL — Planning Parser (brain/planning_parser.py)
Extracts JSON, validates the schema using Pydantic, computes statistics, and returns the ExecutionPlan.
"""

import json
import logging
from pydantic import ValidationError

from sentinel.brain.contracts import ExecutionPlan, ExecutionBlock

logger = logging.getLogger("sentinel.planning_parser")


class PlanningParser:
    def parse_plan_response(self, raw: str, today: str, day_type: str) -> ExecutionPlan:
        """
        Parses the AI's JSON plan response into a strongly-typed ExecutionPlan.
        Raises ValueError if parsing or schema validation fails.
        """
        cleaned = raw.strip()
        if "```json" in cleaned:
            cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in cleaned:
            cleaned = cleaned.split("```", 1)[1].split("```", 1)[0]
            
        try:
            parsed = json.loads(cleaned.strip())
        except json.JSONDecodeError as e:
            logger.warning("Failed to decode AI plan JSON: %s", e)
            raise ValueError(f"Invalid JSON: {e}")
            
        blocks_data = parsed.get("blocks", [])
        if not blocks_data:
            raise ValueError("Parsed JSON contains no blocks.")
            
        blocks = []
        total_cy = 0
        total_time = 0
        
        for block in blocks_data:
            try:
                # Let Pydantic enforce correctness
                validated = ExecutionBlock.model_validate(block)
                blocks.append(validated)
                total_cy += validated.expected_cy
                total_time += validated.target_time
            except ValidationError as e:
                logger.warning("Failed to validate block schema: %s. Block: %s", e, block)
                raise ValueError(f"Schema validation failed: {e}")
                
        return ExecutionPlan(
            date=today,
            day_type=day_type,
            blocks=blocks,
            total_expected_cy=total_cy,
            total_expected_time=total_time,
            is_fallback=False
        )
