# src/layers/l46_under_market.py — Couche 46 : Under Market Consensus
"""
Compare la prédiction Under au marché.

Si le marché dit fortement Over (cote Under > 2.20), la couche retourne
un score bas (rejet du pari Under).

Sinon, elle retourne un score neutre (5.0) ou élevé (Under probable).
"""
from src.layers.base import BaseLayer, LayerResult


class UnderMarketLayer(BaseLayer):
    id = 46
    name = "Under Market Consensus"

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
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.0,
                warnings=["match_id manquant"],
            )

        cotes = self._get_odds(match_id)
        cote_over = cotes.get("over_25_goals")
        cote_under = cotes.get("under_25_goals")

        if cote_over is None or cote_under is None:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.0,
                warnings=["cotes indisponibles"],
            )

        # Score basé sur l'orientation du marché vers Under
        # Si cote Under < 1.60 → marché très orienté Under → score élevé (favorise Under)
        # Si cote Under > 2.20 → marché très orienté Over → score bas (rejette Under)
        if cote_under < 1.60:
            # Marché très orienté Under
            score = 7.5
            reasons = [f"marché orienté Under (cote {cote_under})"]
        elif cote_under < 1.80:
            # Marché orienté Under
            score = 6.0
            reasons = [f"marché plutôt Under (cote {cote_under})"]
        elif cote_under > 2.20:
            # Marché très orienté Over
            score = 2.5
            reasons = [f"marché orienté Over (cote Under {cote_under})"]
        elif cote_under > 2.00:
            # Marché orienté Over
            score = 3.5
            reasons = [f"marché plutôt Over (cote Under {cote_under})"]
        else:
            # Marché équilibré
            score = 5.0
            reasons = [f"marché équilibré (Over {cote_over}, Under {cote_under})"]

        # Confidence basée sur l'écart
        ecart = abs(cote_over - cote_under)
        if ecart > 0.50:
            confidence = 0.85
        elif ecart > 0.30:
            confidence = 0.70
        else:
            confidence = 0.50

        return LayerResult(
            layer_id=self.id,
            layer_name=self.name,
            score=round(score, 2),
            confidence=confidence,
            raw={
                "cote_over": cote_over,
                "cote_under": cote_under,
                "reasons": reasons,
            },
            features={
                "cote_over": cote_over,
                "cote_under": cote_under,
            },
            warnings=reasons,
        )
