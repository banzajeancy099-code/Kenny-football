# src/layers/l27_balance.py — Couche 27 : Équilibre du match (BTTS)
from datetime import datetime
from src.layers.base import BaseLayer, LayerResult


class BalanceLayer(BaseLayer):
    id = 27
    name = "Équilibre du match (BTTS)"

    def __init__(self, bzzoiro):
        self.bzzoiro = bzzoiro

    def _get_form(self, team_id):
        if not team_id:
            return None
        try:
            return self.bzzoiro.request("GET", f"/teams/{team_id}/form/")
        except Exception:
            return None

    def _team_strength(self, form):
        if not form:
            return None
        overall = form.get("overall") or {}
        matches = overall.get("matches") or 0
        if matches < 3:
            return None
        gf_avg = (overall.get("goals_for") or 0) / matches
        return min(10.0, (gf_avg / 2.5) * 10)

    def compute(self, match, context):
        home_id = match.get("home_team_id")
        away_id = match.get("away_team_id")

        if not home_id or not away_id:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.0,
                warnings=["team_id manquant"],
            )

        home_str = self._team_strength(self._get_form(home_id))
        away_str = self._team_strength(self._get_form(away_id))

        if home_str is None or away_str is None:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.1,
                warnings=["forme indisponible"],
            )

        ecart = abs(home_str - away_str)

        if ecart < 2:
            score = 8.0
        elif ecart < 3:
            score = 6.5
        elif ecart < 4:
            score = 5.0
        elif ecart < 5:
            score = 3.5
        else:
            score = 2.0

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=round(score, 2),
            confidence=0.7,
            raw={"home": round(home_str, 2), "away": round(away_str, 2), "ecart": round(ecart, 2)},
            features={"ecart": round(ecart, 2)},
            warnings=[],
        )
