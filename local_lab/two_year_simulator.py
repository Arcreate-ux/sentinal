import asyncio
import json
import logging
import random
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("jee_benchmark")

# ────────────────────────────────────────────────────────────────────────
# WORLD ENGINE
# ────────────────────────────────────────────────────────────────────────
class World:
    """The objective reality. Calendar, Exams, Course Progression, Noise."""
    
    def __init__(self, seed: int = 42):
        random.seed(seed)
        self.current_day = 1
        
        # Course Progression Engine (with prerequisites)
        self.concepts = {
            "Kinematics": {"skill": "Mechanics", "prereqs": []},
            "Vectors": {"skill": "Mechanics", "prereqs": []},
            "NLM": {"skill": "Mechanics", "prereqs": ["Kinematics", "Vectors"]},
            "WPE": {"skill": "Mechanics", "prereqs": ["NLM"]},
            "COM": {"skill": "Mechanics", "prereqs": ["NLM", "WPE"]},
            "Functions": {"skill": "Calculus", "prereqs": []},
            "Limits": {"skill": "Calculus", "prereqs": ["Functions"]},
            "Derivatives": {"skill": "Calculus", "prereqs": ["Limits"]},
        }
        
        self.syllabus_schedule = {
            1: ["Kinematics", "Vectors", "Functions"],
            30: ["NLM", "Limits"],
            60: ["WPE", "Derivatives"],
            90: ["COM"],
        }
        
        self.active_concepts = []

    def advance_day(self):
        if self.current_day in self.syllabus_schedule:
            self.active_concepts.extend(self.syllabus_schedule[self.current_day])
        self.current_day += 1
        
    def generate_question(self, concept: str) -> dict:
        """Questions have stochastic difficulty."""
        difficulties = ["Easy", "Medium", "Hard", "Olympiad"]
        weights = [0.4, 0.4, 0.15, 0.05]
        diff = random.choices(difficulties, weights=weights)[0]
        req_mastery = {"Easy": 0.3, "Medium": 0.6, "Hard": 0.85, "Olympiad": 0.98}[diff]
        return {"concept": concept, "difficulty": diff, "req_mastery": req_mastery}

    def generate_mock_test(self) -> list[dict]:
        """Generate a 30-question mock test from active concepts."""
        questions = []
        if not self.active_concepts:
            return questions
        for _ in range(30):
            concept = random.choice(self.active_concepts)
            questions.append(self.generate_question(concept))
        return questions

# ────────────────────────────────────────────────────────────────────────
# FACULTY AGENT
# ────────────────────────────────────────────────────────────────────────
class FacultyAgent:
    def resolve_doubt(self, concept: str, current_mastery: float) -> dict:
        """Simulates asking a teacher for help. Output changes mastery."""
        roll = random.random()
        if roll < 0.6:  # 60% chance full resolution
            return {"status": "Resolved", "boost": 0.15}
        elif roll < 0.9: # 30% chance partial
            return {"status": "Partial", "boost": 0.05}
        else: # 10% chance teacher didn't explain well
            return {"status": "Failed", "boost": 0.0}

# ────────────────────────────────────────────────────────────────────────
# MEMORY ENGINE
# ────────────────────────────────────────────────────────────────────────
class StudentMemory:
    """Skill -> Concept -> Mastery Hierarchy."""
    
    def __init__(self, world: World):
        self.world = world
        # concept -> {"mastery": float, "last_revised": int}
        self.matrix = {c: {"mastery": 0.0, "last_revised": 0} for c in self.world.concepts}
        
    def get_effective_mastery(self, concept: str) -> float:
        """Mastery decays if prerequisites are forgotten."""
        node = self.matrix[concept]
        base = node["mastery"]
        
        prereqs = self.world.concepts[concept]["prereqs"]
        if not prereqs:
            return base
            
        prereq_mastery = sum(self.get_effective_mastery(p) for p in prereqs) / len(prereqs)
        return base * (0.5 + 0.5 * prereq_mastery) # Prereqs heavily weight effective mastery

    def apply_decay(self, current_day: int):
        for concept, data in self.matrix.items():
            if data["mastery"] > 0:
                days_since = current_day - data["last_revised"]
                if days_since > 0:
                    decay = 0.05 * (days_since / 10.0)
                    data["mastery"] = max(0.0, data["mastery"] - decay)

    def learn(self, concept: str, current_day: int, boost: float):
        current = self.matrix[concept]["mastery"]
        self.matrix[concept]["mastery"] = min(1.0, current + boost * (1.0 - current))
        self.matrix[concept]["last_revised"] = current_day

