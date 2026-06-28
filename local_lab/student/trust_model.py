from local_lab.core.interfaces import TrustModel
from local_lab.models.profiles import PluginMetadata
from local_lab.models.state import TrustState

class DynamicTrustModel(TrustModel):
    def metadata(self) -> PluginMetadata:
        return PluginMetadata("DynamicTrustModel", "v2.1", "Yatin")
        
    def create_state(self) -> TrustState:
        return TrustState(trust=0.5)

    def update(self, state: TrustState, hours_scheduled: float, capacity: float, fatigue: float, completed_ratio: float) -> float:
        effective_capacity = capacity * (1.0 - fatigue)
        if hours_scheduled > effective_capacity * 1.2:
            state.trust = max(0.05, state.trust - 0.15)
        
        if completed_ratio > 0.8:
            state.trust = min(0.95, state.trust + 0.02)
        elif completed_ratio < 0.3:
            state.trust = max(0.05, state.trust - 0.05)
            
        return state.trust
