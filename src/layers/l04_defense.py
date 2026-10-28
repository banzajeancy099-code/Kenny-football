"""Couche 4 — Défense réelle (via H2H)."""
from src.layers.base import BaseLayer, LayerResult


class DefenseLayer(BaseLayer):
    id = 4
    name = "defense_reelle"

    def __init__(self, bzzoiro):
        self.c = bzzoiro

    def compute(self, match: dict, context: dict) -> LayerResult:
        h2h = (match.get("head_to_head") or {})
        total_matches = h2h.get("total_matches", 0)
        home_goals = h2h.get("home_goals", 0)
        away_goals = h2h.get("away_goals", 0)

        if total_matches == 0:
            return self.fallback(match, "no_h2h")

        # Moyenne buts par match
        avg_goals = (home_goals + away_goals) / total_matches

        # Score : plus la moyenne est haute, plus le score est élevé (Over)
        if avg_goals >= 3.0:
            score = 9.0
        elif avg_goals >= 2.5:
            score = 7.5
        elif avg_goals >= 2.0:
            score = 5.5
        else:
            score = 3.0

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=score, confidence=0.75,
            features={
                "h2h_avg_goals": round(avg_goals, 2),
                "h2h_matches": total_matches,
            },
        )
