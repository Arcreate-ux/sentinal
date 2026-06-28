import random
from local_lab.models.profiles import PersonalityDNA, StudentAptitude

class PersonalityGenerator:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)

    def generate_population(self, size: int) -> list[PersonalityDNA]:
        population = []
        for _ in range(size):
            aptitude = StudentAptitude(
                visualization=self.rng.uniform(0.2, 0.95),
                memory=self.rng.uniform(0.3, 0.9),
                calculation=self.rng.uniform(0.4, 0.9),
                pattern_recognition=self.rng.uniform(0.2, 0.95),
                speed=self.rng.uniform(0.3, 0.9),
                consistency=self.rng.uniform(0.1, 0.9),
                spatial_thinking=self.rng.uniform(0.1, 0.95)
            )
            dna = PersonalityDNA(
                discipline=self.rng.uniform(0.3, 0.95),
                anxiety_base=self.rng.uniform(0.1, 0.8),
                curiosity=self.rng.uniform(0.2, 0.9),
                homework_tendency=self.rng.uniform(0.4, 0.95),
                revision_tendency=self.rng.uniform(0.2, 0.8),
                risk_taking=self.rng.uniform(0.1, 0.6),
                aptitude=aptitude
            )
            population.append(dna)
        return population
