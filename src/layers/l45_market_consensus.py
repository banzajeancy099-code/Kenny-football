# src/layers/l45_market_consensus.py — Couche 45 : Market Consensus
from src.layers.base import BaseLayer, LayerResult


class MarketConsensusLayer(BaseLayer):
    id = 45
    name = "Market Consensus"

    def __init__(self, bzzoiro):
        self.bzzoiro = bzzoiro
        self._cache = {}

    def _get_odds(self, match_id):
        if match_id in self._cache:
            return self._cache[match_id]
        try:
            odds = self.bzzoiro.get_event_odds(match_id)
            cotes = odds.get("odds", {}) if isinstance(odds, dict) else {}
        except Exception:
            cotes = {}
        self._cache[match_id] = cotes
        return cotes

    def compute(self, match, context):
        match_id = match.get("id") or match.get("event_id")
        if not match_id:
            return LayerResult(layer_id=self.id, layer_name=self.name, score=5.0, confidence=0.0, warnings=["match_id manquant"])

        cotes = self._get_odds(match_id)
        cote_over = cotes.get("over_25_goals")
        cote_under = cotes.get("under_25_goals")

        if cote_over is None or cote_under is None:
            return LayerResult(layer_id=self.id, layer_name=self.name, score=5.0, confidence=0.0, warnings=["cotes indisponibles"])

        if cote_over < 1.50:
            score = 7.5
        elif cote_over < 1.70:
            score = 6.0
        elif cote_over > 2.20:
            score = 2.5
        elif cote_over > 2.00:
            score = 3.5
        else:
            score = 5.0

        ecart = abs(cote_over - cote_under)
        confidence = 0.85 if ecart > 0.50 else (0.70 if ecart > 0.30 else 0.50)

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=round(score, 2), confidence=confidence,
            raw={"cote_over": cote_over, "cote_under": cote_under},
        )
