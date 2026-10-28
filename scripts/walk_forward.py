# scripts/walk_forward.py — Walk-forward validation (train / test split)
import os
import sys
import json
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from src.clients.bzzoiro import BzzoiroClient
from src.orchestrator import MatchPipeline, TARGET_LEAGUES, prefilter

KEY = os.environ.get("BZZOIRO_API_KEY")
if not KEY:
    print("❌ BZZOIRO_API_KEY manquante")
    sys.exit(1)

with open(Path(__file__).parent.parent / "config" / "settings.yaml") as f:
    SETTINGS = yaml.safe_load(f)
with open(Path(__file__).parent.parent / "config" / "weights.json") as f:
    WEIGHTS = json.load(f)


def _league_over_rates(settings):
    raw = settings.get("leagues", {})
    out = {}
    for _n, cfg in raw.items():
        if isinstance(cfg, dict) and "id" in cfg:
            out[str(cfg["id"])] = float(cfg.get("over_rate", 0.5))
    return out


bzzoiro = BzzoiroClient(api_key=KEY)
pipeline = MatchPipeline(
    bzzoiro=bzzoiro,
    api_football=None,
    weights=WEIGHTS,
    league_over_rates=_league_over_rates(SETTINGS),
)

# ========== FENÊTRES ==========
TRAIN_START = date(2025, 1, 1)
TRAIN_END = date(2025, 9, 30)
TEST_START = date(2025, 10, 1)
TEST_END = date(2025, 10, 27)

print(f"📅 TRAIN : {TRAIN_START} → {TRAIN_END}")
print(f"📅 TEST  : {TEST_START} → {TEST_END}\n")

# ========== COLLECTE ==========
def collect(start, end, label, max_matches=150):
    """Collecte les matchs finis sur une fenêtre."""
    print(f"📥 Collecte {label}...")
    out = []
    d = start
    while d <= end and len(out) < max_matches:
        try:
            matches = bzzoiro.get_matches_today(d.isoformat())
            finished = [
                m for m in matches
                if m.get("league_id") in TARGET_LEAGUES
                and str(m.get("status", "")).lower() in ("finished", "ft", "aet", "pen")
                and m.get("home_score") is not None
                and m.get("away_score") is not None
            ]
            out.extend(finished)
        except Exception:
            pass
        d += timedelta(days=1)

    print(f"   {len(out)} matchs récupérés\n")
    return out[:max_matches]


train_matches = collect(TRAIN_START, TRAIN_END, "TRAIN")
test_matches = collect(TEST_START, TEST_END, "TEST")

if len(train_matches) < 30 or len(test_matches) < 20:
    print(f"⚠️  Pas assez de matchs (train={len(train_matches)}, test={len(test_matches)})")
    print("   Essaie avec des fenêtres plus larges")
    sys.exit(1)

# ========== ANALYSE ==========
def analyze(matches, label):
    print(f"🔬 Analyse {label} ({len(matches)} matchs)...")
    results = []
    for i, m in enumerate(matches, 1):
        hs = m.get("home_score")
        as_ = m.get("away_score")
        actual_over = (int(hs) + int(as_)) >= 3
        try:
            pred = pipeline.run(m)
            proba = pred.get("proba_over", 0.5)
            pred_over = proba >= 0.5
            results.append({
                "proba": proba,
                "pred_over": pred_over,
                "actual_over": actual_over,
                "correct": pred_over == actual_over,
                "score": pred.get("score", 5.0),
            })
        except Exception:
            pass
        if i % 30 == 0:
            print(f"   {i}/{len(matches)}...")

    if not results:
        print(f"❌ Aucun résultat {label}\n")
        return None

    n = len(results)
    correct = sum(1 for r in results if r["correct"])
    acc = correct / n

    # Brier Score
    brier = sum((r["proba"] - (1.0 if r["actual_over"] else 0.0)) ** 2 for r in results) / n

    # Précision par seuil de proba
    high_conf = [r for r in results if r["proba"] >= 0.6]
    high_acc = sum(1 for r in high_conf if r["correct"]) / len(high_conf) if high_conf else 0

    print(f"   Précision : {acc:.1%} ({correct}/{n})")
    print(f"   Brier     : {brier:.4f}")
    print(f"   Précision (proba≥0.6) : {high_acc:.1%} sur {len(high_conf)} matchs\n")

    return {
        "label": label,
        "n": n,
        "correct": correct,
        "accuracy": acc,
        "brier": brier,
        "high_conf_n": len(high_conf),
        "high_conf_accuracy": high_acc,
    }


r_train = analyze(train_matches, "TRAIN")
r_test = analyze(test_matches, "TEST")

if not r_train or not r_test:
    sys.exit(1)

# ========== COMPARAISON ==========
print("=" * 70)
print("📊 COMPARAISON TRAIN vs TEST")
print("=" * 70)
print(f"{'Métrique':<30} {'TRAIN':<15} {'TEST':<15} {'Δ'}")
print("-" * 70)
print(f"{'Matchs analysés':<30} {r_train['n']:<15} {r_test['n']:<15}")
print(f"{'Précision globale':<30} {r_train['accuracy']:.1%}{'':<10} {r_test['accuracy']:.1%}")

delta_acc = r_test['accuracy'] - r_train['accuracy']
delta_pct = delta_acc * 100
print(f"{'Δ Précision':<30} {delta_pct:+.1f}%")

print(f"{'Brier Score':<30} {r_train['brier']:.4f}{'':<9} {r_test['brier']:.4f}")

print(f"{'Matchs proba≥0.6':<30} {r_train['high_conf_n']:<15} {r_test['high_conf_n']:<15}")
print(f"{'Précision proba≥0.6':<30} {r_train['high_conf_accuracy']:.1%}{'':<10} {r_test['high_conf_accuracy']:.1%}")

# ========== VERDICT ==========
print("\n" + "=" * 70)
print("🎯 VERDICT")
print("=" * 70)

if abs(delta_acc) < 0.05:
    verdict = "🟢 PAS D'OVERFIT — modèle stable"
    expl = f"Précision test ({r_test['accuracy']:.1%}) proche de train ({r_train['accuracy']:.1%})"
    action = "→ Le modèle est fiable. On peut passer au paper trading."
elif delta_acc > 0.05:
    verdict = "🟡 TEST MEILLEUR QUE TRAIN — bon signe"
    expl = "Le modèle généralise bien (voire mieux que sur train)"
    action = "→ Excellent signe. On peut passer au paper trading."
elif delta_acc > -0.10:
    verdict = "🟠 LÉGER OVERFIT — acceptable"
    expl = f"Baisse de {abs(delta_pct):.1f}% entre train et test"
    action = "→ Acceptable. À surveiller sur 30 jours de paper trading."
else:
    verdict = "🔴 OVERFIT MASSIF — modèle non fiable"
    expl = f"Baisse de {abs(delta_pct):.1f}% entre train et test"
    action = "→ Le modèle est trop calé sur train. Il faut ajouter des couches."

print(f"\n{verdict}")
print(f"  {expl}")
print(f"\n{action}")

# ========== SAUVEGARDE ==========
out = {
    "date": date.today().isoformat(),
    "train": r_train,
    "test": r_test,
    "delta_accuracy": delta_acc,
    "verdict": verdict,
}
with open("data/walk_forward.json", "w") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
print(f"\n💾 Sauvegardé : data/walk_forward.json")
