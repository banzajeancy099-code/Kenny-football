# scripts/backtest_btts.py — Backtest BTTS sur les 195 matchs
import os, sys, json
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from src.clients.bzzoiro import BzzoiroClient
from src.orchestrator import MatchPipeline, TARGET_LEAGUES, prefilter

KEY = os.environ.get("BZZOIRO_API_KEY")
with open(Path(__file__).parent.parent / "config" / "settings.yaml") as f:
    SETTINGS = yaml.safe_load(f)
with open(Path(__file__).parent.parent / "config" / "weights.json") as f:
    WEIGHTS = json.load(f)

rates = {str(c["id"]): c["over_rate"] for c in SETTINGS["leagues"].values() if isinstance(c, dict)}

b = BzzoiroClient(api_key=KEY)
pipeline = MatchPipeline(b, None, WEIGHTS, rates)

# Charge les 195 matchs du backtest
with open("data/backtest_results.json") as f:
    old_data = json.load(f)

# Récupère les 195 matchs bruts depuis Bzzoiro (via les logs)
# Solution : reconstruire depuis le backtest en cherchant les matchs
print("📥 Chargement des matchs...")
all_matches = []
for delta in range(1, 31):
    d = (date.today() - timedelta(days=delta)).isoformat()
    try:
        matches = b.get_matches_today(d)
        finished = [
            m for m in matches
            if m.get("league_id") in TARGET_LEAGUES
            and str(m.get("status", "")).lower() in ("finished", "ft", "aet", "pen")
            and m.get("home_score") is not None
            and m.get("away_score") is not None
        ]
        all_matches.extend(finished)
        if len(all_matches) >= 195:
            break
    except:
        pass

all_matches = all_matches[:195]
print(f"✅ {len(all_matches)} matchs\n")

print("🔬 Analyse BTTS...")
results = []
for i, m in enumerate(all_matches, 1):
    hs = int(m.get("home_score", 0))
    as_ = int(m.get("away_score", 0))
    actual_btts = hs > 0 and as_ > 0

    try:
        pred = pipeline.run(m)
        # Score BTTS = moyenne pondérée des couches 25, 26, 29 + couche 1 (force)
        layers = pred.get("layers", {})
        l25 = layers.get("25", 5.0)
        l26 = layers.get("26", 5.0)
        l29 = layers.get("29", 5.0)
        l1 = layers.get("1", 5.0)

        # Score BTTS
        btts_score = (l25 * 0.30) + (l26 * 0.25) + (l29 * 0.30) + (l1 * 0.15)
        pred_btts = btts_score >= 5.0

        results.append({
            "home": m.get("home_team"),
            "away": m.get("away_team"),
            "score_btts": round(btts_score, 2),
            "pred_btts": pred_btts,
            "actual_btts": actual_btts,
            "correct": pred_btts == actual_btts,
            "hs": hs, "as": as_,
            "l25": l25, "l26": l26, "l29": l29, "l1": l1,
        })
    except Exception as e:
        pass

    if i % 30 == 0:
        print(f"  {i}/{len(all_matches)}...")

if not results:
    print("❌ Aucun résultat")
    sys.exit(1)

# Analyse
total = len(results)
correct = sum(1 for r in results if r["correct"])
acc = correct / total

tp = sum(1 for r in results if r["pred_btts"] and r["actual_btts"])
fp = sum(1 for r in results if r["pred_btts"] and not r["actual_btts"])
tn = sum(1 for r in results if not r["pred_btts"] and not r["actual_btts"])
fn = sum(1 for r in results if not r["pred_btts"] and r["actual_btts"])

print(f"\n{'='*60}")
print(f"📊 BACKTEST BTTS — {total} matchs")
print(f"{'='*60}")
print(f"Précision : {acc:.1%} ({correct}/{total})")
print(f"\nMatrice :")
print(f"  Vrais positifs (BTTS prédit = BTTS réel) : {tp}")
print(f"  Faux positifs (BTTS prédit = pas BTTS)   : {fp}")
print(f"  Vrais négatifs (pas BTTS = pas BTTS)     : {tn}")
print(f"  Faux négatifs (pas BTTS = BTTS)          : {fn}")

# Score ≥ seuils
print(f"\nPar seuil de score BTTS :")
for seuil in [5.5, 6.0, 6.5, 7.0, 7.5]:
    filtered = [r for r in results if r["score_btts"] >= seuil]
    if filtered:
        n_btss = sum(1 for r in filtered if r["actual_btts"])
        acc_s = n_btss / len(filtered)
        print(f"  Score ≥ {seuil} : {len(filtered)} matchs · {acc_s:.1%} BTTS réel")

# Comparaison avec Over 2.5 (précision)
over_correct = sum(1 for r in results if (r["hs"] + r["as"] >= 3))
print(f"\n📊 Baseline : {over_correct/total:.1%} des matchs ont Over 2.5")
print(f"📊 BTTS réel : {sum(1 for r in results if r['actual_btts'])/total:.1%} des matchs ont BTTS")

out = {"total": total, "accuracy": acc, "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn}, "results": results}
with open("data/backtest_btts.json", "w") as f:
    json.dump(out, f, indent=2)
print(f"\n💾 Sauvegardé : data/backtest_btts.json")
