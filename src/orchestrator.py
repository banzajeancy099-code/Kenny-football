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
from src.layers.l33_squad_depth import SquadDepthLayer
from src.layers.l35_red_flags import RedFlagsLayer
from src.layers.l40_momentum_advanced import MomentumAdvancedLayer
from src.layers.l42_split_performance import SplitPerformanceLayer
from src.layers.l44_profile import ProfileLayer
from src.layers.l45_market_consensus import MarketConsensusLayer
from src.layers.l46_under_market import UnderMarketLayer
from src.layers.l34_context_enjeu import ContextEnjeuLayer
from src.scoring import BayesianScorer


import time

_league_stats_cache = {}
_LEAGUE_STATS_TTL = 3600


def _get_league_stats(bzzoiro):
    """Provider : moyenne de buts d'une ligue depuis get_standings (cache 1h)."""
    def provider(league_id):
        now = time.time()
        cached = _league_stats_cache.get(league_id)
        if cached and (now - cached["ts"]) < _LEAGUE_STATS_TTL:
            return cached["data"]

        try:
            standings = bzzoiro.get_standings(league_id)
        except Exception:
            standings = []

        if not standings:
            data = {"goals_avg": None, "n": 0}
        else:
            total_goals = sum((t.get("gf", 0) + t.get("ga", 0)) for t in standings)
            total_played = sum(t.get("played", 0) for t in standings)
            data = {
                "goals_avg": (total_goals / total_played) if total_played else None,
                "n": int(total_played / 2),
            }

        _league_stats_cache[league_id] = {"ts": now, "data": data}
        return data

    return provider




_BZZOIRO_SINGLETON = None

log = logging.getLogger("orchestrator")

TARGET_LEAGUES = {1, 2, 3, 4, 5, 6, 9, 10, 11, 12, 14, 15, 17, 18, 19, 23, 25, 26, 34, 38, 52, 53, 54, 84, 89, 94, 96, 100, 107, 108}

