"""
Kenny Football v3.0 — Layer L02 : Over 2.5 (v5.0, 19 signaux).

Référence :
- 3 croisements (C1, C2, C3) + expected_goals
- 8 ajustements : forme, xG, H2H, contexte, aller/retour, momentum 3v5,
  buts tardifs, arbitre
- 6 corrections : motivation, streak, météo extrême, forme dom/ext,
  validation croisée cotes, détection match truqué
- Feedback loop 3 niveaux (global / ligue / type)
- Cohérence des 3 croisements

Rejet strict :
- played < 5 pour une équipe
- splits dom/ext indisponibles
- cote_over < 1.20 ET expected_goals < 2.5  (match truqué)
- cote_under < 1.20 ET expected_goals > 3.0 (match truqué)

Dépendances DB (via ctx["db"] = module kdb) :
- kget_team_streak(team_id)
- kget_late_goals_ratio(team_id)
- kget_referee_stats(referee_id)
- kget_layer_feedback(layer_id=2, scope=..., ...)

Dépendances API (via ctx) :
- ctx["bzzoiro"] pour xG, H2H, forme, splits
"""

from __future__ import annotations

import statistics

from .kbase import Layer, LayerResult

W_OVER = 1.5
LAYER_ID = 2
FEEDBACK_LIMIT = 15
FEEDBACK_MIN_MATCHES = 15
FEEDBACK_CALIB_MIN = 30


