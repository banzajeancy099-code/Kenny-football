"""Backfill home_team_name, away_team_name, kickoff depuis Bzzoiro (v2)."""
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
      AND (home_team_name IS NULL OR home_team_name = '' OR away_team_name IS NULL OR away_team_name = '' OR kickoff IS NULL)
""")
total = r[0][0]
print(f"{total} matchs à backfiller")

# Récupère les matchs (par paquets de 200)
updated = 0
errors = 0
test_mode = False

while True:
    rows = conn.run("""
        SELECT match_id
        FROM k_predictions
        WHERE result_verdict IS NOT NULL
          AND (home_team_name IS NULL OR home_team_name = '' OR away_team_name IS NULL OR away_team_name = '' OR kickoff IS NULL)
        LIMIT 200
    """)
    if not rows:
        break

    for (mid,) in rows:
        try:
            ev = bzz.get_event_detail(int(mid))

            home_team = ev.get("home_team") or ""
            away_team = ev.get("away_team") or ""
            kickoff = ev.get("event_date") or ""

            if not home_team or not away_team:
                print(f"  ! {mid} : noms manquants (home={home_team!r}, away={away_team!r})")
                errors += 1
                continue

            conn.run(
                "UPDATE k_predictions SET home_team_name = :h, away_team_name = :a, kickoff = :k WHERE match_id = :mid",
                h=home_team,
                a=away_team,
                k=kickoff,
                mid=str(mid),
            )
            updated += 1

            if updated % 50 == 0:
                print(f"  ... {updated}/{total} OK ({errors} KO)")

        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"  ! {mid} KO: {e}")

    # Vérifie si on progresse
    if updated == 0:
        print("⚠️ Aucun match mis à jour, arrêt.")
        break

print(f"\n✅ Terminé : {updated} backfillés, {errors} erreurs")
conn.close()
