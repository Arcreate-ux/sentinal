import random
from typing import Any
from local_lab.core.interfaces import CurriculumEngine
from local_lab.models.profiles import ConceptProfile, PluginMetadata
from local_lab.models.state import CurriculumState

class StandardCurriculumEngine(CurriculumEngine):
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.concept_order = [
            "Vectors", "Kinematics", "Mole Concept", "Quadratic Equations",
            "NLM", "Atomic Structure", "Sequences and Series", "WPE",
            "Chemical Equilibrium", "Trigonometry", "COM", "Rotation",
            "Thermodynamics", "Integration", "Electrostatics",
            "Coordinate Geometry", "Organic Basics", "Modern Physics"
        ]
        
        self.profiles = {
            "Vectors": ConceptProfile("Vectors", 0.3, 0.4, 0.8, 0.2, 0.3),
            "Kinematics": ConceptProfile("Kinematics", 0.4, 0.6, 0.7, 0.3, 0.5),
            "Mole Concept": ConceptProfile("Mole Concept", 0.2, 0.8, 0.2, 0.6, 0.4),
            "Quadratic Equations": ConceptProfile("Quadratic Equations", 0.6, 0.9, 0.1, 0.3, 0.6),
            "NLM": ConceptProfile("NLM", 0.5, 0.5, 0.8, 0.3, 0.7),
            "Atomic Structure": ConceptProfile("Atomic Structure", 0.8, 0.4, 0.5, 0.7, 0.5),
            "Sequences and Series": ConceptProfile("Sequences and Series", 0.7, 0.8, 0.1, 0.4, 0.8),
            "WPE": ConceptProfile("WPE", 0.6, 0.6, 0.7, 0.3, 0.6),
            "Chemical Equilibrium": ConceptProfile("Chemical Equilibrium", 0.5, 0.8, 0.3, 0.6, 0.7),
            "Trigonometry": ConceptProfile("Trigonometry", 0.6, 0.9, 0.7, 0.8, 0.7),
            "COM": ConceptProfile("COM", 0.7, 0.7, 0.8, 0.4, 0.8),
            "Rotation": ConceptProfile("Rotation", 0.95, 0.7, 0.95, 0.25, 0.9),
            "Thermodynamics": ConceptProfile("Thermodynamics", 0.7, 0.6, 0.5, 0.6, 0.6),
            "Integration": ConceptProfile("Integration", 0.9, 0.9, 0.4, 0.7, 0.8),
            "Electrostatics": ConceptProfile("Electrostatics", 0.8, 0.7, 0.8, 0.5, 0.7),
            "Coordinate Geometry": ConceptProfile("Coordinate Geometry", 0.6, 0.9, 0.8, 0.5, 0.6),
            "Organic Basics": ConceptProfile("Organic Basics", 0.5, 0.15, 0.2, 0.95, 0.8),
            "Modern Physics": ConceptProfile("Modern Physics", 0.7, 0.5, 0.4, 0.7, 0.6),
        }

    def metadata(self) -> PluginMetadata:
        return PluginMetadata("StandardCurriculumEngine", "v2.0", "Yatin", {"chaos_prob": 0.03})
        
    def create_state(self) -> CurriculumState:
        return CurriculumState(
            current_day=0,
            active_concepts=self.concept_order[:3],
            coaching_progress=0.0,
            coaching_velocity=self.rng.uniform(0.7, 1.3),
            chaos_event=None,
            chaos_days_left=0
        )

    def advance_day(self, state: CurriculumState) -> dict[str, Any]:
        state.current_day += 1
        event = {}
        
        if state.chaos_days_left > 0:
            state.chaos_days_left -= 1
            if state.chaos_days_left == 0:
                state.chaos_event = None
                
        # Random Faculty Chaos
        elif self.rng.random() < 0.03:
            if self.rng.random() < 0.5:
                state.coaching_progress += 2.0
                event = {"type": "FacultySkip", "message": "Faculty suddenly rushed through 2 concepts."}
            else:
                state.chaos_days_left = self.rng.randint(3, 7)
                state.chaos_event = {"type": "FacultyPause", "pauses_coaching": True, "message": f"Faculty paused teaching for {state.chaos_days_left} days."}
                event = state.chaos_event
                
        if not (state.chaos_event and state.chaos_event.get("pauses_coaching")):
            state.coaching_velocity = max(0.5, min(1.8, state.coaching_velocity + self.rng.uniform(-0.1, 0.1)))
            state.coaching_progress += (1.0 / 22.0) * state.coaching_velocity

        unlock_count = min(len(self.concept_order), 3 + int(state.coaching_progress))
        state.active_concepts = self.concept_order[:unlock_count]
        
        return {"active_concepts": list(state.active_concepts), "event": event}

    def get_concept_profile(self, concept: str) -> ConceptProfile:
        return self.profiles.get(concept, ConceptProfile(concept, 0.5, 0.5, 0.5, 0.5, 0.5))
