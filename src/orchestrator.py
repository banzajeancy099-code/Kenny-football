# src/orchestrator.py — MatchPipeline + pré-filtre + vraies cotes + fallback BTTS
import logging
import time as _time

from src.layers.l01_strength import StrengthLayer
from src.layers.l02_over import OverLayer
from src.layers.l03_h2h import H2HLayer
from src.layers.l04_defense import DefenseLayer
from src.layers.l06_momentum import MomentumLayer
from src.layers.l09_fatigue import FatigueLayer
from src.layers.l05_lineups import LineupsLayer
from src.layers.l07_referee import RefereeLayer
from src.layers.l08_context import ContextLayer
from src.layers.l11_league_shift import LeagueShiftLayer
from src.layers.l24_standings_pressure import StandingsPressureLayer
from src.layers.l12_geography import GeographyLayer
from src.layers.l16_lifecycle import LifecycleLayer
from src.layers.l14_xg import XGLayer
from src.layers.l13_smart_money import SmartMoneyLayer
from src.layers.l25_attack_x_attack import AttackXAttackLayer
from src.layers.l26_defense_x_defense import DefenseXDefenseLayer
from src.layers.l29_btts_history import BTTSHistoryLayer

from src.scoring import BayesianScorer

log = logging.getLogger("orchestrator")

TARGET_LEAGUES = {1, 4, 5, 6, 9, 10, 12, 14, 15, 18, 19, 54, 96}

LEAGUES = {
    1: "Premier League", 4: "Serie A", 5: "Bundesliga",
    6: "Ligue 1", 9: "Brasileirão", 10: "Eredivisie",
    12: "Championship", 14: "Pro League BE", 15: "Super League (CH)",
    18: "MLS", 19: "Liga MX", 54: "Eliteserien", 96: "Bundesliga AT",
    3: "La Liga", 7: "Champions League", 8: "Europa League",
    11: "Süper Lig", 13: "Scottish Premiership", 24: "Super League GR",
    25: "Ekstraklasa", 26: "Allsvenskan", 38: "Segunda División",
    40: "Carabao Cup", 41: "Copa del Rey", 43: "DFB Pokal",
    44: "Coupe de France", 45: "Coppa Italia", 84: "Danish Superliga",
    85: "Liga Profesional", 86: "League One", 87: "League Two",
    91: "National League", 94: "2. Bundesliga",
}

# Cache odds (évite les appels redondants dans la même analyse)
_ODDS_CACHE = {}


def _extract_over_odd(odds_json):
    """Extrait la cote Over 2.5 depuis le JSON Bzzoiro /events/{id}/odds/.
    Structure observée : { odds: { over_25_goals: 1.53, ... } }
    """
    if not isinstance(odds_json, dict):
        return None
    odds = odds_json.get("odds") or odds_json
    if not isinstance(odds, dict):
        return None

    # Cas 1 : over_25_goals (nom officiel Bzzoiro)
    if odds.get("over_25_goals") is not None:
        try:
            return float(odds["over_25_goals"])
        except (TypeError, ValueError):
            pass

    # Cas 2 : over_2_5 (variante)
    if odds.get("over_2_5") is not None:
        try:
            return float(odds["over_2_5"])
        except (TypeError, ValueError):
            pass

    # Cas 3 : recherche générique
    for key, val in odds.items():
        if val is None:
            continue
        k = str(key).lower()
        if "over" in k and ("2.5" in k or "25" in k or "2_5" in k):
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    return None


def _estimate_over_from_btts(odds_json):
    """Fallback : estime over_2.5 depuis btts_yes (formule empirique bornée)."""
    if not isinstance(odds_json, dict):
        return None
    odds = odds_json.get("odds") or {}
    if not isinstance(odds, dict):
        return None
    btts = odds.get("btts_yes")
    if btts is None:
        return None
    try:
        estim = round(float(btts) * 0.95, 2)
        estim = max(1.10, min(3.50, estim))
        return estim
    except (TypeError, ValueError):
        return None


def prefilter(match):
    """Pré-filtre 0 coût API."""
    lid = match.get("league_id") or (match.get("league") or {}).get("id")
    if lid not in TARGET_LEAGUES:
        return False

    status = str(match.get("status") or "").lower()
    if status != "notstarted":
        return False

    h2h = match.get("head_to_head") or {}
    if isinstance(h2h, dict):
        h2h_total = (
            h2h.get("total_matches")
            or h2h.get("total")
            or len(h2h.get("recent_matches") or [])
            or len(h2h.get("matches") or [])
        )
    elif isinstance(h2h, list):
        h2h_total = len(h2h)
    else:
        h2h_total = 0

    return h2h_total >= 3


