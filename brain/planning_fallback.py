"""
SENTINEL — Fallback Planner (brain/planning_fallback.py)
Generates a deterministic study plan if the AI API fails, using the ProtocolSnapshot.
"""

from typing import Any

from sentinel.brain.contracts import ExecutionPlan, ExecutionBlock, PlanningPrediction
from sentinel.brain.protocol.snapshot import ProtocolSnapshot

class FallbackPlanner:
    def generate_fallback_plan(self, today: str, day_type: str, homework: list, protocol: ProtocolSnapshot) -> ExecutionPlan:
        """
        Dynamically builds a compliant fallback study schedule based on available homework
        and the immutable ProtocolSnapshot.
        """
        blocks = []
        cy_target = 60 # Assume each fallback block yields roughly 60 CY for simplicity
        
        # Use defaults from protocol if available, otherwise fallback to hardcoded
        block_labels = protocol.block_types[:4] if len(protocol.block_types) >= 4 else ["EB-1", "EB-2", "EB-3", "RB"]
        
        # Ensure we have at least 4 subjects to match blocks (wrap around if needed)
        subjects = protocol.subjects
        if not subjects:
            subjects = ["Physics", "Chem", "Maths"]
        rotation = [subjects[i % len(subjects)] for i in range(4)]
        
        for i, label in enumerate(block_labels):
            # Pick from homework if available
            if i < len(homework):
                hw = homework[i]
                subject = self._get_homework_value(hw, "subject", "Physics")
                chapter = self._get_homework_value(hw, "chapter", "?")
                ex_type = self._get_homework_value(hw, "exercise_type", "Ex 1A")
                q_count = int(self._get_homework_value(hw, "questions", 0) or 0)
                question_range = self._get_homework_value(hw, "range", None)
                questions = question_range or (f"{q_count}Q" if q_count else "")
                block_type = "homework"
            else:
                subject = rotation[i]
                chapter = "Protocol"
                ex_type = "Ex 1A" if label == "RB" else "Ex 2A"
                q_count = 15 if subject != "Chem" else 20
                questions = f"{q_count}Q"
                block_type = "revision" if label == "RB" else "homework"
                
            # Lookup target time dynamically from ProtocolSnapshot
            tq_ex = protocol.t_q_table.get(ex_type, {})
            tq = tq_ex.get(subject, tq_ex.get("_default", 4.0))
            target_time = int(q_count * tq)
            
            blocks.append(ExecutionBlock(
                block_label=label,
                subject=subject,
                chapter=chapter,
                exercise=ex_type,
                exercise_type=ex_type,
                questions=questions,
                block_type=block_type,
                estimated_minutes=target_time,
                expected_questions=q_count,
                question_count=q_count,
                target_time=target_time,
                expected_cy=cy_target
            ))
            
        total_cy = sum(b.expected_cy for b in blocks)
        total_time = sum(b.target_time for b in blocks)
        
        return ExecutionPlan(
            date=today,
            day_type=day_type,
            blocks=blocks,
            total_expected_cy=total_cy,
            total_expected_time=total_time,
            prediction=PlanningPrediction(
                expected_cy=total_cy,
                expected_duration=total_time,
                expected_completion=0.9,
                expected_fatigue=None,
            ),
            is_fallback=True
        )

    @staticmethod
    def _get_homework_value(homework: Any, key: str, default: Any = None) -> Any:
        if isinstance(homework, dict):
            return homework.get(key, default)
        return getattr(homework, key, default)
