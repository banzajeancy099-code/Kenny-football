"""Couche 3 — H2H (depuis match["head_to_head"], fallback API-Football)."""
from src.layers.base import BaseLayer, LayerResult


class H2HLayer(BaseLayer):
    id = 3
    name = "h2h"

    def __init__(self, api_football=None):
        self.af = api_football

    def compute(self, match: dict, context: dict) -> LayerResult:
        h2h = (match.get("head_to_head") or {})
        recent = h2h.get("recent_matches", [])

        if not recent:
            return self.fallback(match, "no_h2h")

        over_count = 0
        for m in recent[:5]:
            if (m.get("home_score", 0) or 0) + (m.get("away_score", 0) or 0) > 2.5:
                over_count += 1

        score = (over_count / min(5, len(recent))) * 10
        score = max(0.0, min(10.0, score))

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=score, confidence=0.85,
            features={
                "h2h_total": h2h.get("total_matches", 0),
                "h2h_over_count": over_count,
                "h2h_avg_goals": h2h.get("avg_total_goals", 0),
            },
        )
