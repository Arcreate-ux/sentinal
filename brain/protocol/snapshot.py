from pydantic import BaseModel, ConfigDict, Field
from typing import Dict, List, Any

# These act as defaults if none are provided
from sentinel.config import (
    DAILY_CY_TARGET,
    HARD_STOP_HOUR,
    SUBJECTS,
    EXERCISE_TYPES,
    BLOCK_TYPES,
    T_Q_TABLE
)

class ProtocolSnapshot(BaseModel):
    """
    Immutable representation of the study protocol rules.
    This serves as the single source of truth for all engines.
    """
    model_config = ConfigDict(frozen=True)

    schema_version: str = Field(default="1.0", frozen=True)
    
    daily_cy_target: int = Field(default=DAILY_CY_TARGET, frozen=True)
    hard_stop_hour: int = Field(default=HARD_STOP_HOUR, frozen=True)
    subjects: List[str] = Field(default_factory=lambda: list(SUBJECTS), frozen=True)
    exercise_types: List[str] = Field(default_factory=lambda: list(EXERCISE_TYPES), frozen=True)
    block_types: List[str] = Field(default_factory=lambda: list(BLOCK_TYPES), frozen=True)
    t_q_table: Dict[str, Dict[str, float]] = Field(default_factory=lambda: dict(T_Q_TABLE), frozen=True)
