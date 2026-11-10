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
# Chargement des ligues actives
# ─────────────────────────────────────────
_LEAGUES_PATH = Path(__file__).parent.parent / "config" / "leagues.json"
ACTIVE_LEAGUES = set()
try:
    with open(_LEAGUES_PATH) as _f:
        _cfg = json.load(_f)
    for _tier_name, _tier in _cfg.items():
        if isinstance(_tier, dict) and "leagues" in _tier:
            for _l in _tier["leagues"]:
                _lid = _l.get("id")
                if _lid is not None:
                    ACTIVE_LEAGUES.add(_lid)
    print(f"[kengine] {len(ACTIVE_LEAGUES)} ligues chargées")
except Exception as _e:
    print(f"[kengine] Impossible de charger leagues.json : {_e}")

# Ligues typées (backtest: ROI +30,06% sur 249 paris)
LEAGUES_OVER = {18, 17, 14, 54, 25, 19}   # Over prioritaire
LEAGUES_UNDER = {34, 85, 89, 23, 53, 32}  # Under prioritaire


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
    """Over prioritaire, Under fallback."""
    warnings = []
    l2 = layer_results.get("l02")
    l47 = layer_results.get("l47")
    SEUIL = 6.0

    if l2 is None and l47 is None:
        return "rejected", 0.0, 0.0, ["Aucune couche"]

    # Over prioritaire
    if l2 is not None and not l2.rejected and l2.score >= SEUIL:
        return "over", min(l2.score / 10.0, 0.95), l2.score, [f"Over (score={l2.score:.2f})"]

    if l2 is not None and l2.rejected:
        warnings.append(f"L2 rejetée : {l2.warnings[:2]}")

    # Under fallback
    if l47 is None:
        return "rejected", 0.0, 0.0, warnings + ["L47 absente"]
    if l47.rejected:
        return "rejected", 0.0, 0.0, warnings + [f"L47 rejetée : {l47.warnings[:2]}"]
    if l47.score >= SEUIL:
        return "under", min(l47.score / 10.0, 0.95), l47.score, warnings + [f"Under (score={l47.score:.2f})"]

    return "rejected", 0.0, 0.0, warnings + ["Aucun marché valide"]


# ─────────────────────────────────────────
# Signal
# ─────────────────────────────────────────
def _signal_from(score: float, edge: float | None, cote: float | None, proba: float | None = None) -> str:
    """
    Seuils calibrés (ancien moteur) :
    - strong : score >= 5.5 + edge >= 0.15
    - medium : score >= 4.5 + edge >= 0.10
    - weak   : score >= 4.0 + edge >= 0.08
    - bonus favori : proba >= 0.70 + score >= 4.5 + edge >= 0.00
    """
    if proba is None:
        proba = score / 10.0

    if cote is None or cote < 1.40:
        if score >= 6.0:
            return "medium_nocote"
        if score >= 5.0:
            return "weak_nocote"
        return "rejected"

    if score >= 5.5 and edge is not None and edge >= 0.15:
        return "strong"
    if score >= 4.5 and edge is not None and edge >= 0.10:
        return "medium"
    if score >= 4.0 and edge is not None and edge >= 0.08:
        return "weak"
    if score >= 4.5 and proba >= 0.70 and edge is not None and edge >= 0.00:
        return "medium"
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

    # 5. Filtre ligues typées
    if league_id in LEAGUES_OVER and market != "over":
        return _rejected_dict(match, f"Ligue {league_id} = Over mais marché={market}", results)
    if league_id in LEAGUES_UNDER and market != "under":
        return _rejected_dict(match, f"Ligue {league_id} = Under mais marché={market}", results)

    if market == "rejected":
        return _rejected_dict(match, "Aucun marché valide", results)

    # 6. Cote correspondante
    cote = match.get("cote_under") if market == "under" else match.get("cote_over")

    # 7. Filtre cote [1.40, 1.80]
    if cote is None or cote < 1.40 or cote > 1.80:
        return _rejected_dict(match, f"Cote {cote} hors [1.40, 1.80]", results)

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
