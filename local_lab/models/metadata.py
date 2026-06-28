from dataclasses import dataclass, field
from datetime import datetime, timezone

@dataclass
class PlannerMetadata:
    git_commit: str
    architecture_version: str
    memory_schema_version: str
    planner_version: str
    protocol_version: str
    config_hash: str

@dataclass
class BenchmarkResult:
    run_id: str
    planner_metadata: PlannerMetadata
    population_size: int
    world_seed: int
    avg_fitness_delta: float
    avg_control_score: float
    avg_sentinel_score: float
    runtime_seconds: float
    cost_estimate: float
    date: str
    
    @classmethod
    def create(cls, run_id: str, meta: PlannerMetadata, pop_size: int, world_seed: int) -> "BenchmarkResult":
        return cls(
            run_id=run_id,
            planner_metadata=meta,
            population_size=pop_size,
            world_seed=world_seed,
            avg_fitness_delta=0.0,
            avg_control_score=0.0,
            avg_sentinel_score=0.0,
            runtime_seconds=0.0,
            cost_estimate=0.0,
            date=datetime.now(timezone.utc).isoformat()
        )
