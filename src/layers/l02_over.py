"""Couche 2 — Potentiel Over."""
from src.layers.base import BaseLayer, LayerResult


class OverLayer(BaseLayer):
    id = 2
    name = "potentiel_over"

    def __init__(self, bzzoiro, league_over_rates: dict):
        self.c = bzzoiro
        self.league_rates = league_rates = league_over_rates

    def compute(self, match: dict, context: dict) -> LayerResult:
        h2h = (match.get("head_to_head") or {})
        avg_goals = h2h.get("avg_total_goals", 2.5)

        league = str(match.get("league_id", "default"))
        league_over = self.league_rates.get(league, 0.5)

        # Score : combine avg H2H + taux Over de la ligue
        score = (avg_goals / 4.0) * 6.0 + league_over * 4.0
        score = max(0.0, min(10.0, score))

        confidence = 0.9 if h2h.get("total_matches", 0) >= 3 else 0.5

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=score, confidence=confidence,
            features={
                "h2h_avg_goals": avg_goals,
                "league_over_rate": league_over,
            },
        )
