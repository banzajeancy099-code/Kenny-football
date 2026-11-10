"""Backfill home_team_name, away_team_name, kickoff depuis Bzzoiro."""
import sys
sys.path.insert(0, 'src')
import kdb
from api.kbzzoiro import KBzzoiro

bzz = KBzzoiro()
conn = kdb._connect()
import contextlib
@contextlib.contextmanager
def _persistent():
    yield conn
kdb.get_conn = _persistent

# Compte les matchs à backfiller
r = conn.run("""
    SELECT COUNT(*) FROM k_predictions
    WHERE result_verdict IS NOT NULL
      AND (home_team_name IS NULL OR away_team_name IS NULL OR kickoff IS NULL)
""")
total = r[0][0]
print(f"{total} matchs à backfiller")

# Traite par paquets de 100
updated = 0
errors = 0
offset = 0

while offset < total:
    rows = conn.run("""
        SELECT match_id
        FROM k_predictions
        WHERE result_verdict IS NOT NULL
          AND (home_team_name IS NULL OR away_team_name IS NULL OR kickoff IS NULL)
        LIMIT 100
    """)
    if not rows:
        break
    
    for (mid,) in rows:
        try:
            ev = bzz.get_event_detail(int(mid))
            conn.run("""
                UPDATE k_predictions
                SET home_team_name = :h,
                    away_team_name = :a,
                    kickoff = :k
                WHERE match_id = :mid
            """,
                h=ev.get("home_team"),
                a=ev.get("away_team"),
                k=ev.get("event_date"),
                mid=str(mid),
            )
            updated += 1
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"  ! {mid} KO: {e}")
    
    offset += 100
    print(f"  ... {min(offset, total)}/{total} traités ({updated} OK, {errors} KO)")

print(f"\n✅ Terminé : {updated} backfillés, {errors} erreurs")
conn.close()
