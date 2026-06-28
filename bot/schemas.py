from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class PerformanceReport(BaseModel):
    attempted: int = Field(..., description="Number of questions attempted")
    correct: int = Field(..., description="Number of questions correct")
    time_taken: int = Field(..., description="Time taken in minutes")
    subject: Optional[str] = Field(None, description="Subject name")
    exercise_type: Optional[str] = Field(None, description="Exercise type")
    is_report: bool = Field(True, description="Whether this is actually a performance report")

class HomeworkEntry(BaseModel):
    subject: str
    chapter: str
    exercise_type: str
    questions: int
    range: Optional[str] = None

class HomeworkList(BaseModel):
    entries: List[HomeworkEntry]

class TestScores(BaseModel):
    p_score: int = 0
    p_total: int = 120
    c_score: int = 0
    c_total: int = 120
    m_score: int = 0
    m_total: int = 120

class SystemCommandEntities(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None

class IntentClassification(BaseModel):
    intent: str = Field(description="The classified intent (e.g. reschedule, report, analyze_history, system_command, query, general)")
    complexity_tier: str = Field(description="'fast' for simple chat, 'think' for deep analysis/scheduling")
    entities: Dict[str, Any] = Field(default_factory=dict, description="Extracted entities")

    def get_system_entities(self) -> SystemCommandEntities:
        """Helper to safely parse system command entities."""
        return SystemCommandEntities.model_validate(self.entities)

class TaskProfile(BaseModel):
    task: str = Field(description="The internal name of the task (e.g. weekly_analysis)")
    priority: str = Field("medium", description="Task priority")
    quality_target: int = Field(5, description="1-10 scale of required quality")
    latency_budget: int = Field(10, description="Allowed latency in seconds. 0 = unlimited.")
    background: bool = Field(False, description="True if the task runs asynchronously without user waiting")
    allow_benchmark: bool = Field(False, description="Can we run background benchmarks for this task?")
    allow_synthesis: bool = Field(False, description="Can we use multi-model synthesis (Ollama + G4F -> Gemini)?")
    preferred_models: List[str] = Field(default_factory=list, description="Preferred models to use if available")

class CapabilitySnapshot(BaseModel):
    timestamp: float = Field(description="Epoch time when the benchmark was completed")
    fast_rankings: List[str] = Field(description="Fast tier providers sorted by latency/success")
    think_rankings: List[str] = Field(description="Think tier providers sorted by latency/success")
    provider_stats: Dict[str, Any] = Field(default_factory=dict, description="Raw latency and success metrics")


# --- Permanent Learning Hierarchy Schemas ---

class LearningEvent(BaseModel):
    timestamp: float = Field(description="Epoch time of the event")
    subject: str
    chapter: str
    exercise_type: str
    attempted: int
    correct: int
    questions_encountered: List[str] = Field(default_factory=list, description="List of Q-ids e.g., ['Q7', 'Q8']")
    reasons_for_skipping: Dict[str, str] = Field(default_factory=dict, description="Map of Q-id to reason (e.g. 'Time')")
    time_taken: int = Field(0, description="Time taken for the block")

class ErrorProfile(BaseModel):
    mistake_type: str = Field(description="e.g. Concept, Formula, Calculation, Reading, Visualization, Silly, Time Pressure")
    description: str = Field(description="Specific detail of the error")

class ArchivedQuestion(BaseModel):
    question_id: str = Field(description="e.g. Q7, Ex3 Q12")
    subject: str
    chapter: str
    concept_label: str = Field(description="The underlying concept")
    mistake_type: str = Field(description="Type of mistake made")
    source_block: str = Field(description="The block label where this occurred")
    timestamp: float = Field(description="Epoch time of the archive")
    archived: bool = Field(True, description="Always true for evidence")

class ConceptRevision(BaseModel):
    timestamp: float
    faculty_notes: str = ""
    current_understanding: str = ""
    error_profiles: List[ErrorProfile] = Field(default_factory=list)

class ConceptAsset(BaseModel):
    concept_name: str = Field(description="Name of the concept, e.g. 'Wedge Constraint'")
    subject: str
    chapter: str
    connected_to: List[str] = Field(default_factory=list, description="Graph edges to other concepts")
    revisions: List[ConceptRevision] = Field(default_factory=list, description="Append-only timeline of understanding")
    first_seen: Optional[float] = None
    last_seen: Optional[float] = None
    times_encountered: int = 0
    faculty_dependency: int = 0
    mastery_stage: str = Field("Novice", description="e.g., Novice, Struggling, Improving, Mastered")
    confidence_score: float = Field(0.0, description="System confidence in this concept")
    typical_failure_step: str = ""
    common_failure_patterns: List[str] = Field(default_factory=list)
    successful_interventions: List[str] = Field(default_factory=list)
    linked_error_profiles: List[ErrorProfile] = Field(default_factory=list)
    resolved: bool = Field(False)
    resolved_date: Optional[float] = None

class SkillAsset(BaseModel):
    skill_name: str = Field(description="Name of the skill, e.g. 'Constraint Modeling'")
    subject: str
    parent_skills: List[str] = Field(default_factory=list, description="Hierarchical skills above this one")
    child_concepts: List[str] = Field(default_factory=list, description="Concepts that map to this skill")
    confidence_score: float = Field(0.0, description="Aggregated confidence score")
    last_updated: float = Field(description="Epoch time of last update")

class RecommendationRecord(BaseModel):
    timestamp: float
    recommendation_text: str
    applied: Optional[bool] = Field(None, description="True if user applied it, False if ignored, None if untested")
    reason_ignored: str = Field("", description="Why it was not applied")
    effectiveness_score: float = Field(0.0, description="-1.0 to 1.0 score of how well it worked")
    is_recovery_action: bool = Field(False)
