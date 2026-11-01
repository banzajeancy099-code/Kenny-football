# src/layers/l42_split_performance.py — Couche 42 : Split Performance
from src.layers.base import LayerResult


class SplitPerformanceLayer:
    """L42 : Split performance (domicile/extérieur/force adverse)."""
    id = 42
    name = "Split Performance"

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

    def _analyze_split(self, form, split_key):
        if not form or not isinstance(form, dict):
            return None
        split = form.get(split_key) or {}
        matches = split.get("matches") or 0
        if matches < 3:
            return None

        gf = split.get("goals_for") or 0
        ga = split.get("goals_against") or 0
        ppg = split.get("points_per_match") or 0

        return {
            "matches": matches,
            "gf_avg": gf / matches,
            "ga_avg": ga / matches,
            "ppg": ppg,
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

        if not home_form or not away_form:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.1,
                warnings=["form indisponible"],
            )

        # Récupérer les splits pertinents
        home_split = self._analyze_split(home_form, "home")
        away_split = self._analyze_split(away_form, "away")

        if home_split is None or away_split is None:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.1,
                warnings=["splits insuffisants"],
            )

        # Buts attendus : attaque domicile vs défense extérieur
        # + attaque extérieur vs défense domicile
        home_attack = home_split["gf_avg"]
        away_defense = away_split["ga_avg"]
        away_attack = away_split["gf_avg"]
        home_defense = home_split["ga_avg"]

        expected_goals = (home_attack + away_defense) / 2 + (away_attack + home_defense) / 2

        # Score basé sur les buts attendus
        # 2.5 = neutre, 3.5+ = Over, 1.5- = Under
        score = 5.0 + (expected_goals - 2.5) * 2.0

        # Ajustement : si une équipe est très forte à domicile, bonus
        if home_split["ppg"] > 2.0:
            score += 0.3
        elif home_split["ppg"] < 0.5:
            score -= 0.3

        # Ajustement : si l'extérieur est faible, bonus (favori à domicile)
        if away_split["ppg"] < 0.8:
            score += 0.2
        elif away_split["ppg"] > 1.8:
            score -= 0.2

        score = max(0.0, min(10.0, score))

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=round(score, 2),
            confidence=0.7,
            raw={
                "home_split": home_split,
                "away_split": away_split,
                "expected_goals": round(expected_goals, 2),
            },
            features={
                "expected_goals": round(expected_goals, 2),
                "home_ppg": home_split["ppg"],
                "away_ppg": away_split["ppg"],
            },
            warnings=[],
        )

