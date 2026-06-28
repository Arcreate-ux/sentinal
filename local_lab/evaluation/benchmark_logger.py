import json
import logging
from pathlib import Path
from dataclasses import asdict
from local_lab.models.metadata import BenchmarkResult

logger = logging.getLogger("academic_digital_twin.logger")

class BenchmarkLogger:
    def __init__(self, uri: str = ""):
        self.uri = uri
        
    def log_run(self, result: BenchmarkResult):
        record = asdict(result)
        
        if self.uri:
            # Here we would use pymongo:
            # client = pymongo.MongoClient(self.uri)
            # db = client.sentinel_brain
            # db.benchmark_runs.insert_one(record)
            logger.info(f"Mocked MongoDB insert for run {result.run_id}")
        
        # Fallback persistence: JSONL
        runtime_dir = Path("local_lab/runtime")
        runtime_dir.mkdir(parents=True, exist_ok=True)
        
        jsonl_path = runtime_dir / "benchmark_runs.jsonl"
        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\\n")
            
        logger.info(f"Logged benchmark run {result.run_id} to {jsonl_path}")
