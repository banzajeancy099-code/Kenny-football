"""
Kenny Football v3.0 — Orchestrateur principal (version propre).

Pipeline :
  1. Filtre ligue
  2. Exécute L1, L2, L31, L35, L47, L49
  3. Décision marché (Over prioritaire, Under fallback)
  4. Filtre ligues typées (LEAGUES_OVER / LEAGUES_UNDER)
  5. Signal (strong / medium / weak / rejected)
  6. Mise Kelly
  7. Retour dict exploitable
"""
from __future__ import annotations

import json
from pathlib import Path

import kdb
import kscoring
import kkelly
from layers.kl01_strength import KL01Strength
from layers.kl02_over import KL02Over
from layers.kl31_negatives import KL31Negatives
from layers.kl35_red_flags import KL35RedFlags
from layers.kl47_under_score import KL47UnderScore
from layers.kl49_signal_strength import KL49SignalStrength


# ─────────────────────────────────────────
# ─────────────────────────────────────────
# Ligues typées (AUDIT v3 : 28 ligues optimisées)
# Source unique de vérité : plus de dépendance à leagues.json
# ─────────────────────────────────────────
LEAGUES_OVER = {
    # Tier 1 (N >= 50, Strong >= 25) : très fiables
    4, 7, 8, 14, 17, 18, 19, 25, 38, 54, 80, 83,
    # Tier 2 (N 20-50, Over >= 60%) : bonnes
    5, 10, 11, 13, 36, 43, 52, 56, 70, 96,
    # Nouvelles (championnats nationaux uniquement, pas de coupe)
    1,    # Premier League
    2,    # Liga Portugal
    3,    # La Liga
    6,    # Ligue 1
    12,   # Championship
    15,   # Super League (Suisse)
    22,   # Parva Liga (Bulgarie)
    24,   # Super League GR
    26,   # Allsvenskan (Suède)
    28,   # Nigeria Premier
    49,   # J1 League (Japon)
    50,   # K League 1 (Corée)
    55,   # Veikkausliiga (Finlande)
    57,   # USL Championship
    82,   # Liga 3 (Portugal)
    86,   # League One
    87,   # League Two
    89,   # Ligue 2 (France)
    91,   # National League
    95,   # Campeonato de Portugal
    97,   # Challenger Pro League
    98,   # Girabola (Angola)
    99,   # Czech First League
    100,  # Serie B (Italie)
    101,  # Serie C Girone A
    102,  # Serie C Girone C
    103,  # Serie C Girone B
    104,  # A-League Men
    105,  # Ligue 3 (France)
    106,  # Superettan (Suède)
    107,  # Trendyol 1. Lig (Turquie D2)
    108,  # Eerste Divisie
    109,  # Niké liga (Slovaquie)
    # Nouvelles (coupes/international)
    57,   # USL Championship
    104,  # A-League Men
}

LEAGUES_UNDER = {
    34,   # Brasileirão Série B
    35,   # Copa do Brasil
    53,   # Botola Pro (Maroc)
    84,   # Superliga DK
    85,   # Argentine Primera
    94,   # 2. Bundesliga
    # Nouvelles Under
    92,   # Taça de Portugal
    58,   # World Cup Qualif UEFA
    64,   # UEFA Nations League
    72,   # NWSL (F)
    98,   # Girabola (Angola)
    28,   # Nigeria Premier
    105,  # Ligue 3 (France)
}

# Ligues actives = Over + Under (utilisée par run_match)
ACTIVE_LEAGUES = LEAGUES_OVER | LEAGUES_UNDER
print(f"[kengine] {len(ACTIVE_LEAGUES)} ligues actives (Over={len(LEAGUES_OVER)}, Under={len(LEAGUES_UNDER)})")


WEIGHTS = {
    "l01": 1.5,
    "l02": 1.5,
    "l31": 1.5,
    "l35": 1.5,
    "l47": 1.5,
    "l49": 2.0,
}


