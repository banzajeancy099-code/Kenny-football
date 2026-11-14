"""
Recalcule les edges (Poisson) sur toutes les prédictions existantes.
Pas d'appel API → rapide (10-15 min pour 7 000 matchs).
"""
import os
import sys
import math
import psycopg2
import psycopg2.extras

sys.path.insert(0, 'src')


def main():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Récupère toutes les prédictions avec expected_goals
    cur.execute("""
        SELECT 
            match_id,
            date,
            cote_over,
            cote_under,
            match_data->'l2_meta'->>'expected_goals' AS eg_str
        FROM k_predictions
        WHERE match_data->'l2_meta'->>'expected_goals' IS NOT NULL
          AND result_verdict IN ('✓','×')
    """)
    rows = cur.fetchall()
    print(f"=== {len(rows)} matchs à recalculer ===\n")

    n_updated = 0
    n_skipped = 0

    for r in rows:
        try:
            eg = float(r["eg_str"])
        except (TypeError, ValueError):
            n_skipped += 1
            continue

        if eg <= 0:
            n_skipped += 1
            continue

        # Poisson P(Over 2.5)
        p0 = math.exp(-eg)
        p_over = 1 - p0 * (1 + eg + eg**2 / 2)
        p_under = 1 - p_over

        # Edges
        cote_over = float(r["cote_over"]) if r["cote_over"] else None
        cote_under = float(r["cote_under"]) if r["cote_under"] else None

        edge_over = (p_over * cote_over - 1) if cote_over else None
        edge_under = (p_under * cote_under - 1) if cote_under else None

        # Update
        cur.execute("""
            UPDATE k_predictions
            SET proba_over = %s,
                proba_under = %s,
                edge_over = %s,
                edge_under = %s
            WHERE match_id = %s AND date = %s
        """, (round(p_over, 4), round(p_under, 4), 
              round(edge_over, 4) if edge_over else None,
              round(edge_under, 4) if edge_under else None,
              r["match_id"], r["date"]))
        n_updated += 1

        if n_updated % 500 == 0:
            conn.commit()
            print(f"  {n_updated} mis à jour...")

    conn.commit()
    print(f"\n✅ {n_updated} matchs mis à jour, {n_skipped} skippés")

    # Stats après
    cur.execute("""
        SELECT 
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE edge_over >= 0.03) AS edge_over_3pct,
            COUNT(*) FILTER (WHERE edge_under >= 0.03) AS edge_under_3pct,
            COUNT(*) FILTER (WHERE result_verdict = '✓') AS wins,
            COUNT(*) FILTER (WHERE result_verdict = '×') AS losses
        FROM k_predictions
        WHERE (edge_over >= 0.03 OR edge_under >= 0.03)
    """)
    stats = cur.fetchone()
    print(f"\n=== Stats après recalcule ===")
    print(f"  Total edge >= 3% : {stats['total']}")
    print(f"  Edge over >= 3% : {stats['edge_over_3pct']}")
    print(f"  Edge under >= 3% : {stats['edge_under_3pct']}")
    print(f"  Wins : {stats['wins']}")
    print(f"  Losses : {stats['losses']}")

    conn.close()


if __name__ == "__main__":
    main()