class KL02Over(Layer):
    id = "l02"
    name = "Over 2.5"
    weight_key = "l02"

    def run(self, match: dict, ctx: dict) -> LayerResult:
        res = LayerResult(confidence=1.0)
        warnings = []
        meta = {}

        data = self._collect(match, ctx, warnings)
        if data.get("rejected"):
            res.rejected = True
            res.confidence = 0.0
            res.warnings = warnings + data.get("reasons", [])
            return res

        # ─────────────────────────────────────────
        # FILTRE F1 : favori écrasant (cote 1X2 < 1.25)
        # ─────────────────────────────────────────
        is_heavy, reason_heavy = self._is_heavy_favorite(match, data)
        if is_heavy:
            res.rejected = True
            res.confidence = 0.0
            res.warnings = warnings + [reason_heavy]
            return res

        # ─────────────────────────────────────────
        # FILTRE F2 : DÉSACTIVÉ (test 7 nov : élimine les meilleurs gagnants)
        # Conservé en commentaire pour usage futur éventuel
        # ─────────────────────────────────────────
        # is_convinced, reason_convinced = self._is_under_market_convinced(data)
        # if is_convinced:
        #     res.rejected = True
        #     res.confidence = 0.0
        #     res.warnings = warnings + [reason_convinced]
        #     return res

        # ─────────────────────────────────────────
        # FILTRE F3 : ligue fermée fin de saison (malus)
        # ─────────────────────────────────────────
        closed_malus = self._is_closed_league_end_season(match, data)
        if closed_malus < 0:
            warnings.append(f"F3: ligue fermée fin saison (malus {closed_malus:.1f})")
            meta["closed_league_malus"] = closed_malus

        data = self._apply_croisements(data, warnings, meta)
        
        # Sauvegarde EG initial (avant tous les ajustements)
        eg_initial = data["expected_goals"]
        data = self._apply_forme(data, warnings, meta)
        data = self._apply_xg(data, warnings, meta)
        data = self._apply_h2h(data, warnings, meta)
        data = self._apply_contexte(data, ctx, warnings, meta)
        data = self._apply_aller_retour(data, warnings, meta)
        data = self._apply_momentum_3v5(data, warnings, meta)
        data = self._apply_late_goals(data, ctx, warnings, meta)
        data = self._apply_referee(data, ctx, warnings, meta)
        data = self._apply_motivation(data, warnings, meta)
        data = self._apply_streak(data, ctx, warnings, meta)
        data = self._apply_weather(data, warnings, meta)
        data = self._apply_form_dom_ext(data, warnings, meta)

        # PLAFONNEMENT GLOBAL : EG ne peut varier que de ±30% par rapport à l'initial
        if eg_initial > 0:
            eg_final = data["expected_goals"]
            ratio = eg_final / eg_initial
            if ratio > 1.30:
                data["expected_goals"] = eg_initial * 1.30
                warnings.append(f"L02: plafond EG +30% appliqué (ratio {ratio:.2f})")
            elif ratio < 0.70:
                data["expected_goals"] = eg_initial * 0.70
                warnings.append(f"L02: plafond EG -30% appliqué (ratio {ratio:.2f})")
            meta["eg_initial"] = round(eg_initial, 3)
            meta["eg_final"] = round(data["expected_goals"], 3)
            meta["eg_ratio"] = round(ratio, 3)

        score = self._base_score(data, warnings, meta)
        score = self._validate_market(score, data, warnings, meta)

        # Applique le malus F3 (ligue fermée fin saison)
        if meta.get("closed_league_malus"):
            score += meta["closed_league_malus"]

        if self._is_fake_match(data):
            res.rejected = True
            res.confidence = 0.0
            res.warnings = warnings + ["incohérence marché (cote anormale)"]
            return res

        score, feedback_breakdown = self._apply_feedback(
            score, data, ctx, warnings, meta
        )

        score = max(0.0, min(10.0, score))
        confidence = self._compute_confidence(data, meta)

        res.score = round(score, 2)
        res.confidence = confidence
        res.warnings = warnings
        res.meta = {
            **meta,
            "expected_goals": round(data.get("expected_goals", 0.0), 3),
            "feedback_breakdown": feedback_breakdown,
            "weight": W_OVER,
            # Champs exposés pour backtest
            "xgf_home": data.get("home_xgf"),
            "xgf_away": data.get("away_xgf"),
            "home_form_gf": data.get("home_form_gf"),
            "away_form_gf": data.get("away_form_gf"),
            "home_form_3": data.get("home_form_3"),
            "away_form_3": data.get("away_form_3"),
            "h2h_avg_goals": (match.get("head_to_head") or {}).get("avg_total_goals"),
        }
        return res

    # ------------------------------------------------------------------ #
    #  Méthodes à remplir dans les blocs suivants
    # ------------------------------------------------------------------ #
    def _collect(self, match, ctx, warnings):
        data = {}
        bzz = ctx.get("bzzoiro")

        data["home_team_id"] = match["home_team_id"]
        data["away_team_id"] = match["away_team_id"]
        data["league_id"] = match.get("league_id")
        data["fixture_id"] = match.get("fixture_id") or match.get("id")
        data["match_type"] = match.get("match_type")
        data["competition_context"] = match.get("competition_context", {})

        home = bzz.fetch_team_splits(match["home_team_id"]) if bzz else None
        away = bzz.fetch_team_splits(match["away_team_id"]) if bzz else None
        if not home or not away:
            data["rejected"] = True
            data["reasons"] = ["splits domicile/extérieur indisponibles"]
            return data

        played_h = home.get("played", 0)
        played_a = away.get("played", 0)
        min_played = min(played_h, played_a)

        if min_played < 5:
            data["rejected"] = True
            data["reasons"] = [f"données insuffisantes ({min_played} matchs, <3)"]
            return data

        data["played_min"] = min_played
        if min_played < 5:
            warnings.append(f"L2: fenêtre réduite ({min_played} matchs, <5)")

        keys = ["home_gf_avg", "home_ga_avg", "away_gf_avg", "away_ga_avg"]
        if any(home.get(k) is None or away.get(k) is None for k in keys):
            data["rejected"] = True
            data["reasons"] = ["splits domicile/extérieur indisponibles"]
            return data

        data["home_gf_avg"] = float(home["home_gf_avg"])
        data["home_ga_avg"] = float(home["home_ga_avg"])
        data["away_gf_avg"] = float(away["away_gf_avg"])
        data["away_ga_avg"] = float(away["away_ga_avg"])

        data["home_form_gf"] = self._safe_float(home.get("form_gf"), warnings, "forme récente indisponible")
        data["away_form_gf"] = self._safe_float(away.get("form_gf"), warnings, "forme récente indisponible")
        data["home_form_3"] = self._safe_float(home.get("form_gf_3"), warnings, "forme récente indisponible")
        data["away_form_3"] = self._safe_float(away.get("form_gf_3"), warnings, "forme récente indisponible")

        data["home_xgf"] = self._safe_float(home.get("xgf"), warnings, "xG indisponible")
        data["away_xgf"] = self._safe_float(away.get("xgf"), warnings, "xG indisponible")
        data["league_xg"] = self._safe_float(match.get("league_xg"), warnings, "xG indisponible")

        data["over_rate"] = self._safe_float(match.get("over_rate"), warnings, None)
        data["cote_over"] = match.get("cote_over")
        data["cote_under"] = match.get("cote_under")

        h2h = bzz.fetch_h2h(match["home_team_id"], match["away_team_id"], match) if bzz else None
        data["h2h"] = h2h or []
        if len(data["h2h"]) < 3:
            warnings.append("H2H insuffisant (< 3 matchs)")

        # Weather directement depuis Bzzoiro
        weather_raw = match.get("weather") or {}
        data["weather"] = {
            "condition": weather_raw.get("description") or weather_raw.get("code"),
            "wind_kmh": weather_raw.get("wind_speed"),
            "temp_c": weather_raw.get("temperature_c"),
        }
        data["unavailable_players"] = match.get("unavailable_players") or []
        data["lineups"] = match.get("lineups")
        if not data["lineups"] and not data["unavailable_players"]:
            warnings.append("lineups officiels indisponibles")

        data["previous_leg_event_id"] = match.get("previous_leg_event_id")
        data["previous_leg_score"] = match.get("previous_leg_score")
        data["referee_id"] = match.get("referee_id")
        data["home_position"] = match.get("home_position")
        data["away_position"] = match.get("away_position")
        data["home_form_gf_dom"] = self._safe_float(home.get("form_gf_dom"), warnings, None)
        data["home_form_gf_ext"] = self._safe_float(home.get("form_gf_ext"), warnings, None)
        data["away_form_gf_dom"] = self._safe_float(away.get("form_gf_dom"), warnings, None)
        data["away_form_gf_ext"] = self._safe_float(away.get("form_gf_ext"), warnings, None)

        return data

    def _safe_float(self, v, warnings, warn_msg):
        if v is None:
            if warn_msg:
                warnings.append(warn_msg)
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            if warn_msg:
                warnings.append(warn_msg)
            return None
    def _apply_croisements(self, data, warnings, meta):
        c1 = data["home_gf_avg"] + data["away_gf_avg"]
        c2 = data["home_gf_avg"] + data["away_ga_avg"]
        c3 = data["home_ga_avg"] + data["away_gf_avg"]
        data["c1"], data["c2"], data["c3"] = c1, c2, c3

        if len({c1, c2, c3}) > 1:
            ecart = statistics.pstdev([c1, c2, c3])
        else:
            ecart = 0.0
        data["ecart_type"] = ecart

        if ecart < 0.5:
            cons = 1.0
        elif ecart < 1.0:
            cons = 0.8
        else:
            cons = 0.5
        data["consistency_score"] = cons
        if cons < 0.6:
            warnings.append("croisements incohérents (écart-type > 1.0)")

        data["expected_goals"] = (c1 + c2 + c3) / 3.0

        meta["c1"] = round(c1, 3)
        meta["c2"] = round(c2, 3)
        meta["c3"] = round(c3, 3)
        meta["consistency_score"] = cons
        meta["ecart_type"] = round(ecart, 3)
        return data
    def _apply_forme(self, data, warnings, meta):
        if data["home_form_gf"] is None or data["away_form_gf"] is None:
            meta["form_factor"] = None
            return data
        form_avg = (data["home_form_gf"] + data["away_form_gf"]) / 2.0
        base = data["expected_goals"] / 2.0
        if base <= 0:
            meta["form_factor"] = None
            return data
        form_factor = form_avg / base
        if form_factor > 1.15:
            data["expected_goals"] *= 1.05
        elif form_factor < 0.85:
            data["expected_goals"] *= 0.95
        meta["form_factor"] = round(form_factor, 3)
        return data
    def _apply_xg(self, data, warnings, meta):
        if data["home_xgf"] is None or data["away_xgf"] is None:
            meta["xg_factor"] = None
            return data
        xg_avg = data["home_xgf"] + data["away_xgf"]
        if data["expected_goals"] <= 0:
            meta["xg_factor"] = None
            return data
        xg_factor = xg_avg / data["expected_goals"]
        if xg_factor > 1.10:
            data["expected_goals"] *= 1.04
        elif xg_factor < 0.90:
            data["expected_goals"] *= 0.96
        meta["xg_factor"] = round(xg_factor, 3)
        return data
    def _apply_h2h(self, data, warnings, meta):
        h2h = data.get("h2h") or []
        if len(h2h) < 3:
            meta["h2h_factor"] = None
            return data
        goals = [float(m.get("total_goals", 0)) for m in h2h if m.get("total_goals") is not None]
        if not goals:
            meta["h2h_factor"] = None
            return data
        avg = sum(goals) / len(goals)
        h2h_factor = avg / 2.5
        if h2h_factor < 0.7:
            data["expected_goals"] *= 0.95
        elif h2h_factor > 1.3:
            data["expected_goals"] *= 1.05
        meta["h2h_factor"] = round(h2h_factor, 3)
        return data
    def _apply_contexte(self, data, ctx, warnings, meta):
        adj = 1.0
        weather = data.get("weather") or {}
        if weather.get("condition") == "heavy_rain":
            adj *= 0.95

        unavailable = data.get("unavailable_players") or []
        starters_out = sum(1 for p in unavailable if p.get("player_role") == "starter")
        if starters_out >= 3:
            adj *= 0.95

        hp = data.get("home_position")
        ap = data.get("away_position")
        if hp in (1, 2, 3) or ap in (1, 2, 3):
            adj *= 1.05
        if hp and hp >= 17 or ap and ap >= 17:
            adj *= 1.05

        lineups = data.get("lineups") or {}
        star_out = lineups.get("star_striker_absent") if isinstance(lineups, dict) else None
        if star_out:
            adj *= 0.90
            warnings.append("attaquant vedette absent des lineups")

        data["expected_goals"] *= adj
        meta["context_adjustment"] = round(adj, 3)
        return data
    def _apply_aller_retour(self, data, warnings, meta):
        if not data.get("previous_leg_event_id"):
            meta["aller_retour_adjustment"] = None
            return data
        prev = data.get("previous_leg_score") or {}
        trailing = prev.get("home_trailing") or prev.get("away_trailing")
        if trailing:
            data["expected_goals"] *= 1.05
            meta["aller_retour_adjustment"] = 1.10
        else:
            meta["aller_retour_adjustment"] = 1.0
        return data
    def _apply_momentum_3v5(self, data, warnings, meta):
        if any(data.get(k) is None for k in ("home_form_3", "away_form_3", "home_form_gf", "away_form_gf")):
            meta["momentum_3v5_adjustment"] = None
            return data
        form_3 = (data["home_form_3"] + data["away_form_3"]) / 2.0
        form_5 = (data["home_form_gf"] + data["away_form_gf"]) / 2.0
        if form_5 <= 0:
            meta["momentum_3v5_adjustment"] = None
            return data
        if form_3 > form_5 * 1.3:
            data["expected_goals"] *= 1.04
            meta["momentum_3v5_adjustment"] = 1.04
        elif form_3 < form_5 * 0.7:
            data["expected_goals"] *= 0.96
            meta["momentum_3v5_adjustment"] = 0.92
        else:
            meta["momentum_3v5_adjustment"] = 1.0
        return data
    def _apply_late_goals(self, data, ctx, warnings, meta):
        db = ctx.get("db")
        if db is None:
            warnings.append("buts tardifs indisponibles")
            meta["late_goals_adjustment"] = None
            return data
        ratios = []
        for key in ("home_team_id", "away_team_id"):
            tid = data.get(key) or ctx.get("match", {}).get(key)
            if tid is None:
                ratios.append(None)
                continue
            try:
                ratios.append(db.kget_late_goals_ratio(tid))
            except Exception:
                ratios.append(None)
        valid = [r for r in ratios if r is not None]
        if not valid:
            warnings.append("buts tardifs indisponibles")
            meta["late_goals_adjustment"] = None
            return data
        avg = sum(valid) / len(valid)
        if avg > 0.35:
            data["expected_goals"] *= 1.03
            meta["late_goals_adjustment"] = 1.03
        else:
            meta["late_goals_adjustment"] = 1.0
        return data
    def _apply_referee(self, data, ctx, warnings, meta):
        rid = data.get("referee_id")
        db = ctx.get("db")
        if rid is None or db is None:
            warnings.append("arbitre indisponible")
            meta["referee_adjustment"] = None
            return data
        try:
            stats = db.kget_referee_stats(rid)
        except Exception:
            stats = None
        if not stats or stats.get("goals_avg") is None:
            warnings.append("arbitre indisponible")
            meta["referee_adjustment"] = None
            return data
        avg = float(stats["goals_avg"])
        if avg > 2.8:
            data["expected_goals"] *= 1.03
            meta["referee_adjustment"] = 1.03
        elif avg < 2.2:
            data["expected_goals"] *= 0.97
            meta["referee_adjustment"] = 0.95
        else:
            meta["referee_adjustment"] = 1.0
        return data
    def _apply_motivation(self, data, warnings, meta):
        adj = 1.0
        ctx_flag = data.get("competition_context") or {}
        if ctx_flag.get("already_qualified"):
            adj *= 0.95
            warnings.append("équipe déjà qualifiée → fait tourner")
        if ctx_flag.get("must_win"):
            adj *= 1.05
        data["expected_goals"] *= adj
        meta["motivation_adjustment"] = round(adj, 3)
        return data
    def _apply_streak(self, data, ctx, warnings, meta):
        db = ctx.get("db")
        if db is None:
            warnings.append("streak indisponible")
            meta["streak_adjustment"] = None
            return data
        try:
            hs = db.kget_team_streak(data["home_team_id"]) if data.get("home_team_id") else 0
            as_ = db.kget_team_streak(data["away_team_id"]) if data.get("away_team_id") else 0
        except Exception:
            warnings.append("streak indisponible")
            meta["streak_adjustment"] = None
            return data
        adj = 1.0
        if hs >= 5:
            adj *= 1.03
        if as_ >= 5:
            adj *= 1.03
        if hs >= 5 and as_ >= 5:
            adj *= 1.05
            warnings.append("streak cumulé (2 équipes en feu)")
        data["expected_goals"] *= adj
        meta["streak_adjustment"] = round(adj, 3)
        return data
    def _apply_weather(self, data, warnings, meta):
        weather = data.get("weather") or {}
        adj = 1.0
        cond = weather.get("condition")
        if cond == "snow":
            adj *= 0.90
        elif cond == "fog":
            adj *= 0.95
        wind = weather.get("wind_kmh")
        if wind and wind > 40:
            adj *= 0.92
        temp = weather.get("temp_c")
        if temp and temp > 35:
            adj *= 0.95
        if adj < 1.0:
            warnings.append("météo extrême détectée")
            data["expected_goals"] *= adj
        meta["extreme_weather_adjustment"] = round(adj, 3)
        return data
    def _apply_form_dom_ext(self, data, warnings, meta):
        adj = 1.0
        h_dom = data.get("home_form_gf_dom")
        h_ext = data.get("home_form_gf_ext")
        a_dom = data.get("away_form_gf_dom")
        a_ext = data.get("away_form_gf_ext")
        if h_dom is not None and h_ext is not None and h_ext > 0:
            if h_dom > h_ext * 1.3:
                adj *= 1.03
        if a_ext is not None and a_dom is not None and a_dom > 0:
            if a_ext > a_dom * 1.3:
                adj *= 1.03
        data["expected_goals"] *= adj
        meta["form_dom_ext_adjustment"] = round(adj, 3)
        return data
    def _base_score(self, data, warnings, meta):
        eg = data["expected_goals"]
        score_base = 5.0 + (eg - 2.5) * 2.5
        over_rate = data.get("over_rate")
        if over_rate is None:
            over_rate = 0.50
        league_factor = (over_rate - 0.50) * 4.0
        meta["score_base"] = round(score_base, 3)
        meta["league_factor"] = round(league_factor, 3)
        return score_base + league_factor
    def _validate_market(self, score, data, warnings, meta):
        cote_over = data.get("cote_over")
        eg = data["expected_goals"]
        adj = 0.0
        if cote_over is not None:
            if cote_over < 1.30 and eg > 2.5:
                adj -= 1.0
            elif cote_over > 2.20 and eg < 2.5:
                adj += 1.0
        if adj != 0.0:
            warnings.append("incohérence marché (cote anormale)")
        meta["market_validation_adjustment"] = adj
        return score + adj
    def _is_heavy_favorite(self, match, data):
        """
        Filtre F1 — Favori écrasant.
        Si une équipe a une cote 1X2 < 1.25, l'Over est piégé
        (le favori gère son avance, fait tourner).
        """
        cote_home = match.get("cote_home")
        cote_away = match.get("cote_away")

        if cote_home is not None and cote_home < 1.25:
            return True, f"F1: favori écrasant home (cote {cote_home:.2f})"
        if cote_away is not None and cote_away < 1.25:
            return True, f"F1: favori écrasant away (cote {cote_away:.2f})"
        return False, None

    def _is_under_market_convinced(self, data):
        """
        Filtre F2 — Marché déjà convaincu du Over.
        Si la cote Under est > 2.50, le marché est sûr du Over.
        Ton edge est donc très faible (le marché est déjà au même niveau).
        """
        cote_under = data.get("cote_under")
        if cote_under is None:
            return False, None
        if cote_under > 2.50:
            return True, f"F2: marché convaincu Over (cote Under {cote_under:.2f} > 2.50)"
        return False, None

    def _is_closed_league_end_season(self, match, data):
        """
        Filtre F3 — Ligue fermée en fin de saison.
        Si la ligue est 'closed' (tendance Under) et qu'on est en fin de saison
        (journée > 30), les matchs sont plus fermés → malus -1.0 sur le score.
        """
        try:
            import json
            from pathlib import Path
            leagues_path = Path(__file__).parent.parent.parent / "config" / "leagues.json"
            with open(leagues_path) as f:
                cfg = json.load(f)
        except Exception:
            return 0.0

        league_id = match.get("league_id")
        tendance = None
        for tier in cfg.values():
            if isinstance(tier, dict) and "leagues" in tier:
                for l in tier["leagues"]:
                    if l["id"] == league_id:
                        tendance = l.get("tendance")
                        break
                if tendance:
                    break

        if tendance != "closed":
            return 0.0

        # Vérifie si on est en fin de saison (journée > 30)
        round_number = match.get("round_number")
        if round_number is not None and round_number > 30:
            return -1.0
        # Sinon malus léger si pas d'info journée (novembre = fin de saison pour la plupart)
        from datetime import datetime
        month = datetime.now().month
        if month in (10, 11, 4, 5):  # fin de saison automne / printemps
            return -0.5
        return 0.0

    def _is_fake_match(self, data):
        cote_over = data.get("cote_over")
        cote_under = data.get("cote_under")
        eg = data.get("expected_goals", 2.5)
        if cote_over is not None and cote_over < 1.20 and eg < 2.5:
            return True
        if cote_under is not None and cote_under < 1.20 and eg > 3.0:
            return True
        return False
    def _apply_feedback(self, score, data, ctx, warnings, meta):
        db = ctx.get("db")
        breakdown = {"global": None, "league": None, "type": None}
        if db is None:
            return score, breakdown

        adj = 0.0

        try:
            g = db.kget_layer_feedback(LAYER_ID, scope="global", limit=FEEDBACK_LIMIT)
        except Exception:
            g = None
        if g and g.get("n", 0) >= FEEDBACK_MIN_MATCHES and g.get("precision") is not None:
            p = float(g["precision"])
            delta = self._feedback_delta(p, g["n"])
            breakdown["global"] = {"n": g["n"], "precision": round(p, 3), "delta": delta}
            adj += delta
            if p < 0.40:
                warnings.append("feedback loop : L2 en difficulté (précision < 40%)")
            if g["n"] < FEEDBACK_CALIB_MIN:
                warnings.append("feedback loop : calibration réduite (n < 30)")

        league_id = data.get("league_id")
        if league_id is not None:
            try:
                lg = db.kget_layer_feedback(LAYER_ID, scope="league", league_id=league_id, limit=FEEDBACK_LIMIT)
            except Exception:
                lg = None
            if lg and lg.get("n", 0) >= FEEDBACK_MIN_MATCHES and lg.get("precision") is not None:
                p = float(lg["precision"])
                delta = self._feedback_delta(p, lg["n"])
                breakdown["league"] = {"n": lg["n"], "precision": round(p, 3), "delta": delta}
                adj += delta

        match_type = data.get("match_type")
        if match_type is not None:
            try:
                tp = db.kget_layer_feedback(LAYER_ID, scope="type", match_type=match_type, limit=FEEDBACK_LIMIT)
            except Exception:
                tp = None
            if tp and tp.get("n", 0) >= FEEDBACK_MIN_MATCHES and tp.get("precision") is not None:
                p = float(tp["precision"])
                delta = self._feedback_delta(p, tp["n"])
                breakdown["type"] = {"n": tp["n"], "precision": round(p, 3), "delta": delta}
                adj += delta

        adj = max(-3.0, min(3.0, adj))
        meta["feedback_adjustment"] = round(adj, 3)
        return score + adj, breakdown

    def _feedback_delta(self, precision, n):
        base = 0.0
        if precision > 0.60:
            base = 1.0
        elif precision < 0.40:
            base = -1.0
        if n < FEEDBACK_CALIB_MIN:
            base *= 0.5
        return base
    def _compute_confidence(self, data, meta):
        form_ok = data.get("home_form_gf") is not None and data.get("away_form_gf") is not None
        xg_ok = data.get("home_xgf") is not None and data.get("away_xgf") is not None
        h2h_ok = len(data.get("h2h") or []) >= 3
        lineups_ok = bool(data.get("lineups"))
        played = data.get("played_min", 10)

        if played >= 10 and form_ok and xg_ok and h2h_ok and lineups_ok:
            return 0.95
        if played >= 10 and (form_ok or xg_ok or h2h_ok):
            return 0.85
        if played >= 5:
            return 0.75
        if played >= 3:
            return 0.55
        return 0.0
layer = KL02Over()
