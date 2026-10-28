"""Couche 1 — Duel de force (basée sur H2H)."""
from src.layers.base import BaseLayer, LayerResult


class StrengthLayer(BaseLayer):
    id = 1
    name = "strength"

    def __init__(self, bzzoiro):
        self.c = bzzoiro

    def compute(self, match: dict, context: dict) -> LayerResult:
        h2h = (match.get("head_to_head") or {})
        home_goals = h2h.get("home_goals", 0)
        away_goals = h2h.get("away_goals", 0)
        total = home_goals + away_goals

        if total == 0:
            return self.fallback(match, "no_h2h_goals")

        # Avantage home si home_goals > away_goals
        ratio = home_goals / total
        score = 5.0 + (ratio - 0.5) * 8
        score = max(0.0, min(10.0, score))

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=score, confidence=0.7,
            features={
                "h2h_home_goals": home_goals,
                "h2h_away_goals": away_goals,
            },
        )