LEAGUES = {
    1: "Premier League", 4: "Serie A", 5: "Bundesliga",
    6: "Ligue 1", 9: "Brasileirão", 10: "Eredivisie",
    12: "Championship", 14: "Pro League BE", 15: "Super League (CH)",
    18: "MLS", 19: "Liga MX", 54: "Eliteserien", 96: "Bundesliga AT",
    3: "La Liga", 34: "Brasileirão B", 85: "Primera División ARG", 89: "Ligue 2",
    94: "2. Bundesliga",
    38: "Segunda División",
    84: "Danish Superliga",
    100: "Serie B (ITA)",
    107: "Trendyol 1. Lig (TUR)",
    108: "Eerste Divisie",
    17: "Saudi Pro League",
    23: "Superliga (ROU)",
    25: "Ekstraklasa",
    52: "Chinese Super League",
    53: "Botola Pro",
    2: "Liga Portugal",
    11: "Super Lig (TUR)",
    26: "Allsvenskan",
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
    # H2H : accepter les matchs avec au moins 1 confrontation
    # (3 était trop strict, éliminait 80% des matchs)
    if h2h_total < 1:
        return False

    # === FILTRE COTE : exclure les matchs sans cote exploitable AVANT l'analyse ===
    # On ne garde que les matchs avec une cote Over 2.5 dans la plage 1.35 - 2.50
    # (le moteur utilise ces cotes pour calculer l'edge, autant les filtrer en amont)
    match_id = match.get("id") or match.get("event_id")
    if match_id:
        try:
            from src.clients.bzzoiro import BzzoiroClient
            # Le client est passé via une variable globale (voir app.py)
            bz = _BZZOIRO_SINGLETON
            if bz:
                odds_data = bz.get_event_odds(match_id)
                odds = odds_data.get("odds", {}) if isinstance(odds_data, dict) else {}
                cote_over = odds.get("over_25_goals")
                cote_under = odds.get("under_25_goals")
                
                # Accepter le match si Over OU Under a une cote valide
                # Accepter les cotes très basses (1.10-1.35) pour les gros favoris
                min_cote = 1.10 if (proba_over or 0) >= 0.65 else 1.35
                over_valid = (cote_over is not None and min_cote <= cote_over <= 2.50)
                under_valid = (cote_under is not None and 1.50 <= cote_under <= 2.00)
                
                if not over_valid and not under_valid:
                    return False
        except Exception:
            # Si on ne peut pas récupérer la cote, on rejette le match
            return False

    return True




def _score_to_proba(score):
    """Calibration empirique basée sur 200 matchs backtestés.
    Score 5.0→0.55, 5.5→0.62, 6.0→0.75, 6.5→0.90, 7.0→0.95."""
    if score >= 7.0:
        return 0.95
    elif score >= 6.5:
        return 0.75 + (score - 6.5) * 0.40
    elif score >= 6.0:
        return 0.62 + (score - 6.0) * 0.26
    elif score >= 5.5:
        return 0.55 + (score - 5.5) * 0.14
    elif score >= 5.0:
        return 0.50 + (score - 5.0) * 0.10
    else:
        return max(0.40, 0.50 + (score - 5.0) * 0.10)


def _score_to_proba_under(score):
    """Calibration Under basée sur 50 matchs réels.
    Score 4.5→0.90, 5.0→0.80, 5.5→0.58, 6.0→0.41, 6.5→0.17."""
    if score < 4.5:
        return 0.90
    elif score < 5.0:
        return 0.80
    elif score < 5.5:
        return 0.58
    elif score < 6.0:
        return 0.41
    else:
        return 0.17


class MatchPipeline:
    def __init__(self, bzzoiro, api_football, weights, league_over_rates):
        global _BZZOIRO_SINGLETON
        _BZZOIRO_SINGLETON = bzzoiro
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
            LeagueShiftLayer(league_stats_provider=_get_league_stats(bzzoiro)),
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
            # SquadDepthLayer(bzzoiro),
            RedFlagsLayer(bzzoiro),
            MomentumAdvancedLayer(bzzoiro),
            SplitPerformanceLayer(bzzoiro),
            ProfileLayer(bzzoiro),
            MarketConsensusLayer(bzzoiro),
            UnderMarketLayer(bzzoiro),
            ContextEnjeuLayer(bzzoiro),
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
            under = odds.get("under_25_goals")
            btts_yes = odds.get("btts_yes")
            btts_no = odds.get("btts_no")

            return {
                "over_2_5": float(over) if over is not None and over > 1.01 else None,
                "under_2_5": float(under) if under is not None and under > 1.01 else None,
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
                        mise = round(1000 * edge_over_pinnacle * 0.05, 2)
                        mise = min(mise, 15.0)
                    elif signal == "medium":
                        mise = round(1000 * edge_over_pinnacle * 0.03, 2)
                        mise = min(mise, 10.0)
                    else:
                        mise = round(1000 * edge_over_pinnacle * 0.02, 2)
                        mise = min(mise, 5.0)
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

        proba_over = min(0.95, max(0.05, _score_to_proba(ensemble.score)))

        cotes_dict, cote_source = self._get_cotes(match)
        cote_over = cotes_dict.get("over_2_5")
        cote_btts_yes = cotes_dict.get("btts_yes")
        cote_btts_no = cotes_dict.get("btts_no")
        
        # Si pas de cote Bzzoiro, on utilise un fallback pour l'edge initial
        # Le vrai edge sera recalculé avec Pinnacle dans run_with_pinnacle
        # Vérifier si Over est exploitable
        # Accepter les cotes très basses (1.10-1.35) pour les gros favoris
        min_cote = 1.10 if (proba_over or 0) >= 0.65 else 1.35
        over_valid = (cote_over is not None and min_cote <= cote_over <= 2.50)
        
        # Calculer l'edge Over (seulement si cote valide)
        edge = proba_over * cote_over - 1 if over_valid else None

        # Si Over n'est pas valide, on continue pour évaluer Under
        # (pas de return immédiat)
        if not over_valid:
            log.info(f"[OVER] {home} · cote invalide ({cote_over}) · évaluation Under")

        layers_dict = {str(r.layer_id): r.score for r in results}

        # ===== 1. HARD REJECT : Signaux négatifs (L31) =====
        l31_score = layers_dict.get("31", 5.0)
        l35_score = layers_dict.get("35", 5.0)
        l45_score = layers_dict.get("45", 5.0)
        signal_strength = "rejected"
        signal_reasons = []
        mise = 0.0

        if l31_score < 3.0 or l35_score < 3.0 or l45_score < 3.0:
            signal_strength = "rejected"
            if l31_score < 3.0:
                signal_reasons.append(f"L31={l31_score:.1f} (match à éviter)")
            if l35_score < 3.0:
                signal_reasons.append(f"L35={l35_score:.1f} (red flags)")
            if l45_score < 3.0:
                signal_reasons.append(f"L45={l45_score:.1f} (contre le marché)")
        else:
            # ===== BASCULE UNDER si signaux négatifs forts =====
            if (l31_score < 4.0 or l35_score < 4.0):
                signal_strength = "rejected"
                signal_reasons.append(f"signaux négatifs forts (L31={l31_score:.1f}, L35={l35_score:.1f}) → bascule Under")
                # On laisse le bloc Under s'exécuter plus bas
            elif edge is None:
                signal_strength = "rejected"
                signal_reasons.append("pas de cote Over valide")
            elif (ensemble.score >= 5.0 and proba_over >= 0.55 
                and edge >= 0.10 and ensemble.confidence >= 0.55):
                signal_strength = "strong"
                signal_reasons.append(f"score {ensemble.score:.2f} + edge {edge:.2f}")
            elif (ensemble.score >= 4.5 and proba_over >= 0.50 
                  and edge >= 0.10 and ensemble.confidence >= 0.50):
                signal_strength = "medium"
                signal_reasons.append(f"score {ensemble.score:.2f} + edge {edge:.2f}")
            # Bonus : gros favoris (proba >= 70%) même avec edge faible
            elif (ensemble.score >= 4.5 and proba_over >= 0.70
                  and edge >= 0.00 and ensemble.confidence >= 0.50):
                signal_strength = "medium"
                signal_reasons.append(f"gros favori (proba {proba_over:.2f}) + edge {edge:.2f}")
            elif (ensemble.score >= 4.0 and proba_over >= 0.45 and edge >= 0.08):
                signal_strength = "weak"
                signal_reasons.append("signal faible")
            else:
                signal_strength = "rejected"
                signal_reasons.append("critères non atteints")

            # ===== 3. Mise adaptative =====
            if signal_strength == "strong":
                mise = round(1000 * edge * 0.03, 2)
                mise = min(mise, 10.0)
            elif signal_strength == "medium":
                mise = round(1000 * edge * 0.02, 2)
                mise = min(mise, 5.0)
            elif signal_strength == "weak":
                mise = round(1000 * edge * 0.02, 2)
                mise = min(mise, 5.0)

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

        edge_str = f"{edge:.2f}" if edge is not None else "N/A"
        log.info(f"[FINAL] {home} · signal={signal_strength} · mise={mise}€ · edge={edge_str}")

        # ===== 5. UNDER 2.5 (stratégie validée) =====
        cote_under = cotes_dict.get("under_2_5")
        score_final_under = ensemble.score

        is_under_bet = False
        proba_under = None
        edge_under = None
        mise_under = 0.0

        # Vérifier L46 (marché orienté Under ou pas)
        l46_score = layers_dict.get("46", 5.0)
        
        if (cote_under is not None
            and 1.50 <= cote_under <= 2.00
            and score_final_under < 4.8
            and l46_score >= 3.0):
            proba_under = _score_to_proba_under(ensemble.score)
            edge_under = proba_under * cote_under - 1
            if edge_under >= 0.05:
                is_under_bet = True
                mise_under = min(1000 * edge_under * 0.03, 10.0)
                log.info(f"[UNDER] {home} · bet=True · edge={edge_under:.2f} · mise={mise_under:.2f}€ · cote={cote_under} · L46={l46_score:.1f}")
        elif cote_under is not None and l46_score < 3.0:
            log.info(f"[UNDER] {home} · SKIP · L46={l46_score:.1f} (marché opposé)")

        # === COLLECTE DES DÉTAILS (lineups + top joueurs + classement) ===
        lineups = None
        top_players = {}
        home_position = None
        away_position = None
        weather_data = None
        
        try:
            import time
            match_id_for_details = match.get("id") or match.get("event_id")
            if match_id_for_details:
                # Lineups (1 requête)
                lineups = self.bzzoiro.get_event_lineups(match_id_for_details)
                
                # Top 3 joueurs par équipe (6 requêtes)
                for side in ("home", "away"):
                    team_lineup = lineups.get("lineups", {}).get(side, {})
                    players = team_lineup.get("players", [])
                    offensive = [p for p in players if p.get("position") in ("F", "M")][:3]
                    
                    player_stats = []
                    for p in offensive:
                        pid = p.get("id")
                        try:
                            stats = self.bzzoiro.request("GET", f"/players/{pid}/stats/", params={"limit": 5})
                            results_stats = stats.get("results", []) if isinstance(stats, dict) else []
                            total_goals = sum(s.get("goals", 0) or 0 for s in results_stats)
                            total_xg = sum(s.get("expected_goals", 0) or 0 for s in results_stats)
                            total_assists = sum(s.get("goal_assist", 0) or 0 for s in results_stats)
                            total_minutes = sum(s.get("minutes_played", 0) or 0 for s in results_stats)
                            player_score = total_goals * 2 + total_xg * 1.5 + total_assists + (total_minutes / 90) * 0.5
                            player_stats.append({
                                "id": pid,
                                "name": p.get("name", "?"),
                                "position": p.get("position", "?"),
                                "goals": total_goals,
                                "xg": round(total_xg, 2),
                                "assists": total_assists,
                                "score": round(player_score, 2),
                            })
                        except Exception:
                            pass
                        time.sleep(0.15)
                    
                    player_stats.sort(key=lambda x: -x["score"])
                    top_players[side] = player_stats[:3]
                
                # Classement (1 requête, cache)
                league_id_for_details = match.get("league_id")
                standings = []
                try:
                    standings = self.bzzoiro.get_standings(league_id_for_details) or []
                except Exception:
                    standings = []
                
                home_id_for_details = match.get("home_team_id")
                away_id_for_details = match.get("away_team_id")
                home_pos_data = next((t for t in standings if t.get("team_id") == home_id_for_details), None)
                away_pos_data = next((t for t in standings if t.get("team_id") == away_id_for_details), None)
                
                if home_pos_data:
                    home_position = {"position": home_pos_data.get("position"), "points": home_pos_data.get("pts")}
                if away_pos_data:
                    away_position = {"position": away_pos_data.get("position"), "points": away_pos_data.get("pts")}
                
                weather_data = match.get("weather", {})
        except Exception as e:
            log.warning(f"[DETAILS] {match.get('id')}: {e}")

        return {
            "match_id": match.get("id") or match.get("event_id"),
            "home": home,
            "home_team_id": match.get("home_team_id"),
            "away_team_id": match.get("away_team_id"),
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
            "edge": round(edge, 3) if edge is not None else None,
            "mise_kelly": mise,
            "score_btts": round(score_btts, 2),
            "proba_btts": round(proba_btts, 3),
            "edge_btts": round(edge_btts, 4) if edge_btts is not None else None,
            "mise_btts": mise_btts,
            "retenu_btts": retenu_btts,
            "is_under_bet": is_under_bet,
            "proba_under": proba_under,
            "edge_under": edge_under,
            "mise_under": mise_under,
            "cote_under": cote_under,
            "layers": {str(r.layer_id): round(r.score, 2) for r in results},
            "warnings": warnings,
            "result": None,
            "lineups": lineups,
            "top_players": top_players,
            "home_position": home_position,
            "away_position": away_position,
            "weather": weather_data,
        }
