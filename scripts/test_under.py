#!/usr/bin/env python3
"""Test Under 2.5 isolément (inverse d'Over 2.5)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "scripts")

from src.clients.bzzoiro import BzzoiroClient
from test_l14_xg import XGLayer
from test_l02_over import OverLayer
from test_l35_redflags import RedFlagsLayer
from test_l40_momentum_advanced import MomentumAdvancedLayer
from test_l42_split import SplitPerformanceLayer
from test_l44_profile import ProfileLayer


WEIGHTS = {
    "L1": 0.7,
    "L4": 0.5,
    "L40": 1.0,
    "L42": 1.5,
    "L35": 1.5,
    "L14": 1.5,
    "L2": 1.0,
    "L44": 2.0,
}


def compute_combined_score(scores):
    total_weight = 0
    weighted_sum = 0
    for layer_id, (score, conf) in scores.items():
        if layer_id not in WEIGHTS:
            continue
        w = WEIGHTS[layer_id]
        if conf <= 0:
            continue
        w_eff = w * conf
        weighted_sum += w_eff * score
        total_weight += w_eff
    if total_weight == 0:
        return 5.0
    return weighted_sum / total_weight


def main():
    api_key = os.environ.get("BZZOIRO_API_KEY_TEST") or os.environ.get("BZZOIRO_API_KEY")
    print(f"Cle utilisee : ...{api_key[-8:]}")
    bz = BzzoiroClient(api_key=api_key)

    l14 = XGLayer(bz)
    l2 = OverLayer(bz)
    l35 = RedFlagsLayer(bz)
    l40 = MomentumAdvancedLayer(bz)
    l42 = SplitPerformanceLayer(bz)
    l44 = ProfileLayer(bz)

    from datetime import date, timedelta

    total = 0
    under_real = 0
    under_predicted = 0
    correct = 0

    # Seuil Under : score < 4.5 → Under probable
    SEUIL_UNDER = 4.5

    for days_back in range(1, 6):
        d = (date.today() - timedelta(days=days_back)).isoformat()
        try:
            matches = bz.get_matches_today(d)
        except Exception:
            continue
        finished = [m for m in matches if m.get("status") == "finished"]
        if not finished:
            continue

        for m in finished[:10]:
            r14 = l14.safe_compute(m, {})
            r2 = l2.safe_compute(m, {})
            r35 = l35.safe_compute(m, {})
            r40 = l40.safe_compute(m, {})
            r42 = l42.safe_compute(m, {})
            r44 = l44.safe_compute(m, {})

            scores = {
                "L1": (5.0, 0.7),
                "L4": (5.0, 0.7),
                "L40": (r40.score, r40.confidence),
                "L42": (r42.score, r42.confidence),
                "L35": (r35.score, r35.confidence),
                "L14": (r14.score, r14.confidence),
                "L2": (r2.score, r2.confidence),
                "L44": (r44.score, r44.confidence),
            }

            combined = compute_combined_score(scores)
            pred_under = combined < SEUIL_UNDER

            hs = m.get("home_score", 0) or 0
            as_ = m.get("away_score", 0) or 0
            actual_under = (hs + as_) < 3

            total += 1
            if actual_under: under_real += 1
            if pred_under: under_predicted += 1
            if pred_under == actual_under: correct += 1

    print(f"\n{'='*60}")
    print(f"UNDER 2.5 - TEST (seuil {SEUIL_UNDER})")
    print(f"{'='*60}")
    print(f"TOTAL : {total} matchs")
    print(f"Under reels : {under_real} ({under_real/total*100:.0f}%)")
    print(f"Under predits : {under_predicted} ({under_predicted/total*100:.0f}%)")
    print(f"Accuracy : {correct}/{total} = {correct/total*100:.1f}%")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
