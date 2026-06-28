import json
import logging
import math
import random
import uuid
from typing import Dict, List, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("academic_digital_twin")

# ────────────────────────────────────────────────────────────────────────
# QUESTION BANK & IDENTITIES
# ────────────────────────────────────────────────────────────────────────
class QuestionBank:
    """Generates and stores permanent question identities."""
    def __init__(self):
        self.questions = {}

    def get_or_generate(self, concept: str, diff_target: str = "Medium") -> dict:
        q_id = f"Q_{uuid.uuid4().hex[:8].upper()}"
        difficulties = {"Easy": 0.3, "Medium": 0.5, "Hard": 0.8, "Olympiad": 0.95}
        blooms = ["Recall", "Understand", "Apply", "Analyze", "Evaluate", "Create"]
        
        diff_val = difficulties.get(diff_target, 0.5)
        # Add stochastic noise to the theoretical difficulty
        true_difficulty = max(0.1, min(0.99, diff_val + random.uniform(-0.1, 0.1)))
        
        q = {
            "id": q_id,
            "concept": concept,
            "difficulty_label": diff_target,
            "true_difficulty": true_difficulty,
            "discrimination": random.uniform(0.2, 0.8), # Item Response Theory param
            "bloom_level": random.choice(blooms),
            "est_solve_time": int(true_difficulty * 180 + 60) # 60s to 240s
        }
        self.questions[q_id] = q
        return q

# ────────────────────────────────────────────────────────────────────────
# WORLD ENGINE
# ────────────────────────────────────────────────────────────────────────
class World:
    """Objective reality engine. Handles time, curriculum, exams, and chaos events."""
    def __init__(self, seed: int = 42):
        random.seed(seed)
        self.current_day = 1
        self.qbank = QuestionBank()
        
        # Course Graph
        self.concepts = {
            "Kinematics": {"prereqs": []},
            "Vectors": {"prereqs": []},
            "NLM": {"prereqs": ["Kinematics", "Vectors"]},
            "WPE": {"prereqs": ["NLM"]},
            "COM": {"prereqs": ["NLM", "WPE"]},
        }
        self.active_concepts = ["Kinematics", "Vectors"]
        self.active_event = None

    def advance_day(self) -> dict:
        self.current_day += 1
        self.active_event = None
        
        # Chaos Events (e.g. 5% chance of something happening)
        if random.random() < 0.05:
            events = [
                {"type": "Fever", "fatigue_penalty": 1.0, "anxiety_spike": 0.2, "duration": 3},
                {"type": "PowerCut", "time_penalty": 3.0, "anxiety_spike": 0.1, "duration": 1},
                {"type": "ExamWeek", "fatigue_penalty": 0.3, "anxiety_spike": 0.5, "duration": 7}
            ]
            self.active_event = random.choice(events)
            
        # Curriculum Advancement
        if self.current_day == 30: self.active_concepts.append("NLM")
        if self.current_day == 60: self.active_concepts.append("WPE")
        if self.current_day == 90: self.active_concepts.append("COM")
        
        return self.active_event or {}

    def generate_jee_paper(self) -> List[dict]:
        """Generates a 75-question realistic JEE Mock."""
        paper = []
        for _ in range(75):
            concept = random.choice(self.active_concepts)
            # JEE is mostly Hard/Olympiad
            diff = random.choices(["Medium", "Hard", "Olympiad"], weights=[0.2, 0.6, 0.2])[0]
            paper.append(self.qbank.get_or_generate(concept, diff))
        return paper

# ────────────────────────────────────────────────────────────────────────
# MULTI-DIMENSIONAL MEMORY
# ────────────────────────────────────────────────────────────────────────
class MemoryDimension:
    def __init__(self, concept: str):
        self.concept = concept
        self.mastery = 0.0
        self.faculty_dependency = random.uniform(0.3, 0.9) # How much they need a teacher
        self.forgetting_rate = random.uniform(0.02, 0.08) # How fast they forget this specifically
        self.times_encountered = 0
        self.last_revised_day = 0

