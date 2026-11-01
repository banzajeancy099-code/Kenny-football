# src/layers/l02_over.py — Couche 2 : Over 2.5 (refonte dynamique v2)
from src.layers.base import BaseLayer, LayerResult


class OverLayer(BaseLayer):
    id = 2
    name = "Over 2.5"

    def __init__(self, bzzoiro, league_over_rates=None):
        self.bzzoiro = bzzoiro
        self._standings_cache = {}

    def _get_standings_cached(self, league_id):
        if not league_id:
            return []
        if league_id in self._standings_cache:
            return self._standings_cache[league_id]
        try:
            standings = self.bzzoiro.get_standings(league_id) or []
        except Exception:
            standings = []
        self._standings_cache[league_id] = standings
        return standings

    def _compute_league_stats(self, league_id):
        """Calcule les stats réelles de la ligue via get_standings."""
        standings = self._get_standings_cached(league_id)
        if not standings:
            return None

        total_goals = 0
        total_matches = 0
        for t in standings:
            played = t.get("played", 0) or 0
            if played == 0:
                continue
            total_goals += (t.get("gf", 0) or 0)  # On compte UNE fois les buts marqués
            total_matches += played

        if total_matches == 0:
            return None

        # Buts par match = (total buts marqués / nombre de matchs-équipes) × 2
        # Car chaque match a 2 équipes, et chaque but est compté 1x (gf)
        goals_per_match = (total_goals / total_matches) * 2

        # Taux Over 2.5 estimé (moyenne 2.70 buts → ~55% Over)
        over_rate = min(0.95, max(0.30, (goals_per_match / 2.70) * 0.55))

        return {
            "goals_per_match": round(goals_per_match, 2),
            "over_rate": round(over_rate, 3),
            "matches": int(total_matches / 2),
        }

    def _get_team_stats(self, team_id, league_id):
        for t in self._get_standings_cached(league_id):
            if t.get("team_id") == team_id:
                played = t.get("played", 0) or 1
                return {
                    "gf_avg": (t.get("gf", 0) or 0) / played,
                    "ga_avg": (t.get("ga", 0) or 0) / played,
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

        league = self._compute_league_stats(league_id)
        if league is None or league["matches"] < 20:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.1,
                warnings=["pas assez de matchs dans la ligue"],
            )

        home = self._get_team_stats(home_id, league_id)
        away = self._get_team_stats(away_id, league_id)

        if home is None or away is None:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.2,
                warnings=["stats équipes indisponibles"],
            )

        # Score de base sur le taux Over de la ligue
        # 0.55 = neutre (5.0), 0.75 = très offensif (8.0), 0.35 = très fermé (2.0)
        base_score = 5.0 + (league["over_rate"] - 0.55) * 15.0

        # Ajustement selon la confrontation des 2 équipes
        # Moyenne de buts attendue par match (moyenne des attaques et défenses)
        home_attack = home["gf_avg"]
        away_attack = away["gf_avg"]
        home_defense = home["ga_avg"]
        away_defense = away["ga_avg"]
        # Buts attendus par match (attaque domicile vs défense extérieur + inverse)
        expected_goals = (home_attack + away_defense) / 2 + (away_attack + home_defense) / 2

        if expected_goals > 3.5:
            base_score += 0.5
        elif expected_goals > 3.0:
            base_score += 0.2
        elif expected_goals < 2.0:
            base_score -= 0.5
        elif expected_goals < 2.5:
            base_score -= 0.2

        score = max(0.0, min(10.0, base_score))
        confidence = 0.8 if league["matches"] >= 50 else 0.5

        return LayerResult(
            layer_id=self.id,
            layer_name=self.name,
            score=round(score, 2),
            confidence=confidence,
            raw={
                "league_id": league_id,
                "league_over_rate": league["over_rate"],
                "league_goals_per_match": league["goals_per_match"],
                "league_matches": league["matches"],
                "expected_goals": round(expected_goals, 2),
                "home_attack": round(home_attack, 2),
                "away_attack": round(away_attack, 2),
            },
            features={
                "league_over_rate": league["over_rate"],
                "expected_goals": round(expected_goals, 2),
            },
            warnings=[],
        )
