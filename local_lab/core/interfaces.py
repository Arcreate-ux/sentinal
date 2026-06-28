from abc import ABC, abstractmethod
from typing import Any

from local_lab.models.profiles import PluginMetadata, PersonalityDNA, StudentAptitude
from local_lab.models.state import MemoryState, TrustState, FatigueState, CurriculumState

class SimEngine(ABC):
    @abstractmethod
    def metadata(self) -> PluginMetadata:
        pass

class CurriculumEngine(SimEngine):
    @abstractmethod
    def create_state(self) -> CurriculumState:
        pass

    @abstractmethod
    def advance_day(self, state: CurriculumState) -> dict[str, Any]:
        """Returns active concepts and any events blocking coaching. Mutates state."""
        pass
        
    @abstractmethod
    def get_concept_profile(self, concept: str) -> Any:
        pass

class FacultyEngine(SimEngine):
    @abstractmethod
    def get_faculty_profile(self, concept: str) -> Any:
        pass

class MemoryModel(SimEngine):
    @abstractmethod
    def create_state(self) -> MemoryState:
        pass

    @abstractmethod
    def apply_decay(self, state: MemoryState, current_day: int, aptitude: StudentAptitude) -> None:
        pass
        
    @abstractmethod
    def update_learning(self, state: MemoryState, concept: str, is_revision: bool, used_faculty: bool, performance: float, duration: float, aptitude: StudentAptitude, concept_load: float, current_day: int) -> None:
        pass

class TrustModel(SimEngine):
    @abstractmethod
    def create_state(self) -> TrustState:
        pass

    @abstractmethod
    def update(self, state: TrustState, hours_scheduled: float, capacity: float, fatigue: float, completed_ratio: float) -> float:
        """Returns the new trust value and mutates state."""
        pass

class FatigueModel(SimEngine):
    @abstractmethod
    def create_state(self, base_anxiety: float) -> FatigueState:
        pass

    @abstractmethod
    def update(self, state: FatigueState, hours_spent: float, capacity: float, event_penalty: float) -> tuple[float, float, int]:
        """Returns (fatigue, anxiety, burnout_days_increment) and mutates state."""
        pass
