# src/layers/l14_xg.py — Couche 14 : Expected Goals (xG)
"""
Analyse les expected goals RÉELS (xgf, xga) depuis get_standings.

Signaux détectés :
  1. Total xG attendu (xgf_home + xgf_away + xga_home + xga_away)
  2. Sur-performance offensive (buts réels >> xG) → régression probable
  3. Sous-performance offensive (buts réels << xG) → rebond probable
  4. Sur-performance défensive (encaissés << xGA) → régression probable
  5. Sous-performance défensive (encaissés >> xGA) → rebond probable

Score final :
  - xG total élevé → score > 5 (Over probable)
  - xG total faible → score < 5 (Under probable)
  - Ajustements selon les sur/sous-performances
"""
from src.layers.base import BaseLayer, LayerResult


class XGLayer(BaseLayer):
    id = 14
    name = "Expected Goals (xG)"

    def __init__(self, bzzoiro):
        self.bzzoiro = bzzoiro
        self._standings_cache = {}

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
        """Retourne les vrais xG d'une équipe depuis get_standings."""
        if not team_id or not league_id:
            return None

        for t in self._get_standings_cached(league_id):
            if t.get("team_id") == team_id:
                played = t.get("played", 0) or 0
                xg_games = t.get("xg_games", 0) or 0

                # Vérifier qu'on a assez de matchs avec xG
                if xg_games < 5:
                    return None

                return {
                    "team_name": t.get("team_name", "?"),
                    "played": played,
                    "xg_games": xg_games,
                    "xgf_total": t.get("xgf", 0) or 0,
                    "xga_total": t.get("xga", 0) or 0,
                    "gf_total": t.get("gf", 0) or 0,
                    "ga_total": t.get("ga", 0) or 0,
                    # Moyennes par match
                    "xgf_avg": (t.get("xgf", 0) or 0) / xg_games if xg_games else 0,
                    "xga_avg": (t.get("xga", 0) or 0) / xg_games if xg_games else 0,
                    "gf_avg": (t.get("gf", 0) or 0) / played if played else 0,
                    "ga_avg": (t.get("ga", 0) or 0) / played if played else 0,
                    # Écarts (buts réels - xG)
                    "attack_overperf": ((t.get("gf", 0) or 0) - (t.get("xgf", 0) or 0)) / xg_games if xg_games else 0,
                    "defense_overperf": ((t.get("ga", 0) or 0) - (t.get("xga", 0) or 0)) / xg_games if xg_games else 0,
                }
        return None

    def compute(self, match, context):
        home_id = match.get("home_team_id")
        away_id = match.get("away_team_id")
        league_id = match.get("league_id")

        if not home_id or not away_id or not league_id:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.0,
                warnings=["team_id ou league_id manquant"],
            )

        home = self._get_team_xg(home_id, league_id)
        away = self._get_team_xg(away_id, league_id)

        if home is None or away is None:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.1,
                warnings=["données xG indisponibles"],
            )

        # === 1. xG total attendu ===
        # xgf_home + xgf_away + xga_home + xga_away
        total_xg = home["xgf_avg"] + away["xgf_avg"] + home["xga_avg"] + away["xga_avg"]

        # === 2. Score de base : normalisé par la moyenne de la ligue ===
        # Moyenne xG par match en général : 2.5-2.8
        # Un match à xG=2.7 est "neutre" (score 5.0)
        # Un match à xG=4.8 dans une ligue à 2.8 est 1.71× → score 8.5
        LEAGUE_AVG_XG = 2.70  # référence universelle (moyenne européenne)
        ratio = total_xg / LEAGUE_AVG_XG

        # Score = 5.0 + (ratio - 1) * 5.0, clampé 0-10
        score = 5.0 + (ratio - 1.0) * 5.0

        # Clamp final
        score = max(0.0, min(10.0, score))

        reasons = [f"xG total attendu: {total_xg:.2f}"]

        # === 3. Ajustement attaque : sur-performance = régression ===
        # attack_overperf > 0.3 → l'équipe marque plus que ses xG → régression probable
        for label, team in (("home", home), ("away", away)):
            overperf = team["attack_overperf"]
            if overperf > 0.40:
                score -= 0.5
                reasons.append(f"{label} sur-perf attaque (+{overperf:.2f}/match) → régression")
            elif overperf > 0.20:
                score -= 0.25
                reasons.append(f"{label} sur-perf attaque légère (+{overperf:.2f})")
            elif overperf < -0.40:
                score += 0.5
                reasons.append(f"{label} sous-perf attaque ({overperf:.2f}/match) → rebond")
            elif overperf < -0.20:
                score += 0.25
                reasons.append(f"{label} sous-perf attaque légère ({overperf:.2f})")

        # === 4. Ajustement défense : sur-performance = régression ===
        # defense_overperf < 0 → encaisse MOINS que xGA → chance → régression (plus de buts)
        # defense_overperf > 0 → encaisse PLUS que xGA → malchance → rebond (moins de buts)
        for label, team in (("home", home), ("away", away)):
            overperf = team["defense_overperf"]
            if overperf < -0.40:
                score += 0.5
                reasons.append(f"{label} défense sur-régime ({overperf:.2f}/match) → régression (plus de buts)")
            elif overperf < -0.20:
                score += 0.25
                reasons.append(f"{label} défense sur-régime légère ({overperf:.2f})")
            elif overperf > 0.40:
                score -= 0.5
                reasons.append(f"{label} défense sous-régime (+{overperf:.2f}/match) → rebond défensif")
            elif overperf > 0.20:
                score -= 0.25
                reasons.append(f"{label} défense sous-régime légère (+{overperf:.2f})")

        score = max(0.0, min(10.0, score))

        # Confiance : haute si assez de matchs avec xG
        confidence = 0.85 if (home["xg_games"] >= 10 and away["xg_games"] >= 10) else 0.6

        return LayerResult(
            layer_id=self.id,
            layer_name=self.name,
            score=round(score, 2),
            confidence=confidence,
            raw={
                "home": home,
                "away": away,
                "total_xg": round(total_xg, 2),
                "reasons": reasons,
            },
            features={
                "total_xg": round(total_xg, 2),
                "home_xgf": round(home["xgf_avg"], 2),
                "away_xgf": round(away["xgf_avg"], 2),
                "home_attack_overperf": round(home["attack_overperf"], 2),
                "away_attack_overperf": round(away["attack_overperf"], 2),
            },
            warnings=reasons if len(reasons) > 1 else [],
        )
