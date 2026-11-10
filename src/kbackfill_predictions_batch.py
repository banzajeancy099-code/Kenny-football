"""Backfill k_predictions depuis k_team_matches — BATCH optimisé."""
import sys
import json
import kdb


def main():
    print("=== Phase 1 : lecture k_team_matches ===")
    sql = """
        SELECT DISTINCT ON (match_id)
            match_id, date,
            team_id AS home_team_id,
            opponent_id AS away_team_id,
            goals_for AS home_score,
            goals_against AS away_score,
            league_id
        FROM k_team_matches
        WHERE is_home = true AND league_id IS NOT NULL
        ORDER BY match_id, date DESC
    """
    with kdb.get_conn() as conn:
        rows = conn.run(sql)
        cols = [c["name"] for c in conn.columns]

    print(f"{len(rows)} matchs à insérer\n")

    print("=== Phase 2 : INSERT BATCH (500 par 500) ===")
    BATCH_SIZE = 500
    inserted = 0
    errors = 0

    with kdb.get_conn() as conn:
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i:i+BATCH_SIZE]
            # Construit la clause VALUES pour le batch
            values = []
            for r in batch:
                d = dict(zip(cols, r))
                hs = d["home_score"] or 0
                as_ = d["away_score"] or 0
                total = hs + as_
                verdict = "✓" if total > 2.5 else "×"
                date_val = d["date"].isoformat() if hasattr(d["date"], "isoformat") else str(d["date"])
                match_data_json = json.dumps({
                    "home_score": hs, "away_score": as_,
                    "total_goals": total, "league_id": d["league_id"],
                }).replace("'", "''")

                values.append(
                    f"('{date_val}', '{d['match_id']}', {d['league_id']}, "
                    f"{d['home_team_id']}, {d['away_team_id']}, "
                    f"'{verdict}', '{match_data_json}'::jsonb)"
                )

            sql = f"""
                INSERT INTO k_predictions (
                    date, match_id, league_id, home_team_id, away_team_id,
                    result_verdict, match_data
                ) VALUES {', '.join(values)}
                ON CONFLICT (date, match_id) DO UPDATE SET
                    result_verdict = EXCLUDED.result_verdict,
                    match_data = EXCLUDED.match_data,
                    league_id = EXCLUDED.league_id
            """
            try:
                conn.run(sql)
                inserted += len(batch)
                print(f"  ... {min(i+BATCH_SIZE, len(rows))}/{len(rows)} ({inserted} OK)")
            except Exception as e:
                errors += len(batch)
                print(f"  ! Batch {i//BATCH_SIZE + 1} KO : {e}")

    print(f"\n✅ {inserted} insérés, {errors} erreurs")

    with kdb.get_conn() as conn:
        r = conn.run("SELECT COUNT(*) FROM k_predictions WHERE result_verdict IS NOT NULL")
        print(f"k_predictions résolus : {r[0][0]}")
        r = conn.run("SELECT COUNT(DISTINCT date) FROM k_predictions WHERE result_verdict IS NOT NULL")
        print(f"Dates distinctes : {r[0][0]}")


if __name__ == "__main__":
    main()
