"""Backfill home_team_name, away_team_name depuis Bzzoiro."""
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

# Trouve les matchs sans home_team_name
rows = conn.run("""
    SELECT match_id, home_team_id, away_team_id
    FROM k_predictions
    WHERE result_verdict IS NOT NULL
      AND (home_team_name IS NULL OR away_team_name IS NULL)
    LIMIT 50
""")
print(f"{len(rows)} matchs à backfiller")

# Cache des noms d'équipes
team_names = {}

updated = 0
for row in rows:
    mid, home_id, away_id = row
    # Récupère le nom via Bzzoiro
    for tid in (home_id, away_id):
        if tid not in team_names:
            try:
                data = bzz._get(f"/teams/{tid}/")
                team_names[tid] = data.get("name", "")
            except Exception:
                team_names[tid] = ""
    
    home_name = team_names.get(home_id, "")
    away_name = team_names.get(away_id, "")
    
    if home_name and away_name:
        conn.run(
            "UPDATE k_predictions SET home_team_name = :h, away_team_name = :a WHERE match_id = :mid",
            h=home_name, a=away_name, mid=str(mid),
        )
        updated += 1

print(f"✅ {updated}/{len(rows)} matchs backfillés")
conn.close()
