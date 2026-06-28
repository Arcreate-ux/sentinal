from dataclasses import dataclass, field

@dataclass
class ConceptProfile:
    name: str
    abstraction: float
    algebra_load: float
    visualization: float
    memory_load: float
    trickiness: float

@dataclass
class StudentAptitude:
    visualization: float
    memory: float
    calculation: float
    pattern_recognition: float
    speed: float
    consistency: float
    spatial_thinking: float

@dataclass
class PersonalityDNA:
    discipline: float
    anxiety_base: float
    curiosity: float
    homework_tendency: float
    revision_tendency: float
    risk_taking: float
    aptitude: StudentAptitude

@dataclass
class FacultyProfile:
    name: str
    clarity: float
    speed: float
    problem_quality: float
    doubt_resolution: float
    revision_quality: float
    motivation: float

@dataclass
class LuckState:
    sleep_quality: float
    paper_difficulty: float
    mental_pressure: float
    silly_mistakes: float
    health: float
    noise: float
    exam_hall_condition: float

@dataclass
class PluginMetadata:
    name: str
    version: str
    author: str
    parameters: dict[str, float | str] = field(default_factory=dict)

@dataclass
class FatigueParameters:
    fatigue_accumulation_rate: float = 0.08
    fatigue_recovery_rate: float = 0.07
    day_off_fatigue_recovery: float = 0.35
    anxiety_recovery_rate: float = 0.02
    day_off_anxiety_recovery: float = 0.05
    burnout_fatigue_threshold: float = 0.8
    burnout_anxiety_threshold: float = 0.82
    burnout_fatigue_drop: float = 0.5
    burnout_anxiety_drop: float = 0.2
