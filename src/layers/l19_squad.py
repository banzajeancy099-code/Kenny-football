# src/layers/l19_squad.py — Couche 19 : Solidité défensive (GA + défaites)
from datetime import datetime
from src.layers.base import BaseLayer, LayerResult


class SquadLayer(BaseLayer):
    id = 19
    name = "Solidité défensive"

    def __init__(self, bzzoiro):
        self.bzzoiro = bzzoiro

    def _get_form(self, team_id):
        if not team_id:
            return None
        try:
            return self.bzzoiro.request("GET", f"/teams/{team_id}/form/")
        except Exception:
            return None

    def _analyze_defense(self, form):
        if not form:
            return None
        overall = form.get("overall") or {}
        matches = overall.get("matches") or 0
        if matches < 3:
            return None

        ga = overall.get("goals_against") or 0
        lost = overall.get("lost") or 0
        drawn = overall.get("drawn") or 0
        won = overall.get("won") or 0

        ga_avg = ga / matches
        lost_rate = lost / matches
        win_rate = won / matches

        return {
            "ga_avg": round(ga_avg, 2),
            "lost": lost,
            "lost_rate": round(lost_rate, 2),
            "win_rate": round(win_rate, 2),
            "matches": matches,
        }

    def _score_defense(self, defense):
        """Score combiné : goals_against + défaites."""
        ga_avg = defense["ga_avg"]
        lost_rate = defense["lost_rate"]

        # Score basé sur goals_against (base)
        if ga_avg >= 2.5: ga_score = 9.0
        elif ga_avg >= 2.0: ga_score = 8.0
        elif ga_avg >= 1.5: ga_score = 6.5
        elif ga_avg >= 1.0: ga_score = 5.5
        elif ga_avg >= 0.7: ga_score = 4.0
        elif ga_avg >= 0.3: ga_score = 2.5
        else: ga_score = 1.5

        # Ajustement par défaites
        # lost_rate 0% = -1 (défense solide)
        # lost_rate 50% = +1 (défense poreuse)
        # lost_rate 30% = 0 (neutre)
        lost_bonus = (lost_rate - 0.3) * 3.33  # -1 à +2.33
        lost_bonus = max(-1.5, min(1.5, lost_bonus))

        final = ga_score + lost_bonus
        return max(0.0, min(10.0, round(final, 2)))

    def compute(self, match, context):
        home_id = match.get("home_team_id")
        away_id = match.get("away_team_id")

        if not home_id or not away_id:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.0,
                warnings=["team_id manquant"],
            )

        home_def = self._analyze_defense(self._get_form(home_id))
        away_def = self._analyze_defense(self._get_form(away_id))

        if home_def is None or away_def is None:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.1,
                warnings=["forme indisponible"],
            )

        home_score = self._score_defense(home_def)
        away_score = self._score_defense(away_def)

        min_score = min(home_score, away_score)
        avg_score = (home_score + away_score) / 2
        final_score = (min_score * 0.6) + (avg_score * 0.4)

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=round(final_score, 2),
            confidence=0.75,
            raw={
                "home_ga_avg": home_def["ga_avg"],
                "home_lost_rate": home_def["lost_rate"],
                "away_ga_avg": away_def["ga_avg"],
                "away_lost_rate": away_def["lost_rate"],
                "home_score": home_score,
                "away_score": away_score,
            },
            features={
                "home_ga": home_def["ga_avg"],
                "away_ga": away_def["ga_avg"],
                "home_lost": home_def["lost"],
                "away_lost": away_def["lost"],
            },
            warnings=[],
        )
