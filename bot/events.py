"""
SENTINEL — Event Sourcing Types (bot/events.py)

Defines the core immutable events that drive SENTINEL's timeline.
"""

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
import uuid
import time

class BaseEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = Field(default_factory=time.time)
    event_type: str
    source: str
    payload: Dict[str, Any]
    status: str = Field(default="processed")
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None

class ReflectionCompleted(BaseEvent):
    event_type: str = "ReflectionCompleted"
    source: str = "ReflectionEngine"

class KnowledgeExtracted(BaseEvent):
    event_type: str = "KnowledgeExtracted"
    source: str = "KnowledgeEngine"

class ConceptResolved(BaseEvent):
    event_type: str = "ConceptResolved"
    source: str = "KnowledgeEngine"

class RecoverySuggested(BaseEvent):
    event_type: str = "RecoverySuggested"
    source: str = "RecoveryEngine"

class ProviderBenchmarked(BaseEvent):
    event_type: str = "ProviderBenchmarked"
    source: str = "CapabilityRegistry"

class PlanningFinished(BaseEvent):
    event_type: str = "PlanningFinished"
    source: str = "PlanningEngine"

class BattlePlanGenerated(BaseEvent):
    event_type: str = "BattlePlanGenerated"
    source: str = "PlanningEngine"

class FacultyQuestionCreated(BaseEvent):
    event_type: str = "FacultyQuestionCreated"
    source: str = "ReflectionEngine"

class RevisionCompleted(BaseEvent):
    event_type: str = "RevisionCompleted"
    source: str = "NotionSync"

class ExperienceRuleDiscovered(BaseEvent):
    event_type: str = "ExperienceRuleDiscovered"
    source: str = "ExperienceEngine"