class StudentMemory:
    def __init__(self, world: World):
        self.world = world
        self.dims = {c: MemoryDimension(c) for c in self.world.concepts}
        
    def get_effective_mastery(self, concept: str) -> float:
        node = self.dims[concept]
        base = node.mastery
        prereqs = self.world.concepts[concept]["prereqs"]
        if not prereqs: return base
        prereq_mastery = sum(self.get_effective_mastery(p) for p in prereqs) / len(prereqs)
        return base * (0.3 + 0.7 * prereq_mastery) # High penalty if prereqs forgotten

    def apply_decay(self, current_day: int):
        for c, dim in self.dims.items():
            days_since = current_day - dim.last_revised_day
            if days_since > 0 and dim.mastery > 0:
                decay = dim.forgetting_rate * (days_since / 10.0)
                dim.mastery = max(0.0, dim.mastery - decay)

# ────────────────────────────────────────────────────────────────────────
# VIRTUAL STUDENT
# ────────────────────────────────────────────────────────────────────────
class VirtualStudent:
    def __init__(self, world: World):
        self.world = world
        self.memory = StudentMemory(world)
        
        # Physical/Psychological State
        self.fatigue = 0.0
        self.motivation = 0.8
        self.trust = 0.5
        
        # Emotional Momentum Vector
        self.anxiety = 0.2
        self.self_belief = 0.7
        
        self.daily_hours_capacity = 8.0
        self.burnout_days = 0

    def solve_question(self, q: dict) -> bool:
        """Item Response Theory (IRT) probability model with emotional noise."""
        eff_mastery = self.memory.get_effective_mastery(q["concept"])
        
        # Anxiety makes questions seem harder (lowers effective mastery)
        # High self-belief counteracts anxiety
        emotional_modifier = (self.self_belief - self.anxiety) * 0.2
        realized_mastery = max(0.0, min(1.0, eff_mastery + emotional_modifier))
        
        # Logistic probability based on difficulty and discrimination
        # P(Correct) = 1 / (1 + e^(-a(θ - b)))
        theta = realized_mastery # Ability
        b = q["true_difficulty"] # Difficulty
        a = q["discrimination"] * 10 # Discrimination scalar
        
        prob_correct = 1.0 / (1.0 + math.exp(-a * (theta - b)))
        return random.random() < prob_correct

    def the_learning_equation(self, concept: str, is_revision: bool, was_faculty_assisted: bool):
        """The Grand Learning Equation. Logistic plateau, spacing effect, faculty."""
        dim = self.memory.dims[concept]
        dim.times_encountered += 1
        
        # 1. Spacing Effect (Optimal revision is right as it's being forgotten)
        days_since = self.world.current_day - dim.last_revised_day
        optimal_days = 1 / dim.forgetting_rate
        spacing_multiplier = 1.0
        if is_revision and days_since > 0:
            # Bell curve centering around optimal spacing
            spacing_multiplier = 2.0 * math.exp(-(((days_since - optimal_days)**2) / (2 * (optimal_days/2)**2)))
        
        # 2. Faculty Assistance Penalty/Boost
        faculty_mult = 1.0
        if was_faculty_assisted:
            # Over-reliance on faculty lowers independent mastery gain
            faculty_mult = 1.0 - (dim.faculty_dependency * 0.5)
            dim.faculty_dependency = max(0.1, dim.faculty_dependency - 0.05) # Slowly become independent
            
        # 3. Emotional State
        emo_mult = max(0.1, self.self_belief * self.motivation * (1.0 - self.fatigue))
        
        # 4. Logistic Growth (Harder to grow from 80->90 than 20->30)
        # Growth capacity = 1.0 - current
        base_rate = 0.15 * (1.5 if is_revision else 1.0)
        delta = base_rate * spacing_multiplier * faculty_mult * emo_mult * (1.0 - dim.mastery)
        
        dim.mastery = min(1.0, dim.mastery + delta)
        dim.last_revised_day = self.world.current_day

    def execute_plan(self, plan_json: str) -> str:
        """Parses telegram plan, mathematically executes, outputs telegram reflection."""
        try:
            plan = json.loads(plan_json)
        except:
            return json.dumps({"msg": "Parser error", "completed": []})

        blocks = plan.get("blocks", [])
        
        # Apply World Chaos
        available_hours = self.daily_hours_capacity
        if self.world.active_event:
            if "time_penalty" in self.world.active_event:
                available_hours -= self.world.active_event["time_penalty"]
            if "anxiety_spike" in self.world.active_event:
                self.anxiety = min(1.0, self.anxiety + self.world.active_event["anxiety_spike"])
            if "fatigue_penalty" in self.world.active_event:
                self.fatigue = min(1.0, self.fatigue + self.world.active_event["fatigue_penalty"])
        
        hours_spent = 0.0
        results = []

        # Downward Spiral check
        if self.anxiety > 0.8 and self.motivation < 0.3:
            self.burnout_days += 1
            return json.dumps({"message": "I'm completely burnt out. I didn't study at all today.", "completed": []})

        for block in blocks:
            concept = block.get("concept", "Unknown")
            is_rev = block.get("is_revision", False)
            duration = block.get("duration", 1.0)
            
            if hours_spent + duration > available_hours * (1.0 - self.fatigue):
                self.fatigue = min(1.0, self.fatigue + 0.1)
                break
                
            hours_spent += duration
            
            # Generate and solve questions
            correct = 0
            attempted = 15
            for _ in range(attempted):
                q = self.world.qbank.get_or_generate(concept, "Medium")
                if self.solve_question(q):
                    correct += 1
                    
            # Faculty Intervention if struggling
            used_faculty = False
            if correct / attempted < 0.4:
                used_faculty = True
                
            # GRAND LEARNING EQUATION
            self.the_learning_equation(concept, is_rev, used_faculty)
            results.append({"concept": concept, "correct": correct, "attempted": attempted})
            
        # Emotional update based on daily outcome
        if hours_spent > 0:
            self.self_belief = min(1.0, self.self_belief + 0.02)
            self.anxiety = max(0.0, self.anxiety - 0.05)
            self.fatigue = max(0.0, self.fatigue - 0.1)
            
        return json.dumps({
            "message": f"Did {len(results)} blocks. Spent {hours_spent} hours.",
            "completed": results
        })

    def take_jee_exam(self, paper: List[dict]) -> dict:
        correct = 0
        for q in paper:
            if self.solve_question(q): correct += 1
        return {"score": correct * 4, "max_score": len(paper) * 4}

