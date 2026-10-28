# src/orchestrator.py — MatchPipeline + pré-filtre
import logging
from src.layers.l01_strength import StrengthLayer
from src.layers.l02_over import OverLayer
from src.layers.l03_h2h import H2HLayer
from src.layers.l04_defense import DefenseLayer
from src.layers.l06_momentum import MomentumLayer
from src.layers.l09_fatigue import FatigueLayer
from src.scoring import BayesianScorer

log = logging.getLogger("orchestrator")

# Ligues cibles (13) : 7 originales + 6 nouvelles
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


def prefilter(match: dict) -> bool:
    """Retourne True si le match mérite une analyse complète.
    Coût: 0 appel API. Basé sur les champs déjà présents dans /events/.

    Filtres :
    - Ligue cible (13 ligues configurées)
    - Statut == "notstarted"
    - H2H >= 3 matchs (sinon couche 3 inutile)

    NOTE: la cote n'est PAS dans /events/, elle est récupérée
    pendant pipeline.run() via l02_over.
    """
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

    if h2h_total < 3:
        return False

    return True


class MatchPipeline:
    def __init__(self, bzzoiro, api_football, weights, league_over_rates):
        self.layers = [
            StrengthLayer(bzzoiro),
            OverLayer(bzzoiro, league_over_rates),
            H2HLayer(api_football),
            DefenseLayer(bzzoiro),
            MomentumLayer(bzzoiro),
            FatigueLayer(bzzoiro),
        ]
        self.scorer = BayesianScorer(weights)

    def run(self, match: dict) -> dict:
        home = match.get("home_team") or match.get("home") or "?"
        away = match.get("away_team") or match.get("away") or "?"
        log.info(f"Analyse {home} vs {away}")

        results = [layer.safe_compute(match, {}) for layer in self.layers]
        league_key = str(match.get("league_id", "default"))
        ensemble = self.scorer.score(results, league=league_key)

        proba_over = min(0.95, max(0.05, ensemble.score / 10.0))

        cote_over = (
            match.get("cote_over")
            or match.get("odds_over")
            or (match.get("odds") or {}).get("over_2_5")
            or 2.0
        )
        try:
            cote_over = float(cote_over)
        except (TypeError, ValueError):
            cote_over = 2.0

        edge = proba_over * cote_over - 1

        mise = 0.0
        if edge > 0.05 and ensemble.score >= 8.0:
            mise = round(1000 * edge * 0.15, 2)

        retenu = (
            ensemble.score >= 8.0
            and ensemble.confidence >= 0.7
            and ensemble.std < 1.5
        )

        league_id = match.get("league_id") or (match.get("league") or {}).get("id")
        league_name = (
            match.get("league_name")
            or (match.get("league") or {}).get("name")
            or LEAGUES.get(league_id, f"Ligue {league_id}")
        )

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
            "proba_over": round(proba_over, 3),
            "edge": round(edge, 3),
            "mise_kelly": mise,
            "layers": {r.layer_id: round(r.score, 2) for r in results},
            "warnings": [w for r in results for w in (r.warnings or [])],
            "result": None,
        }
