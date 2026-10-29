# src/layers/l25_attack_x_attack.py — Couche 25 : Attaque × Attaque (BTTS)
from datetime import datetime
from src.layers.base import BaseLayer, LayerResult


class AttackXAttackLayer(BaseLayer):
    id = 25
    name = "Attaque × Attaque (BTTS)"

    def __init__(self, bzzoiro):
        self.bzzoiro = bzzoiro

    def _get_form(self, team_id):
        if not team_id:
            return None
        try:
            return self.bzzoiro.request("GET", f"/teams/{team_id}/form/")
        except Exception:
            return None

    def _score_attack(self, form):
        """Score 0-10 de la capacité à marquer."""
        if not form:
            return None
        overall = form.get("overall") or {}
        matches = overall.get("matches") or 0
        if matches < 3:
            return None

        gf = overall.get("goals_for") or 0
        gf_avg = gf / matches

        # Buts marqués moyens : 0 → 0, 2.0+ → 10
        # 1 but/match = 5/10 (moyen)
        score = min(10.0, (gf_avg / 2.0) * 10)
        return {"score": score, "gf_avg": round(gf_avg, 2), "matches": matches}

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

        home_attack = self._score_attack(home_form)
        away_attack = self._score_attack(away_form)

        if home_attack is None or away_attack is None:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.1,
                warnings=["forme indisponible"],
            )

        # Score final : moyenne pondérée (le MIN compte plus que le max)
        # Si une équipe ne marque pas, le BTTS est improbable
        home_s = home_attack["score"]
        away_s = away_attack["score"]

        # Utilise le minimum comme base (l'équipe la plus faible à marquer)
        min_attack = min(home_s, away_s)
        avg_attack = (home_s + away_s) / 2

        # Score final : 60% le minimum, 40% la moyenne
        final_score = min_attack * 0.6 + avg_attack * 0.4

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=round(final_score, 2),
            confidence=0.8,
            raw={
                "home_attack": home_attack,
                "away_attack": away_attack,
                "min_attack": round(min_attack, 2),
            },
            features={
                "home_gf_avg": home_attack["gf_avg"],
                "away_gf_avg": away_attack["gf_avg"],
                "min_attack": round(min_attack, 2),
            },
            warnings=[],
        )
