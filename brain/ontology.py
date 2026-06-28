"""
SENTINEL — Seed Ontology (brain/ontology.py)

A lightweight static seed ontology for the core JEE structure.
This provides the AI extractor with deterministic anchors to attach dynamic concepts to.
"Questions are evidence; concepts are memory; skills are guidance."
"""

SEED_ONTOLOGY = {
    "Physics": {
        "Mechanics": {
            "skills": [
                "Kinematics Modeling",
                "Constraint Modeling",
                "Force Analysis",
                "Energy Conservation",
                "Momentum Conservation",
                "Rotational Dynamics"
            ],
            "core_concepts": [
                "Relative Motion",
                "Wedge Constraint",
                "String Constraint",
                "FBD Construction",
                "Center of Mass",
                "Variable Acceleration",
                "Work Energy Theorem",
                "Rolling without Slipping"
            ]
        },
        "Electromagnetism": {
            "skills": [
                "Field Calculation",
                "Circuit Analysis",
                "Flux Geometry"
            ],
            "core_concepts": [
                "Gauss Law",
                "Kirchhoff's Laws",
                "RC Circuits",
                "Ampere's Law",
                "Faraday's Law"
            ]
        }
    },
    "Chemistry": {
        "Physical Chemistry": {
            "skills": [
                "Stoichiometric Setup",
                "Equilibrium Analysis",
                "Thermodynamic State Tracking"
            ],
            "core_concepts": [
                "Mole Concept",
                "Le Chatelier's Principle",
                "Gibbs Free Energy",
                "Nernst Equation",
                "Rate Law"
            ]
        }
    },
    "Mathematics": {
        "Calculus": {
            "skills": [
                "Limit Evaluation",
                "Derivative Tracking",
                "Integral Substitution"
            ],
            "core_concepts": [
                "L'Hopital's Rule",
                "Chain Rule",
                "Integration by Parts",
                "Area under Curve",
                "Differential Equations"
            ]
        },
        "Algebra": {
            "skills": [
                "Root Analysis",
                "Sequence Modeling",
                "Combinatorial Counting"
            ],
            "core_concepts": [
                "Quadratic Roots",
                "Arithmetic Progression",
                "Geometric Progression",
                "Binomial Theorem",
                "Permutations"
            ]
        }
    }
}

def get_core_concepts(subject: str) -> list[str]:
    """Return a flat list of core concepts for a subject to ground the AI."""
    subject_data = SEED_ONTOLOGY.get(subject, {})
    concepts = []
    for category_data in subject_data.values():
        concepts.extend(category_data.get("core_concepts", []))
    return concepts

def get_core_skills(subject: str) -> list[str]:
    """Return a flat list of core skills for a subject."""
    subject_data = SEED_ONTOLOGY.get(subject, {})
    skills = []
    for category_data in subject_data.values():
        skills.extend(category_data.get("skills", []))
    return skills
