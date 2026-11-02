#!/usr/bin/env python3
"""Test BTTS + Over 2.5 combiné."""
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
    "L1": 0.7, "L4": 0.5, "L40": 1.0, "L42": 1.5,
    "L35": 1.5, "L14": 1.5, "L2": 1.0, "L44": 2.0,
}

def compute_combined_score(scores):
    total_weight = 0
    weighted_sum = 0
    for layer_id, (score, conf) in scores.items():
        if layer_id not in WEIGHTS: continue
        w = WEIGHTS[layer_id]
        if conf <= 0: continue
        w_eff = w * conf
        weighted_sum += w_eff * score
        total_weight += w_eff
    if total_weight == 0: return 5.0
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
    
    # Collecter les données
    data = []
    for days_back in range(1, 6):
        d = (date.today() - timedelta(days=days_back)).isoformat()
        try: matches = bz.get_matches_today(d)
        except: continue
        finished = [m for m in matches if m.get("status") == "finished"]
        for m in finished[:10]:
            r14 = l14.safe_compute(m, {})
            r2 = l2.safe_compute(m, {})
            r35 = l35.safe_compute(m, {})
            r40 = l40.safe_compute(m, {})
            r42 = l42.safe_compute(m, {})
            r44 = l44.safe_compute(m, {})
            
            scores = {
                "L1": (5.0, 0.7), "L4": (5.0, 0.7),
                "L40": (r40.score, r40.confidence),
                "L42": (r42.score, r42.confidence),
                "L35": (r35.score, r35.confidence),
                "L14": (r14.score, r14.confidence),
                "L2": (r2.score, r2.confidence),
                "L44": (r44.score, r44.confidence),
            }
            combined = compute_combined_score(scores)
            
            hs = m.get("home_score", 0) or 0
            as_ = m.get("away_score", 0) or 0
            total_goals = hs + as_
            
            # BTTS + Over 2.5 : les 2 équipes marquent ET 3+ buts
            actual_btts_over = (hs >= 1 and as_ >= 1 and total_goals >= 3)
            
            # Cotes disponibles ?
            mid = m.get("id")
            cote_btts = None
            cote_over = None
            try:
                odds = bz.get_event_odds(mid)
                cotes = odds.get("odds", {}) if isinstance(odds, dict) else {}
                cote_btts = cotes.get("btts_yes")
                cote_over = cotes.get("over_25_goals")
            except: pass
            
            data.append({
                "score": combined,
                "actual_btts_over": actual_btts_over,
                "cote_btts": cote_btts,
                "cote_over": cote_over,
                "home_score": hs,
                "away_score": as_,
            })
    
    print(f"Total : {len(data)} matchs")
    print(f"BTTS+Over réels : {sum(1 for d in data if d['actual_btts_over'])} ({sum(1 for d in data if d['actual_btts_over'])/len(data)*100:.0f}%)")
    print()
    
    # Tester différents seuils
    print("=== Optimisation du seuil ===")
    print(f'{"Seuil":<8} | {"Prédits":<8} | {"Corrects":<8} | {"Accuracy":<8}')
    print("-" * 50)
    for seuil in [6.5, 6.8, 7.0, 7.2, 7.5, 8.0]:
        predits = [d for d in data if d["score"] >= seuil]
        if not predits: continue
        corrects = sum(1 for d in predits if d["actual_btts_over"])
        acc = corrects / len(predits) * 100
        print(f"{seuil:<8} | {len(predits):<8} | {corrects:<8} | {acc:.1f}%")
    
    print()
    print("=== Détail par seuil 7.0 ===")
    for d in sorted([x for x in data if x["score"] >= 7.0], key=lambda x: -x["score"])[:15]:
        result = "✓" if d["actual_btts_over"] else "✗"
        print(f'  score={d["score"]:.2f} | {d["home_score"]}-{d["away_score"]} | {result}')


if __name__ == "__main__":
    main()
