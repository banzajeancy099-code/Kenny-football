"""
Refresh odds — Récupère les côtes des matchs typés pour les 7 prochains jours.
Écrit dans k_odds_snapshots pour la détection fraude.

Usage :
    python3 scripts/refresh_odds.py
"""
import os
import sys
import json
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta

sys.path.insert(0, 'src')

import kdb
import kengine


KEYS = [k for k in [
    os.environ.get("BZZOIRO_API_KEY_5"),
    os.environ.get("BZZOIRO_API_KEY"),
] if k]

if not KEYS:
    print("❌ Aucune clé Bzzoiro (BZZOIRO_API_KEY ou BZZOIRO_API_KEY_5)")
    sys.exit(1)

key_idx = 0


def get(path, params=None):
    """GET avec rotation clés sur 429."""
    global key_idx
    url = "https://sports.bzzoiro.com/api/v2" + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    
    for _ in range(len(KEYS)):
        key = KEYS[key_idx % len(KEYS)]
        key_idx += 1
        req = urllib.request.Request(
            url, headers={"Authorization": f"Token {key}"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                continue
            if e.code == 404:
                return None
            raise
        except Exception as e:
            print(f"  ⚠️ {path} : {e}")
            continue
    return None


def main():
    TYPED = kengine.LEAGUES_OVER | kengine.LEAGUES_UNDER
    today = datetime.now().date()
    total_snapshots = 0
    total_matches = 0
    errors = 0
    
    for offset in range(-1, 7):  # J-1 (veille) à J-6
        date_str = (today + timedelta(days=offset)).isoformat()
        
        # Récupère les matchs du jour
        data = get("/events/", {
            "date_from": date_str,
            "date_to": date_str,
            "limit": 200,
        })
        if not data:
            print(f"📅 {date_str} : ❌ aucun match")
            continue
        
        events = data.get("results", [])
        typed = [
            e for e in events
            if e.get("league_id") in TYPED and e.get("home_score") is None
        ]
        
        print(f"📅 {date_str} : {len(typed)} matchs typés (sur {len(events)})")
        
        for ev in typed:
            ev_id = ev.get("id")
            if not ev_id:
                continue
            
            odds = get(f"/events/{ev_id}/odds/")
            if not odds or "odds" not in odds:
                continue
            
            raw = odds["odds"]
            cote_over = raw.get("over_25_goals")
            cote_under = raw.get("under_25_goals")
            
            if cote_over and cote_under:
                try:
                    kdb.ksave_odds_snapshot(
                        str(ev_id), "bzzoiro", "over_2.5", 2.5, float(cote_over)
                    )
                    kdb.ksave_odds_snapshot(
                        str(ev_id), "bzzoiro", "under_2.5", 2.5, float(cote_under)
                    )
                    total_snapshots += 2
                    total_matches += 1
                except Exception as e:
                    errors += 1
                    print(f"  ⚠️ save {ev_id} : {e}")
            
            time.sleep(0.05)  # rate limit
    
    print(f"\n✅ {total_matches} matchs, {total_snapshots} snapshots, {errors} erreurs")


if __name__ == "__main__":
    main()
