# src/layers/l06_momentum.py — Couche 6 : Momentum (forme actuelle, pas H2H)
from datetime import datetime
from src.layers.base import BaseLayer, LayerResult


class MomentumLayer(BaseLayer):
    id = 6
    name = "Momentum (forme actuelle)"

    def __init__(self, bzzoiro):
        self.bzzoiro = bzzoiro

    def _get_form(self, team_id):
        if not team_id:
            return None
        try:
            return self.bzzoiro.request("GET", f"/teams/{team_id}/form/")
        except Exception:
            return None

    def _momentum_score(self, form):
        """Score 0-10 basé sur la forme des 5 derniers matchs.

        - Attaque forte + défense poreuse = match ouvert → score haut
        - Attaque faible + défense solide = match fermé → score bas
        """
        if not form:
            return None
        overall = form.get("overall") or {}
        matches = overall.get("matches") or 0
        if matches < 3:
            return None

        # Les 5 derniers matchs
        gf = overall.get("goals_for") or 0
        ga = overall.get("goals_against") or 0
        gf_avg = gf / matches
        ga_avg = ga / matches

        # Points par match (indicateur de forme)
        ppm = overall.get("points_per_match") or 1.0

        # Score d'attaque : plus on marque, plus c'est offensif
        # gf_avg 0 → 0, gf_avg 2.5+ → 5
        attack = min(2.5, gf_avg) / 2.5 * 5

        # Score de défense poreuse : plus on encaisse, plus c'est ouvert
        # ga_avg 0 → 0, ga_avg 2.5+ → 5
        leaky = min(2.5, ga_avg) / 2.5 * 5

        # Bonus forme : équipe en forme = plus de buts (confiance, attaque)
        # ppm 0 → -1, ppm 1.5 → 0, ppm 3 → +1
        form_bonus = (ppm - 1.5) * 0.5
        form_bonus = max(-1, min(1, form_bonus))

        return attack + leaky + form_bonus

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

        home_mom = self._momentum_score(home_form)
        away_mom = self._momentum_score(away_form)

        if home_mom is None or away_mom is None:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.2,
                warnings=["forme indisponible"],
            )

        # Score = moyenne des 2 momentum
        final_score = (home_mom + away_mom) / 2
        final_score = max(0.0, min(10.0, final_score))

        # Confiance haute : données fraîches (5-10 derniers matchs)
        confidence = 0.85

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=round(final_score, 2),
            confidence=confidence,
            raw={
                "home_momentum": round(home_mom, 2),
                "away_momentum": round(away_mom, 2),
                "home_form": home_form.get("overall", {}).get("form") if home_form else None,
                "away_form": away_form.get("overall", {}).get("form") if away_form else None,
            },
            features={
                "home_momentum": round(home_mom, 2),
                "away_momentum": round(away_mom, 2),
            },
            warnings=[],
        )
