# src/layers/l25_attack_x_attack.py — Couche 25 : Attaque × Défense adverse
from src.layers.base import BaseLayer, LayerResult


class AttackXAttackLayer(BaseLayer):
    id = 25
    name = "Attaque × Défense adverse"

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

    def _get_team_stats(self, team_id, league_id):
        for t in self._get_standings_cached(league_id):
            if t.get("team_id") == team_id:
                played = t.get("played", 0) or 0
                if played < 5:
                    return None
                gf = t.get("gf", 0) or 0
                ga = t.get("ga", 0) or 0
                return {
                    "gf_avg": round(gf / played, 2),
                    "ga_avg": round(ga / played, 2),
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

        home = self._get_team_stats(home_id, league_id)
        away = self._get_team_stats(away_id, league_id)

        if home is None or away is None:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.1,
                warnings=["stats indisponibles"],
            )

        # Attaque × Défense adverse = buts attendus
        # Home marque contre away (away_def) + away marque contre home (home_def)
        home_expected = (home["gf_avg"] + away["ga_avg"]) / 2
        away_expected = (away["gf_avg"] + home["ga_avg"]) / 2
        total_expected = home_expected + away_expected

        # Score : total_expected 2.5 = neutre (5.0)
        # 3.5+ = Over (8.0), 1.5- = Under (2.0)
        score = 5.0 + (total_expected - 2.5) * 3.0

        score = max(0.0, min(10.0, score))

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=round(score, 2),
            confidence=0.75,
            raw={
                "home_gf_avg": home["gf_avg"],
                "away_ga_avg": away["ga_avg"],
                "away_gf_avg": away["gf_avg"],
                "home_ga_avg": home["ga_avg"],
                "total_expected": round(total_expected, 2),
            },
            features={
                "total_expected": round(total_expected, 2),
            },
            warnings=[],
        )
