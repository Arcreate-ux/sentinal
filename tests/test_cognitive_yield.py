import pytest
from sentinel.notion_client.formulas import cognitive_yield

def test_cy_exponential_penalty():
    # If a student attempts 10 questions and gets 10 correct
    # Accuracy = 1.0
    # T_target = 10 * 4.0 = 40.0
    # Velocity = 1.0 (assuming they took exactly 40 mins)
    # cy = 1.666 * 40 * (1.0 ** (10/4)) * 1.0 = 1.666 * 40 = 66.64 -> 67
    assert cognitive_yield(T=40, A=10, C=10, exercise_type="JMYL", subject="Physics") == 67

def test_cy_90_percent_accuracy():
    # 90% accuracy: 10 attempted, 9 correct
    # Accuracy = 0.9
    # T_target = 40
    # Penalty: 0.9 ** 2.5 = 0.768
    # cy = 1.666 * 40 * 0.768 * 1.0 = 51.17 -> 51
    assert cognitive_yield(T=40, A=10, C=9, exercise_type="JMYL", subject="Physics") == 51
    
def test_cy_low_accuracy():
    # 50% accuracy
    # Accuracy = 0.5
    # Penalty: 0.5 ** 2.5 = 0.176
    # cy = 1.666 * 40 * 0.176 * 1.0 = 11.7 -> 12
    assert cognitive_yield(T=40, A=10, C=5, exercise_type="JMYL", subject="Physics") == 12

def test_cy_velocity_cap():
    # Student goes super fast (T = 10, T_target = 40)
    # Velocity = 40 / 10 = 4.0 -> Capped at 1.5
    # cy = 1.666 * 40 * (1.0) * 1.5 = 99.96 -> 100
    assert cognitive_yield(T=10, A=10, C=10, exercise_type="JMYL", subject="Physics") == 100
