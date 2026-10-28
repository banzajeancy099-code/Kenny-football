# scripts/opening_edge_v2.py — Compare modèle vs opening sur snapshot actuel
# Bzzoiro élargi à J+MAX_DELTA pour croiser plus de matchs
import os
import sys
import json
from datetime import datetime, date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.clients.bzzoiro import BzzoiroClient
from src.orchestrator import MatchPipeline, prefilter
import yaml

BZ_KEY = os.environ.get("BZZOIRO_API_KEY")
if not BZ_KEY:
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


bzzoiro = BzzoiroClient(api_key=BZ_KEY)
pipeline = MatchPipeline(
    bzzoiro=bzzoiro,
    api_football=None,
    weights=WEIGHTS,
    league_over_rates=_league_over_rates(SETTINGS),
)

# 1. Charger le snapshot le plus récent
snap_dir = Path(__file__).parent.parent / "data" / "odds_snapshots"
snapshots = sorted(snap_dir.glob("*.json"))
if not snapshots:
    print("❌ Aucun snapshot")
    sys.exit(1)

latest = snapshots[-1]
print(f"📂 Snapshot : {latest.name}\n")
with open(latest) as f:
    snap = json.load(f)

# 2. Index des cotes par (home_lower, away_lower)
odds_by_match = {}
for sport, matches in snap.get("odds", {}).items():
    for m in matches:
        key = (m["home"].lower().strip(), m["away"].lower().strip())
        odds_by_match[key] = {
            "cote": m["best_over_2_5"],
            "home": m["home"],
            "away": m["away"],
            "sport": sport,
        }
print(f"💹 {len(odds_by_match)} matchs avec cotes\n")

# 3. Charger Bzzoiro sur J à J+MAX_DELTA
MAX_DELTA = int(os.environ.get("MAX_DELTA", "3"))
print(f"📥 Chargement des matchs Bzzoiro (J à J+{MAX_DELTA})...")
all_bz = []
for delta in range(0, MAX_DELTA + 1):
    d = (date.today() + timedelta(days=delta)).isoformat()
    try:
        matches = bzzoiro.get_matches_today(d)
        filtered = [m for m in matches if prefilter(m)]
        all_bz.extend(filtered)
        print(f"  {d} : {len(matches)} → {len(filtered)} après filtre")
    except Exception as e:
        print(f"  {d} : erreur {e}")

print(f"\n✅ {len(all_bz)} matchs Bzzoiro à analyser\n")

# 4. Croiser et analyser
print("🔬 Analyse modèle vs opening\n")
results = []
not_matched = 0
for m in all_bz:
    bz_home = m.get("home_team", "").lower().strip()
    bz_away = m.get("away_team", "").lower().strip()

    matched_key = None
    for key in odds_by_match:
        oh, oa = key
        if (oh in bz_home or bz_home in oh) and (oa in bz_away or bz_away in oa):
            matched_key = key
            break

    if not matched_key:
        not_matched += 1
        continue

    od = odds_by_match[matched_key]
    try:
        pred = pipeline.run(m)
        proba_model = pred["proba_over"]
        cote_open = od["cote"]
        proba_open = 1.0 / cote_open
        edge = proba_model - proba_open
        ev = proba_model * cote_open - 1

        results.append({
            "home": m.get("home_team"),
            "away": m.get("away_team"),
            "league_id": m.get("league_id"),
            "score": pred["score"],
            "proba_model": round(proba_model, 4),
            "proba_open": round(proba_open, 4),
            "edge": round(edge, 4),
            "ev": round(ev, 4),
            "cote": cote_open,
            "sport": od["sport"],
        })
    except Exception as e:
        print(f"  ⚠️ {m.get('home_team')} vs {m.get('away_team')} : {e}")

print(f"\n📊 {len(results)} matchs analysés · {not_matched} non croisés\n")

if not results:
    print("❌ Aucun match croisé")
    sys.exit(0)

# 5. Affichage
print(f"{'Match':<38} {'Modèle':<8} {'Marché':<8} {'Edge':<9} {'Cote':<7} {'EV'}")
print("-" * 88)
for r in sorted(results, key=lambda x: x["edge"], reverse=True):
    ms = f"{r['home']} vs {r['away']}"[:36]
    print(f"{ms:<38} {r['proba_model']:.1%}     {r['proba_open']:.1%}     "
          f"{r['edge']:+.1%}    {r['cote']:<7} {r['ev']:+.1%}")

# 6. Stats
edges = [r["edge"] for r in results]
evs = [r["ev"] for r in results]
mean_edge = sum(edges) / len(edges)
mean_ev = sum(evs) / len(evs)
pos_edge = sum(1 for e in edges if e > 0.02)
pos_ev = sum(1 for e in evs if e > 0)

print(f"\n{'='*80}")
print(f"📈 STATISTIQUES GLOBALES")
print(f"{'='*80}")
print(f"Edge moyen    : {mean_edge:+.2%}")
print(f"Edge médian   : {sorted(edges)[len(edges)//2]:+.2%}")
print(f"Edge > +2%    : {pos_edge}/{len(edges)} ({pos_edge/len(edges):.1%})")
print(f"EV moyen      : {mean_ev:+.2%}")
print(f"EV positif    : {pos_ev}/{len(evs)} ({pos_ev/len(evs):.1%})")

if mean_edge > 0.03:
    print(f"\n🟢 VERDICT : Edge réel ({mean_edge:+.1%}) → modèle bat opening")
elif mean_edge > 0:
    print(f"\n🟡 VERDICT : Edge marginal ({mean_edge:+.1%})")
else:
    print(f"\n🔴 VERDICT : Pas d'edge ({mean_edge:+.1%})")

# Sauvegarde
out = {
    "date": datetime.now().isoformat(),
    "total": len(results),
    "edge_mean": mean_edge,
    "ev_mean": mean_ev,
    "results": results,
}
with open("data/opening_edge_v2.json", "w") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
print(f"\n💾 Sauvegardé : data/opening_edge_v2.json")
