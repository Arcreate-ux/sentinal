import math
from local_lab.core.interfaces import MemoryModel
from local_lab.models.profiles import PluginMetadata, StudentAptitude
from local_lab.models.state import MemoryState, MemoryDimension

class StandardMemoryModel(MemoryModel):
    def metadata(self) -> PluginMetadata:
        return PluginMetadata("StandardMemoryModel", "v2.1", "Yatin")

    def create_state(self) -> MemoryState:
        return MemoryState()

    def _get_dim(self, state: MemoryState, concept: str) -> MemoryDimension:
        if concept not in state.dims:
            state.dims[concept] = MemoryDimension(concept)
        return state.dims[concept]

    def apply_decay(self, state: MemoryState, current_day: int, aptitude: StudentAptitude) -> None:
        for dim in state.dims.values():
            if current_day > dim.last_revised_day and dim.mastery > 0:
                forget_rate = 0.025 * (1.1 - aptitude.memory)
                dim.mastery = max(0.0, dim.mastery * math.exp(-forget_rate))

    def update_learning(self, state: MemoryState, concept: str, is_revision: bool, used_faculty: bool, performance: float, duration: float, aptitude: StudentAptitude, concept_load: float, current_day: int) -> None:
        dim = self._get_dim(state, concept)
        dim.times_encountered += 1
        
        days_since = max(1, 1 if dim.last_revised_day == 0 else (current_day - dim.last_revised_day))
        optimal_days = 4.0
        bell = math.exp(-(((days_since - optimal_days) ** 2) / (2 * (optimal_days / 2) ** 2)))
        spacing_multiplier = 1.0 + (1.2 * bell if is_revision else 0.0)

        if used_faculty:
            faculty_mult = 1.0 - (dim.faculty_dependency * 0.35)
            dim.faculty_dependency = max(0.1, dim.faculty_dependency - 0.02)
        else:
            faculty_mult = 1.0
            dim.faculty_dependency = max(0.1, dim.faculty_dependency - 0.08)

        aptitude_match = (aptitude.calculation * (1 - concept_load) + aptitude.memory * 0.5) 
        duration_mult = max(0.75, min(1.4, duration / 1.5))
        quality_mult = max(0.35, min(1.25, 0.55 + (0.9 * performance)))
        
        base_rate = 0.115 * (1.45 if is_revision else 1.0)
        delta = base_rate * spacing_multiplier * faculty_mult * aptitude_match * duration_mult * quality_mult * (1.0 - dim.mastery)
        dim.mastery = min(1.0, dim.mastery + delta)
        dim.last_revised_day = current_day # FIXED: Update last revised day
