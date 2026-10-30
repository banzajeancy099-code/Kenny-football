# src/layers/l32_btts_context.py — Couche 32 : BTTS contextuel
from datetime import datetime
from src.layers.base import BaseLayer, LayerResult


class BTTSContextLayer(BaseLayer):
    id = 32
    name = "BTTS contextuel"

    def __init__(self, bzzoiro):
        self.bzzoiro = bzzoiro

    def _get_form(self, team_id):
        if not team_id:
            return None
        try:
            return self.bzzoiro.request("GET", f"/teams/{team_id}/form/")
        except Exception:
            return None

    def _analyze_attack(self, form):
        if not form:
            return None
        overall = form.get("overall") or {}
        matches = overall.get("matches") or 0
        if matches < 3:
            return None
        gf = overall.get("goals_for") or 0
        return {"gf_avg": round(gf / matches, 2), "matches": matches}

    def _analyze_losses(self, form):
        if not form:
            return None
        overall = form.get("overall") or {}
        matches = overall.get("matches") or 0
        if matches < 3:
            return None
        lost = overall.get("lost") or 0
        return {"lost": lost, "lost_rate": round(lost / matches, 2)}

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

        home_attack = self._analyze_attack(home_form)
        away_attack = self._analyze_attack(away_form)
        home_losses = self._analyze_losses(home_form)
        away_losses = self._analyze_losses(away_form)

        if not all([home_attack, away_attack, home_losses, away_losses]):
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.1,
                warnings=["forme indisponible"],
            )

        score = 5.0
        reasons = []

        # 1. Attaques
        if home_attack["gf_avg"] >= 1.5 and away_attack["gf_avg"] >= 1.5:
            score += 1.5
            reasons.append("2 attaques fortes")
        elif home_attack["gf_avg"] >= 1.0 and away_attack["gf_avg"] >= 1.0:
            score += 0.8
            reasons.append("2 attaques correctes")
        elif home_attack["gf_avg"] < 0.8 or away_attack["gf_avg"] < 0.8:
            score -= 1.0
            reasons.append("1 attaque faible")

        # 2. Défaites
        avg_lost_rate = (home_losses["lost_rate"] + away_losses["lost_rate"]) / 2
        if avg_lost_rate < 0.2:
            score += 0.8
            reasons.append(f"peu de défaites ({avg_lost_rate:.0%})")
        elif avg_lost_rate < 0.3:
            score += 0.3
        elif avg_lost_rate > 0.5:
            score -= 1.0
            reasons.append(f"beaucoup de défaites ({avg_lost_rate:.0%})")

        # 3. Équilibre
        ecart = abs(home_attack["gf_avg"] - away_attack["gf_avg"])
        if ecart < 0.5:
            score += 0.5
            reasons.append("match équilibré")
        elif ecart > 1.5:
            score -= 0.5
            reasons.append("match déséquilibré")

        score = max(0.0, min(10.0, score))

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=round(score, 2),
            confidence=0.7,
            raw={
                "home_attack": home_attack,
                "away_attack": away_attack,
                "home_losses": home_losses,
                "away_losses": away_losses,
                "reasons": reasons,
            },
            features={
                "avg_lost_rate": round(avg_lost_rate, 2),
                "ecart_attack": round(ecart, 2),
            },
            warnings=[],
        )
