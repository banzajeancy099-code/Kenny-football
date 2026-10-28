"""Couche 6 — Momentum (via H2H)."""
from src.layers.base import BaseLayer, LayerResult


class MomentumLayer(BaseLayer):
    id = 6
    name = "momentum"

    def __init__(self, bzzoiro):
        self.c = bzzoiro

    def compute(self, match: dict, context: dict) -> LayerResult:
        h2h = (match.get("head_to_head") or {})
        home_wins = h2h.get("home_wins", 0)
        away_wins = h2h.get("away_wins", 0)
        draws = h2h.get("draws", 0)
        total = home_wins + away_wins + draws

        if total == 0:
            return self.fallback(match, "no_h2h")

        # Avantage home si plus de victoires
        home_ratio = home_wins / total
        score = 5.0 + (home_ratio - 0.5) * 8
        score = max(0.0, min(10.0, score))

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=score, confidence=0.7,
            features={
                "h2h_home_wins": home_wins,
                "h2h_away_wins": away_wins,
                "h2h_draws": draws,
            },
        )
