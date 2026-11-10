"""
Kenny Football v3.0 — Layer L47 : Under Score.

7 couches :
  1. Stats de base  : défense solide, attaque faible, clean sheets, H2H fermés
  2. Forme récente  : pondérée sur 5 derniers matchs
  3. Météo          : pluie, vent, froid
  4. Enjeu          : via standings / positions
  5. PitchAPI       : xT, VAEP, xAG, PPDA (borné [-2, +2])
  6. Blessures      : API-Football (gardien, défenseur, attaquant)
  7. CLV            : cote actuelle vs Pinnacle (borné [-0.5, +0.5])

Formule (normalisée 0-10) :
  raw_score = sum(signaux × poids)   # signaux bruts, borné en interne
  score_under = clamp(5.0 + raw_score, 0.0, 10.0)

Rejets stricts :
  - Couche 1 incomplète (pas de stats de base)
  - Cote Under hors [1.40, 2.10]

Seuil de validation (dans l'orchestrateur) : score_under >= 6.5
"""

from __future__ import annotations

from .kbase import Layer, LayerResult


W_UNDER = 1.5
LAYER_ID = 47


class KL47UnderScore(Layer):
    id = "l47"
    name = "Under Score"
    weight_key = "l47"

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

        # Couche 1 — stats de base
        c1 = self._layer1_stats(data, meta)

        # Couche 2 — forme récente
        c2 = self._layer2_forme(data, warnings, meta)

        # Couche 3 — météo
        c3 = self._layer3_meteo(data, warnings, meta)

        # Couche 4 — enjeu
        c4 = self._layer4_enjeu(data, warnings, meta)

        # Couche 5 — PitchAPI
        c5 = self._layer5_pitchapi(data, ctx, warnings, meta)

        # Couche 6 — blessures
        c6 = self._layer6_blessures(data, ctx, warnings, meta)

        # Couche 7 — CLV Pinnacle
        c7 = self._layer7_clv(data, ctx, warnings, meta)

        # Coalesce None -> 0.0 pour le calcul (meta garde None pour signaler la source manquante)
        c1v = c1 if c1 is not None else 0.0
        c2v = c2 if c2 is not None else 0.0
        c3v = c3 if c3 is not None else 0.0
        c4v = c4 if c4 is not None else 0.0
        c5v = c5 if c5 is not None else 0.0
        c6v = c6 if c6 is not None else 0.0
        c7v = c7 if c7 is not None else 0.0

        raw_score = c1v + c2v + c3v + c4v + c5v + c6v + c7v

        # Bornes de sécurité
        raw_score = max(-5.0, min(5.0, raw_score))
        score_under = max(0.0, min(10.0, 5.0 + raw_score))

        # Rejet sur cote hors plage
        cote_under = data.get("cote_under")
        if cote_under is None:
            res.rejected = True
            res.confidence = 0.0
            res.warnings = warnings + ["L47: cote under absente"]
            return res
        if cote_under < 1.40 or cote_under > 2.10:
            res.rejected = True
            res.confidence = 0.0
            res.warnings = warnings + [
                f"L47: cote under hors plage [{cote_under:.2f} hors 1.40-2.10]"
            ]
            return res

        # Confidence selon couches actives
        active = sum(1 for x in (c5, c6, c7) if x is not None and x != 0.0)
        if c5 is None:
            warnings.append("L47: PitchAPI indisponible")
        if c6 is None:
            warnings.append("L47: blessures indisponibles")
        if c7 is None:
            warnings.append("L47: CLV Pinnacle indisponible")

        contributions = [x for x in (c1, c2, c3, c4, c5, c6, c7) if x is not None]
        confidence = 1.0 if len(contributions) >= 6 else 0.85 if len(contributions) >= 5 else 0.7

        res.score = round(score_under, 2)
        res.confidence = confidence
        res.warnings = warnings
        res.meta = {
            **meta,
            "raw_score": round(raw_score, 3),
            "c1_stats": round(c1, 3),
            "c2_forme": round(c2, 3) if c2 is not None else None,
            "c3_meteo": round(c3, 3) if c3 is not None else None,
            "c4_enjeu": round(c4, 3) if c4 is not None else None,
            "c5_pitchapi": round(c5, 3) if c5 is not None else None,
            "c6_blessures": round(c6, 3) if c6 is not None else None,
            "c7_clv": round(c7, 3) if c7 is not None else None,
            "cote_under_final": cote_under,
            "weight": W_UNDER,
        }
        return res

    # ------------------------------------------------------------------ #
    #  Collecte
    # ------------------------------------------------------------------ #
    def _collect(self, match, ctx, warnings):
        data = {
            "home_team_id": match.get("home_team_id"),
            "away_team_id": match.get("away_team_id"),
            "league_id": match.get("league_id"),
            "fixture_id": match.get("fixture_id") or match.get("id"),
            "home_team_name": match.get("home_team_name", ""),
            "away_team_name": match.get("away_team_name", ""),
            "kickoff": match.get("kickoff") or match.get("event_date"),
            "weather": match.get("weather") or {},
            "cote_over": match.get("cote_over"),
            "cote_under": match.get("cote_under"),
        }

        # Stats de base via Bzzoiro
        bzz = ctx.get("bzzoiro")
        if bzz is None:
            data["rejected"] = True
            data["reasons"] = ["L47: bzzoiro indisponible"]
            return data

        try:
            home_split = bzz.fetch_team_splits(match["home_team_id"])
            away_split = bzz.fetch_team_splits(match["away_team_id"])
        except Exception as e:
            data["rejected"] = True
            data["reasons"] = [f"L47: splits KO ({e})"]
            return data

        if not home_split or not away_split:
            data["rejected"] = True
            data["reasons"] = ["L47: splits domicile/extérieur indisponibles"]
            return data

        data["home_split"] = home_split
        data["away_split"] = away_split

        # H2H (fallback Bzzoiro ou PitchAPI)
        h2h = match.get("head_to_head", {})
        data["h2h"] = h2h

        return data

    # ------------------------------------------------------------------ #
    #  Couche 1 — stats de base
    # ------------------------------------------------------------------ #
    def _layer1_stats(self, data, meta):
        home = data["home_split"]
        away = data["away_split"]

        # Moyennes de buts
        avg_ga = (home.get("home_ga_avg", 2.0) + away.get("away_ga_avg", 2.0)) / 2.0
        avg_gf = (home.get("home_gf_avg", 2.0) + away.get("away_gf_avg", 2.0)) / 2.0

        score = 0.0
        score += 2.0 if avg_ga < 0.8 else 0.0
        score += 1.5 if avg_gf < 1.0 else 0.0

        # Clean sheets : proxy via ga_avg < 0.5
        cs = 1.0 if home.get("home_ga_avg", 2.0) < 0.5 or away.get("away_ga_avg", 2.0) < 0.5 else 0.0
        score += cs

        # H2H fermés
        h2h_avg = data.get("h2h", {}).get("avg_total_goals")
        if h2h_avg is not None and h2h_avg < 2.0:
            score += 1.0

        meta["l1_avg_ga"] = round(avg_ga, 2)
        meta["l1_avg_gf"] = round(avg_gf, 2)
        meta["l1_h2h_avg"] = h2h_avg
        return score

    # ------------------------------------------------------------------ #
    #  Couche 2 — forme récente
    # ------------------------------------------------------------------ #
    def _layer2_forme(self, data, warnings, meta):
        home = data["home_split"]
        away = data["away_split"]
        h_fg = home.get("form_gf")
        a_fg = away.get("form_gf")
        if h_fg is None or a_fg is None:
            warnings.append("L47: forme récente indisponible")
            return None
        avg_form = (h_fg + a_fg) / 2.0
        if avg_form < 1.5:
            return 1.0
        if avg_form < 2.0:
            return 0.5
        if avg_form > 3.0:
            return -1.0
        return 0.0

    # ------------------------------------------------------------------ #
    #  Couche 3 — météo
    # ------------------------------------------------------------------ #
    def _layer3_meteo(self, data, warnings, meta):
        w = data.get("weather") or {}
        score = 0.0
        if w.get("rain_mm") and w["rain_mm"] > 5:
            score += 1.0
        if w.get("wind_kmh") and w["wind_kmh"] > 30:
            score += 0.5
        if w.get("temp_c") is not None and w["temp_c"] < 5:
            score += 0.5
        return score

    # ------------------------------------------------------------------ #
    #  Couche 4 — enjeu
    # ------------------------------------------------------------------ #
    def _layer4_enjeu(self, data, warnings, meta):
        # Basé sur les positions (fallback si indisponible)
        hp = data.get("home_position")
        ap = data.get("away_position")
        if hp is None or ap is None:
            return 0.0
        # Sans enjeu : les deux équipes en milieu de tableau (9-16)
        if 9 <= hp <= 16 and 9 <= ap <= 16:
            return 1.0
        # Enjeu critique : top 3 ou bottom 3
        if hp <= 3 or hp >= 18 or ap <= 3 or ap >= 18:
            return -1.0
        return 0.0

    # ------------------------------------------------------------------ #
    #  Couche 5 — PitchAPI
    # ------------------------------------------------------------------ #
    def _layer5_pitchapi(self, data, ctx, warnings, meta):
        pitch = ctx.get("pitchapi")
        if pitch is None:
            return None
        try:
            stats = pitch.fetch_match_stats({
                "match_id": data.get("fixture_id"),
                "home_team_name": data["home_team_name"],
                "away_team_name": data["away_team_name"],
                "kickoff": data.get("kickoff"),
            })
        except Exception as e:
            warnings.append(f"L47: PitchAPI KO ({e})")
            return None

        if not stats:
            return None

        score = 0.0

        # xT
        xt_h = stats.get("xt_home")
        xt_a = stats.get("xt_away")
        if xt_h is not None and xt_a is not None:
            avg_xt = (xt_h + xt_a) / 2.0
            if avg_xt < 0.8:
                score += 0.5
            elif avg_xt > 1.5:
                score -= 0.5

        # VAEP
        vaep_h = stats.get("vaep_home")
        vaep_a = stats.get("vaep_away")
        if vaep_h is not None and vaep_a is not None:
            avg_vaep = (vaep_h + vaep_a) / 2.0
            if avg_vaep < 1.5:
                score += 0.3
            elif avg_vaep > 3.5:
                score -= 0.8

        # xAG
        xag_h = stats.get("xag_home")
        xag_a = stats.get("xag_away")
        if xag_h is not None and xag_a is not None:
            avg_xag = (xag_h + xag_a) / 2.0
            if avg_xag < 0.5:
                score += 0.3
            elif avg_xag > 0.9:
                score -= 0.5

        # PPDA
        ppda_h = stats.get("ppda_home")
        ppda_a = stats.get("ppda_away")
        if ppda_h is not None and ppda_a is not None:
            avg_ppda = (ppda_h + ppda_a) / 2.0
            if avg_ppda > 15:
                score += 0.4
            elif avg_ppda < 8:
                score -= 0.3

        score = max(-2.0, min(2.0, score))
        meta["pitchapi_stats"] = stats
        return score

    # ------------------------------------------------------------------ #
    #  Couche 6 — blessures
    # ------------------------------------------------------------------ #
    def _layer6_blessures(self, data, ctx, warnings, meta):
        api_fb = ctx.get("api_football")
        if api_fb is None:
            return None

        fixture_id = data.get("fixture_id")
        if fixture_id is None:
            return None

        try:
            home_abs = api_fb.fetch_absences(int(fixture_id), data["home_team_id"])
            away_abs = api_fb.fetch_absences(int(fixture_id), data["away_team_id"])
        except Exception as e:
            warnings.append(f"L47: absences KO ({e})")
            return None

        if home_abs is None and away_abs is None:
            return None

        home_abs = home_abs or []
        away_abs = away_abs or []
        all_abs = home_abs + away_abs

        score = 0.0

        # Gardien titulaire absent
        gk_out = sum(1 for a in all_abs if "goalkeeper" in (a.get("type") or "").lower())
        score -= 1.5 * gk_out

        # Défenseur central titulaire absent
        def_out = sum(1 for a in all_abs
                      if "defender" in (a.get("reason") or "").lower()
                      and a.get("player_role") == "starter")
        score -= 1.0 * def_out

        # Attaquant vedette absent → moins de buts → +0.5
        star_fwd_out = sum(1 for a in all_abs
                            if "attacker" in (a.get("reason") or "").lower()
                            and a.get("player_role") == "starter")
        score += 0.5 if star_fwd_out >= 1 else 0.0

        # Plus de 3 absents majeurs
        majors = len(home_abs) + len(away_abs)
        if majors > 3:
            score -= 0.5

        meta["absences_count"] = majors
        return score

    # ------------------------------------------------------------------ #
    #  Couche 7 — CLV Pinnacle
    # ------------------------------------------------------------------ #
    def _layer7_clv(self, data, ctx, warnings, meta):
        pinnacle = ctx.get("pinnacle")
        if pinnacle is None:
            return None

        try:
            pin_odds = pinnacle.fetch_pinnacle_ou({
                "home_team_name": data["home_team_name"],
                "away_team_name": data["away_team_name"],
                "league_id": data["league_id"],
            })
        except Exception as e:
            warnings.append(f"L47: Pinnacle KO ({e})")
            return None

        if not pin_odds:
            return None

        cote_under = data.get("cote_under")
        pin_under = pin_odds.get("cote_under")
        if cote_under is None or pin_under is None:
            return None

        clv = (cote_under / pin_under) - 1.0
        meta["pinnacle_cote_under"] = pin_under
        meta["clv"] = round(clv, 4)

        if clv > 0:
            return 0.5
        elif clv < 0:
            return -0.5
        return 0.0


layer = KL47UnderScore()
