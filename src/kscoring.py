"""
Kenny Football v3.0 — Agrégation bayésienne des couches.

Poids dynamique (#8) :
    effective_weight = base_weight * (0.5 + confidence * 0.5)

Une couche avec confidence=0.3 pèse 0.65 * base_weight (au lieu de 1.0 * base_weight).
Une couche avec confidence=1.0 pèse 1.0 * base_weight.

VETO :
    Si au moins une couche retourne rejected=True, le match est rejeté globalement.
    Le score retourné est alors 0.0, veto=True, et l'orchestrator doit forcer
    signal="rejected" et mise=0.

Les couches rejetées sont exclues du calcul pondéré (elles ne polluent pas
la moyenne), mais elles déclenchent le veto.
"""

from __future__ import annotations

WEIGHT_CONFIDENCE_FLOOR = 0.5


def keffective_weight(base_weight: float, confidence: float) -> float:
    """Poids effectif d'une couche (poids dynamique #8)."""
    conf = max(0.0, min(1.0, confidence))
    return base_weight * (WEIGHT_CONFIDENCE_FLOOR + (1.0 - WEIGHT_CONFIDENCE_FLOOR) * conf)


def kscore_layers(layer_results: dict, weights: dict) -> dict:
    """
    Agrège les LayerResult.

    Args:
        layer_results : {layer_id: LayerResult}
        weights       : {layer_id: base_weight}

    Returns:
        {
            "score":          float (0-10),
            "total_weight":   float,
            "breakdown":      {layer_id: {score, confidence, effective_weight, contribution}},
            "rejected_layers": list[str],
            "veto":           bool,
        }
    """
    breakdown = {}
    rejected_layers = []
    weighted_sum = 0.0
    total_weight = 0.0

    for layer_id, res in layer_results.items():
        base_w = weights.get(layer_id, 0.0)

        if res.rejected:
            rejected_layers.append(layer_id)
            breakdown[layer_id] = {
                "score": res.score,
                "confidence": res.confidence,
                "effective_weight": 0.0,
                "contribution": 0.0,
                "rejected": True,
                "warnings": list(res.warnings),
            }
            continue

        if base_w <= 0.0:
            breakdown[layer_id] = {
                "score": res.score,
                "confidence": res.confidence,
                "effective_weight": 0.0,
                "contribution": 0.0,
                "rejected": False,
                "warnings": list(res.warnings),
            }
            continue

        eff_w = keffective_weight(base_w, res.confidence)
        contrib = res.score * eff_w
        weighted_sum += contrib
        total_weight += eff_w

        breakdown[layer_id] = {
            "score": res.score,
            "confidence": res.confidence,
            "effective_weight": round(eff_w, 4),
            "contribution": round(contrib, 4),
            "rejected": False,
            "warnings": list(res.warnings),
        }

    veto = len(rejected_layers) > 0
    score = round(weighted_sum / total_weight, 2) if total_weight > 0 else 0.0

    if veto:
        score = 0.0

    return {
        "score": score,
        "total_weight": round(total_weight, 4),
        "breakdown": breakdown,
        "rejected_layers": rejected_layers,
        "veto": veto,
    }