# ────────────────────────────────────────────────────────────────────────
# VIRTUAL STUDENT
# ────────────────────────────────────────────────────────────────────────
class VirtualStudent:
    """The psychological and cognitive entity."""
    
    def __init__(self, world: World, profile: str = "Average"):
        self.world = world
        self.memory = StudentMemory(world)
        self.faculty = FacultyAgent()
        
        self.fatigue = 0.20
        self.motivation = 0.70
        self.trust = 0.50
        
        self.learning_rate = 0.10
        self.discipline = 0.70
        self.backlog = 0
        self.burnout_days = 0
        self.cumulative_confidence_gain = 0.0
        self.study_hours_total = 0.0
        self.mock_history = []

    def execute_plan(self, telegram_message: str) -> str:
        """
        AIR GAP ENFORCED: 
        Takes a string (representing parsed plan). 
        Outputs a string (representing actual reflection).
        """
        self.memory.apply_decay(self.world.current_day)
        
        # Extremely basic mock parser to simulate LLM extraction for the benchmark
        # In a real run, this would be `json.loads(telegram_message)` after Sentinel sends it.
        try:
            plan = json.loads(telegram_message)
        except json.JSONDecodeError:
            plan = {"blocks": [], "predicted_hours": 0}

        blocks = plan.get("blocks", [])
        predicted_hours = plan.get("predicted_hours", 0)
        
        actual_hours = 0.0
        results = []
        
        # 1. Protocol Violations Check
        if self.trust < 0.4 and self.motivation < 0.5 and random.random() < 0.3:
            return json.dumps({
                "message": "I'm exhausted and don't trust this schedule. I'm skipping theory and only doing PYQs today.",
                "blocks_completed": []
            })
            
        max_capacity = 10.0 * (1.0 - self.fatigue * 0.5)

        for block in blocks:
            concept = block.get("concept", "Unknown")
            is_revision = block.get("is_revision", False)
            duration = block.get("duration_hrs", 1.0)
            
            # Trust based skipping
            if is_revision and random.random() > (self.discipline * self.trust):
                self.backlog += 1
                continue
                
            if actual_hours + duration > max_capacity:
                self.fatigue = min(1.0, self.fatigue + 0.1)
                self.backlog += 1
                break # Burnout stop
                
            actual_hours += duration
            self.study_hours_total += duration
            
            # Question execution
            attempted = 20
            correct = 0
            for _ in range(attempted):
                q = self.world.generate_question(concept)
                eff_mastery = self.memory.get_effective_mastery(concept)
                
                # Stochastic Luck / Stress variance
                roll = eff_mastery * random.uniform(0.8, 1.2)
                if roll >= q["req_mastery"]:
                    correct += 1
                    
            # Faculty Doubt Resolution Trigger
            if correct / attempted < 0.4:
                doubt_res = self.faculty.resolve_doubt(concept, eff_mastery)
                self.memory.learn(concept, self.world.current_day, doubt_res["boost"])

            # Learning Math
            boost = self.learning_rate * (1.5 if is_revision else 1.0)
            self.memory.learn(concept, self.world.current_day, boost)
            self.cumulative_confidence_gain += boost
            
            results.append({"concept": concept, "attempted": attempted, "correct": correct})

        # 2. Trust Engine (Prediction vs Reality)
        if predicted_hours > 0:
            accuracy_ratio = actual_hours / predicted_hours
            if accuracy_ratio > 0.8:
                self.trust = min(1.0, self.trust + 0.05)
            elif accuracy_ratio < 0.5:
                self.trust = max(0.0, self.trust - 0.1)

        # 3. Rest & Motivation
        self.fatigue = max(0.0, self.fatigue - 0.15)
        if self.fatigue > 0.9:
            self.burnout_days += 1
            self.motivation = max(0.0, self.motivation - 0.3)
        elif len(results) > 0 and len(results) == len(blocks):
            self.motivation = min(1.0, self.motivation + 0.05)

        return json.dumps({
            "message": f"Completed {len(results)} blocks. Got {sum(r['correct'] for r in results)} correct.",
            "actual_hours": actual_hours,
            "blocks_completed": results
        })

    def take_mock_test(self) -> float:
        """Takes a mock test with stochastic noise. Returns percentile."""
        questions = self.world.generate_mock_test()
        if not questions:
            return 0.0
            
        sleep_modifier = random.uniform(0.8, 1.1)
        stress_modifier = random.uniform(0.8, 1.1)
        
        correct = 0
        for q in questions:
            eff_mastery = self.memory.get_effective_mastery(q["concept"])
            roll = eff_mastery * sleep_modifier * stress_modifier
            if roll >= q["req_mastery"]:
                correct += 1
                
        percentile = correct / len(questions)
        self.mock_history.append(percentile)
        
        # Motivation feedback from Mocks
        if percentile > 0.7:
            self.motivation = min(1.0, self.motivation + 0.15)
        elif percentile < 0.4:
            self.motivation = max(0.0, self.motivation - 0.15)
            
        return percentile

