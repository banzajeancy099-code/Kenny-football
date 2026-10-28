# src/layers/l08_context.py — Couche 8 : Contexte (derby / terrain neutre)
from datetime import datetime
from src.layers.base import BaseLayer, LayerResult


class ContextLayer(BaseLayer):
    id = 8
    name = "Contexte (derby / neutre)"

    def __init__(self):
        pass

    def compute(self, match, context):
        is_derby = bool(match.get("is_local_derby"))
        is_neutral = bool(match.get("is_neutral_ground"))

        score = 5.0
        reasons = []

        if is_derby:
            score += 1.5
            reasons.append("derby local (motivation +)")

        if is_neutral:
            score -= 0.5
            reasons.append("terrain neutre (pas d'avantage domicile)")

        score = max(0.0, min(10.0, score))

        return LayerResult(
            layer_id=self.id,
            layer_name=self.name,
            score=score,
            confidence=0.6,
            raw={"is_derby": is_derby, "is_neutral": is_neutral, "reasons": reasons},
            features={"is_derby": is_derby, "is_neutral": is_neutral},
            warnings=[],
        )
