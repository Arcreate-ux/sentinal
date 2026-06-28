import logging
from typing import Any
from local_lab.core.interfaces import MemoryModel, TrustModel, FatigueModel
from local_lab.models.profiles import PersonalityDNA
from local_lab.models.state import StudentState

logger = logging.getLogger("academic_digital_twin.student")

def execute_plan(
    state: StudentState, 
    dna: PersonalityDNA, 
    memory: MemoryModel, 
    trust: TrustModel, 
    fatigue: FatigueModel, 
    blocks: list[dict[str, Any]], 
    event_penalty: float, 
    active_concepts: list[str], 
    rng,
    current_day: int,
    get_concept_load
) -> list[dict[str, Any]]:
    
    obedience = dna.discipline * (0.5 + state.trust.trust) * (0.6 + state.motivation) * (1.0 - state.fatigue.fatigue * 0.6) * (1.0 - state.fatigue.anxiety * 0.4)
    obedience = max(0.05, min(0.95, obedience))
    
    hours_spent = 0.0
    results = []
    available_hours = state.daily_hours_capacity - event_penalty
    
    for block in blocks:
        if rng.random() > obedience:
            if rng.random() < dna.risk_taking:
                concept = rng.choice(active_concepts) if active_concepts else "Vectors"
                task_type = rng.choice(["pyq", "theory", "revision"])
                duration = max(0.5, min(3.0, float(block.get("duration", 1.0))))
                is_revision = (task_type == "revision")
            else:
                continue
        else:
            concept = str(block.get("concept", active_concepts[-1] if active_concepts else "Vectors"))
            duration = max(0.25, min(4.0, float(block.get("duration", 1.0))))
            task_type = str(block.get("task_type", "homework"))
            is_revision = bool(block.get("is_revision", False))

        if hours_spent + duration > available_hours * (1.0 - state.fatigue.fatigue):
            break
            
        hours_spent += duration
        accuracy = rng.uniform(0.3, 0.95)
        used_faculty = accuracy < 0.4
        
        load = get_concept_load(concept)
        memory.update_learning(state.memory, concept, is_revision, used_faculty, accuracy, duration, dna.aptitude, load, current_day)
        
        results.append({
            "concept": concept,
            "task_type": task_type,
            "duration": duration,
            "accuracy": accuracy,
            "is_revision": is_revision
        })
        
    completed_ratio = len(results) / max(1, len(blocks))
    scheduled_hours = sum(max(0.25, min(4.0, float(b.get("duration", 1.0)))) for b in blocks)
    
    trust.update(state.trust, scheduled_hours, state.daily_hours_capacity, state.fatigue.fatigue, completed_ratio)
    fatigue.update(state.fatigue, hours_spent, state.daily_hours_capacity, event_penalty)
    
    if hours_spent > 0:
        state.self_belief = min(1.0, state.self_belief + 0.018 * completed_ratio)
    else:
        state.self_belief = max(0.0, state.self_belief - 0.015)
        
    return results
