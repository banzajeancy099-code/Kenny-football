# src/layers/l14_xg.py — Couche 14 : Expected Goals (xG)
from datetime import datetime
from src.layers.base import BaseLayer, LayerResult


class XGLayer(BaseLayer):
    id = 14
    name = "Expected Goals (xG)"

    def __init__(self, bzzoiro):
        self.bzzoiro = bzzoiro

    def _get_form(self, team_id):
        if not team_id:
            return None
        try:
            return self.bzzoiro.request("GET", f"/teams/{team_id}/form/")
        except Exception:
            return None

    def _compute_xg(self, form):
        """Calcule un xG estimé par match pour une équipe.

        Basé sur :
        - big_chances (occasions nettes)
        - attack (efficacité offensive)
        - big_chances_scored (buts sur occasions nettes)
        """
        if not form:
            return None
        overall = form.get("overall") or {}
        matches = overall.get("matches") or 0
        if matches < 3:
            return None

        stats = overall.get("stats") or {}

        # Big chances (occasions nettes) par match
        big_chances = stats.get("big_chances", {}).get("average", 0) or 0
        big_chances_scored = stats.get("big_chances_scored", {}).get("average", 0) or 0

        # Attack rating (0-100)
        attack = stats.get("attack", {}).get("average", 0) or 0

        # Buts réels par match
        gf_avg = (overall.get("goals_for") or 0) / matches

        # xG estimé : moyenne pondérée de plusieurs indicateurs
        # big_chances × 0.35 (chaque grosse occasion vaut ~0.35 xG)
        xg_from_chances = big_chances * 0.35
        # attack rating normalisé (75 = moyenne, xG implicite ~1.2)
        xg_from_attack = (attack / 75) * 1.2 if attack > 0 else 0
        # buts réels (proxy)
        xg_from_goals = gf_avg * 0.8

        # Moyenne des 3 (avec pondération)
        xg_est = (xg_from_chances * 0.5) + (xg_from_attack * 0.2) + (xg_from_goals * 0.3)

        return {
            "xg": round(xg_est, 2),
            "big_chances": big_chances,
            "big_chances_scored": big_chances_scored,
            "attack": attack,
            "gf_avg": round(gf_avg, 2),
            "matches": matches,
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

        home_form = self._get_form(home_id)
        away_form = self._get_form(away_id)

        home_xg = self._compute_xg(home_form)
        away_xg = self._compute_xg(away_form)

        if home_xg is None or away_xg is None:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.1,
                warnings=["données xG indisponibles"],
            )

        # Score Over 0-10 : plus le xG total est élevé, plus le match est ouvert
        # xG total = home_xg + away_xg
        # 0 → 0, 4.0+ → 10
        total_xg = home_xg["xg"] + away_xg["xg"]
        score = min(10.0, (total_xg / 4.0) * 10)

        # Ajustement : si les 2 équipes ont un xG élevé, bonus
        if home_xg["xg"] >= 1.5 and away_xg["xg"] >= 1.5:
            score = min(10.0, score + 1.0)  # match très offensif

        # Pénalité : si les 2 ont xG faible
        if home_xg["xg"] <= 1.0 and away_xg["xg"] <= 1.0:
            score = max(0.0, score - 1.0)

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=round(score, 2),
            confidence=0.8,
            raw={
                "home_xg": home_xg,
                "away_xg": away_xg,
                "total_xg": round(total_xg, 2),
            },
            features={
                "home_xg": home_xg["xg"],
                "away_xg": away_xg["xg"],
                "total_xg": round(total_xg, 2),
            },
            warnings=[],
        )
