# scripts/compare_odds.py — Comparer modèle vs marché (current odds)
import os
import sys
import json
import time
from datetime import datetime
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from src.clients.bzzoiro import BzzoiroClient
from src.clients.the_odds_api import TheOddsAPIClient
from src.orchestrator import MatchPipeline, TARGET_LEAGUES, prefilter

BZ_KEY = os.environ.get("BZZOIRO_API_KEY")
TO_KEY = os.environ.get("THE_ODDS_API_KEY")
if not BZ_KEY or not TO_KEY:
    print("❌ Clés manquantes")
    sys.exit(1)

with open(Path(__file__).parent.parent / "config" / "settings.yaml") as f:
    SETTINGS = yaml.safe_load(f)
with open(Path(__file__).parent.parent / "config" / "weights.json") as f:
    WEIGHTS = json.load(f)

# Mapping ligues Bzzoiro → The Odds API
LEAGUE_MAP = {
    1: "soccer_epl",
    4: "soccer_italy_serie_a",
    5: "soccer_germany_bundesliga",
    6: "soccer_france_ligue_one",
    9: "soccer_brazil_campeonato",
    10: "soccer_netherlands_eredivisie",
    12: "soccer_efl_champ",
    14: "soccer_belgium_first_div",
    15: "soccer_switzerland_superleague",
    18: "soccer_usa_mls",
    19: "soccer_mexico_ligamx",
    54: "soccer_norway_eliteserien",
    96: "soccer_austria_bundesliga",
}


def _league_over_rates(settings):
    raw = settings.get("leagues", {})
    out = {}
    for _n, cfg in raw.items():
        if isinstance(cfg, dict) and "id" in cfg:
            out[str(cfg["id"])] = float(cfg.get("over_rate", 0.5))
    return out


bzzoiro = BzzoiroClient(api_key=BZ_KEY)
odds_api = TheOddsAPIClient(api_key=TO_KEY)

pipeline = MatchPipeline(
    bzzoiro=bzzoiro,
    api_football=None,
    weights=WEIGHTS,
    league_over_rates=_league_over_rates(SETTINGS),
)

# 1. Charger les matchs du jour
print("📥 Chargement des matchs du jour via Bzzoiro...")
today = datetime.now().date().isoformat()
all_matches = bzzoiro.get_matches_today(today)
filtered = [m for m in all_matches if prefilter(m)]
print(f"   {len(all_matches)} matchs Bzzoiro → {len(filtered)} après pré-filtre")

if not filtered:
    print("❌ Aucun match à analyser")
    sys.exit(0)

# 2. Grouper par ligue
by_league = defaultdict(list)
for m in filtered:
    by_league[m.get("league_id")].append(m)

# 3. Récupérer les cotes marché
print(f"\n💹 Récupération des cotes marché...")
market_odds = {}  # {match_id: {"best_over": cote, "bookmaker": nom, "all_odds": [...]}}
for lid, matches in by_league.items():
    sport_key = LEAGUE_MAP.get(lid)
    if not sport_key:
        continue
    try:
        print(f"   [{lid}] {sport_key} : {len(matches)} matchs...")
        data = odds_api._get(f"/sports/{sport_key}/odds", {
            "regions": "eu",
            "markets": "totals",
            "oddsFormat": "decimal",
        })
        for mo in data:
            home = mo.get("home_team", "")
            away = mo.get("away_team", "")
            # Matche les noms Bzzoiro vs Odds API
            bz_match = next(
                (x for x in matches
                 if x.get("home_team", "").lower() in home.lower()
                 or home.lower() in x.get("home_team", "").lower()),
                None
            )
            if not bz_match:
                continue
            mid = bz_match.get("id")
            # Cherche Over 2.5
            best_over = None
            best_bk = None
            for bk in mo.get("bookmakers", []):
                for mkt in bk.get("markets", []):
                    if mkt.get("key") != "totals":
                        continue
                    for out in mkt.get("outcomes", []):
                        if out.get("name") == "Over" and out.get("point") == 2.5:
                            price = out.get("price", 0)
                            if price and (best_over is None or price > best_over):
                                best_over = price
                                best_bk = bk.get("key")
            if best_over:
                market_odds[mid] = {
                    "best_over": best_over,
                    "bookmaker": best_bk,
                    "proba_market": 1.0 / best_over,
                }
        time.sleep(0.3)
    except Exception as e:
        print(f"   ⚠️ {sport_key} : {e}")