class MatchPipeline:
    def __init__(self, bzzoiro, api_football, weights, league_over_rates):
        self.bzzoiro = bzzoiro
        self.layers = [
            StrengthLayer(bzzoiro),
            OverLayer(bzzoiro, league_over_rates),
            H2HLayer(api_football),
            DefenseLayer(bzzoiro),
            MomentumLayer(bzzoiro),
            LineupsLayer(),
            LifecycleLayer(bzzoiro),
            XGLayer(bzzoiro),
            SmartMoneyLayer(),
            AttackXAttackLayer(bzzoiro),
            DefenseXDefenseLayer(bzzoiro),
            BTTSHistoryLayer(bzzoiro),
            RefereeLayer(),
            ContextLayer(),
            StandingsPressureLayer(),
            LeagueShiftLayer(),
            GeographyLayer(),
            FatigueLayer(bzzoiro),
        ]
        self.scorer = BayesianScorer(weights)

    def _get_cotes(self, match):
        """Retourne (cotes_dict, source)."""
        match_id = match.get("id") or match.get("event_id")
        if not match_id:
            return {"over_2_5": 2.0, "btts_yes": None, "btts_no": None}, "default"

        try:
            odds_json = self.bzzoiro.get_event_odds(match_id)
            if not isinstance(odds_json, dict):
                return {"over_2_5": 2.0, "btts_yes": None, "btts_no": None}, "default"

            odds = odds_json.get("odds")
            if not isinstance(odds, dict):
                return {"over_2_5": 2.0, "btts_yes": None, "btts_no": None}, "default"

            over = odds.get("over_25_goals")
            btts_yes = odds.get("btts_yes")
            btts_no = odds.get("btts_no")

            return {
                "over_2_5": float(over) if over is not None and over > 1.01 else None,
                "btts_yes": float(btts_yes) if btts_yes is not None and btts_yes > 1.01 else None,
                "btts_no": float(btts_no) if btts_no is not None and btts_no > 1.01 else None,
            }, "api"
        except Exception as e:
            log.debug(f"[ODDS] {match_id} : {e}")
            return {"over_2_5": 2.0, "btts_yes": None, "btts_no": None}, "default"


    def _get_cote_over(self, match):
        """Retourne (cote_over, source)."""
        # 1. Cote déjà dans le match
        for key in ("cote_over", "odds_over"):
            v = match.get(key)
            if v is not None:
                try:
                    return float(v), f"match.{key}"
                except (TypeError, ValueError):
                    pass

        odds_nested = (match.get("odds") or {}).get("over_2_5")
        if odds_nested is not None:
            try:
                return float(odds_nested), "match.odds.over_2_5"
            except (TypeError, ValueError):
                pass

        # 2. Appel API /events/{id}/odds/
        match_id = match.get("id") or match.get("event_id")
        if not match_id:
            return 2.0, "default (no match_id)"

        if match_id in _ODDS_CACHE:
            c, s = _ODDS_CACHE[match_id]
            return c, s + " (cache)"

        last_error = None
        odds_json = None
        for attempt in range(2):
            try:
                t0 = _time.time()
                odds_json = self.bzzoiro.get_event_odds(match_id)
                dt = _time.time() - t0
                cote = _extract_over_odd(odds_json)
                if cote is not None and cote > 1.01:
                    _ODDS_CACHE[match_id] = (cote, "api")
                    log.info(f"[ODDS] {match_id} OK · {cote} en {dt:.2f}s")
                    return cote, "api /events/{id}/odds/"
                else:
                    log.info(f"[ODDS] {match_id} over_25 absent → tentative estimation BTTS")
                    break
            except Exception as e:
                last_error = f"{type(e).__name__}: {str(e)[:100]}"
                log.warning(f"[ODDS] {match_id} tentative {attempt+1}/2 échec : {last_error}")
                if attempt == 0:
                    _time.sleep(1.5)

        # 3. Fallback intelligent : estimation via btts_yes
        if odds_json is not None:
            estim = _estimate_over_from_btts(odds_json)
            if estim is not None:
                _ODDS_CACHE[match_id] = (estim, "est")
                log.info(f"[ODDS] {match_id} estimation btts→over · {estim}")
                return estim, "estimated (btts_yes×0.95)"

        return 2.0, f"default (api fail: {last_error or 'no over_25, no btts'})"

    def run(self, match):
        home = match.get("home_team") or match.get("home") or "?"
        away = match.get("away_team") or match.get("away") or "?"
        log.info(f"Analyse {home} vs {away}")

        results = [layer.safe_compute(match, {}) for layer in self.layers]
        league_key = str(match.get("league_id", "default"))
        ensemble = self.scorer.score(results, league=league_key)

        # Calibration non-linéaire basée sur backtest 191 matchs
        raw_p = min(0.95, max(0.05, ensemble.score / 10.0))
        if raw_p < 0.45:
            proba_over = raw_p * 0.3
        elif raw_p < 0.50:
            proba_over = raw_p * 0.7
        elif raw_p < 0.55:
            proba_over = raw_p * 1.10
        elif raw_p < 0.65:
            proba_over = raw_p * 1.20
        else:
            proba_over = min(0.95, raw_p * 1.15)

        cotes_dict, cote_source = self._get_cotes(match)
        cote_over = cotes_dict.get("over_2_5") or 2.0
        cote_btts_yes = cotes_dict.get("btts_yes")
        cote_btts_no = cotes_dict.get("btts_no")
        log.info(f"[DEBUG COTES] cotes_dict={cotes_dict} cote_btts_yes={cote_btts_yes}")
        edge = proba_over * cote_over - 1

        mise = 0.0
        if edge >= 0.10 and ensemble.score >= 5.2:
            mise = round(1000 * edge * 0.10, 2)
            mise = min(mise, 30.0)  # CAP à 3% de bankroll

        retenu = (
            ensemble.score >= 5.5
            and proba_over >= 0.55
            and ensemble.confidence >= 0.65
            and ensemble.std < 1.5
            and edge >= 0.10   # ← edge minimum, pas de plafond
        )

        league_id = match.get("league_id") or (match.get("league") or {}).get("id")
        league_name = (
            match.get("league_name")
            or (match.get("league") or {}).get("name")
            or LEAGUES.get(league_id, f"Ligue {league_id}")
        )

        warnings = [w for r in results for w in (r.warnings or [])]
        if cote_source.startswith("default"):
            warnings.append(f"cote par défaut 2.0 ({cote_source})")
        elif cote_source.startswith("estimated"):
            warnings.append("cote estimée depuis BTTS (Bzzoiro pas encore publié)")

        # Détection Under : si proba_over < 0.45, c'est un pari Under potentiel
        is_under_bet = proba_over < 0.45
        proba_under = 1.0 - proba_over
        edge_under = None
        mise_under = 0.0

        if is_under_bet and (cote_source.startswith("api") or cote_source.startswith("estimated")):
            # Cote Under = 1 / (1 - proba_marché)
            # Mais on utilise la cote réelle du marché
            # L'API peut donner Under directement, sinon approximation
            try:
                cote_under = 1.0 / (1.0 - (1.0 / cote_over))
                if cote_under > 1.01:
                    edge_under = proba_under * cote_under - 1
                    if edge_under >= 0.10 and ensemble.score <= 5.2:
                        mise_under = round(1000 * edge_under * 0.10, 2)
                        mise_under = min(mise_under, 30.0)  # CAP
            except Exception:
                pass
        # Score BTTS (couches 25, 26, 29)
        layers_dict = {str(r.layer_id): r.score for r in results}
        l25 = layers_dict.get("25", 5.0)
        l26 = layers_dict.get("26", 5.0)
        l29 = layers_dict.get("29", 5.0)
        l1 = layers_dict.get("1", 5.0)
        score_btts = (l25 * 0.30) + (l26 * 0.25) + (l29 * 0.30) + (l1 * 0.15)
        proba_btts = min(0.95, max(0.05, score_btts / 10.0))
        edge_btts = None
        mise_btts = 0.0
        retenu_btts = False
        if cote_btts_yes and cote_btts_yes > 1.01:
            edge_btts = proba_btts * cote_btts_yes - 1
            if score_btts >= 6.5 and edge_btts >= 0.10:
                retenu_btts = True
                mise_btts = round(1000 * edge_btts * 0.10, 2)
                mise_btts = min(mise_btts, 30.0)


        log.info(f"[DEBUG FINAL] cote_btts_yes={cote_btts_yes} score_btts={score_btts}")

        return {
            "match_id": match.get("id") or match.get("event_id"),
            "home": home,
            "away": away,
            "league_id": league_id,
            "league_name": league_name,
            "kickoff": match.get("kickoff") or match.get("event_date") or match.get("date"),
            "score": round(ensemble.score, 2),
            "confidence": round(ensemble.confidence, 3),
            "std": round(ensemble.std, 3),
            "ci_low": round(ensemble.ci_low, 2),
            "ci_high": round(ensemble.ci_high, 2),
            "retenu": retenu,
            "cote_over": round(cote_over, 2),
            "cote_source": cote_source,
            "proba_over": round(proba_over, 3),
            "edge": round(edge, 3),
            "mise_kelly": mise,
            "is_under_bet": is_under_bet,
            "proba_under": proba_under,
            "edge_under": round(edge_under, 4) if edge_under is not None else None,
            "mise_under": mise_under,
            "layers": {str(r.layer_id): round(r.score, 2) for r in results},
            "cote_btts_yes": cote_btts_yes,
            "cote_btts_no": cote_btts_no,
            "score_btts": round(score_btts, 2),
            "proba_btts": round(proba_btts, 3),
            "edge_btts": round(edge_btts, 4) if edge_btts is not None else None,
            "mise_btts": mise_btts,
            "retenu_btts": retenu_btts,
            "warnings": warnings,
            "result": None,
        }