# ─────────────────────────────────────────
# Exécution des couches
# ─────────────────────────────────────────
def _run_layers(match: dict, ctx: dict) -> dict:
    """Exécute toutes les couches dans l'ordre, avec try/except."""
    results = {}

    for layer_id, layer_cls in [
        ("l01", KL01Strength),
        ("l02", KL02Over),
        ("l31", KL31Negatives),
        ("l35", KL35RedFlags),
        ("l47", KL47UnderScore),
    ]:
        try:
            results[layer_id] = layer_cls().run(match, ctx)
        except Exception as e:
            print(f"[kengine] {layer_id.upper()} KO : {e}")

    # L49 dépend des résultats précédents
    try:
        ctx["l31_result"] = results.get("l31")
        ctx["l35_result"] = results.get("l35")
        ctx["l47_result"] = results.get("l47")
        results["l49"] = KL49SignalStrength().run(match, ctx)
    except Exception as e:
        print(f"[kengine] L49 KO : {e}")

    return results


def _weights_for(layer_results: dict) -> dict:
    return {lid: WEIGHTS[lid] for lid in layer_results if lid in WEIGHTS}


# ─────────────────────────────────────────
# Décision marché
# ─────────────────────────────────────────
def _decide_market(layer_results: dict, match: dict = None) -> tuple[str, float, float, list]:
    """Over prioritaire, Under fallback. Proba via Poisson (EG)."""
    import math
    warnings = []
    l2 = layer_results.get("l02")
    l47 = layer_results.get("l47")
    SEUIL = 6.0

    if l2 is None and l47 is None:
        return "rejected", 0.0, 0.0, ["Aucune couche"]

    # Calcule EG et P(Over) via Poisson
    eg = None
    if l2 and hasattr(l2, "meta") and isinstance(l2.meta, dict):
        eg = l2.meta.get("expected_goals")
    
    p_over = 0.5
    p_under = 0.5
    if eg and eg > 0:
        p0 = math.exp(-eg)
        p_over = 1 - p0 * (1 + eg + eg**2 / 2)
        p_under = 1 - p_over

    # Over prioritaire
    if l2 is not None and not l2.rejected and l2.score >= SEUIL:
        return "over", min(p_over, 0.95), l2.score, [f"Over (EG={eg:.2f}, P={p_over:.1%})"]

    if l2 is not None and l2.rejected:
        warnings.append(f"L2 rejetée : {l2.warnings[:2]}")

    # Under fallback
    if l47 is None:
        return "rejected", 0.0, 0.0, warnings + ["L47 absente"]
    if l47.rejected:
        return "rejected", 0.0, 0.0, warnings + [f"L47 rejetée : {l47.warnings[:2]}"]
    if l47.score >= SEUIL:
        return "under", min(p_under, 0.95), l47.score, warnings + [f"Under (EG={eg:.2f}, P={p_under:.1%})"]

    return "rejected", 0.0, 0.0, warnings + ["Aucun marché valide"]


# ─────────────────────────────────────────
# Signal
# ─────────────────────────────────────────
def _signal_from(score: float, edge: float | None, cote: float | None, proba: float | None = None) -> str:
    """
    Seuils calibrés pour Poisson (proba réelle, pas score/10) :
    - strong : score >= 6.0 + edge >= 0.05
    - medium : score >= 5.0 + edge >= 0.03
    - weak   : score >= 4.0 + edge >= 0.02
    """
    if proba is None:
        proba = score / 10.0

    if cote is None or cote < 1.40:
        if score >= 6.0:
            return "medium_nocote"
        if score >= 5.0:
            return "weak_nocote"
        return "rejected"

    if score >= 6.0 and edge is not None and edge >= 0.05:
        return "strong"
    if score >= 5.0 and edge is not None and edge >= 0.03:
        return "medium"
    if score >= 4.0 and edge is not None and edge >= 0.02:
        return "weak"
    return "rejected"


