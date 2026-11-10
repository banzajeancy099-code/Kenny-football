"""Backfill league_id dans k_team_matches — version BATCH optimisée pg8000."""
import sys
sys.path.insert(0, 'src')

from datetime import datetime, timezone, timedelta
from api.kbzzoiro import KBzzoiro
import kdb

print("=== Phase 1 : collecte Bzzoiro (180 jours) ===")
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

print(f"Total collecté : {len(all_events)} matchs\n")

print("=== Phase 2 : UPDATE BATCH (500 par 500) ===")
BATCH_SIZE = 500
items = list(all_events.items())
total = len(items)
updated = 0
failed = 0

with kdb.get_conn() as conn:
    for i in range(0, total, BATCH_SIZE):
        batch = items[i:i+BATCH_SIZE]
        # Construit la clause VALUES (safe car match_id et league_id sont numériques)
        values_clause = ", ".join(
            f"('{mid}', {int(lid)})" for mid, lid in batch
        )
        sql = f"""
            UPDATE k_team_matches AS m
            SET league_id = v.league_id
            FROM (VALUES {values_clause}) AS v(match_id, league_id)
            WHERE m.match_id = v.match_id
              AND m.league_id IS NULL
        """
        try:
            conn.run(sql)
            updated += len(batch)
        except Exception as e:
            print(f"  ! Batch {i//BATCH_SIZE + 1} KO : {e}")
            failed += len(batch)

        print(f"  ... {min(i+BATCH_SIZE, total)}/{total} traités (batch {i//BATCH_SIZE + 1})")

print(f"\n✅ Terminé : {updated} matchs traités, {failed} échecs")

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
