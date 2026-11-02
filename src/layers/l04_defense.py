# src/layers/l04_defense.py — Couche 4 : Défense réelle (via get_standings)
from src.layers.base import BaseLayer, LayerResult


class DefenseLayer(BaseLayer):
    id = 4
    name = "Défense réelle"

    def __init__(self, bzzoiro):
        self.bzzoiro = bzzoiro
        self._cache = {}

    def _get_standings_cached(self, league_id):
        if league_id in self._cache:
            return self._cache[league_id]
        try:
            standings = self.bzzoiro.get_standings(league_id) or []
        except Exception:
            standings = []
        self._cache[league_id] = standings
        return standings

    def _get_team_defense(self, team_id, league_id):
        for t in self._get_standings_cached(league_id):
            if t.get("team_id") == team_id:
                played = t.get("played", 0) or 0
                if played < 5:
                    return None
                ga = t.get("ga", 0) or 0
                xga = t.get("xga", 0) or 0
                xg_games = t.get("xg_games", 0) or 0

                ga_avg = ga / played
                xga_avg = xga / xg_games if xg_games > 0 else ga_avg

                return {
                    "ga_avg": round(ga_avg, 2),
                    "xga_avg": round(xga_avg, 2),
                    "played": played,
                }
        return None

    def compute(self, match, context):
        home_id = match.get("home_team_id")
        away_id = match.get("away_team_id")
        league_id = match.get("league_id")

        if not home_id or not away_id or not league_id:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.0,
                warnings=["données manquantes"],
            )

        home_def = self._get_team_defense(home_id, league_id)
        away_def = self._get_team_defense(away_id, league_id)

        if home_def is None or away_def is None:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.1,
                warnings=["défenses indisponibles"],
            )

        # Moyenne des 2 défenses (ga_avg)
        avg_defense = (home_def["ga_avg"] + away_def["ga_avg"]) / 2

        # Score : plus la défense est faible (ga élevé), plus le score est élevé (Over)
        # ga 0.8 = défense solide → score 3.0
        # ga 1.5 = défense moyenne → score 5.5
        # ga 2.5+ = défense faible → score 8.0
        if avg_defense >= 2.5:
            score = 8.5
        elif avg_defense >= 2.0:
            score = 7.0
        elif avg_defense >= 1.5:
            score = 5.5
        elif avg_defense >= 1.0:
            score = 4.0
        else:
            score = 2.5

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=round(score, 2),
            confidence=0.75,
            raw={
                "home_ga_avg": home_def["ga_avg"],
                "away_ga_avg": away_def["ga_avg"],
                "avg_defense": round(avg_defense, 2),
            },
            features={
                "home_ga_avg": home_def["ga_avg"],
                "away_ga_avg": away_def["ga_avg"],
                "avg_defense": round(avg_defense, 2),
            },
            warnings=[],
        )
