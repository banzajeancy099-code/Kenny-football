# src/layers/l26_defense_x_defense.py — Couche 26 : Défense × Défense (BTTS)
from datetime import datetime
from src.layers.base import BaseLayer, LayerResult


class DefenseXDefenseLayer(BaseLayer):
    id = 26
    name = "Défense × Défense (BTTS)"

    def __init__(self, bzzoiro):
        self.bzzoiro = bzzoiro

    def _get_form(self, team_id):
        if not team_id:
            return None
        try:
            return self.bzzoiro.request("GET", f"/teams/{team_id}/form/")
        except Exception:
            return None

    def _score_leakiness(self, form):
        """Score 0-10 de la perméabilité défensive (encaisser des buts)."""
        if not form:
            return None
        overall = form.get("overall") or {}
        matches = overall.get("matches") or 0
        if matches < 3:
            return None

        ga = overall.get("goals_against") or 0
        ga_avg = ga / matches

        # Buts encaissés moyens : 0 → 0, 2.0+ → 10
        # 1 but encaissé/match = 5/10 (moyen)
        score = min(10.0, (ga_avg / 2.0) * 10)
        return {"score": score, "ga_avg": round(ga_avg, 2), "matches": matches}

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

        home_def = self._score_leakiness(home_form)
        away_def = self._score_leakiness(away_form)

        if home_def is None or away_def is None:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.1,
                warnings=["forme indisponible"],
            )

        # Score final : moyenne (les 2 défenses doivent être perméables)
        home_s = home_def["score"]
        away_s = away_def["score"]

        # Si une équipe a une défense de fer, le BTTS est improbable
        min_leak = min(home_s, away_s)
        avg_leak = (home_s + away_s) / 2

        final_score = min_leak * 0.6 + avg_leak * 0.4

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=round(final_score, 2),
            confidence=0.8,
            raw={
                "home_def": home_def,
                "away_def": away_def,
                "min_leak": round(min_leak, 2),
            },
            features={
                "home_ga_avg": home_def["ga_avg"],
                "away_ga_avg": away_def["ga_avg"],
                "min_leak": round(min_leak, 2),
            },
            warnings=[],
        )
