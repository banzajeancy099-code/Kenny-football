"""Backfill league_id dans k_team_matches sur TOUS les jours (180 derniers)."""
import sys
sys.path.insert(0, 'src')

from datetime import datetime, timezone, timedelta
from api.kbzzoiro import KBzzoiro
import kdb

print("=== Phase 1 : collecte Bzzoiro (180 jours, jour par jour) ===")
bzz = KBzzoiro()
today = datetime.now(timezone.utc).date()

all_events = {}
for offset in range(180):
    d = (today - timedelta(days=offset)).isoformat()
    try:
        events = bzz.get_matches_range(d, d)
        for e in events:
            mid = str(e.get("id"))
            lid = e.get("league_id")
            if mid and lid:
                all_events[mid] = lid
    except Exception as ex:
        print(f"  ! {d} KO : {ex}")
    if offset % 10 == 0:
        print(f"  ... {offset}/180 jours, {len(all_events)} matchs collectés")

print(f"Total collecté : {len(all_events)} matchs avec league_id")

print("\n=== Phase 2 : UPDATE en DB ===")
sql = "UPDATE k_team_matches SET league_id = :league_id WHERE match_id = :match_id AND league_id IS NULL"
updated = 0
with kdb.get_conn() as conn:
    for i, (mid, lid) in enumerate(all_events.items()):
        try:
            conn.run(sql, match_id=mid, league_id=lid)
            updated += 1
        except Exception:
            pass
        if i > 0 and i % 500 == 0:
            print(f"  ... {i}/{len(all_events)} UPDATE, {updated} lignes")

print(f"\n✓ {updated} lignes mises à jour")

# Vérif
with kdb.get_conn() as conn:
    r = conn.run("SELECT COUNT(*) FROM k_team_matches WHERE league_id IS NOT NULL")
    print(f"k_team_matches avec league_id : {r[0][0]}")

    r = conn.run("""
        SELECT EXTRACT(DOW FROM date) AS dow, COUNT(DISTINCT match_id)
        FROM k_team_matches
        WHERE league_id IS NOT NULL
        GROUP BY dow ORDER BY dow
    """)
    print("\nMatchs par jour de semaine :")
    jours = ['Dim', 'Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam']
    for row in r:
        dow, n = row
        print(f"  {jours[int(dow)]} : {n}")
