# scripts/collect_odds.py — Enregistrer les cotes toutes les 2h (snapshots)
import os
import sys
import json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.clients.the_odds_api import TheOddsAPIClient

TO_KEY = os.environ.get("THE_ODDS_API_KEY")
if not TO_KEY:
    print("❌ THE_ODDS_API_KEY manquante")
    sys.exit(1)

LEAGUES = [
    "soccer_epl",
    "soccer_italy_serie_a",
    "soccer_germany_bundesliga",
    "soccer_france_ligue_one",
    "soccer_brazil_campeonato",
    "soccer_netherlands_eredivisie",
    "soccer_efl_champ",
    "soccer_belgium_first_div",
    "soccer_switzerland_superleague",
    "soccer_usa_mls",
    "soccer_mexico_ligamx",
    "soccer_norway_eliteserien",
    "soccer_austria_bundesliga",
]

client = TheOddsAPIClient(api_key=TO_KEY)
data_dir = Path(__file__).parent.parent / "data" / "odds_snapshots"
data_dir.mkdir(parents=True, exist_ok=True)

now = datetime.now()
snapshot_time = now.strftime("%Y%m%d_%H%M")
out_file = data_dir / f"{snapshot_time}.json"

print(f"💾 Snapshot cotes : {snapshot_time}")

snapshot = {
    "timestamp": now.isoformat(),
    "odds": {}
}

total_matches = 0
for sport_key in LEAGUES:
    try:
        data = client._get(f"/sports/{sport_key}/odds", {
            "regions": "eu",
            "markets": "totals",
            "oddsFormat": "decimal",
        })
        if not data:
            continue
        snapshot["odds"][sport_key] = []
        for m in data:
            best_over = None
            best_bk = None
            for bk in m.get("bookmakers", []):
                for mkt in bk.get("markets", []):
                    if mkt.get("key") != "totals":
                        continue
                    for o in mkt.get("outcomes", []):
                        if o.get("name") == "Over" and o.get("point") == 2.5:
                            p = o.get("price", 0)
                            if p and (best_over is None or p > best_over):
                                best_over = p
                                best_bk = bk.get("key")
            if best_over:
                snapshot["odds"][sport_key].append({
                    "id": m.get("id"),
                    "home": m.get("home_team"),
                    "away": m.get("away_team"),
                    "commence_time": m.get("commence_time"),
                    "best_over_2_5": best_over,
                    "bookmaker": best_bk,
                })
                total_matches += 1
        n = len(snapshot["odds"][sport_key])
        if n:
            print(f"  {sport_key} : {n} matchs")
    except Exception as e:
        print(f"  ⚠️ {sport_key} : {e}")

with open(out_file, "w") as f:
    json.dump(snapshot, f, indent=2, ensure_ascii=False)
print(f"\n✅ Snapshot sauvegardé : {out_file}")
print(f"📊 {total_matches} matchs au total")
