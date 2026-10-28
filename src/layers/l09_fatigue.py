"""Couche 9 — Fatigue (via travel_distance_km + weather)."""
from src.layers.base import BaseLayer, LayerResult


class FatigueLayer(BaseLayer):
    id = 9
    name = "fatigue"

    def __init__(self, bzzoiro):
        self.c = bzzoiro

    def compute(self, match: dict, context: dict) -> LayerResult:
        travel = match.get("travel_distance_km") or 0
        weather = match.get("weather") or {}
        temp = weather.get("temperature_c", 20)
        wind = weather.get("wind_speed", 0)

        # Score fatigue (0=frais, 10=épuisé)
        # Plus le voyage est long, plus la fatigue est grande
        if travel > 1000:
            fatigue = 8.0
        elif travel > 500:
            fatigue = 6.0
        elif travel > 200:
            fatigue = 4.0
        else:
            fatigue = 2.0

        # Météo extrême = fatigue supplémentaire
        if temp > 30 or temp < 5:
            fatigue += 1.0
        if wind > 8:
            fatigue += 0.5

        # Score final : l'équipe qui voyage bcp a un désavantage
        # Ici, on suppose que l'équipe EXTÉRIEUR voyage
        score = 10.0 - fatigue
        score = max(0.0, min(10.0, score))

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=score, confidence=0.7,
            features={
                "travel_km": travel,
                "temperature_c": temp,
                "wind_speed": wind,
                "fatigue_score": fatigue,
            },
        )
