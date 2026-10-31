# src/layers/l31_negatives.py — Couche 31 : Signaux négatifs (red flags)
from datetime import datetime
from src.layers.base import BaseLayer, LayerResult


class NegativesLayer(BaseLayer):
    id = 31
    name = "Signaux négatifs"

    def __init__(self, bzzoiro):
        self.bzzoiro = bzzoiro

    def _get_form(self, team_id):
        if not team_id:
            return None
        try:
            return self.bzzoiro.request("GET", f"/teams/{team_id}/form/")
        except Exception:
            return None

    def _analyze_team(self, form):
        if not form:
            return None
        overall = form.get("overall") or {}
        matches = overall.get("matches") or 0
        if matches < 3:
            return None

        gf = overall.get("goals_for") or 0
        ga = overall.get("goals_against") or 0
        lost = overall.get("lost") or 0

        return {
            "gf_avg": round(gf / matches, 2),
            "ga_avg": round(ga / matches, 2),
            "lost": lost,
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

        home = self._analyze_team(self._get_form(home_id))
        away = self._analyze_team(self._get_form(away_id))

        if home is None or away is None:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.1,
                warnings=["forme indisponible"],
            )

        # Score de base : 5.0 (neutre)
        # Chaque drapeau rouge retire des points
        penalties = []
        score = 5.0

        # 1. Match fermé : les 2 défenses sont TRÈS solides (ga < 0.7)
        if home["ga_avg"] < 0.7 and away["ga_avg"] < 0.7:
            score -= 2.0
            penalties.append(f"match très fermé (GA: {home['ga_avg']:.2f}/{away['ga_avg']:.2f})")

        # 2. Défenses d'élite (ga < 0.5)
        if home["ga_avg"] < 0.5 and away["ga_avg"] < 0.5:
            score -= 1.5
            penalties.append("défenses d'élite")

        # 3. Pas d'attaque (gf < 1.0 pour les 2)
        if home["gf_avg"] < 1.0 and away["gf_avg"] < 1.0:
            score -= 1.0
            penalties.append(f"pas d'attaque (GF: {home['gf_avg']:.2f}/{away['gf_avg']:.2f})")

        # 4. 2 équipes en crise (total défaites >= 12, soit 60% de défaites)
        if home["lost"] + away["lost"] >= 12:
            score -= 1.5
            penalties.append(f"2 équipes en crise ({home['lost']}+{away['lost']} défaites)")
        elif home["lost"] + away["lost"] >= 9:
            score -= 0.5
            penalties.append(f"2 équipes moyennes ({home['lost']}+{away['lost']} défaites)")

        # 5. Enjeu critique : derby + enjeu
        is_derby = match.get("is_local_derby", False)
        stage = (match.get("stage") or "").lower()
        if is_derby and any(s in stage for s in ("final", "semifinal", "playoff", "relegation")):
            score -= 0.5
            penalties.append("derby + enjeu critique")

        # 6. Météo extrême
        weather = match.get("weather") or {}
        rain = weather.get("precipitation_mm") or 0
        wind = weather.get("wind_speed") or 0
        try:
            if float(rain) > 5 or float(wind) > 10:
                score -= 0.5
                penalties.append("météo extrême")
        except (TypeError, ValueError):
            pass

        # 7. Fatigue extrême
        travel = match.get("travel_distance_km") or 0
        try:
            if float(travel) > 1500:
                score -= 0.5
                penalties.append(f"voyage extrême ({travel} km)")
        except (TypeError, ValueError):
            pass

        # 8. Terrain neutre (pas d'avantage domicile)
        if match.get("is_neutral_ground"):
            score -= 0.3
            penalties.append("terrain neutre")

        score = max(0.0, min(10.0, score))

        # Confiance : haute si beaucoup de pénalités trouvées
        confidence = 0.75 if penalties else 0.5

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=round(score, 2),
            confidence=confidence,
            raw={
                "penalties": penalties,
                "penalty_count": len(penalties),
                "home": home,
                "away": away,
            },
            features={
                "penalty_count": len(penalties),
            },
            warnings=penalties if penalties else [],
        )
