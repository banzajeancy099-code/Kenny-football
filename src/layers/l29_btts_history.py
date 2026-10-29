# src/layers/l29_btts_history.py — Couche 29 : Historique BTTS
from datetime import datetime
from src.layers.base import BaseLayer, LayerResult


class BTTSHistoryLayer(BaseLayer):
    id = 29
    name = "Historique BTTS"

    def __init__(self, bzzoiro):
        self.bzzoiro = bzzoiro

    def _get_form(self, team_id):
        if not team_id:
            return None
        try:
            return self.bzzoiro.request("GET", f"/teams/{team_id}/form/")
        except Exception:
            return None

    def _compute_btts_rate(self, form):
        """Taux de BTTS dans les 5 derniers matchs."""
        if not form:
            return None
        recent = form.get("recent_matches") or []
        if not recent:
            return None

        # Prend les 5 derniers
        recent = recent[:5]
        btts_count = 0
        for m in recent:
            hs = m.get("home_score")
            as_ = m.get("away_score")
            if hs is not None and as_ is not None:
                if int(hs) > 0 and int(as_) > 0:
                    btts_count += 1

        return {
            "btts_count": btts_count,
            "total": len(recent),
            "rate": btts_count / len(recent) if recent else 0,
        }

    def compute(self, match, context):
        home_id = match.get("home_team_id")
        away_id = match.get("away_team_id")

        if not home_id or not away_id:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.0,
                warnings=["team_id manquant"],
            )

        home_form = self._get_form(home_id)
        away_form = self._get_form(away_id)

        home_btts = self._compute_btts_rate(home_form)
        away_btts = self._compute_btts_rate(away_form)

        if home_btts is None or away_btts is None:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.1,
                warnings=["historique indisponible"],
            )

        # Moyenne des 2 taux
        avg_rate = (home_btts["rate"] + away_btts["rate"]) / 2

        # Score 0-10 : 0% → 0, 100% → 10
        score = min(10.0, avg_rate * 10)

        # Bonus si les 2 sont ≥ 60%
        if home_btts["rate"] >= 0.6 and away_btts["rate"] >= 0.6:
            score = min(10.0, score + 1.0)

        # Pénalité si une équipe est < 40%
        if home_btts["rate"] < 0.4 or away_btts["rate"] < 0.4:
            score = max(0.0, score - 1.0)

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=round(score, 2),
            confidence=0.7,
            raw={
                "home_btts": home_btts,
                "away_btts": away_btts,
                "avg_rate": round(avg_rate, 2),
            },
            features={
                "home_btts_rate": round(home_btts["rate"], 2),
                "away_btts_rate": round(away_btts["rate"], 2),
                "avg_rate": round(avg_rate, 2),
            },
            warnings=[],
        )
