import asyncio
import logging
from local_lab.core.runner import BenchmarkRunner
from local_lab.world.curriculum_engine import StandardCurriculumEngine
from local_lab.student.memory_model import StandardMemoryModel
from local_lab.student.trust_model import DynamicTrustModel
from local_lab.student.fatigue_model import StandardFatigueModel
from local_lab.models.metadata import PlannerMetadata
from local_lab.models.profiles import FatigueParameters

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("academic_digital_twin.wrapper")

async def main():
    logger.info("Initializing Extensible Research Platform wrapper...")
    
    curriculum = StandardCurriculumEngine(seed=42)
    memory = StandardMemoryModel()
    trust = DynamicTrustModel() # Fixed initialization
    fatigue = StandardFatigueModel(parameters=FatigueParameters())
    
    logger.info(f"Loaded Plugin: {curriculum.metadata().name} {curriculum.metadata().version}")
    logger.info(f"Loaded Plugin: {memory.metadata().name} {memory.metadata().version}")
    logger.info(f"Loaded Plugin: {trust.metadata().name} {trust.metadata().version}")
    logger.info(f"Loaded Plugin: {fatigue.metadata().name} {fatigue.metadata().version}")
    
    runner = BenchmarkRunner(curriculum, memory, trust, fatigue)
    
    meta = PlannerMetadata(
        git_commit="HEAD",
        architecture_version="v2.0-extensible",
        memory_schema_version="v3.1",
        planner_version="groq-latest",
        protocol_version="2028.1",
        config_hash="abc123def"
    )
    
    res = await runner.run_population(population_size=10, days=365, seed=8821, metadata=meta)
    
    print("\\n=== Extensible Platform Run Complete ===")
    print(res["knowledge"])

if __name__ == "__main__":
    asyncio.run(main())