# ────────────────────────────────────────────────────────────────────────
# BENCHMARKING HARNESS
# ────────────────────────────────────────────────────────────────────────
class BenchmarkingHarness:
    
    def generate_dummy_planner_telegram(self, world: World, use_ai: bool) -> str:
        """Mock SENTINEL generating a JSON string plan."""
        blocks = []
        if world.active_concepts:
            # AI schedules revisions, normal doesn't
            if use_ai and world.current_day % 3 == 0:
                blocks.append({"concept": random.choice(world.active_concepts), "is_revision": True, "duration_hrs": 1.0})
            
            blocks.append({"concept": world.active_concepts[-1], "is_revision": False, "duration_hrs": 2.0})
            if not use_ai:
                blocks.append({"concept": random.choice(world.active_concepts), "is_revision": False, "duration_hrs": 4.0}) # Causes fatigue
                
        return json.dumps({"blocks": blocks, "predicted_hours": sum(b["duration_hrs"] for b in blocks)})

    def run_benchmark(self, name: str, use_ai: bool, days: int = 365):
        logger.info(f"--- Starting Regression Benchmark: {name} ---")
        world = World(seed=1337)
        student = VirtualStudent(world)
        
        for day in range(1, days + 1):
            world.advance_day()
            
            # 1. PLANNER GENERATES TELEGRAM MESSAGE (AIR GAP)
            plan_str = self.generate_dummy_planner_telegram(world, use_ai)
            
            # 2. STUDENT EXECUTES AND RETURNS TELEGRAM MESSAGE (AIR GAP)
            reflection_str = student.execute_plan(plan_str)
            
            # 3. MOCK TEST
            if day % 14 == 0:
                student.take_mock_test()

        # METRICS
        velocity = student.cumulative_confidence_gain / max(1.0, student.study_hours_total)
        
        # Predict JEE Score from Mock Trend (Avg of last 3 mocks)
        recent_mocks = student.mock_history[-3:] if len(student.mock_history) >= 3 else student.mock_history
        final_percentile = sum(recent_mocks) / len(recent_mocks) if recent_mocks else 0.0
        predicted_score = int(final_percentile * 300)
        
        logger.info(f"[{name}] Benchmark Complete.")
        logger.info(f"  -> Predicted JEE Score: {predicted_score}/300")
        logger.info(f"  -> Learning Velocity: {velocity:.4f} Δ/hr")
        logger.info(f"  -> Burnout Days: {student.burnout_days}")
        logger.info(f"  -> Backlog: {student.backlog}")
        logger.info(f"  -> Final Trust: {student.trust:.2f}")
        return predicted_score

if __name__ == "__main__":
    harness = BenchmarkingHarness()
    score_no_ai = harness.run_benchmark("Control (No AI)", use_ai=False)
    score_with_ai = harness.run_benchmark("SENTINEL (AI)", use_ai=True)
    
    logger.info("\n=== CONTINUOUS INTEGRATION REPORT ===")
    logger.info(f"SENTINEL Delta: {score_with_ai - score_no_ai:+} marks")
