# src/layers/l28_scorers.py — Couche 28 : Buteurs présents (BTTS)
from datetime import datetime
from src.layers.base import BaseLayer, LayerResult


class ScorersLayer(BaseLayer):
    id = 28
    name = "Buteurs présents (BTTS)"

    def __init__(self, bzzoiro):
        self.bzzoiro = bzzoiro

    def _get_form(self, team_id):
        if not team_id:
            return None
        try:
            return self.bzzoiro.request("GET", f"/teams/{team_id}/form/")
        except Exception:
            return None

    def _score_attackers(self, form):
        if not form:
            return None
        overall = form.get("overall") or {}
        matches = overall.get("matches") or 0
        if matches < 3:
            return None

        stats = overall.get("stats") or {}
        big_chances_scored = stats.get("big_chances_scored", {}).get("average", 0) or 0
        big_chances = stats.get("big_chances", {}).get("average", 0) or 0
        gf_avg = (overall.get("goals_for") or 0) / matches

        efficiency = big_chances_scored / big_chances if big_chances > 0 else 0

        goals_score = min(10.0, (gf_avg / 2.0) * 10)
        efficiency_score = efficiency * 10
        chances_score = min(10.0, (big_chances / 3.0) * 10)

        final_score = (goals_score * 0.5) + (efficiency_score * 0.2) + (chances_score * 0.3)

        return {
            "score": final_score,
            "gf_avg": round(gf_avg, 2),
            "efficiency": round(efficiency, 2),
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

        home_score = self._score_attackers(self._get_form(home_id))
        away_score = self._score_attackers(self._get_form(away_id))

        if home_score is None or away_score is None:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.1,
                warnings=["forme indisponible"],
            )

        home_s = home_score["score"]
        away_s = away_score["score"]
        min_score = min(home_s, away_s)
        avg_score = (home_s + away_s) / 2
        final_score = (min_score * 0.6) + (avg_score * 0.4)

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=round(final_score, 2),
            confidence=0.75,
            raw={"home": home_score, "away": away_score, "min": round(min_score, 2)},
            features={"home_gf": home_score["gf_avg"], "away_gf": away_score["gf_avg"]},
            warnings=[],
        )
