# src/layers/l01_strength.py — Couche 1 : Strength (force offensive/défensive)
from datetime import datetime
from src.layers.base import BaseLayer, LayerResult


class StrengthLayer(BaseLayer):
    id = 1
    name = "Strength (force)"

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
        """Force offensive d'une équipe (0-10).
        Basée sur goals_for + big_chances + attack.
        """
        if not form:
            return None
        overall = form.get("overall") or {}
        matches = overall.get("matches") or 0
        if matches < 3:
            return None

        gf = overall.get("goals_for") or 0
        gf_avg = gf / matches

        # Bonus big_chances (occasions nettes)
        stats = overall.get("stats") or {}
        big_chances = stats.get("big_chances", {}).get("average", 0)
        big_chances_scored = stats.get("big_chances_scored", {}).get("average", 0)

        # Score de base : buts marqués (0-2.5 → 0-6)
        goals_score = min(2.5, gf_avg) / 2.5 * 6

        # Bonus occasions nettes (0-3 → 0-4)
        chances_score = min(3.0, big_chances) / 3.0 * 4

        return goals_score + chances_score

    def compute(self, match, context):
        home_id = match.get("home_team_id")
        away_id = match.get("away_team_id")

        if not home_id or not away_id:
            # Fallback H2H (ancien comportement)
            h2h = match.get("head_to_head") or {}
            home_goals = h2h.get("home_goals", 0)
            away_goals = h2h.get("away_goals", 0)
            total = home_goals + away_goals
            if total == 0:
                return LayerResult(
                    layer_id=self.id, layer_name=self.name,
                    score=5.0, confidence=0.2,
                    warnings=["pas de données team"],
                )
            ratio = home_goals / total
            score = 5.0 + (ratio - 0.5) * 8
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=max(0.0, min(10.0, score)),
                confidence=0.5,
                warnings=["fallback H2H"],
            )

        home_form = self._get_form(home_id)
        away_form = self._get_form(away_id)

        home_str = self._team_strength(home_form)
        away_str = self._team_strength(away_form)

        if home_str is None or away_str is None:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.2,
                warnings=["forme indisponible"],
            )

        # Somme des forces des 2 équipes / 2
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
