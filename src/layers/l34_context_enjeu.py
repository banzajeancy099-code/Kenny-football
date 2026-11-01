# src/layers/l34_context_enjeu.py — Couche 34 : Contexte de classement & enjeu
"""
Analyse l'enjeu réel d'un match pour chaque équipe.

Pour chaque équipe :
  - Position au classement et points
  - Écart avec le 1er, la zone Europe, la zone relégation
  - Enjeu structurel : bataille pour le titre / maintien / rien à jouer
  - Type de match (amical, coupe, championnat, derby)
  - Détection de rotation probable (match important suivant)

Score final :
  - Enjeu MAX (bataille titre/maintien, derby, finale) → score > 6.0
  - Enjeu normal → 5.0
  - Enjeu FAIBLE (amical, équipe déjà championne/reléguée) → score < 4.0
"""

from src.layers.base import BaseLayer, LayerResult


# Ligues qui sont des compétitions amicales (à compléter)
FRIENDLY_LEAGUES = set()  # Bzzoiro n'a probablement pas d'ID dédié

# Zones de classement (basé sur la structure Bzzoiro observée)
ZONE_CHAMPION = "cl"         # Copa Libertadores / Champions League
ZONE_RELEGATION_KEYWORDS = ("relegation", "relegated")


class ContextEnjeuLayer(BaseLayer):
    id = 34
    name = "Contexte & Enjeu"

    def __init__(self, bzzoiro):
        self.bzzoiro = bzzoiro
        self._standings_cache = {}

    def _get_standings_cached(self, league_id):
        if league_id in self._standings_cache:
            return self._standings_cache[league_id]
        try:
            standings = self.bzzoiro.get_standings(league_id) or []
        except Exception:
            standings = []
        self._standings_cache[league_id] = standings
        return standings

    def _find_team_in_standings(self, team_id, league_id):
        """Retourne (position, points, played, zone, ecart_avec_1er, ecart_avec_relegation)."""
        standings = self._get_standings_cached(league_id)
        if not standings:
            return None

        team_data = None
        for t in standings:
            if t.get("team_id") == team_id:
                team_data = t
                break

        if not team_data:
            return None

        position = team_data.get("position")
        points = team_data.get("pts", 0)
        played = team_data.get("played", 0)
        zone = team_data.get("zone") or {}

        # Écart avec le 1er
        leader_points = standings[0].get("pts", 0) if standings else points
        gap_to_leader = leader_points - points

        # Écart avec la zone de relégation (les 4 derniers en général)
        relegation_points = None
        if len(standings) >= 4:
            relegation_zone = standings[-4:]
            if relegation_zone:
                relegation_points = relegation_zone[0].get("pts", 0)
                if relegation_points is not None and relegation_points > points:
                    relegation_points = points

        gap_to_relegation = (points - relegation_points) if relegation_points is not None else None

        return {
            "position": position,
            "points": points,
            "played": played,
            "zone": zone.get("label") if isinstance(zone, dict) else str(zone),
            "gap_to_leader": gap_to_leader,
            "gap_to_relegation": gap_to_relegation,
        }

    def _compute_team_enjeu(self, team_id, league_id, position):
        """Calcule l'enjeu d'une équipe (0-10)."""
        if not position:
            return 5.0, ["position indisponible"]

        pos = position.get("position")
        points = position.get("points", 0)
        played = position.get("played", 1)
        gap_leader = position.get("gap_to_leader", 0)
        gap_releg = position.get("gap_to_relegation")

        reasons = []
        score = 5.0

        # 1. Enjeu pour le titre (top 4)
        if pos and pos <= 4:
            if gap_leader is not None and gap_leader <= 8:
                score += 0.9
                reasons.append(f"{pos}e à {gap_leader} pts du titre → enjeu MAX")
            elif gap_leader is not None and gap_leader > 15:
                score -= 0.5
                reasons.append(f"{pos}e à {gap_leader} pts du titre → course terminée")

        # 2. Enjeu pour la relégation (4 derniers)
        if pos:
            total = len(self._get_standings_cached(league_id))
            if total > 0 and pos >= total - 3:
                score += 1.0
                reasons.append(f"{pos}e (zone relégation) → enjeu MAX")

        # 3. Milieu de tableau sans enjeu
        if pos and 8 <= pos <= 14:
            score -= 0.2
            reasons.append(f"{pos}e (milieu de tableau) → enjeu modéré")

        return max(0.0, min(10.0, score)), reasons

    def compute(self, match, context):
        league_id = match.get("league_id")
        home_id = match.get("home_team_id")
        away_id = match.get("away_team_id")

        if not league_id or not home_id or not away_id:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.0,
                warnings=["données manquantes (league_id ou team_id)"],
            )

        # === Analyse de chaque équipe ===
        home_pos = self._find_team_in_standings(home_id, league_id)
        away_pos = self._find_team_in_standings(away_id, league_id)

        home_enjeu, home_reasons = self._compute_team_enjeu(home_id, league_id, home_pos)
        away_enjeu, away_reasons = self._compute_team_enjeu(away_id, league_id, away_pos)

        # === Score combiné ===
        # Un match avec 2 équipes à fort enjeu → plus de buts (les équipes se donnent à fond)
        # Un match avec 2 équipes sans enjeu → moins de buts (match amical de fait)
        avg_enjeu = (home_enjeu + away_enjeu) / 2
        min_enjeu = min(home_enjeu, away_enjeu)

        # On privilégie le minimum : si une équipe n'a pas d'enjeu, le match est moins fiable
        score = min_enjeu * 0.6 + avg_enjeu * 0.4

        reasons = []
        if home_reasons:
            reasons.append(f"home: {home_reasons[0]}")
        if away_reasons:
            reasons.append(f"away: {away_reasons[0]}")

        # === Détection de type de match ===
        stage = str(match.get("stage") or "").lower()
        is_derby = match.get("is_local_derby", False)

        if any(k in stage for k in ("final", "semifinal")):
            score += 0.5
            reasons.append(f"match {stage} → enjeu MAX")

        if is_derby:
            score += 0.3
            reasons.append("derby → enjeu supplémentaire")

        score = max(0.0, min(10.0, score))

        # Confiance
        confidence = 0.7 if (home_pos and away_pos) else 0.3

        return LayerResult(
            layer_id=self.id,
            layer_name=self.name,
            score=round(score, 2),
            confidence=confidence,
            raw={
                "home": {
                    "position": home_pos,
                    "enjeu": round(home_enjeu, 2),
                    "reasons": home_reasons,
                },
                "away": {
                    "position": away_pos,
                    "enjeu": round(away_enjeu, 2),
                    "reasons": away_reasons,
                },
                "reasons": reasons,
            },
            features={
                "home_enjeu": round(home_enjeu, 2),
                "away_enjeu": round(away_enjeu, 2),
                "avg_enjeu": round(avg_enjeu, 2),
                "is_derby": is_derby,
            },
            warnings=reasons if reasons else [],
        )
