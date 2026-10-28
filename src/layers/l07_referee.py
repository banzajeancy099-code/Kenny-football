# src/layers/l07_referee.py — Couche 7 : Arbitre
from datetime import datetime
from src.layers.base import BaseLayer, LayerResult


class RefereeLayer(BaseLayer):
    id = 7
    name = "Arbitre"

    def __init__(self):
        pass

    def compute(self, match, context):
        ref_id = match.get("referee_id")

        if not ref_id:
            # Pas d'arbitre assigné → neutre, confiance 0
            return LayerResult(
                layer_id=self.id,
                layer_name=self.name,
                score=5.0,
                confidence=0.0,
                raw={"referee_id": None, "reason": "pas d'arbitre assigné"},
                features={"referee_id": None},
                warnings=["pas d'arbitre dans /events/"],
            )

        # TODO : appel API /referees/{id}/stats/ quand disponible
        # Pour l'instant : neutre avec confiance basse
        return LayerResult(
            layer_id=self.id,
            layer_name=self.name,
            score=5.0,
            confidence=0.3,
            raw={"referee_id": ref_id, "reason": "arbitre présent, stats indisponibles"},
            features={"referee_id": ref_id},
            warnings=[],
        )
