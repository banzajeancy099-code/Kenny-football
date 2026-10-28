# src/layers/l05_lineups.py — Couche 5 : Joueurs forts / lineups
from datetime import datetime
from src.layers.base import BaseLayer, LayerResult


class LineupsLayer(BaseLayer):
    id = 5
    name = "Joueurs forts / lineups"

    def __init__(self):
        pass

    def compute(self, match, context):
        match_id = match.get("id") or match.get("event_id")

        if not match_id:
            return LayerResult(
                layer_id=self.id,
                layer_name=self.name,
                score=5.0,
                confidence=0.0,
                raw={"reason": "pas de match_id"},
                features={},
                warnings=[],
            )

        # TODO : appel /events/{id}/lineups/ + analyse buteurs
        # Pour l'instant : neutre avec confiance 0 (pas de données lineups)
        return LayerResult(
            layer_id=self.id,
            layer_name=self.name,
            score=5.0,
            confidence=0.0,
            raw={"match_id": match_id, "reason": "lineups non intégrés"},
            features={"match_id": match_id},
            warnings=["lineups pas encore intégrés"],
        )
