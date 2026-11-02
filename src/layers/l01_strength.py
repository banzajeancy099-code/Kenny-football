# src/layers/l01_strength.py — Couche 1 : Strength (force globale)
from src.layers.base import BaseLayer, LayerResult


class StrengthLayer(BaseLayer):
    id = 1
    name = "Strength (force)"

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

    def _team_strength(self, team_id, league_id):
        for t in self._get_standings_cached(league_id):
            if t.get("team_id") == team_id:
                played = t.get("played", 0) or 0
                if played < 5:
                    return None

                gf = t.get("gf", 0) or 0
                ga = t.get("ga", 0) or 0
                pts = t.get("pts", 0) or 0

                gf_avg = gf / played
                ga_avg = ga / played
                ppg = pts / played

                # Force globale : attaque (gf_avg) + défense (ga_avg inversé) + points (ppg)
                # gf 2.0 = 5.0 (moyen), gf 3.0+ = 8.0
                attack_score = min(3.0, gf_avg) / 3.0 * 10.0

                # ga 0.5 = 8.0 (défense solide), ga 2.0 = 2.0
                defense_score = max(0.0, (2.5 - ga_avg) / 2.0 * 10.0)

                # ppg 0.5 = 2.0, ppg 2.0 = 8.0
                ppg_score = min(2.5, ppg) / 2.5 * 10.0

                # Moyenne pondérée : 40% attaque, 30% défense, 30% ppg
                final = attack_score * 0.4 + defense_score * 0.3 + ppg_score * 0.3
                return final
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

        home_str = self._team_strength(home_id, league_id)
        away_str = self._team_strength(away_id, league_id)

        if home_str is None or away_str is None:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.2,
                warnings=["forme indisponible"],
            )

        final_score = (home_str + away_str) / 2
        final_score = max(0.0, min(10.0, final_score))

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=round(final_score, 2),
            confidence=0.8,
            raw={
                "home_strength": round(home_str, 2),
                "away_strength": round(away_str, 2),
            },
            features={
                "home_strength": round(home_str, 2),
                "away_strength": round(away_str, 2),
            },
            warnings=[],
        )
