from pydantic import BaseModel, Field
from typing import List, Dict, Any, Literal, Optional
from datetime import datetime

class HomeworkItem(BaseModel):
    model_config = {"extra": "forbid"}
    subject: str = Field(default="?")
    chapter: str = Field(default="?")
    exercise_type: str = Field(default="?")
    questions: int = Field(default=0)
    range: Optional[str] = None

class RevisionItem(BaseModel):
    model_config = {"extra": "forbid"}
    subject: str = Field(default="?")
    chapter: str = Field(default="?")
    status: str = Field(default="?")

class YesterdaySummary(BaseModel):
    model_config = {"extra": "forbid"}
    total_cy: int = Field(default=0)
    physics_cy: int = Field(default=0)
    physics_ty: int = Field(default=0)
    chem_cy: int = Field(default=0)
    chem_ty: int = Field(default=0)
    maths_cy: int = Field(default=0)
    maths_ty: int = Field(default=0)
    blocks_completed: int = Field(default=0)
    blocks_skipped: int = Field(default=0)
    raw_data: Dict[str, Any] = Field(default_factory=dict)

class StreakInfo(BaseModel):
    model_config = {"extra": "forbid"}
    current_count: int = Field(default=0)

class PlanningContext(BaseModel):
    model_config = {"extra": "forbid"}
    schema_version: Literal["1.0"] = "1.0"
    yesterday_summary: YesterdaySummary
    streak: StreakInfo
    revision_backlog: List[RevisionItem]
    homework: List[HomeworkItem]
    learning_confidence_level: int = Field(default=0, ge=0, le=4)

class ExecutionBlock(BaseModel):
    model_config = {"extra": "forbid"}
    schema_version: Literal["1.0"] = "1.0"
    block_id: str = ""
    date: str = ""
    label: str = ""
    block_label: str
    subject: str
    chapter: str = "?"
    exercise: str = ""
    exercise_type: str
    questions: str = ""
    block_type: str = "homework"
    estimated_minutes: int = 0
    expected_questions: int = 0
    question_count: int
    target_time: int
    expected_cy: int
    difficulty: str = "Medium"
    start_time: str = ""
    end_time: str = ""
    actual_cy: int = 0  # To be populated after completion
    status: str = "PLANNED"

class ExecutionPlan(BaseModel):
    model_config = {"extra": "forbid"}
    schema_version: Literal["1.0"] = "1.0"
    date: str
    day_type: str
    blocks: List[ExecutionBlock] = Field(default_factory=list)
    total_expected_cy: int = 0
    total_expected_time: int = 0
    is_fallback: bool = False

class PlanningResult(BaseModel):
    model_config = {"extra": "forbid"}
    schema_version: Literal["1.0"] = "1.0"
    plan: ExecutionPlan
    used_fallback: bool
    ai_provider: Optional[str] = None
    model: Optional[str] = None
    generated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
