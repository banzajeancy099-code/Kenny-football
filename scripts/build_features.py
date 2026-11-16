"""
Build k_features (version propre).
- Commit toutes les 50 lignes
- Timeout 30s
- Rollback en cas d'erreur
- Ferme la connexion proprement
"""
import os
import sys
import math
import psycopg2
import psycopg2.extras

sys.path.insert(0, 'src')


def main():
    conn = None
    try:
        conn = psycopg2.connect(
            os.environ["DATABASE_URL"],
            options="-c statement_timeout=30000"
        )
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Récupère les matchs avec l2_meta
        cur.execute("""
            SELECT 
                kp.match_id,
                kp.date,
                kp.league_id,
                kp.home_team_id,
                kp.away_team_id,
                kp.cote_over,
                kp.cote_under,
                kp.result_verdict,
                (kp.match_data->'l2_meta'->>'expected_goals')::float AS eg,
                kp.match_data->'weather' AS weather,
                kp.match_data->'head_to_head' AS h2h,
                kp.match_data->>'round_number' AS round_number,
                kp.match_data->>'is_local_derby' AS is_local_derby
            FROM k_predictions kp
            WHERE kp.result_verdict IN ('✓','×')
              AND kp.match_data->'l2_meta'->>'expected_goals' IS NOT NULL
              AND kp.league_id IN (9, 85, 19, 4, 7, 83, 14, 89, 8, 34, 18, 38)
        """)
        matchs = cur.fetchall()
        print(f"=== {len(matchs)} matchs à traiter ===\n", flush=True)

        n_inserted = 0

        for i, m in enumerate(matchs, 1):
            try:
                # Forme (5 derniers matchs) — 1 seule requête
                cur.execute("""
                    SELECT 
                        team_id,
                        AVG(goals_for) AS form_gf,
                        AVG(goals_against) AS form_ga
                    FROM (
                        SELECT team_id, goals_for, goals_against,
                               ROW_NUMBER() OVER (PARTITION BY team_id ORDER BY date DESC) AS rn
                        FROM k_team_matches
                        WHERE team_id IN (%s, %s)
                    ) sub
                    WHERE rn <= 5
                    GROUP BY team_id
                """, (m["home_team_id"], m["away_team_id"]))
                forms = {r["team_id"]: r for r in cur.fetchall()}
                home_form = forms.get(m["home_team_id"])
                away_form = forms.get(m["away_team_id"])

                # H2H
                h2h = m.get("h2h") or {}
                h2h_avg = h2h.get("avg_total_goals") if isinstance(h2h, dict) else None
                h2h_n = h2h.get("total_matches", 0) if isinstance(h2h, dict) else 0

                # Météo
                weather = m.get("weather") or {}
                weather_severity = 0
                if isinstance(weather, dict):
                    desc = (weather.get("description") or "").lower()
                    wind = weather.get("wind_speed") or 0
                    if "heavy_rain" in desc or "storm" in desc:
                        weather_severity = 3
                    elif "rain" in desc:
                        weather_severity = 1
                    elif wind > 30:
                        weather_severity = 2

                # Contexte
                round_num = m.get("round_number")
                is_end_season = 1 if round_num and int(round_num) > 30 else 0
                is_derby = 1 if m.get("is_local_derby") == "true" else 0

                # Target
                over_target = 1 if m["eg"] > 2.5 else 0

                # Proba Poisson
                eg = m["eg"]
                p0 = math.exp(-eg)
                proba_poisson = 1 - p0 * (1 + eg + eg**2 / 2)

                # Insert
                cur.execute("""
                    INSERT INTO k_features (
                        match_id, date, league_id, home_team_id, away_team_id,
                        is_end_season_home, is_end_season_away,
                        is_local_derby, weather_severity,
                        form_gf_5_home, form_gf_5_away,
                        form_ga_5_home, form_ga_5_away,
                        h2h_avg_goals, h2h_n,
                        cote_over, cote_under, proba_poisson,
                        over_target, result_verdict
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s
                    )
                    ON CONFLICT (match_id, date) DO UPDATE SET
                        form_gf_5_home = EXCLUDED.form_gf_5_home,
                        form_gf_5_away = EXCLUDED.form_gf_5_away,
                        h2h_avg_goals = EXCLUDED.h2h_avg_goals,
                        h2h_n = EXCLUDED.h2h_n,
                        weather_severity = EXCLUDED.weather_severity,
                        is_local_derby = EXCLUDED.is_local_derby,
                        is_end_season_home = EXCLUDED.is_end_season_home,
                        is_end_season_away = EXCLUDED.is_end_season_away,
                        proba_poisson = EXCLUDED.proba_poisson,
                        over_target = EXCLUDED.over_target,
                        result_verdict = EXCLUDED.result_verdict
                """, (
                    m["match_id"], m["date"], m["league_id"], m["home_team_id"], m["away_team_id"],
                    is_end_season, is_end_season,
                    is_derby, weather_severity,
                    home_form["form_gf"] if home_form else None,
                    away_form["form_gf"] if away_form else None,
                    home_form["form_ga"] if home_form else None,
                    away_form["form_ga"] if away_form else None,
                    h2h_avg, h2h_n,
                    m["cote_over"], m["cote_under"], proba_poisson,
                    over_target, m["result_verdict"]
                ))
                n_inserted += 1

                # Commit toutes les 50 lignes
                if n_inserted % 50 == 0:
                    conn.commit()
                    print(f"  {n_inserted} traités...", flush=True)

            except Exception as e:
                print(f"  KO {m.get('match_id')} : {e}", flush=True)
                conn.rollback()
                continue

        conn.commit()
        print(f"\n✅ {n_inserted} matchs traités", flush=True)

        # Stats
        cur.execute("""
            SELECT 
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE form_gf_5_home IS NOT NULL) AS avec_forme,
                COUNT(*) FILTER (WHERE h2h_avg_goals IS NOT NULL) AS avec_h2h,
                COUNT(*) FILTER (WHERE weather_severity > 0) AS avec_meteo,
                COUNT(*) FILTER (WHERE is_local_derby = 1) AS avec_derby,
                COUNT(*) FILTER (WHERE over_target = 1) AS over,
                COUNT(*) FILTER (WHERE over_target = 0) AS under
            FROM k_features
        """)
        stats = cur.fetchone()
        print(f"\n=== Stats finales ===")
        for k, v in stats.items():
            print(f"  {k} : {v}")

    except Exception as e:
        print(f"❌ Erreur globale : {e}", flush=True)
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()
            print("✅ Connexion fermée", flush=True)


if __name__ == "__main__":
    main()
