from dataclasses import dataclass, field
from typing import Any

@dataclass
class MemoryDimension:
    concept: str
    mastery: float = 0.0
    times_encountered: int = 0
    last_revised_day: int = 0
    faculty_dependency: float = 0.85

@dataclass
class MemoryState:
    dims: dict[str, MemoryDimension] = field(default_factory=dict)

@dataclass
class FatigueState:
    fatigue: float = 0.0
    anxiety: float = 0.0
    burnout_days: int = 0

@dataclass
class TrustState:
    trust: float = 0.5

@dataclass
class CurriculumState:
    current_day: int = 0
    active_concepts: list[str] = field(default_factory=list)
    coaching_progress: float = 0.0
    coaching_velocity: float = 1.0
    chaos_event: dict[str, Any] | None = None
    chaos_days_left: int = 0

@dataclass
class StudentState:
    memory: MemoryState = field(default_factory=MemoryState)
    fatigue: FatigueState = field(default_factory=FatigueState)
    trust: TrustState = field(default_factory=TrustState)
    self_belief: float = 0.8
    motivation: float = 0.8
    daily_hours_capacity: float = 8.0
