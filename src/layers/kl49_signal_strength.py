"""
L49 — Signal Strength (couche maîtresse).

Agrège L31 (Negatives) + L35 (Red Flags) + L47 (Cohérence).

Score 0-10 :
- Élevé = signal fort → mise maintenue
- Bas = signal faible → mise réduite ou rejet

Rejet si score < 3.0.
"""

from __future__ import annotations

from .kbase import Layer, LayerResult


class KL49SignalStrength(Layer):
    id = "l49"
    name = "Signal Strength"
    weight_key = "l49"

    def run(self, match: dict, ctx: dict) -> LayerResult:
        res = LayerResult(confidence=1.0)
        warnings = []
        meta = {}

        l31_result = ctx.get("l31_result")
        l35_result = ctx.get("l35_result")
        l47_result = ctx.get("l47_result")

        scores = []
        if l31_result is not None:
            scores.append(("L31", l31_result.score))
        if l35_result is not None:
            scores.append(("L35", l35_result.score))
        if l47_result is not None and not l47_result.rejected:
            scores.append(("L47", l47_result.score))

        if not scores:
            res.score = 5.0
            res.warnings = ["L49: aucune sous-branche disponible"]
            return res

        # Moyenne pondérée 40/30/30
        weights = {"L31": 0.4, "L35": 0.3, "L47": 0.3}
        total_weight = 0.0
        weighted_sum = 0.0
        for name, score in scores:
            w = weights.get(name, 0.33)
            weighted_sum += score * w
            total_weight += w
            meta[f"{name.lower()}_score"] = round(score, 2)

        base_score = weighted_sum / total_weight if total_weight > 0 else 5.0

        # RÈGLE 1 : plafonner si moyenne couches < 6.5
        moyenne_couches = sum(s for _, s in scores) / len(scores)
        meta["moyenne_couches"] = round(moyenne_couches, 2)

        if moyenne_couches < 5.5:
            base_score = min(base_score, 5.0)
            warnings.append(f"L49: moyenne basse ({moyenne_couches:.1f}) → plafond 5.0")
        elif moyenne_couches < 6.5:
            base_score = min(base_score, 7.0)
            warnings.append(f"L49: moyenne moyenne ({moyenne_couches:.1f}) → plafond 7.0")

        # RÈGLE 2 : VETO forcé si L31 ou L35 très bas
        if l31_result and l31_result.score < 3.0:
            base_score = min(base_score, 4.0)
            warnings.append(f"L49: L31 très bas ({l31_result.score:.1f}) → plafond 4.0")
        if l35_result and l35_result.score < 3.0:
            base_score = min(base_score, 4.0)
            warnings.append(f"L49: L35 très bas ({l35_result.score:.1f}) → plafond 4.0")
        if l31_result and l35_result and l31_result.score < 3.0 and l35_result.score < 3.0:
            base_score = min(base_score, 3.0)
            warnings.append("L49: L31 ET L35 très bas → plafond 3.0")

        # RÈGLE 3 : L31+L35 OK mais L47 faible
        if l31_result and l35_result and l47_result:
            if l31_result.score >= 6.0 and l35_result.score >= 6.0 and l47_result.score < 4.5:
                base_score = min(base_score, 5.0)
                warnings.append("L49: L31+L35 OK mais L47 faible → plafond 5.0")

        score = max(0.0, min(10.0, base_score))

        res.score = round(score, 2)
        res.warnings = warnings
        res.meta = {**meta, "base_score": round(base_score, 2), "weight": 2.0}
        return res


layer = KL49SignalStrength()
