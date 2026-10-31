# src/layers/l31_negatives.py — Couche 31 : Signaux négatifs (red flags)
from src.layers.base import BaseLayer, LayerResult


class NegativesLayer(BaseLayer):
    id = 31
    name = "Signaux négatifs"

    def __init__(self, bzzoiro):
        self.bzzoiro = bzzoiro
        self._standings_cache = {}  # {league_id: list}

    def _get_standings_cached(self, league_id):
        if not league_id:
            return []
        if league_id in self._standings_cache:
            return self._standings_cache[league_id]
        try:
            standings = self.bzzoiro.get_standings(league_id) or []
        except Exception:
            standings = []
        self._standings_cache[league_id] = standings
        return standings

    def _get_team_xg(self, team_id, league_id):
        """Récupère xgf/xga/played d'une équipe depuis le classement."""
        if not team_id or not league_id:
            return None
        for t in self._get_standings_cached(league_id):
            if t.get("team_id") == team_id:
                return {
                    "xgf": t.get("xgf", 0) or 0,
                    "xga": t.get("xga", 0) or 0,
                    "played": t.get("played", 0) or 0,
                    "gf": t.get("gf", 0) or 0,
                    "ga": t.get("ga", 0) or 0,
                }
        return None

    def _get_form(self, team_id):
        if not team_id:
            return None
        try:
            return self.bzzoiro.request("GET", f"/teams/{team_id}/form/")
        except Exception:
            return None

    def _analyze_team(self, form, team_id=None, league_id=None):
        if not form:
            return None
        overall = form.get("overall") or {}
        matches = overall.get("matches") or 0
        if matches < 3:
            return None

        gf = overall.get("goals_for") or 0
        ga = overall.get("goals_against") or 0
        lost = overall.get("lost") or 0

        result = {
            "gf_avg": round(gf / matches, 2),
            "ga_avg": round(ga / matches, 2),
            "lost": lost,
            "matches": matches,
            "xgf_avg": None,
            "xga_avg": None,
            "overperf": None,   # buts réels - xG par match (attaque)
            "underperf": None,  # buts encaissés - xGA par match (défense)
        }

        # Enrichissement xG depuis le classement
        if team_id and league_id:
            xg_data = self._get_team_xg(team_id, league_id)
            if xg_data and xg_data["played"] >= 5 and xg_data["xgf"] > 0:
                played = xg_data["played"]
                xgf_avg = xg_data["xgf"] / played
                xga_avg = xg_data["xga"] / played
                gf_avg_league = xg_data["gf"] / played
                ga_avg_league = xg_data["ga"] / played
                result["xgf_avg"] = round(xgf_avg, 2)
                result["xga_avg"] = round(xga_avg, 2)
                result["overperf"] = round(gf_avg_league - xgf_avg, 2)
                result["underperf"] = round(ga_avg_league - xga_avg, 2)

        return result

    def compute(self, match, context):
        home_id = match.get("home_team_id")
        away_id = match.get("away_team_id")
        league_id = match.get("league_id")

        if not home_id or not away_id:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.0,
                warnings=["team_id manquant"],
            )

        home = self._analyze_team(self._get_form(home_id), home_id, league_id)
        away = self._analyze_team(self._get_form(away_id), away_id, league_id)

        if home is None or away is None:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.1,
                warnings=["forme indisponible"],
            )

        penalties = []
        score = 5.0

        # 1. Match fermé : les 2 défenses sont TRÈS solides
        if home["ga_avg"] < 0.7 and away["ga_avg"] < 0.7:
            score -= 2.0
            penalties.append(f"match très fermé (GA: {home['ga_avg']:.2f}/{away['ga_avg']:.2f})")

        # 2. Défenses d'élite
        if home["ga_avg"] < 0.5 and away["ga_avg"] < 0.5:
            score -= 1.5
            penalties.append("défenses d'élite")

        # 3. Pas d'attaque
        if home["gf_avg"] < 1.0 and away["gf_avg"] < 1.0:
            score -= 1.0
            penalties.append(f"pas d'attaque (GF: {home['gf_avg']:.2f}/{away['gf_avg']:.2f})")

        # 4. Équipes en crise
        if home["lost"] + away["lost"] >= 12:
            score -= 1.5
            penalties.append(f"2 équipes en crise ({home['lost']}+{away['lost']} défaites)")
        elif home["lost"] + away["lost"] >= 9:
            score -= 0.5
            penalties.append(f"2 équipes moyennes ({home['lost']}+{away['lost']} défaites)")

        # 5. Derby + enjeu
        is_derby = match.get("is_local_derby", False)
        stage = (match.get("stage") or "").lower()
        if is_derby and any(s in stage for s in ("final", "semifinal", "playoff", "relegation")):
            score -= 0.5
            penalties.append("derby + enjeu critique")

        # 6. Météo
        weather = match.get("weather") or {}
        rain = weather.get("precipitation_mm") or 0
        wind = weather.get("wind_speed") or 0
        try:
            if float(rain) > 5 or float(wind) > 10:
                score -= 0.5
                penalties.append("météo extrême")
        except (TypeError, ValueError):
            pass

        # 7. Voyage
        travel = match.get("travel_distance_km") or 0
        try:
            if float(travel) > 1500:
                score -= 0.5
                penalties.append(f"voyage extrême ({travel} km)")
        except (TypeError, ValueError):
            pass

        # 8. Terrain neutre
        if match.get("is_neutral_ground"):
            score -= 0.3
            penalties.append("terrain neutre")

        # 9. OVER FAUX : équipe(s) qui sur-performent leur xG (régression probable)
        for label, team in (("domicile", home), ("extérieur", away)):
            overperf = team.get("overperf")
            if overperf is None:
                continue
            if overperf >= 0.40:
                score -= 0.5
                penalties.append(f"{label} sur-performe ses xG (+{overperf:.2f}/match) → régression probable")
            elif overperf >= 0.20:
                score -= 0.25
                penalties.append(f"{label} sur-performe légèrement ses xG (+{overperf:.2f}/match)")

        # 10. UNDER FAUX : équipe(s) qui sous-performent leurs xG (rebond probable)
        for label, team in (("domicile", home), ("extérieur", away)):
            overperf = team.get("overperf")
            if overperf is None:
                continue
            if overperf <= -0.40:
                score -= 0.3
                penalties.append(f"{label} sous-performe ses xG ({overperf:.2f}/match) → rebond probable")

        # 11. Défense en sur-régime (encaissent moins que xGA = chance)
        for label, team in (("domicile", home), ("extérieur", away)):
            underperf = team.get("underperf")
            if underperf is None:
                continue
            if underperf <= -0.40:
                score -= 0.3
                penalties.append(f"{label} défense sur-régime ({underperf:.2f} buts/xGA) → régression")

        score = max(0.0, min(10.0, score))
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
            features={"penalty_count": len(penalties)},
            warnings=penalties if penalties else [],
        )
