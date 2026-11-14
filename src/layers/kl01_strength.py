"""
Kenny Football v3.0 — Layer L01 : Strength.
Version finale verrouillée : fenêtre 15 matchs, rejet strict, poids 1.5.
"""

from __future__ import annotations

from .kbase import Layer, LayerResult

COMP_WEIGHTS = {
    "league": 1.0,
    "europe": 1.2,
    "cup": 0.8,
    "friendly": 0.3,
}

WINDOW = 15
W_L1 = 1.5


class KL01Strength(Layer):
    id = "l01"
    name = "Strength"
    weight_key = "l01"

    def run(self, match: dict, ctx: dict) -> LayerResult:
        res = LayerResult(confidence=1.0)  # sera ajusté selon min_matches

        if not ctx.get("api_football"):
            # API-Football absent : on continue avec absences neutres
            res.warnings.append("L1: absences non vérifiées (API-Football absent)")

        home_id = match["home_team_id"]
        away_id = match["away_team_id"]
        league_id = match["league_id"]
        nb_teams = match.get("league_nb_teams")

        standings = ctx["bzzoiro"].fetch_league_standings(league_id)
        
        # Fallback : si standings absents (match international, coupe),
        # on calcule un pos_map approximatif depuis k_team_matches
        if not standings or not nb_teams:
            res.warnings.append("L1: standings absents → fallback sans pondération qualité")
            pos_map = {}
        else:
            pos_map = {row["team_id"]: row["position"] for row in standings}

        # Si une équipe n'est pas dans le classement, on continue quand même
        if home_id not in pos_map or away_id not in pos_map:
            res.warnings.append("L1: standings adversaire partiel → pondération neutre")
            # On ajoute les équipes manquantes avec position médiane
            nb_teams = nb_teams or 20
            mid = nb_teams // 2
            if home_id not in pos_map:
                pos_map[home_id] = mid
            if away_id not in pos_map:
                pos_map[away_id] = mid

        home_matches = ctx["bzzoiro"].fetch_team_matches(home_id, limit=WINDOW)
        away_matches = ctx["bzzoiro"].fetch_team_matches(away_id, limit=WINDOW)

        if not home_matches or not away_matches:
            res.rejected = True
            res.confidence = 0.0
            res.warnings.append("L1: aucun match disponible")
            return res

        min_matches = min(len(home_matches), len(away_matches))

        # Rejet strict uniquement si vraiment trop peu de données
        if min_matches < 5:
            res.rejected = True
            res.confidence = 0.0
            res.warnings.append(f"L1: données insuffisantes ({min_matches} matchs, <3)")
            return res

        # Dégradation progressive de la confiance
        if min_matches >= WINDOW:
            data_confidence = 1.0
        elif min_matches >= 10:
            data_confidence = 0.85
            res.warnings.append(f"L1: fenêtre réduite ({min_matches} matchs, <15)")
        else:
            data_confidence = 0.60
            res.warnings.append(f"L1: fenêtre très réduite ({min_matches} matchs, <10)")

        fixture_id = match.get("fixture_id")
        if fixture_id is None:
            res.rejected = True
            res.confidence = 0.0
            res.warnings.append("L1: fixture_id absent (absences non vérifiables)")
            return res

        home_abs = ctx["api_football"].fetch_absences(fixture_id, home_id) if ctx.get("api_football") else []
        away_abs = ctx["api_football"].fetch_absences(fixture_id, away_id) if ctx.get("api_football") else []
        if home_abs is None:
            home_abs = []
            res.warnings.append("L1: home_abs None → fallback []")
        if away_abs is None:
            away_abs = []
            res.warnings.append("L1: away_abs None → fallback []")

        attack_attack = self._attack_attack(home_matches, away_matches, pos_map, nb_teams)
        ha_vs_ad      = self._attack_vs_defense(home_matches, away_matches, pos_map, nb_teams)
        hd_vs_aa      = self._attack_vs_defense(away_matches, home_matches, pos_map, nb_teams)
        contexte      = self._contexte(home_matches, away_matches)
        absences      = self._absences(home_abs, away_abs)

        score = (
            attack_attack * 0.20 +
            ha_vs_ad     * 0.20 +
            hd_vs_aa     * 0.20 +
            contexte     * 0.20 +
            absences     * 0.20
        )
        score = max(0.0, min(10.0, score))

        res.score = round(score, 2)
        res.confidence = data_confidence
        # Détection favori écrasant : si une équipe a un score très haut et l'autre très bas
        # (proxy : écart entre attaque_attack et les autres sous-scores)
        heavy_fav = False
        if attack_attack > 7.0 and contexte < 4.0:
            heavy_fav = True
            res.warnings.append("L1: favori probable (attaque forte, contexte faible)")
        
        # Détection favori écrasant (avant le meta)
        heavy_fav = attack_attack > 7.0 and contexte < 4.0
        if heavy_fav:
            res.warnings.append("L1: favori probable (attaque forte, contexte faible)")

        res.meta = {
            "attack_attack": round(attack_attack, 2),
            "home_attack_vs_away_defense": round(ha_vs_ad, 2),
            "home_defense_vs_away_attack": round(hd_vs_aa, 2),
            "contexte": round(contexte, 2),
            "absences": round(absences, 2),
            "window": WINDOW,
            "min_matches": min_matches,
            "data_confidence": data_confidence,
            "heavy_favorite": heavy_fav,
            "weight": W_L1,
        }
        return res

    def _weighted_goals(self, matches, pos_map, nb_teams):
        num, den = 0.0, 0.0
        for m in matches:
            comp_w = COMP_WEIGHTS.get(m.get("competition_type", "league"), 1.0)
            pos = pos_map.get(m.get("opponent_id"))
            if pos is None:
                continue
            quality_w = ((nb_teams - pos + 1) / nb_teams) * 2.0
            w = comp_w * quality_w
            num += m.get("goals_for", 0) * w
            den += w
        return num / den if den else 0.0

    def _weighted_conceded(self, matches, pos_map, nb_teams):
        num, den = 0.0, 0.0
        for m in matches:
            comp_w = COMP_WEIGHTS.get(m.get("competition_type", "league"), 1.0)
            pos = pos_map.get(m.get("opponent_id"))
            if pos is None:
                continue
            quality_w = ((nb_teams - pos + 1) / nb_teams) * 2.0
            w = comp_w * quality_w
            num += m.get("goals_against", 0) * w
            den += w
        return num / den if den else 0.0

    def _attack_attack(self, home_matches, away_matches, pos_map, nb_teams):
        h = self._weighted_goals(home_matches, pos_map, nb_teams)
        a = self._weighted_goals(away_matches, pos_map, nb_teams)
        return min(((h + a) / 3.0) * 10.0, 10.0)

    def _attack_vs_defense(self, att_matches, def_matches, pos_map, nb_teams):
        att = self._weighted_goals(att_matches, pos_map, nb_teams)
        dfc = self._weighted_conceded(def_matches, pos_map, nb_teams)
        expected = (att + dfc) / 2.0
        return min((expected / 3.0) * 10.0, 10.0)

    def _contexte(self, home_matches, away_matches):
        def form(matches):
            last5 = matches[:5]
            if not last5:
                return 5.0
            pts = 0
            for m in last5:
                r = m.get("result", "")
                pts += 3 if r == "W" else 1 if r == "D" else 0
            return (pts / (len(last5) * 3)) * 10.0

        base = (form(home_matches) + form(away_matches)) / 2.0

        def rest_adj(matches):
            d = matches[0].get("days_since_last_match") if matches else None
            if d is None:
                return 0.0
            if d < 3:
                return -1.0
            if d > 6:
                return 1.0
            return 0.0

        adj = (rest_adj(home_matches) + rest_adj(away_matches)) / 2.0
        return max(min(base + adj, 10.0), 0.0)

    def _absences(self, home_abs, away_abs):
        def impact(abs_list):
            total = 0.0
            for p in abs_list:
                total += 1.5 if p.get("player_role") == "starter" else 0.5
            return min(total, 10.0)

        combined = (impact(home_abs) + impact(away_abs)) / 2.0
        return max(10.0 - combined, 0.0)


layer = KL01Strength()
