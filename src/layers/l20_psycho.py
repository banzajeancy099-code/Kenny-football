# src/layers/l20_psycho.py — Couche 20 : Psychologie / Style de jeu
from datetime import datetime
from src.layers.base import BaseLayer, LayerResult


class PsychoLayer(BaseLayer):
    id = 20
    name = "Psycho / Style de jeu"

    def __init__(self, bzzoiro):
        self.bzzoiro = bzzoiro

    def _get_form(self, team_id):
        if not team_id:
            return None
        try:
            return self.bzzoiro.request("GET", f"/teams/{team_id}/form/")
        except Exception:
            return None

    def _analyze_style(self, form):
        """Analyse le style de jeu d'une équipe."""
        if not form:
            return None
        overall = form.get("overall") or {}
        matches = overall.get("matches") or 0
        if matches < 3:
            return None

        stats = overall.get("stats") or {}
        attack_pct = stats.get("attack_pct", {}).get("average", 0) or 0
        ball_possession = stats.get("ball_possession", {}).get("average", 0) or 0
        form_string = overall.get("form", "") or ""

        # Compte les victoires sur les 5 derniers
        recent_form = form_string[:5]
        wins = recent_form.count("W")
        losses = recent_form.count("L")

        # Style offensif : attack_pct > 50% et possession > 50%
        is_offensive = attack_pct >= 50 and ball_possession >= 50

        # Style défensif : attack_pct < 40% et possession < 45%
        is_defensive = attack_pct < 40 and ball_possession < 45

        return {
            "attack_pct": round(attack_pct, 1),
            "possession": round(ball_possession, 1),
            "wins": wins,
            "losses": losses,
            "is_offensive": is_offensive,
            "is_defensive": is_defensive,
            "form_string": form_string[:5],
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

        home_style = self._analyze_style(self._get_form(home_id))
        away_style = self._analyze_style(self._get_form(away_id))

        if home_style is None or away_style is None:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.1,
                warnings=["forme indisponible"],
            )

        # Score de base 5.0
        score = 5.0
        reasons = []

        # 1. Style offensif vs défensif
        if home_style["is_offensive"] and away_style["is_offensive"]:
            score += 1.5
            reasons.append("2 équipes offensives")
        elif home_style["is_defensive"] and away_style["is_defensive"]:
            score -= 1.5
            reasons.append("2 équipes défensives")
        elif home_style["is_offensive"] or away_style["is_offensive"]:
            score += 0.5
            reasons.append("1 équipe offensive")

        # 2. Forme récente (W/L)
        total_wins = home_style["wins"] + away_style["wins"]
        total_losses = home_style["losses"] + away_style["losses"]

        if total_losses >= 6:
            score -= 1.0
            reasons.append("2 équipes en crise")
        elif total_wins >= 6:
            score += 1.0
            reasons.append("2 équipes en confiance")

        # 3. Enjeu (derby)
        if match.get("is_local_derby"):
            score -= 0.5  # Derby = prudence
            reasons.append("derby (prudence)")

        # 4. Terrain neutre
        if match.get("is_neutral_ground"):
            score -= 0.3
            reasons.append("terrain neutre")

        score = max(0.0, min(10.0, score))

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=round(score, 2),
            confidence=0.7,
            raw={
                "home": home_style,
                "away": away_style,
                "reasons": reasons,
            },
            features={
                "home_attack_pct": home_style["attack_pct"],
                "away_attack_pct": away_style["attack_pct"],
                "home_wins": home_style["wins"],
                "away_wins": away_style["wins"],
            },
            warnings=[],
        )
