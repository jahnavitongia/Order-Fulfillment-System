"""Courier definitions and the contract-net style bidding used by the Shipping agent."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Courier:
    name: str
    base: float
    per_kg: float
    per_km: float
    max_kg: float
    max_km: float
    eta_days: int

    def eligibility_problem(self, weight_kg: float, distance_km: float):
        if weight_kg > self.max_kg:
            return f"weight {weight_kg}kg > limit {self.max_kg}kg"
        if distance_km > self.max_km:
            return f"distance {distance_km}km > limit {self.max_km}km"
        return None

    def quote(self, weight_kg: float, distance_km: float) -> float:
        return round(self.base + self.per_kg * weight_kg + self.per_km * distance_km, 2)


# BudgetPost's formula is the original jury-1 formula: 2.5*kg + 0.05*km
COURIERS = [
    Courier("BudgetPost",   base=0.0, per_kg=2.5, per_km=0.05, max_kg=30, max_km=500,  eta_days=5),
    Courier("SpeedyExpress", base=5.0, per_kg=4.0, per_km=0.10, max_kg=50, max_km=2000, eta_days=1),
    Courier("EcoShip",      base=1.5, per_kg=2.0, per_km=0.08, max_kg=15, max_km=300,  eta_days=4),
    Courier("LocalBike",    base=0.0, per_kg=1.5, per_km=0.20, max_kg=5,  max_km=20,   eta_days=1),
]
