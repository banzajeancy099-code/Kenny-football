# src/layers/l40_momentum_advanced.py — Couche 40 : Momentum avancé
from src.layers.base import LayerResult


class MomentumAdvancedLayer:
    """L40 : Momentum pondéré par la qualité de l'adversaire."""
    id = 40
    name = "Momentum avancé"

    def __init__(self, bzzoiro):
        self.bzzoiro = bzzoiro
        self._cache = {}

    def _get_form(self, team_id):
        if team_id in self._cache:
            return self._cache[team_id]
        try:
            form = self.bzzoiro.request("GET", f"/teams/{team_id}/form/")
        except Exception:
            form = None
        self._cache[team_id] = form
        return form

    def _analyze_form(self, form, team_id):
        if not form or not isinstance(form, dict):
            return None

        overall = form.get("overall") or {}
        matches = overall.get("matches") or 0
        if matches < 5:
            return None

        gf = overall.get("goals_for") or 0
        ga = overall.get("goals_against") or 0
        wins = overall.get("won") or 0
        draws = overall.get("drawn") or 0
        lost = overall.get("lost") or 0

        points = wins * 3 + draws
        ppg = points / matches if matches > 0 else 0

        gf_avg = gf / matches
        ga_avg = ga / matches

        # Force offensive (points par match)
        # 2.0 ppg = excellent (score 8.0)
        # 1.0 ppg = moyen (score 5.0)
        # 0.5 ppg = mauvais (score 3.0)
        form_score = 5.0 + (ppg - 1.0) * 3.0

        return {
            "matches": matches,
            "wins": wins,
            "draws": draws,
            "lost": lost,
            "points": points,
            "ppg": round(ppg, 2),
            "gf_avg": round(gf_avg, 2),
            "ga_avg": round(ga_avg, 2),
            "form_score": round(max(0, min(10, form_score)), 2),
        }

    def safe_compute(self, match, context=None):
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

        home = self._analyze_form(home_form, home_id)
        away = self._analyze_form(away_form, away_id)

        if home is None or away is None:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.1,
                warnings=["form indisponible"],
            )

        # Score Over = plus les 2 équipes marquent, plus c'est Over-friendly
        # Utiliser gf_avg (attaque) et ga_avg (défense)
        total_gf = home["gf_avg"] + away["gf_avg"]
        total_ga = home["ga_avg"] + away["ga_avg"]

        # Moyenne des buts attendus (attaque + défense)
        expected_goals = (total_gf + total_ga) / 2

        # Score basé sur les buts attendus
        # 2.5 = neutre, 3.5+ = Over, 1.5- = Under
        score = 5.0 + (expected_goals - 2.5) * 2.0

        # Ajustement : si les 2 équipes sont en forme offensive, bonus
        if home["ppg"] > 1.8 and away["ppg"] > 1.8:
            score += 0.5
        elif home["ppg"] < 0.8 and away["ppg"] < 0.8:
            score -= 0.5

        score = max(0.0, min(10.0, score))

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=round(score, 2),
            confidence=0.7,
            raw={
                "home": home,
                "away": away,
                "expected_goals": round(expected_goals, 2),
            },
            features={
                "home_ppg": home["ppg"],
                "away_ppg": away["ppg"],
                "expected_goals": round(expected_goals, 2),
            },
            warnings=[],
        )