print(f"\n✅ Cotes marché trouvées pour {len(market_odds)} matchs")

# 4. Analyser les matchs avec cotes
print(f"\n🔬 Analyse modèle vs marché...")
comparisons = []
for m in filtered:
    mid = m.get("id")
    if mid not in market_odds:
        continue
    try:
        pred = pipeline.run(m)
        mo = market_odds[mid]
        proba_model = pred["proba_over"]
        proba_market = mo["proba_market"]
        edge = proba_model - proba_market

        comparisons.append({
            "home": m.get("home_team"),
            "away": m.get("away_team"),
            "league": m.get("league_id"),
            "score": pred["score"],
            "proba_model": round(proba_model, 4),
            "proba_market": round(proba_market, 4),
            "edge": round(edge, 4),
            "cote": mo["best_over"],
            "bookmaker": mo["bookmaker"],
            "expected_value": round(proba_model * mo["best_over"] - 1, 4),
        })
    except Exception as e:
        print(f"   ⚠️ {m.get('home_team')} : {e}")

# 5. Analyse
if not comparisons:
    print("❌ Aucune comparaison")
    sys.exit(1)

print(f"\n{'='*70}")
print(f"📊 MODÈLE vs MARCHÉ — {len(comparisons)} matchs")
print(f"{'='*70}\n")

print(f"{'Match':<40} {'Modèle':<8} {'Marché':<8} {'Edge':<8} {'Cote':<6} {'EV'}")
print("-" * 80)
for c in sorted(comparisons, key=lambda x: x["edge"], reverse=True):
    match_str = f"{c['home']} vs {c['away']}"[:38]
    ev_sign = "+" if c["expected_value"] > 0 else ""
    print(f"{match_str:<40} {c['proba_model']:.1%}     {c['proba_market']:.1%}     "
          f"{c['edge']:+.1%}   {c['cote']:<6} {ev_sign}{c['expected_value']:.1%}")

# Stats
edges = [c["edge"] for c in comparisons]
evs = [c["expected_value"] for c in comparisons]
positive_edge = sum(1 for e in edges if e > 0)
positive_ev = sum(1 for e in evs if e > 0)

print(f"\n{'='*70}")
print(f"📈 STATISTIQUES GLOBALES")
print(f"{'='*70}")
print(f"Edge moyen        : {sum(edges)/len(edges):+.2%}")
print(f"Edge médian       : {sorted(edges)[len(edges)//2]:+.2%}")
print(f"Edge positif      : {positive_edge}/{len(edges)} ({positive_edge/len(edges):.1%})")
print(f"EV moyen          : {sum(evs)/len(evs):+.2%}")
print(f"EV positif        : {positive_ev}/{len(evs)} ({positive_ev/len(evs):.1%})")

if positive_ev > 0:
    print(f"\n💰 Si on avait parié sur les {positive_ev} EV positifs :")
    print(f"   Mise totale : {positive_ev}€ (1€ par pari)")
    total_return = sum(evs[i] + 1 for i in range(len(evs)) if evs[i] > 0)
    print(f"   Retour attendu : {total_return:.2f}€")
    print(f"   Profit attendu : {total_return - positive_ev:+.2f}€")

# Sauvegarde
out = {
    "date": datetime.now().isoformat(),
    "total": len(comparisons),
    "edge_mean": sum(edges)/len(edges),
    "ev_mean": sum(evs)/len(evs),
    "positive_edges": positive_edge,
    "comparisons": comparisons,
}
with open("data/compare_odds.json", "w") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
print(f"\n💾 Sauvegardé : data/compare_odds.json")
