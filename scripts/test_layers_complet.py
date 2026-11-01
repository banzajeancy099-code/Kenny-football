#!/usr/bin/env python3
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date, timedelta

from src.clients.bzzoiro import BzzoiroClient
from src.layers.l14_xg import XGLayer
from src.layers.l33_squad_depth import SquadDepthLayer
from src.layers.l34_context_enjeu import ContextEnjeuLayer

print("=" * 60)
print("ETAPE 0 : Test Bzzoiro")
print("=" * 60)
bz = BzzoiroClient(api_key=os.environ.get("BZZOIRO_API_KEY"))
try:
    t0 = time.time()
    matches = bz.get_matches_today("2026-10-30")
    print(f"OK Bzzoiro : {len(matches)} matchs en {time.time()-t0:.1f}s")
except Exception as e:
    print(f"ECHEC Bzzoiro : {e}")
    sys.exit(1)

print()
print("=" * 60)
print("ETAPE 1 : Trouver un match test")
print("=" * 60)
test_match = None
for days_back in range(1, 10):
    d = (date.today() - timedelta(days=days_back)).isoformat()
    try:
        day_matches = bz.get_matches_today(d)
        finished = [m for m in day_matches if m.get("status") == "finished" and m.get("league_id") in (9, 10, 5)]
        if finished:
            test_match = finished[0]
            print(f"OK Match : {test_match.get('home_team')} vs {test_match.get('away_team')}")
            print(f"  Ligue {test_match.get('league_id')}, date {d}")
            break
    except Exception:
        continue

if not test_match:
    print("ECHEC : aucun match termine trouve")
    sys.exit(1)

print()
print("=" * 60)
print("ETAPE 2 : Test L14")
print("=" * 60)
try:
    l14 = XGLayer(bz)
    r14 = l14.compute(test_match, {})
    print(f"Score L14    : {r14.score}")
    print(f"Confiance    : {r14.confidence}")
    if r14.raw:
        print(f"xG total     : {r14.raw.get('total_xg')}")
        print(f"Reasons      : {r14.raw.get('reasons', [])[:2]}")
    print("OK L14")
except Exception as e:
    print(f"ECHEC L14 : {e}")
    r14 = None

print()
print("=" * 60)
print("ETAPE 3 : Test L34")
print("=" * 60)
try:
    l34 = ContextEnjeuLayer(bz)
    r34 = l34.compute(test_match, {})
    print(f"Score L34    : {r34.score}")
    print(f"Confiance    : {r34.confidence}")
    if r34.raw:
        h = r34.raw.get("home") or {}
        a = r34.raw.get("away") or {}
        print(f"Home enjeu   : {h.get('enjeu')}")
        print(f"Away enjeu   : {a.get('enjeu')}")
    print("OK L34")
except Exception as e:
    print(f"ECHEC L34 : {e}")
    r34 = None

print()
print("=" * 60)
print("ETAPE 4 : Test L33 (peut prendre 30-40s)")
print("=" * 60)
try:
    l33 = SquadDepthLayer(bz)
    t0 = time.time()
    r33 = l33.compute(test_match, {})
    elapsed = time.time() - t0
    print(f"Score L33    : {r33.score}")
    print(f"Confiance    : {r33.confidence}")
    print(f"Temps        : {elapsed:.1f}s")
    if r33.raw:
        h = r33.raw.get("home") or {}
        a = r33.raw.get("away") or {}
        print(f"Home attack  : {h.get('attack_per_player')}")
        print(f"Away attack  : {a.get('attack_per_player')}")
        print(f"Home FWD     : {h.get('n_fwd_titulaires')}")
        print(f"Away FWD     : {a.get('n_fwd_titulaires')}")
    print("OK L33")
except Exception as e:
    print(f"ECHEC L33 : {e}")
    r33 = None

print()
print("=" * 60)
print("RESUME")
print("=" * 60)
print(f"Bzzoiro : OK")
print(f"L14     : {'OK' if r14 else 'ECHEC'}")
print(f"L33     : {'OK' if r33 else 'ECHEC'}")
print(f"L34     : {'OK' if r34 else 'ECHEC'}")
