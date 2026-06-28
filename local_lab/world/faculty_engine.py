import random
from local_lab.core.interfaces import FacultyEngine
from local_lab.models.profiles import FacultyProfile, PluginMetadata

class StandardFacultyEngine(FacultyEngine):
    def __init__(self, seed: int):
        self.rng = random.Random(seed + 1)
        self.profiles = {
            "Physics": FacultyProfile("Physics Faculty", 0.9, 0.6, 0.85, 0.7, 0.6, 0.8),
            "Math": FacultyProfile("Math Faculty", 0.6, 0.9, 0.9, 0.5, 0.4, 0.5),
            "Chemistry": FacultyProfile("Chemistry Faculty", 0.8, 0.7, 0.7, 0.8, 0.9, 0.9)
        }
        
    def metadata(self) -> PluginMetadata:
        return PluginMetadata("StandardFacultyEngine", "v1.0", "Yatin")
        
    def _get_subject(self, concept: str) -> str:
        if concept in ["Vectors", "Kinematics", "NLM", "WPE", "COM", "Rotation", "Thermodynamics", "Electrostatics", "Modern Physics"]:
            return "Physics"
        elif concept in ["Quadratic Equations", "Sequences and Series", "Trigonometry", "Integration", "Coordinate Geometry"]:
            return "Math"
        else:
            return "Chemistry"

    def get_faculty_profile(self, concept: str) -> FacultyProfile:
        subject = self._get_subject(concept)
        return self.profiles[subject]
