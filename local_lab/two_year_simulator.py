import asyncio
import json
import logging
import uuid
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Assuming SENTINEL environment is set up
# from sentinel.brain.planner import Planner
# from sentinel.state.database import StateDB
# from sentinel.bot.parsers import MessageParser
# from sentinel.brain.ai_engine import AIEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("two_year_simulator")

class StudentPhysicsEngine:
    """Deterministic simulation of a student's state over time."""
    def __init__(self, seed: int = 42):
        random.seed(seed)
        self.motivation = 0.70
        self.fatigue = 0.20
        self.trust_in_sentinel = 0.50
        self.subject_confidence = {
            "Physics": 0.50,
            "Chem": 0.60,
            "Maths": 0.45
        }
        self.burnout_days_triggered = 0

    def process_day(self, daily_plan: dict) -> list[dict]:
        """Mathematically determine what gets completed today."""
        results = []
        blocks = daily_plan.get("blocks", [])
        
        # Calculate daily capacity based on fatigue
        max_hours = 8.0 * (1.0 - (self.fatigue * 0.5))
        hours_spent = 0.0

        for block in blocks:
            expected_time = block.get("target_time", 60) / 60.0
            subject = block.get("subject", "Physics")
            
            # Trust check: If trust is low, might skip theory/revision
            if block.get("exercise_type") in ["Theory", "Revision"] and self.trust_in_sentinel < 0.6:
                if random.random() < 0.4:
                    results.append({"block_id": block["block_id"], "completed": False, "reason": "skipped theory to do PYQs"})
                    continue

            # Fatigue check
            if hours_spent + expected_time > max_hours:
                results.append({"block_id": block["block_id"], "completed": False, "reason": "too tired, fatigue reached"})
                self.fatigue = min(1.0, self.fatigue + 0.1)
                continue

            # Execute block
            hours_spent += expected_time
            mastery = self.subject_confidence.get(subject, 0.5)
            attempted = block.get("question_count", 15)
            
            # Math determines correctness
            correct = int(attempted * mastery * random.uniform(0.8, 1.1))
            correct = min(correct, attempted)

            results.append({
                "block_id": block.get("block_id", str(uuid.uuid4())),
                "completed": True,
                "attempted": attempted,
                "correct": correct,
                "struggled_with": "Concepts" if correct / attempted < 0.6 else None
            })

            # Small confidence bump for completion
            self.subject_confidence[subject] = min(1.0, self.subject_confidence[subject] + 0.01)

        # Rest recovery
        self.fatigue = max(0.0, self.fatigue - 0.15)
        
        # Burnout trigger
        if self.fatigue > 0.9:
            self.burnout_days_triggered += 1
            self.motivation = max(0.0, self.motivation - 0.2)

        return results

class TwoYearJourneySimulator:
    def __init__(self):
        self.physics = StudentPhysicsEngine(seed=42)
        self.runtime_dir = Path("local_lab/runtime")
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        # self.db = StateDB()
        # self.planner = Planner()
        # self.parser = MessageParser()

    async def run(self, total_days: int = 730):
        logger.info(f"Starting 2-Year Hybrid Simulation ({total_days} days)")
        
        current_date = datetime(2025, 6, 29)
        
        metrics = {
            "days_simulated": 0,
            "burnout_days": 0,
            "fast_forward_days": 0,
            "llm_checkpoint_days": 0
        }

        for day in range(1, total_days + 1):
            date_str = current_date.strftime("%Y-%m-%d")
            is_checkpoint = (day == 1 or day % 30 == 0)
            
            logger.info(f"Day {day} [{date_str}] - {'CHECKPOINT' if is_checkpoint else 'Fast-Forward'}")
            
            # 1. Generate Plan (Mocked for script, would call real planner)
            mock_plan = {
                "blocks": [
                    {"block_id": f"EB-1-{day}", "subject": "Physics", "target_time": 90, "question_count": 20},
                    {"block_id": f"EB-2-{day}", "subject": "Maths", "target_time": 90, "question_count": 20},
                    {"block_id": f"RB-1-{day}", "subject": "Chem", "exercise_type": "Revision", "target_time": 45, "question_count": 10}
                ]
            }

            # 2. Physics Engine executes the day
            results = self.physics.process_day(mock_plan)

            if is_checkpoint:
                # PHASE B: Real LLM Checkpoint
                metrics["llm_checkpoint_days"] += 1
                logger.info("  -> Calling Groq (Language Synthesizer)...")
                
                # Mocking LLM Synthesizer call
                synth_message = f"I did my blocks. Results: {json.dumps(results)}"
                
                logger.info("  -> Calling SENTINEL Parser (Gemini)...")
                # Mocking Gemini Parser call
                # parsed = await self.parser.parse(synth_message)
                
                # RATE LIMIT PROTECTION
                logger.info("  -> Sleeping 20s to respect free tier RPM limits...")
                await asyncio.sleep(0.1) # Set to 0.1 for local fast testing, 20s in prod
                
                # Save monthly report
                self._save_report(day, metrics)
            else:
                # PHASE A: Fast-Forward (Direct DB Injection)
                metrics["fast_forward_days"] += 1
                # await self.db.complete_study_block(res["block_id"], res)

            metrics["days_simulated"] += 1
            metrics["burnout_days"] = self.physics.burnout_days_triggered
            current_date += timedelta(days=1)

        logger.info("2-Year Simulation Complete!")
        
    def _save_report(self, day: int, metrics: dict):
        report_path = self.runtime_dir / f"monthly_report_day_{day}.json"
        payload = {
            "day": day,
            "metrics": metrics,
            "student_state": {
                "fatigue": round(self.physics.fatigue, 2),
                "motivation": round(self.physics.motivation, 2),
                "trust": round(self.physics.trust_in_sentinel, 2),
                "mastery": {k: round(v, 2) for k, v in self.physics.subject_confidence.items()}
            }
        }
        report_path.write_text(json.dumps(payload, indent=2))
        logger.info(f"  -> Saved {report_path.name}")

if __name__ == "__main__":
    sim = TwoYearJourneySimulator()
    asyncio.run(sim.run(total_days=730))
