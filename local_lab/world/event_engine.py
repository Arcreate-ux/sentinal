import random
from typing import Any
from local_lab.core.interfaces import SimEngine
from local_lab.models.profiles import PluginMetadata

class StandardEventEngine(SimEngine):
    def __init__(self, seed: int):
        self.rng = random.Random(seed + 2)
        self.active_event: dict[str, Any] = {}
        self._event_days_left = 0
        
    def metadata(self) -> PluginMetadata:
        return PluginMetadata("StandardEventEngine", "v1.0", "Yatin")
        
    def advance_day(self) -> dict[str, Any]:
        if self._event_days_left > 0:
            self._event_days_left -= 1
            if self._event_days_left == 0:
                self.active_event = {}
        elif self.rng.random() < 0.08:
            events = [
                {"type": "Fever", "fatigue_penalty": 0.65, "anxiety_spike": 0.18, "duration": 3, "time_penalty": 6.0},
                {"type": "PowerCut", "time_penalty": 3.0, "anxiety_spike": 0.08, "duration": 1, "fatigue_penalty": 0.0},
                {"type": "ExamWeek", "fatigue_penalty": 0.25, "anxiety_spike": 0.35, "duration": 7, "time_penalty": 2.0},
                {"type": "FamilyFunction", "time_penalty": 4.0, "anxiety_spike": 0.12, "duration": 1, "fatigue_penalty": 0.2},
                {"type": "Holiday", "fatigue_penalty": -0.2, "anxiety_spike": -0.1, "duration": 2, "time_penalty": -2.0},
            ]
            self.active_event = dict(self.rng.choice(events))
            self._event_days_left = int(self.active_event.get("duration", 1))
            
        return self.active_event
