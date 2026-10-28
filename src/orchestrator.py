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
            RefereeLayer(),
            ContextLayer(),
            StandingsPressureLayer(),
            LeagueShiftLayer(),
            GeographyLayer(),
            FatigueLayer(bzzoiro),
        ]
        self.scorer = BayesianScorer(weights)

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

        cote_over, cote_source = self._get_cote_over(match)
        edge = proba_over * cote_over - 1

        mise = 0.0
        if edge > 0.05 and ensemble.score >= 5.5:
            mise = round(1000 * edge * 0.15, 2)

        retenu = (
            ensemble.score >= 5.5
            and proba_over >= 0.55
            and ensemble.confidence >= 0.7
            and ensemble.std < 1.5
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
            "layers": {str(r.layer_id): round(r.score, 2) for r in results},
            "warnings": warnings,
            "result": None,
        }