# ────────────────────────────────────────────────────────────────────────
# DIGITAL TWIN HARNESS
# ────────────────────────────────────────────────────────────────────────
class AcademicDigitalTwin:
    def dummy_ai_plan(self, world: World, use_ai: bool) -> str:
        blocks = []
        if world.active_concepts:
            blocks.append({"concept": world.active_concepts[-1], "duration": 2.0})
            if use_ai and world.current_day % 2 == 0:
                blocks.append({"concept": random.choice(world.active_concepts), "is_revision": True, "duration": 1.0})
        return json.dumps({"blocks": blocks})

    def run_benchmark(self, name: str, use_ai: bool, days: int = 365):
        logger.info(f"--- Starting Digital Twin: {name} ---")
        world = World(seed=999)
        student = VirtualStudent(world)
        
        for day in range(1, days + 1):
            world.advance_day()
            student.memory.apply_decay(world.current_day)
            
            plan = self.dummy_ai_plan(world, use_ai)
            reflection = student.execute_plan(plan)
            
        # Day 365: Take JEE
        jee_paper = world.generate_jee_paper()
        result = student.take_jee_exam(jee_paper)
        
        logger.info(f"[{name}] Completed.")
        logger.info(f"  -> JEE Score: {result['score']}/{result['max_score']}")
        logger.info(f"  -> Burnout Days: {student.burnout_days}")
        logger.info(f"  -> Final Anxiety: {student.anxiety:.2f}")
        logger.info(f"  -> Final Self-Belief: {student.self_belief:.2f}")
        return result['score']

if __name__ == "__main__":
    twin = AcademicDigitalTwin()
    control_score = twin.run_benchmark("Control (No AI)", use_ai=False)
    ai_score = twin.run_benchmark("SENTINEL (AI)", use_ai=True)
    logger.info(f"\nSENTINEL Delta: {ai_score - control_score:+} marks on Final JEE Paper")
