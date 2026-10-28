# src/layers/l16_lifecycle.py — Couche 16 : Cycle de vie (big_chances, forme globale)
from datetime import datetime
from src.layers.base import BaseLayer, LayerResult


class LifecycleLayer(BaseLayer):
    id = 16
    name = "Cycle de vie"

    def __init__(self, bzzoiro):
        self.bzzoiro = bzzoiro

    def _get_form(self, team_id):
        if not team_id:
            return None
        try:
            return self.bzzoiro.request("GET", f"/teams/{team_id}/form/")
        except Exception:
            return None

    def _score_form(self, form):
        """Score 0-10 basé sur la dangerosité offensive + défensive."""
        if not form:
            return None
        overall = form.get("overall") or {}
        matches = overall.get("matches") or 0
        if matches < 3:
            return None

        stats = overall.get("stats") or {}

        # Moyennes par match
        big_chances = stats.get("big_chances", {}).get("average", 0)
        big_scored = stats.get("big_chances_scored", {}).get("average", 0)
        attack = stats.get("attack", {}).get("average", 0)

        # Buts marqués + encaissés
        gf_avg = (overall.get("goals_for") or 0) / matches
        ga_avg = (overall.get("goals_against") or 0) / matches

        # Score big_chances : 2.5+ par match = très dangereux
        bc_score = min(3.0, big_chances) / 3.0 * 3.5

        # Score attack : 75+ = très offensif
        atk_score = min(85, attack) / 85 * 2.0

        # Score buts totaux : 3+ = match ouvert
        total_goals_avg = gf_avg + ga_avg
        goals_score = min(3.5, total_goals_avg) / 3.5 * 4.5

        return bc_score + atk_score + goals_score

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

        home_sc = self._score_form(home_form)
        away_sc = self._score_form(away_form)

        if home_sc is None or away_sc is None:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.2,
                warnings=["forme indisponible"],
            )

        final_score = (home_sc + away_sc) / 2
        final_score = max(0.0, min(10.0, final_score))

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=round(final_score, 2),
            confidence=0.85,
            raw={
                "home_score": round(home_sc, 2),
                "away_score": round(away_sc, 2),
            },
            features={"home_score": round(home_sc, 2), "away_score": round(away_sc, 2)},
            warnings=[],
        )
