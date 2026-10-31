# src/layers/l33_squad_depth.py — Couche 33 : Effectif & Profondeur
"""
Analyse la profondeur des effectifs pour détecter les déséquilibres offensifs.

Pour chaque équipe :
  - Récupère les stats des 20 derniers matchs de chaque titulaire et remplaçant
  - Détecte les absents (blessés/suspendus) parmi les titulaires habituels
  - Mesure la perte offensive due aux absences
  - Compare la qualité des remplaçants à celle des titulaires
  - Compte les attaquants titulaires et sur le banc

Score final :
  - Plus offensif → score > 5.0 (favorise Over)
  - Plus défensif → score < 5.0 (favorise Under)
"""

from src.layers.base import BaseLayer, LayerResult


# Cache mémoire par instance (session)
_PLAYER_CACHE = {}
_PLAYER_STATS_CACHE = {}


class SquadDepthLayer(BaseLayer):
    id = 33
    name = "Effectif & Profondeur"

    def __init__(self, bzzoiro):
        self.bzzoiro = bzzoiro

    # ========== CACHE ==========

    def _get_player_profile(self, player_id):
        """Profil joueur (availability, value, position). Cache session."""
        if player_id in _PLAYER_CACHE:
            return _PLAYER_CACHE[player_id]
        try:
            profile = self.bzzoiro.request("GET", f"/players/{player_id}/")
            if not isinstance(profile, dict):
                profile = {}
        except Exception:
            profile = {}
        _PLAYER_CACHE[player_id] = profile
        return profile

    def _get_player_stats(self, player_id, limit=20):
        """20 dernières stats de match. Cache session."""
        key = f"{player_id}_{limit}"
        if key in _PLAYER_STATS_CACHE:
            return _PLAYER_STATS_CACHE[key]

        try:
            data = self.bzzoiro.request(
                "GET", f"/players/{player_id}/stats/",
                params={"limit": limit}
            )
            if isinstance(data, dict):
                stats = data.get("results", [])
            elif isinstance(data, list):
                stats = data
            else:
                stats = []
        except Exception:
            stats = []

        _PLAYER_STATS_CACHE[key] = stats
        return stats

    # ========== ANALYSE D'UN JOUEUR ==========

    def _player_offensive_value(self, player_id):
        """
        Retourne un dict avec les stats offensives moyennes du joueur
        sur ses 20 derniers matchs.
        """
        profile = self._get_player_profile(player_id)
        stats = self._get_player_stats(player_id, limit=20)

        # Infos de base
        position = profile.get("specific_position") or profile.get("position", "")
        availability = profile.get("availability", "available")
        market_value = profile.get("market_value_eur") or 0

        # Si pas de stats (jeune, remplaçant jamais titulaire)
        if not stats:
            return {
                "player_id": player_id,
                "name": profile.get("name", "?"),
                "position": position,
                "availability": availability,
                "market_value": market_value,
                "matches": 0,
                "goals_pm": 0.0,
                "xg_pm": 0.0,
                "assists_pm": 0.0,
                "minutes_pm": 0.0,
                "rating_avg": 0.0,
                "is_offensive": position in ("FWD", "F", "M", "AM", "W"),
            }

        # Calcul moyennes pondérées par les minutes
        n = len(stats)
        total_minutes = sum(s.get("minutes_played", 0) or 0 for s in stats)

        # Pondération : un match de 90 min compte plein, 45 min compte moitié
        # Evite que les remplaçants à 5 min tirent la moyenne vers le bas
        weighted_goals = 0.0
        weighted_xg = 0.0
        weighted_assists = 0.0
        minutes_weight_total = 0.0

        for s in stats:
            mins = s.get("minutes_played", 0) or 0
            weight = mins / 90.0
            weighted_goals += (s.get("goals", 0) or 0) * weight
            weighted_xg += (s.get("expected_goals", 0) or 0) * weight
            weighted_assists += (s.get("goal_assist", 0) or 0) * weight
            minutes_weight_total += weight

        if minutes_weight_total > 0:
            goals_pm = weighted_goals / minutes_weight_total
            xg_pm = weighted_xg / minutes_weight_total
            assists_pm = weighted_assists / minutes_weight_total
        else:
            goals_pm = xg_pm = assists_pm = 0.0

        ratings = [s.get("rating") for s in stats if s.get("rating") is not None]
        rating_avg = sum(ratings) / len(ratings) if ratings else 0.0

        return {
            "player_id": player_id,
            "name": profile.get("name", "?"),
            "position": position,
            "availability": availability,
            "market_value": market_value,
            "matches": n,
            "goals_pm": goals_pm,
            "xg_pm": xg_pm,
            "assists_pm": assists_pm,
            "minutes_pm": total_minutes / n if n else 0,
            "rating_avg": rating_avg,
            "is_offensive": position in ("FWD", "F", "M", "AM", "W"),
        }

    # ========== ANALYSE D'UNE ÉQUIPE ==========

    def _analyze_team(self, lineup_data):
        """Analyse la profondeur d'une équipe."""
        titulaires = lineup_data.get("players", []) or []
        remplacants = lineup_data.get("substitutes", []) or []
        formation = lineup_data.get("formation", "") or ""

        # Analyser les 11 titulaires
        titulaires_data = [self._player_offensive_value(p["id"]) for p in titulaires if p.get("id")]

        # Analyser les remplaçants (limit 7 pour rester rapide)
        remplacants_data = [self._player_offensive_value(p["id"]) for p in remplacants[:7] if p.get("id")]

        # Force offensive des titulaires — SEULEMENT les joueurs offensifs
        offensive_titulaires = [t for t in titulaires_data if t["position"] in ("FWD", "F", "M", "AM", "W")]
        titulaires_attack = sum(t["goals_pm"] + t["xg_pm"] for t in offensive_titulaires)
        titulaires_minutes = sum(t["minutes_pm"] for t in titulaires_data) / max(len(titulaires_data), 1)

        # Attaquants titulaires
        fwd_titulaires = [t for t in titulaires_data if t["position"] in ("FWD", "F")]
        n_fwd = len(fwd_titulaires)

        # Absents (blessés/suspendus)
        absents = [t for t in titulaires_data if t["availability"] not in ("available", None, "")]
        absents_attack = sum(t["goals_pm"] + t["xg_pm"] for t in absents)

        # Qualité des remplaçants (attack par match)
        remplacants_attack = sum(r["goals_pm"] + r["xg_pm"] for r in remplacants_data)
        fwd_remplacants = [r for r in remplacants_data if r["position"] in ("FWD", "F")]

        # Qualité des remplaçants par rapport aux titulaires
        # (1.0 = aussi bon, 0.5 = moitié moins bon)
        titulaires_attack_per_player = titulaires_attack / max(len(offensive_titulaires), 1)
        remplacants_attack_per_player = remplacants_attack / max(len(remplacants_data), 1) if remplacants_data else 0

        if titulaires_attack_per_player > 0:
            depth_ratio = remplacants_attack_per_player / titulaires_attack_per_player
        else:
            depth_ratio = 0.5

        # Formation défensive ou offensive ?
        defensive_formations = {"5-3-2", "5-4-1", "5-2-3", "3-5-2", "3-4-3"}
        offensive_formations = {"4-3-3", "3-4-3", "4-2-4", "4-1-5"}
        if formation in defensive_formations:
            formation_factor = -1
        elif formation in offensive_formations:
            formation_factor = 1
        else:
            formation_factor = 0

        # Valeur marchande moyenne (mesure la qualité globale)
        mv_titulaires = [t["market_value"] for t in titulaires_data if t["market_value"] > 0]
        avg_mv = sum(mv_titulaires) / len(mv_titulaires) if mv_titulaires else 0

        return {
            "team_name": lineup_data.get("team_name", "?"),
            "formation": formation,
            "formation_factor": formation_factor,
            "n_titulaires": len(titulaires_data),
            "n_remplacants": len(remplacants_data),
            "n_fwd_titulaires": n_fwd,
            "n_fwd_remplacants": len(fwd_remplacants),
            "attack_per_player": round(titulaires_attack_per_player, 3),
            "remplacants_attack_per_player": round(remplacants_attack_per_player, 3),
            "depth_ratio": round(depth_ratio, 3),
            "absents_count": len(absents),
            "absents_attack_lost": round(absents_attack, 3),
            "avg_market_value": round(avg_mv, 0),
            "titulaires_details": titulaires_data,
            "absents_names": [t["name"] for t in absents],
        }

    # ========== SCORE FINAL ==========

    def compute(self, match, context):
        event_id = match.get("id") or match.get("event_id")
        if not event_id:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.0,
                warnings=["event_id manquant"],
            )

        # Récupérer les lineups
        try:
            lineup_data = self.bzzoiro.get_event_lineups(event_id)
        except Exception as e:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.1,
                warnings=[f"lineups indisponibles: {str(e)[:50]}"],
            )

        if not lineup_data or not isinstance(lineup_data, dict):
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.1,
                warnings=["lineups vides"],
            )

        lineups = lineup_data.get("lineups", {})
        home_data = lineups.get("home", {})
        away_data = lineups.get("away", {})

        if not home_data or not away_data:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.1,
                warnings=["lineups incomplets (home ou away manquant)"],
            )

        # Vérifier statut
        status = lineup_data.get("lineup_status", "")
        if status not in ("confirmed", "probable", "expected"):
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.2,
                warnings=[f"lineup_status={status} (pas confirmé)"],
            )

        # Analyser les 2 équipes
        home = self._analyze_team(home_data)
        away = self._analyze_team(away_data)

        # ========== CALCUL DU SCORE ==========

        score = 5.0
        reasons = []

        # 1. Force offensive totale (les deux équipes cumulées)
        # attack_per_player : normalement 0.3-0.8 pour un top joueur
        total_attack = home["attack_per_player"] + away["attack_per_player"]
        if total_attack > 1.2:
            score += 0.8
            reasons.append(f"attaque cumulée forte ({total_attack:.2f})")
        elif total_attack > 0.9:
            score += 0.4
            reasons.append(f"attaque cumulée correcte ({total_attack:.2f})")
        elif total_attack < 0.4:
            score -= 0.6
            reasons.append(f"attaque cumulée faible ({total_attack:.2f})")

        # 2. Nombre d'attaquants titulaires (cumulé)
        total_fwd = home["n_fwd_titulaires"] + away["n_fwd_titulaires"]
        if total_fwd >= 4:
            score += 0.5
            reasons.append(f"{total_fwd} attaquants titulaires cumulés (offensif)")
        elif total_fwd <= 1:
            score -= 0.6
            reasons.append(f"{total_fwd} attaquant(s) titulaire(s) cumulé(s) (défensif)")

        # 3. Formations
        formation_sum = home["formation_factor"] + away["formation_factor"]
        if formation_sum >= 1:
            score += 0.3
            reasons.append("formation(s) offensive(s)")
        elif formation_sum <= -1:
            score -= 0.3
            reasons.append("formation(s) défensive(s)")

        # 4. Profondeur (les remplaçants peuvent-ils rivaliser ?)
        avg_depth = (home["depth_ratio"] + away["depth_ratio"]) / 2
        if avg_depth < 0.4:
            score -= 0.4
            reasons.append(f"profondeur faible ({avg_depth:.2f}) → banc ne rivalise pas")
        elif avg_depth > 0.8:
            score += 0.2
            reasons.append(f"bonne profondeur ({avg_depth:.2f})")

        # 5. Absents côté offensif
        total_absents_attack = home["absents_attack_lost"] + away["absents_attack_lost"]
        if total_absents_attack > 0.5:
            score -= 0.5
            reasons.append(f"pertes offensives dues aux absents ({total_absents_attack:.2f}/match)")

        # 6. Qualité globale (market value)
        avg_mv = (home["avg_market_value"] + away["avg_market_value"]) / 2
        if avg_mv > 15_000_000:
            score += 0.2
            reasons.append(f"effectifs de qualité (MV moyenne {avg_mv/1e6:.1f}M€)")

        score = max(0.0, min(10.0, score))

        # Confiance : haute si lineups confirmés et données complètes
        confidence = 0.75 if status == "confirmed" else 0.5

        return LayerResult(
            layer_id=self.id,
            layer_name=self.name,
            score=round(score, 2),
            confidence=confidence,
            raw={
                "home": home,
                "away": away,
                "reasons": reasons,
                "lineup_status": status,
            },
            features={
                "total_attack": round(total_attack, 2),
                "total_fwd": total_fwd,
                "avg_depth": round(avg_depth, 2),
                "absents_attack": round(total_absents_attack, 2),
            },
            warnings=reasons if reasons else [],
        )
