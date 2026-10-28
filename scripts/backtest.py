# scripts/backtest.py — Backtest rapide sur matchs historiques
import os
import sys
import json
import time
from datetime import date, timedelta
from collections import defaultdict
from pathlib import Path

# Ajoute le dossier racine au PYTHONPATH
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
    for _name, cfg in raw.items():
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

# ========== ÉTAPE 1 : COLLECTER LES MATCHS FINIS ==========

print("📥 Collecte des matchs finis des 30 derniers jours...")
all_finished = []
for days_back in range(1, 31):
    d = (date.today() - timedelta(days=days_back)).isoformat()
    try:
        matches = bzzoiro.get_matches_today(d)
        finished = [
            m for m in matches
            if m.get("league_id") in TARGET_LEAGUES
            and str(m.get("status", "")).lower() in ("finished", "ft", "aet", "pen")
            and m.get("home_score") is not None
            and m.get("away_score") is not None
        ]
        if finished:
            print(f"  {d} : {len(finished)} matchs finis")
            all_finished.extend(finished)
        if len(all_finished) >= 200:
            break
        time.sleep(0.2)
    except Exception as e:
        print(f"  {d} : erreur {e}")

print(f"\n✅ {len(all_finished)} matchs finis collectés")
if not all_finished:
    print("❌ Aucun match fini trouvé. Impossible de backtester.")
    sys.exit(1)

# Limite à 50
all_finished = all_finished[:200]

# ========== ÉTAPE 2 : REJOUER LE PIPELINE ==========

print(f"\n🔬 Rejouer le pipeline sur {len(all_finished)} matchs...")
results = []
for i, match in enumerate(all_finished, 1):
    home = match.get("home_team", "?")
    away = match.get("away_team", "?")
    hs = match.get("home_score")
    as_ = match.get("away_score")
    total = int(hs) + int(as_)
    actual_over = total >= 3

    try:
        pred = pipeline.run(match)
        pred_over = pred.get("proba_over", 0.5) >= 0.5
        results.append({
            "home": home,
            "away": away,
            "score": pred.get("score", 5.0),
            "proba_over": pred.get("proba_over", 0.5),
            "pred_over": pred_over,
            "actual_over": actual_over,
            "actual_goals": total,
            "correct": pred_over == actual_over,
            "retenu": pred.get("retenu", False),
        })
        if i % 10 == 0:
            print(f"  {i}/{len(all_finished)}...")
    except Exception as e:
        print(f"  ⚠️ {home} vs {away} : {e}")

print(f"\n✅ {len(results)} matchs analysés")

# ========== ÉTAPE 3 : ANALYSE ==========

if not results:
    print("❌ Aucun résultat")
    sys.exit(1)

total = len(results)
correct = sum(1 for r in results if r["correct"])
accuracy = correct / total

# Matrice de confusion
tp = sum(1 for r in results if r["pred_over"] and r["actual_over"])
fp = sum(1 for r in results if r["pred_over"] and not r["actual_over"])
fn = sum(1 for r in results if not r["pred_over"] and r["actual_over"])
tn = sum(1 for r in results if not r["pred_over"] and not r["actual_over"])

# Précision par tranche de proba
buckets = defaultdict(lambda: {"n": 0, "over_real": 0})
for r in results:
    b = int(r["proba_over"] * 10) / 10  # tranches de 10%
    buckets[b]["n"] += 1
    if r["actual_over"]:
        buckets[b]["over_real"] += 1

# Précision si on filtre par score
for threshold in (6.0, 6.5, 7.0, 7.5, 8.0):
    filtered = [r for r in results if r["score"] >= threshold]
    if filtered:
        acc = sum(1 for r in filtered if r["correct"]) / len(filtered)
        n_over = sum(1 for r in filtered if r["pred_over"])
        print(f"  Score ≥ {threshold} : {len(filtered)} matchs · précision {acc:.1%} · {n_over} Over prédits")

# Résumé
print(f"\n{'='*60}")
print(f"📊 RÉSULTATS BACKTEST — {total} matchs")
print(f"{'='*60}")
print(f"Précision globale : {accuracy:.1%} ({correct}/{total})")
print(f"\nMatrice de confusion :")
print(f"  Vrais positifs  (Over prédit = Over réel)     : {tp}")
print(f"  Faux positifs   (Over prédit = Under réel)    : {fp}")
print(f"  Vrais négatifs  (Under prédit = Under réel)   : {tn}")
print(f"  Faux négatifs   (Under prédit = Over réel)    : {fn}")

print(f"\nDistribution par tranche de proba Over :")
print(f"  {'Proba':<10} {'Matchs':<8} {'Over réel':<12} {'Taux réel'}")
for b in sorted(buckets.keys()):
    d = buckets[b]
    rate = d["over_real"] / d["n"] if d["n"] else 0
    bar = "█" * int(rate * 30)
    print(f"  {b*100:>3.0f}-{b*100+10:>3.0f}%    {d['n']:<8} {d['over_real']:<12} {rate:>5.1%} {bar}")

print(f"\n📈 CALIBRATION : si le modèle est bien calibré,")
print(f"   la ligne 'taux réel' doit suivre 'proba' (0.5 → 50%, 0.6 → 60%...)")

# Sauvegarde
out = {
    "date": date.today().isoformat(),
    "total": total,
    "accuracy": accuracy,
    "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
    "buckets": {str(k): v for k, v in buckets.items()},
    "results": results,
}
with open("data/backtest_results.json", "w") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
print(f"\n💾 Résultats sauvegardés : data/backtest_results.json")
