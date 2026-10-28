"""Scoring bayésien pondéré."""
import numpy as np
from dataclasses import dataclass


@dataclass
class EnsembleResult:
    score: float
    confidence: float
    std: float
    ci_low: float
    ci_high: float
    contributions: dict
    warnings: list


class BayesianScorer:
    def __init__(self, weights: dict, league_priors: dict = None):
        self.weights = weights
        self.priors = league_priors or {}

    def score(self, results: list, league: str = "default") -> EnsembleResult:
        valid = [r for r in results if r.confidence > 0]
        if not valid:
            return EnsembleResult(5.0, 0.0, 0.0, 5.0, 5.0, {}, ["no_valid_layers"])

        w = np.array([self.weights.get(r.layer_id, 1.0) for r in valid])
        c = np.array([r.confidence for r in valid])
        s = np.array([r.score for r in valid])
        w_eff = w * c

        prior = self.priors.get(league, {"mu": 5.0})

        raw_score = float(np.sum(w_eff * s) / np.sum(w_eff))
        global_conf = float(np.sum(w_eff) / np.sum(w))

        alpha = 0.15 + 0.85 * global_conf
        score = alpha * raw_score + (1 - alpha) * prior["mu"]
        score = float(np.clip(score, 0.0, 10.0))

        idx = np.random.choice(len(s), size=(1000, len(s)), p=w_eff / w_eff.sum())
        bootstrap = np.sum(w_eff * s[idx], axis=1) / w_eff.sum()
        std = float(np.std(bootstrap))
        ci_low, ci_high = np.percentile(bootstrap, [5, 95])

        contrib_raw = w_eff * s
        total = contrib_raw.sum()
        contributions = {
            valid[i].layer_id: float(contrib_raw[i] / total)
            for i in range(len(valid))
        }

        warnings = []
        if std > 2.0:
            warnings.append(f"high_dispersion: {std:.2f}")

        return EnsembleResult(
            score=score, confidence=global_conf, std=std,
            ci_low=float(ci_low), ci_high=float(ci_high),
            contributions=contributions, warnings=warnings,
        )
