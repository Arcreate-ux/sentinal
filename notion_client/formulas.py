"""
SENTINEL — Notion Formulas (notion_client/formulas.py)
Core metrics calculation: Cognitive Yield (CY) and Theory Yield (TY).
"""
from __future__ import annotations

from sentinel.config import T_Q_TABLE


def _get_t_q(exercise_type: str, subject: str) -> float:
    subj_data = T_Q_TABLE.get(exercise_type, T_Q_TABLE.get("JMYL", {}))
    return subj_data.get(subject, subj_data.get("_default", 4.0))


def cognitive_yield(T: float, A: int, C: int, exercise_type: str, subject: str) -> float:
    """
    Calculate Cognitive Yield (CY) for problem-solving blocks.
    Strictly aligns with the Notion database formula.
    """
    if A == 0 or T <= 0:
        return 0.0
        
    t_q = _get_t_q(exercise_type, subject)
    T_target = A * t_q
    
    # Calculate accuracy (capped at 1.0)
    Accuracy = 1.0 if C > A else (C / A)
    
    # Calculate velocity (capped at 1.5)
    Velocity = 1.5 if (T_target / T) > 1.5 else (T_target / T)
    
    # Exponential accuracy penalty per Notion formula
    cy = 1.666 * T_target * (Accuracy ** (10 / t_q)) * Velocity
    
    return round(cy)


def theory_yield(T: float, A: int, C: int, exercise_type: str, subject: str) -> float:
    """
    Calculate Theory Yield (TY) for theory/reading blocks.
    """
    if T <= 0:
        return 0.0
    
    # If there were questions attempted during theory, use accuracy to scale TY
    if A > 0:
        accuracy = C / A
        return round(T * (0.5 + 0.5 * accuracy), 1)
        
    # Pure theory reading
    return round(T * 0.8, 1)
