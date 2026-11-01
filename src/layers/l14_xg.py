# src/layers/l14_xg.py — Couche 14 : xG normalisé par ligue
from src.layers.base import LayerResult


class XGLayer:
    """L14 : xG normalisé par la ligue (dynamique)."""
    id = 14
    name = "Expected Goals (xG)"

    def __init__(self, bzzoiro):
        self.bzzoiro = bzzoiro
        self._cache = {}

    def _get_standings_cached(self, league_id):
        if league_id in self._cache:
            return self._cache[league_id]
        try:
            standings = self.bzzoiro.get_standings(league_id) or []
        except Exception:
            standings = []
        self._cache[league_id] = standings
        return standings

    def _compute_league_xg_avg(self, league_id):
        """Calcule la moyenne xG de la ligue (xGF + xGA par match)."""
        standings = self._get_standings_cached(league_id)
        if not standings:
            return None, 0

        total_xgf = 0
        total_xga = 0
        total_matches = 0
        for t in standings:
            played = t.get("played", 0) or 0
            xgf = t.get("xgf", 0) or 0
            xga = t.get("xga", 0) or 0
            if played > 0 and xgf > 0 and xga > 0:
                total_xgf += xgf
                total_xga += xga
                total_matches += played

        if total_matches == 0:
            return None, 0

        # xG total par match = xgf_total / (matches / 2)
        # (xgf_total = somme des buts marqués par toutes les équipes)
        xg_per_match = total_xgf / (total_matches / 2) if total_matches > 0 else 0
        return round(xg_per_match, 2), int(total_matches / 2)

    def _get_team_xg(self, team_id, league_id):
        """Retourne les vrais xG d'une équipe depuis get_standings."""
        for t in self._get_standings_cached(league_id):
            if t.get("team_id") == team_id:
                played = t.get("played", 0) or 0
                xg_games = t.get("xg_games", 0) or 0
                if xg_games < 5:
                    return None
                return {
                    "team_name": t.get("team_name", "?"),
                    "played": played,
                    "xg_games": xg_games,
                    "xgf_avg": (t.get("xgf", 0) or 0) / xg_games if xg_games else 0,
                    "xga_avg": (t.get("xga", 0) or 0) / xg_games if xg_games else 0,
                    "gf_avg": (t.get("gf", 0) or 0) / played if played else 0,
                    "ga_avg": (t.get("ga", 0) or 0) / played if played else 0,
                    "attack_overperf": ((t.get("gf", 0) or 0) - (t.get("xgf", 0) or 0)) / xg_games if xg_games else 0,
                    "defense_overperf": ((t.get("ga", 0) or 0) - (t.get("xga", 0) or 0)) / xg_games if xg_games else 0,
                }
        return None

    def safe_compute(self, match, context=None):
        home_id = match.get("home_team_id")
        away_id = match.get("away_team_id")
        league_id = match.get("league_id")

        if not home_id or not away_id or not league_id:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.0,
                warnings=["données manquantes"],
            )

        home = self._get_team_xg(home_id, league_id)
        away = self._get_team_xg(away_id, league_id)

        if home is None or away is None:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.1,
                warnings=["données xG indisponibles"],
            )

        # xG total attendu du match (xgf_home + xgf_away)
        # Les xga sont les buts encaissés par l'adversaire = xgf de l'autre équipe
        # Donc xgf_home + xgf_away suffit
        total_xg = home["xgf_avg"] + away["xgf_avg"]

        # Moyenne xG de la ligue
        league_xg_avg, league_matches = self._compute_league_xg_avg(league_id)

        # Score normalisé par la ligue
        if league_xg_avg and league_xg_avg > 0:
            ratio = total_xg / league_xg_avg
            score = 5.0 + (ratio - 1.0) * 10.0
        else:
            # Fallback : référence universelle
            score = 5.0 + (total_xg / 2.70 - 1.0) * 10.0

        reasons = [f"xG total attendu: {total_xg:.2f}"]
        if league_xg_avg:
            reasons.append(f"xG ligue: {league_xg_avg:.2f}")

        # Ajustement sur/sous-performance attaque
        for label, team in (("home", home), ("away", away)):
            overperf = team["attack_overperf"]
            if overperf > 0.40:
                score -= 0.5
                reasons.append(f"{label} sur-perf attaque (+{overperf:.2f})")
            elif overperf > 0.20:
                score -= 0.25
                reasons.append(f"{label} sur-perf attaque légère (+{overperf:.2f})")
            elif overperf < -0.40:
                score += 0.5
                reasons.append(f"{label} sous-perf attaque ({overperf:.2f})")
            elif overperf < -0.20:
                score += 0.25
                reasons.append(f"{label} sous-perf attaque légère ({overperf:.2f})")

        # Ajustement défense
        for label, team in (("home", home), ("away", away)):
            overperf = team["defense_overperf"]
            if overperf < -0.40:
                score += 0.5
                reasons.append(f"{label} défense sur-régime ({overperf:.2f})")
            elif overperf < -0.20:
                score += 0.25
                reasons.append(f"{label} défense sur-régime légère ({overperf:.2f})")
            elif overperf > 0.40:
                score -= 0.5
                reasons.append(f"{label} défense sous-régime (+{overperf:.2f})")
            elif overperf > 0.20:
                score -= 0.25
                reasons.append(f"{label} défense sous-régime légère (+{overperf:.2f})")

        score = max(0.0, min(10.0, score))

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=round(score, 2),
            confidence=0.85 if (home["xg_games"] >= 10 and away["xg_games"] >= 10) else 0.6,
            raw={
                "home": home, "away": away,
                "total_xg": round(total_xg, 2),
                "league_xg_avg": league_xg_avg,
                "reasons": reasons,
            },
            features={
                "total_xg": round(total_xg, 2),
                "home_attack_overperf": round(home["attack_overperf"], 2),
                "away_attack_overperf": round(away["attack_overperf"], 2),
            },
            warnings=reasons if len(reasons) > 2 else [],
        )

