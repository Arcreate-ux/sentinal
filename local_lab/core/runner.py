import asyncio
import logging
import random
import time
from typing import Any

from local_lab.core.interfaces import CurriculumEngine, MemoryModel, TrustModel, FatigueModel
from local_lab.student.student_state import execute_plan
from local_lab.student.personality import PersonalityGenerator
from local_lab.models.metadata import BenchmarkResult, PlannerMetadata
from local_lab.models.state import StudentState
from local_lab.evaluation.benchmark_logger import BenchmarkLogger
from local_lab.evaluation.knowledge_engine import KnowledgeEngine

logger = logging.getLogger("academic_digital_twin.runner")

class BenchmarkRunner:
    def __init__(self, curriculum: CurriculumEngine, memory: MemoryModel, trust: TrustModel, fatigue: FatigueModel):
        self.curriculum = curriculum
        self.memory = memory
        self.trust = trust
        self.fatigue = fatigue
        
    def _dummy_planner(self, active_concepts: list[str], rng: random.Random) -> list[dict[str, Any]]:
        blocks = []
        for _ in range(rng.randint(1, 4)):
            blocks.append({
                "concept": rng.choice(active_concepts) if active_concepts else "Vectors",
                "task_type": "homework",
                "duration": rng.uniform(0.5, 2.5),
                "is_revision": rng.random() > 0.7
            })
        return blocks
        
    def _dummy_control_planner(self, active_concepts: list[str], rng: random.Random) -> list[dict[str, Any]]:
        # Control group always just studies the most recent concept without revision strategies
        blocks = []
        for _ in range(3):
            blocks.append({
                "concept": active_concepts[-1] if active_concepts else "Vectors",
                "task_type": "theory",
                "duration": 1.5,
                "is_revision": False
            })
        return blocks
        
    async def run_population(self, population_size: int, days: int, seed: int, metadata: PlannerMetadata) -> dict[str, Any]:
        start_time = time.time()
        generator = PersonalityGenerator(seed)
        population_dna = generator.generate_population(population_size)
        
        students = []
        for s_idx, dna in enumerate(population_dna):
            state = StudentState(
                memory=self.memory.create_state(),
                fatigue=self.fatigue.create_state(base_anxiety=dna.anxiety_base),
                trust=self.trust.create_state(),
                motivation=dna.discipline * 0.8 + 0.2,
                self_belief=0.8 - (dna.anxiety_base * 0.5)
            )
            # Control vs Sentinel splitting
            group = "control" if s_idx < population_size // 2 else "sentinel"
            student_rng = random.Random(seed + s_idx)
            
            students.append({
                "group": group,
                "dna": dna, 
                "state": state, 
                "curriculum": self.curriculum.create_state(),
                "rng": student_rng
            })

        for day in range(1, days + 1):
            for student in students:
                dna = student["dna"]
                state = student["state"]
                curriculum_state = student["curriculum"]
                rng = student["rng"]
                group = student["group"]
                
                world_out = self.curriculum.advance_day(curriculum_state)
                active_concepts = world_out["active_concepts"]
                event = world_out["event"]
                event_penalty = float(event.get("time_penalty", 0.0))
                
                if group == "sentinel":
                    blocks = self._dummy_planner(active_concepts, rng)
                else:
                    blocks = self._dummy_control_planner(active_concepts, rng)
                
                self.memory.apply_decay(state.memory, day, dna.aptitude)
                
                def get_load(concept: str) -> float:
                    return self.curriculum.get_concept_profile(concept).abstraction
                    
                execute_plan(
                    state=state,
                    dna=dna,
                    memory=self.memory,
                    trust=self.trust,
                    fatigue=self.fatigue,
                    blocks=blocks,
                    event_penalty=event_penalty,
                    active_concepts=active_concepts,
                    rng=rng,
                    current_day=day,
                    get_concept_load=get_load
                )
            
        control_scores = []
        sentinel_scores = []
        
        for student in students:
            state = student["state"]
            coverage = len(state.memory.dims) / max(1, len(self.curriculum.concept_order))
            avg_mastery = sum(d.mastery for d in state.memory.dims.values()) / max(1, len(state.memory.dims))
            fitness = (avg_mastery * 0.4) + (coverage * 0.4) - (state.fatigue.burnout_days * 0.01) + (state.self_belief * 0.2)
            
            if student["group"] == "control":
                control_scores.append(fitness)
            else:
                sentinel_scores.append(fitness)
                
        avg_control = sum(control_scores) / max(1, len(control_scores))
        avg_sentinel = sum(sentinel_scores) / max(1, len(sentinel_scores))
            
        result = BenchmarkResult.create(run_id="EXP-101", meta=metadata, pop_size=population_size, world_seed=seed)
        result.avg_control_score = avg_control
        result.avg_sentinel_score = avg_sentinel
        result.avg_fitness_delta = avg_sentinel - avg_control
        result.runtime_seconds = time.time() - start_time
        result.cost_estimate = (population_size * days * 50) / 1_000_000.0 * 0.15 # dummy $0.15 per 1M tokens
        
        logger_mongo = BenchmarkLogger()
        logger_mongo.log_run(result)
        
        knowledge = KnowledgeEngine().extract_findings(result, students)
        
        return {
            "result": result,
            "knowledge": knowledge
        }
