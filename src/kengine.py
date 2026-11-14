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
    1, 2, 3, 5, 6, 7, 9, 11, 12, 13, 14, 15, 17, 18, 19, 20, 22, 24, 25, 26, 27, 28, 29, 30, 32, 33, 36, 38, 39, 40, 41, 42, 43, 44, 46, 47, 48, 49, 50, 51, 52, 55, 56, 57, 59, 60, 61, 62, 63, 65, 66, 67, 68, 69, 70, 71, 80, 81, 82, 83, 86, 87, 88, 90, 91, 93, 95, 96, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 107, 109, 110
}

LEAGUES_UNDER = {
    4, 34, 35, 53, 54, 58, 64, 72, 84, 85, 92, 94
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
    l49 = layer_results.get("l49")
    SEUIL = 6.0
    SEUIL_AGREGE = 5.0

    if l2 is None and l47 is None:
        return "rejected", 0.0, 0.0, ["Aucune couche"]

    # VETO si L49 (agrégat L31+L35+L47) trop bas
    if l49 is not None and not l49.rejected and l49.score < SEUIL_AGREGE:
        return "rejected", 0.0, 0.0, [f"L49 trop bas ({l49.score:.1f} < {SEUIL_AGREGE})"]

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

    # Récupère les cotes
    cote_over = match.get("cote_over") if match else None
    cote_under = match.get("cote_under") if match else None

    # Over prioritaire (si cote over >= 1.40)
    if l2 is not None and not l2.rejected and l2.score >= SEUIL:
        if cote_over is not None and cote_over >= 1.40 and cote_over <= 2.50:
            return "over", min(p_over, 0.95), l2.score, [f"Over (EG={eg:.2f}, P={p_over:.1%})"]
        elif cote_over is not None and cote_over < 1.40:
            # Cote over trop basse → rejet (pas de basculement)
            return "rejected", 0.0, 0.0, [f"Cote over {cote_over} < 1.40 → rejet"]
        elif cote_over is not None and cote_over > 2.50:
            # Cote over trop haute → bascule Under
            warnings.append(f"Cote over {cote_over} > 2.50 → bascule Under")

    if l2 is not None and l2.rejected:
        warnings.append(f"L2 rejetée : {l2.warnings[:2]}")

    # Under fallback (avec basculement)
    if l47 is None:
        return "rejected", 0.0, 0.0, warnings + ["L47 absente"]
    if l47.rejected:
        return "rejected", 0.0, 0.0, warnings + [f"L47 rejetée : {l47.warnings[:2]}"]
    if l47.score >= SEUIL:
        if cote_under is not None and 1.40 <= cote_under <= 2.50:
            return "under", min(p_under, 0.95), l47.score, warnings + [f"Under (EG={eg:.2f}, P={p_under:.1%})"]
        elif cote_under is not None and cote_under < 1.40:
            return "rejected", 0.0, 0.0, warnings + [f"Cote under {cote_under} < 1.40 → rejet"]
        elif cote_under is not None and cote_under > 2.50:
            warnings.append(f"Cote under {cote_under} > 2.50 → bascule Over")
            # Bascule Over si L02 est ok
            if l2 is not None and not l2.rejected and l2.score >= SEUIL:
                if cote_over is not None and 1.40 <= cote_over <= 2.50:
                    return "over", min(p_over, 0.95), l2.score, warnings + [f"Bascule Over (cote under {cote_under} > 2.50)"]

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

    # NOUVEAU : si score >= 7.0, accepter même avec edge faible
    if score >= 7.0:
        return "strong"  # score très élevé = confiance
    
    if score >= 6.0 and edge is not None and edge >= 0.03:
        return "strong"
    if score >= 5.0 and edge is not None and edge >= 0.02:
        return "medium"
    if score >= 4.0 and edge is not None and edge >= 0.01:
        return "weak"
    return "rejected"


# ─────────────────────────────────────────
# VETO helper
# ─────────────────────────────────────────
def _rejected_dict(match, reason, layer_results=None):
    # Récupère le score réel des couches (pas 0)
    score = 0.0
    if layer_results:
        l2 = layer_results.get("l02")
        l47 = layer_results.get("l47")
        # Priorité : score de L02 ou L47 (le plus élevé)
        if l2 and not l2.rejected:
            score = l2.score
        elif l47 and not l47.rejected:
            score = l47.score
    
    return {
        "match_id": match.get("match_id"),
        "market": "rejected",
        "signal": "rejected",
        "score": round(score, 2),
        "proba": 0.0,
        "cote": None,
        "edge": None,
        "mise": 0.0,
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

    # 2. NOUVEAU : Détection fraude AVANT les couches
    match_id = match.get("match_id")
    if match_id:
        try:
            from scripts.detect_fraud_odds import detect_fraud
            is_fraud, fraud_reasons = detect_fraud(match_id)
            if is_fraud:
                return _rejected_dict(match, f"FRAUDE détectée : {fraud_reasons}", None)
        except Exception as e:
            print(f"[kengine] detect_fraud KO : {e}")

    # 3. Exécute les couches
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

    # 3.b NOUVEAU : calcule kscoring (agrégation bayésienne)
    weights = _weights_for(results)
    agg = kscoring.kscore_layers(results, weights) if weights else None

    # Si VETO global (une couche a rejeté), rejet
    # EXCEPTION : L01 (standings) peut rejeter sans bloquer le pari
    if agg and agg.get("veto"):
        rejected = agg.get("rejected_layers") or []
        critical_rejected = [r for r in rejected if r != "l01"]
        if critical_rejected:
            return _rejected_dict(match, f"VETO kscoring : {critical_rejected}", results)

    # 4. Décision marché
    market, proba, score, warnings = _decide_market(results, match)

    # 5. Plus de forçage "ligue typée → marché forcé"
    # Le marché est choisi par _decide_market (Over prioritaire, Under fallback)
    # Si la ligue est Over mais que _decide_market dit Under, c'est OK
    if market == "rejected":
        return _rejected_dict(match, "Over ET Under rejetés", results)

    # 6. Cote correspondante
    cote = match.get("cote_under") if market == "under" else match.get("cote_over")
    # 7. Filtre cote STRICT (Décision 6)
    # - Si cote absente → rejet (même le jour du match)
    # - Si cote hors [1.40, 2.50] → rejet
    if cote is None:
        return _rejected_dict(match, f"Cote absente → rejet", results)
    
    if cote < 1.40 or cote > 2.50:
        return _rejected_dict(match, f"Cote {cote} hors [1.40, 2.50]", results)

    # 8. Signal + mise
    if cote is not None:
        edge = kkelly.kelly_edge(proba, cote)
        signal = _signal_from(score, edge, cote, proba)
        mise = kkelly.kelly_mise(proba, cote, signal, bankroll)
    else:
        edge = None
        signal = "strong_nocote" if score >= 7.0 else "rejected"
        mise = 15.0 if signal == "strong_nocote" else 0.0

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