# ─────────────────────────────────────────
# VETO helper
# ─────────────────────────────────────────
def _rejected_dict(match, reason, layer_results=None):
    return {
        "match_id": match.get("match_id"),
        "market": "rejected",
        "signal": "rejected",
        "score": 0.0, "proba": 0.0, "cote": None, "edge": None, "mise": 0.0,
        "warnings": [reason],
        "layer_results": layer_results or {},
    }


# ─────────────────────────────────────────
# Pipeline complet
# ─────────────────────────────────────────
def run_match(match: dict, ctx: dict, bankroll: float = 1000.0) -> dict:
    league_id = match.get("league_id")

    # 1. Filtre ligue
    if ACTIVE_LEAGUES and league_id not in ACTIVE_LEAGUES:
        return _rejected_dict(match, f"Ligue {league_id} non configurée")

    # 2. Exécute les couches
    results = _run_layers(match, ctx)

    # 3. VETO dur si L31 ou L35 rejettent
    l31 = results.get("l31")
    l35 = results.get("l35")
    if (l31 and l31.rejected) or (l35 and l35.rejected):
        reasons = []
        if l31 and l31.rejected:
            reasons.append(f"L31: {l31.warnings[:1]}")
        if l35 and l35.rejected:
            reasons.append(f"L35: {l35.warnings[:1]}")
        return _rejected_dict(match, "VETO " + ", ".join(reasons), results)

    # 4. Décision marché
    market, proba, score, warnings = _decide_market(results, match)

    # 5. Plus de forçage "ligue typée → marché forcé"
    # Le marché est choisi par _decide_market (Over prioritaire, Under fallback)
    # Si la ligue est Over mais que _decide_market dit Under, c'est OK
    if market == "rejected":
        return _rejected_dict(match, "Over ET Under rejetés", results)

    # 6. Cote correspondante
    cote = match.get("cote_under") if market == "under" else match.get("cote_over")

    # 7. Filtre cote [1.40, 1.80]
    # AUDIT v2 : cote élargie [1.40, 2.20] (ROI +11% à +35% sur les cotes 1.80-2.20 avec EG >= 3.5)
    if cote is None or cote < 1.40 or cote > 2.20:
        return _rejected_dict(match, f"Cote {cote} hors [1.40, 2.20]", results)

    # 8. Signal + mise
    edge = kkelly.kelly_edge(proba, cote)
    signal = _signal_from(score, edge, cote, proba)
    mise = kkelly.kelly_mise(proba, cote, signal, bankroll)

    # 9. Log feedback loop (sauf si skip)
    if not ctx.get("skip_layer_perf"):
        try:
            for lid, r in results.items():
                if r is None or r.rejected:
                    continue
                lid_num = {"l01": 1, "l02": 2, "l31": 31, "l35": 35, "l47": 47, "l49": 49}.get(lid)
                if lid_num is None:
                    continue
                kickoff = match.get("kickoff") or match.get("event_date")
                date_val = str(kickoff)[:10] if kickoff else None
                if date_val in ("None", "null", ""):
                    date_val = None
                kdb.ksave_layer_perf(
                    layer_id=lid_num,
                    match_id=str(match.get("match_id")),
                    date=date_val,
                    score=r.score,
                    confidence=r.confidence,
                    rejected=r.rejected,
                    league_id=league_id,
                    match_type=None,
                )
        except Exception as e:
            print(f"[kengine] layer_perf KO : {e}")

    # 10. Combinaison pondérée (info)
    agg = kscoring.kscore_layers(results, _weights_for(results))

    return {
        "match_id": match.get("match_id"),
        "market": market,
        "signal": signal,
        "score": round(score, 2),
        "proba": round(proba, 4),
        "cote": cote,
        "edge": edge,
        "mise": mise,
        "warnings": warnings,
        "agg_score": agg["score"],
        "layer_results": results,
    }


# ─────────────────────────────────────────
# run_and_save (pour usage futur)
# ─────────────────────────────────────────
def run_and_save(match: dict, ctx: dict, bankroll: float = 1000.0) -> dict:
    res = run_match(match, ctx, bankroll)
    # NOTE : à compléter quand kjob_analyse.py sera codé
    return res
