# src/layers/l24_standings_pressure.py — Couche 24 : Pression classement
from datetime import datetime
from src.layers.base import BaseLayer, LayerResult


class StandingsPressureLayer(BaseLayer):
    id = 24
    name = "Pression classement"

    def __init__(self):
        pass

    def compute(self, match, context):
        round_num = match.get("round_number")
        stage = str(match.get("stage") or match.get("stage_name") or "").lower()

        # Fin de saison = pression
        is_end_of_season = (
            any(k in stage for k in ("final", "semifinals", "quarterfinals", "playoffs", "relegation"))
            or (isinstance(round_num, int) and round_num >= 30)
        )

        # Coupe / play-off = enjeu important
        is_knockout = any(k in stage for k in ("final", "semifinals", "quarterfinals", "round-of-16", "playoffs"))

        score = 5.0
        reasons = []

        if is_knockout:
            # Phase éliminatoire = prudence, moins de buts en moyenne
            score -= 0.5
            reasons.append(f"phase éliminatoire ({stage}) → prudence")
        elif is_end_of_season:
            # Fin de saison = matchs à enjeu, plus de buts (désespoir)
            score += 0.3
            reasons.append(f"fin de saison (tour {round_num}) → enjeu")

        score = max(0.0, min(10.0, score))

        return LayerResult(
            layer_id=self.id,
            layer_name=self.name,
            score=score,
            confidence=0.4,
            raw={
                "round_number": round_num,
                "stage": stage,
                "is_end_of_season": is_end_of_season,
                "is_knockout": is_knockout,
                "reasons": reasons,
            },
            features={
                "round_number": round_num,
                "is_end_of_season": is_end_of_season,
                "is_knockout": is_knockout,
            },
            warnings=[],
        )
