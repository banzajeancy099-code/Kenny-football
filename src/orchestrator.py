# src/orchestrator.py — MatchPipeline + pré-filtre + 24 couches
import logging
from src.layers.l01_strength import StrengthLayer
from src.layers.l02_over import OverLayer
from src.layers.l03_h2h import H2HLayer
from src.layers.l04_defense import DefenseLayer
from src.layers.l05_lineups import LineupsLayer
from src.layers.l06_momentum import MomentumLayer
from src.layers.l07_referee import RefereeLayer
from src.layers.l08_context import ContextLayer
from src.layers.l09_fatigue import FatigueLayer
from src.layers.l11_league_shift import LeagueShiftLayer
from src.layers.l12_geography import GeographyLayer
from src.layers.l13_smart_money import SmartMoneyLayer
from src.layers.l14_xg import XGLayer
from src.layers.l16_lifecycle import LifecycleLayer
from src.layers.l19_squad import SquadLayer
from src.layers.l20_psycho import PsychoLayer
from src.layers.l24_standings_pressure import StandingsPressureLayer
from src.layers.l25_attack_x_attack import AttackXAttackLayer
from src.layers.l26_defense_x_defense import DefenseXDefenseLayer
from src.layers.l27_balance import BalanceLayer
from src.layers.l28_scorers import ScorersLayer
from src.layers.l29_btts_history import BTTSHistoryLayer
from src.layers.l31_negatives import NegativesLayer
from src.layers.l32_btts_context import BTTSContextLayer
from src.scoring import BayesianScorer

log = logging.getLogger("orchestrator")

TARGET_LEAGUES = {1, 4, 5, 6, 9, 10, 12, 14, 15, 18, 19, 54, 96}

LEAGUES = {
    1: "Premier League", 4: "Serie A", 5: "Bundesliga",
    6: "Ligue 1", 9: "Brasileirão", 10: "Eredivisie",
    12: "Championship", 14: "Pro League BE", 15: "Super League (CH)",
    18: "MLS", 19: "Liga MX", 54: "Eliteserien", 96: "Bundesliga AT",
}


