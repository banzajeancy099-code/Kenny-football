# src/layers/l03_h2h.py — Couche 3 : H2H (calibrée)
from datetime import datetime
from src.layers.base import BaseLayer, LayerResult


class H2HLayer(BaseLayer):
    id = 3
    name = "H2H"

    def __init__(self, api_football=None):
        self.api_football = api_football

    def compute(self, match, context):
        h2h = match.get("head_to_head") or {}
        avg_goals = h2h.get("avg_total_goals")
        total_matches = h2h.get("total_matches", 0)

        if not avg_goals or total_matches < 3:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.0,
                warnings=["H2H insuffisant"],
            )

        # Calibration plus douce : 2.5 buts = neutre (5.0)
        # 3.5+ = Over probable (7.5+)
        # 1.5- = Under probable (2.5-)
        if avg_goals >= 4.0:
            score = 9.0
        elif avg_goals >= 3.5:
            score = 8.0
        elif avg_goals >= 3.0:
            score = 7.0
        elif avg_goals >= 2.5:
            score = 5.5  # ← était 5.0, maintenant 5.5 (neutre-léger Over)
        elif avg_goals >= 2.0:
            score = 4.0
        elif avg_goals >= 1.5:
            score = 3.0
        else:
            score = 1.5

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=round(score, 2),
            confidence=0.75,
            raw={
                "avg_total_goals": round(avg_goals, 2),
                "total_matches": total_matches,
            },
            features={"avg_goals": avg_goals},
            warnings=[],
        )
