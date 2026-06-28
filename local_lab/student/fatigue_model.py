from local_lab.core.interfaces import FatigueModel
from local_lab.models.profiles import PluginMetadata, FatigueParameters
from local_lab.models.state import FatigueState

class StandardFatigueModel(FatigueModel):
    def __init__(self, parameters: FatigueParameters = FatigueParameters()):
        self.params = parameters

    def metadata(self) -> PluginMetadata:
        return PluginMetadata("StandardFatigueModel", "v2.1", "Yatin", parameters=self.params.__dict__)

    def create_state(self, base_anxiety: float) -> FatigueState:
        return FatigueState(anxiety=base_anxiety)

    def update(self, state: FatigueState, hours_spent: float, capacity: float, event_penalty: float) -> tuple[float, float, int]:
        available_hours = capacity - event_penalty
        
        if hours_spent > 0:
            if hours_spent > available_hours * (1.0 - state.fatigue):
                state.fatigue = min(1.0, state.fatigue + self.params.fatigue_accumulation_rate)
            else:
                state.fatigue = max(0.0, state.fatigue - self.params.fatigue_recovery_rate)
            state.anxiety = max(0.0, state.anxiety - self.params.anxiety_recovery_rate)
        else:
            state.fatigue = max(0.0, state.fatigue - self.params.day_off_fatigue_recovery)
            state.anxiety = max(0.0, state.anxiety - self.params.day_off_anxiety_recovery)
            
        if state.anxiety > self.params.burnout_anxiety_threshold and state.fatigue > self.params.burnout_fatigue_threshold:
            state.burnout_days += 1
            state.fatigue = max(0.0, state.fatigue - self.params.burnout_fatigue_drop)
            state.anxiety = max(0.0, state.anxiety - self.params.burnout_anxiety_drop)
            
        return state.fatigue, state.anxiety, state.burnout_days