def prefilter(match: dict) -> bool:
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
            LineupsLayer(),
            MomentumLayer(bzzoiro),
            RefereeLayer(),
            ContextLayer(),
            FatigueLayer(bzzoiro),
            StandingsPressureLayer(),
            LeagueShiftLayer(),
            GeographyLayer(),
            SmartMoneyLayer(),
            LifecycleLayer(bzzoiro),
            XGLayer(bzzoiro),
            AttackXAttackLayer(bzzoiro),
            DefenseXDefenseLayer(bzzoiro),
            BalanceLayer(bzzoiro),
            ScorersLayer(bzzoiro),
            BTTSHistoryLayer(bzzoiro),
            SquadLayer(bzzoiro),
            PsychoLayer(bzzoiro),
            NegativesLayer(bzzoiro),
            BTTSContextLayer(bzzoiro),
        ]
        self.scorer = BayesianScorer(weights)

    def _get_cotes(self, match):
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

    def run_with_pinnacle(self, match, pinnapi_client=None):
        home = match.get("home_team") or match.get("home") or "?"
        away = match.get("away_team") or match.get("away") or "?"
        log.info(f"[PINNACLE] run_with_pinnacle: {home} vs {away} · client={'OK' if pinnapi_client else 'NONE'}")

        # 1. Run normal (Bzzoiro)
        result = self.run(match)

        # 2. Si score trop bas, pas la peine de chercher Pinnacle
        if result.get("score", 0) < 5.0:
            return result

        # 3. Si L31 rejette (match à éviter), pas la peine
        l31 = result.get("layers", {}).get("31", 5.0)
        if l31 <= 3.0:
            return result

        # 4. Chercher Pinnacle (même si edge Bzzoiro < 10%)
        if pinnapi_client is None:
            return result

        try:
            pinnacle_odds = pinnapi_client.find_fixture_odds(home, away, league_id=match.get("league_id"))
            if not pinnacle_odds:
                result["warnings"].append("Pinnacle: fixture introuvable")
                return result

            cote_over_pinnacle = pinnacle_odds.get("over_2_5")

            if cote_over_pinnacle:
                proba_over = result.get("proba_over", 0)
                edge_over_pinnacle = proba_over * cote_over_pinnacle - 1
                result["edge_pinnacle"] = round(edge_over_pinnacle, 4)
                result["cote_pinnacle_over"] = cote_over_pinnacle
                result["pinnacle_status"] = "available"

                # Recalculer le signal avec edge Pinnacle
                proba = result.get("proba_over", 0.5)
                score = result.get("score", 5.0)
                conf = result.get("confidence", 0.5)
                
                if (score >= 6.0 and proba >= 0.65 and edge_over_pinnacle >= 0.15 and conf >= 0.65):
                    signal = "strong"
                elif (score >= 5.5 and proba >= 0.60 and edge_over_pinnacle >= 0.10 and conf >= 0.65):
                    signal = "medium"
                elif (score >= 5.0 and proba >= 0.55 and edge_over_pinnacle >= 0.08):
                    signal = "weak"
                else:
                    signal = "rejected"
                
                result["signal_strength"] = signal
                result["retenu"] = signal in ("strong", "medium")

                if signal == "rejected":
                    result["mise_kelly"] = 0.0
                    result["warnings"].append(f"Pinnacle: edge {edge_over_pinnacle:+.2%} insuffisant")
                else:
                    if signal == "strong":
                        mise = round(1000 * edge_over_pinnacle * 0.15, 2)
                        mise = min(mise, 50.0)
                    elif signal == "medium":
                        mise = round(1000 * edge_over_pinnacle * 0.10, 2)
                        mise = min(mise, 30.0)
                    else:
                        mise = round(1000 * edge_over_pinnacle * 0.05, 2)
                        mise = min(mise, 15.0)
                    result["mise_kelly"] = mise
            else:
                result["pinnacle_status"] = "pending"
                result["warnings"].append("Pinnacle: cote pas encore publiée")

        except Exception as e:
            result["warnings"].append(f"Pinnacle erreur: {str(e)[:50]}")

        return result


    def run(self, match: dict) -> dict:
        home = match.get("home_team") or match.get("home") or "?"
        away = match.get("away_team") or match.get("away") or "?"
        log.info(f"Analyse {home} vs {away}")

        results = [layer.safe_compute(match, {}) for layer in self.layers]
        league_key = str(match.get("league_id", "default"))
        ensemble = self.scorer.score(results, league=league_key)

        proba_over = min(0.95, max(0.05, ensemble.score / 10.0))

        cotes_dict, cote_source = self._get_cotes(match)
        cote_over = cotes_dict.get("over_2_5")
        cote_btts_yes = cotes_dict.get("btts_yes")
        cote_btts_no = cotes_dict.get("btts_no")
        
        # Si pas de cote Bzzoiro, on utilise un fallback pour l'edge initial
        # Le vrai edge sera recalculé avec Pinnacle dans run_with_pinnacle
        cote_over_for_edge = cote_over or 2.0
        edge = proba_over * cote_over_for_edge - 1

        layers_dict = {str(r.layer_id): r.score for r in results}

        # ===== 1. HARD REJECT : Signaux négatifs (L31) =====
        l31_score = layers_dict.get("31", 5.0)
        signal_strength = "rejected"
        signal_reasons = []
        mise = 0.0

        if l31_score < 3.0:
            signal_strength = "rejected"
            signal_reasons.append(f"L31={l31_score:.1f} (match à éviter)")
        else:
            # ===== 2. Signaux FORT / MOYEN / FAIBLE =====
            if (ensemble.score >= 6.0 and proba_over >= 0.65 
                and edge >= 0.15 and ensemble.confidence >= 0.65):
                signal_strength = "strong"
                signal_reasons.append(f"score {ensemble.score:.2f} + edge {edge:.2f}")
            elif (ensemble.score >= 5.5 and proba_over >= 0.60 
                  and edge >= 0.10 and ensemble.confidence >= 0.65):
                signal_strength = "medium"
                signal_reasons.append(f"score {ensemble.score:.2f} + edge {edge:.2f}")
            elif (ensemble.score >= 5.0 and proba_over >= 0.55 and edge >= 0.08):
                signal_strength = "weak"
                signal_reasons.append("signal faible")
            else:
                signal_strength = "rejected"
                signal_reasons.append("critères non atteints")

            # ===== 3. Mise adaptative =====
            if signal_strength == "strong":
                mise = round(1000 * edge * 0.15, 2)
                mise = min(mise, 50.0)
            elif signal_strength == "medium":
                mise = round(1000 * edge * 0.10, 2)
                mise = min(mise, 30.0)
            elif signal_strength == "weak":
                mise = round(1000 * edge * 0.05, 2)
                mise = min(mise, 15.0)

        retenu = signal_strength in ("strong", "medium")

        # ===== 4. Score BTTS =====
        l25 = layers_dict.get("25", 5.0)
        l26 = layers_dict.get("26", 5.0)
        l27 = layers_dict.get("27", 5.0)
        l28 = layers_dict.get("28", 5.0)
        l29 = layers_dict.get("29", 5.0)
        l31 = layers_dict.get("31", 5.0)
        l32 = layers_dict.get("32", 5.0)
        l1 = layers_dict.get("1", 5.0)
        
        # Score BTTS combiné : base (25/26/27/28/29) + contexte L32 + strength L1 + negatives L31
        score_btts = (
            (l25 * 0.15) +
            (l26 * 0.12) +
            (l27 * 0.10) +
            (l28 * 0.13) +
            (l29 * 0.10) +
            (l32 * 0.30) +   # ← BTTS contextuel (poids fort)
            (l1 * 0.05) +
            (l31 * 0.05)     # ← négatif (pénalise si match à éviter)
        )
        proba_btts = min(0.95, max(0.05, score_btts / 10.0))

        edge_btts = None
        mise_btts = 0.0
        retenu_btts = False

        if cote_btts_yes and cote_btts_yes > 1.01 and l31_score > 3.0:
            edge_btts = proba_btts * cote_btts_yes - 1

            if score_btts >= 7.5 and edge_btts >= 0.15:
                retenu_btts = True
                mise_btts = round(1000 * edge_btts * 0.15, 2)
                mise_btts = min(mise_btts, 50.0)
            elif score_btts >= 6.5 and edge_btts >= 0.10:
                retenu_btts = True
                mise_btts = round(1000 * edge_btts * 0.10, 2)
                mise_btts = min(mise_btts, 30.0)
            elif score_btts >= 6.0 and edge_btts >= 0.08:
                retenu_btts = True
                mise_btts = round(1000 * edge_btts * 0.05, 2)
                mise_btts = min(mise_btts, 15.0)

        league_id = match.get("league_id") or (match.get("league") or {}).get("id")
        league_name = (
            match.get("league_name")
            or (match.get("league") or {}).get("name")
            or LEAGUES.get(league_id, f"Ligue {league_id}")
        )

        warnings = [w for r in results for w in (r.warnings or [])]
        if cote_source.startswith("default"):
            warnings.append(f"cote par défaut 2.0 ({cote_source})")

        log.info(f"[FINAL] {home} · signal={signal_strength} · mise={mise}€ · edge={edge:.2f}")

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
            "signal_strength": signal_strength,
            "signal_reasons": signal_reasons,
            "cote_over": round(cote_over, 2) if cote_over is not None else None,
            "cote_btts_yes": cote_btts_yes,
            "cote_btts_no": cote_btts_no,
            "cote_source": cote_source,
            "proba_over": round(proba_over, 3),
            "edge": round(edge, 3),
            "mise_kelly": mise,
            "score_btts": round(score_btts, 2),
            "proba_btts": round(proba_btts, 3),
            "edge_btts": round(edge_btts, 4) if edge_btts is not None else None,
            "mise_btts": mise_btts,
            "retenu_btts": retenu_btts,
            "layers": {str(r.layer_id): round(r.score, 2) for r in results},
            "warnings": warnings,
            "result": None,
        }
