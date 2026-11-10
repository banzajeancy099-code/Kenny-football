"""
Enrichissement BATCH des matchs (hors amicaux).
Version propre : connexion persistante + autocommit + skip layer_perf + COMMIT par batch.
"""
import sys
import json
import kdb
from api.kbzzoiro import KBzzoiro
from api.kodds import KOdds
import kengine

EXCLUDED_LEAGUES = [79, 31, 57]
BATCH_SIZE = 10  # écriture tous les 10 matchs


def main():
    print("=== Ouverture connexion persistante ===", flush=True)
    persistent_conn = kdb._connect()
    # Force autocommit
    persistent_conn.autocommit = True

    import contextlib
    @contextlib.contextmanager
    def _persistent_get_conn():
        yield persistent_conn
    kdb.get_conn = _persistent_get_conn
    print("✅ Connexion persistante + autocommit", flush=True)

    try:
        _run(persistent_conn)
    finally:
        persistent_conn.close()
        print("✅ Connexion fermée", flush=True)


def _run(conn):
    print("=== Chargement des matchs ===", flush=True)
    sql = """
        SELECT match_id, league_id, home_team_id, away_team_id,
               home_team_name, away_team_name, kickoff, cote_over, cote_under
        FROM k_predictions
        WHERE result_verdict IS NOT NULL
          AND league_id IS NOT NULL
          AND league_id != ALL(:excluded)
          AND (match_data->>'l2_meta' IS NULL)
        ORDER BY date DESC
    """
    rows = conn.run(sql, excluded=EXCLUDED_LEAGUES)
    cols = [c["name"] for c in conn.columns]
    matches = [dict(zip(cols, r)) for r in rows]
    print(f"{len(matches)} matchs à enrichir\n", flush=True)

    if not matches:
        print("✅ Tous les matchs sont déjà enrichis")
        return

    bzz = KBzzoiro(conn=conn)
    print("✅ Cache équipes activé", flush=True)

    ctx = {
        "bzzoiro": bzz,
        "api_football": None,
        "odds": KOdds(bzzoiro=bzz),
        "pitchapi": None,
        "pinnacle": None,
        "db": kdb,
        "skip_layer_perf": True,  # ← CRUCIAL : désactive ksave_layer_perf
    }

    enriched = 0
    errors = 0
    updates = []

    for i, m in enumerate(matches):
        try:
            match = {
                "match_id": str(m["match_id"]),
                "fixture_id": m["match_id"],
                "league_id": m["league_id"],
                "home_team_id": m["home_team_id"],
                "away_team_id": m["away_team_id"],
                "home_team_name": m["home_team_name"] or "Home",
                "away_team_name": m["away_team_name"] or "Away",
                "kickoff": m["kickoff"],
                "event_date": m["kickoff"],
                "cote_over": m["cote_over"],
                "cote_under": m["cote_under"],
                "weather": {}, "head_to_head": {},
                "league_nb_teams": 20, "over_rate": 0.52,
            }

            # Détail Bzzoiro (météo, H2H, arbitre)
            try:
                ev = bzz.get_event_detail(int(m["match_id"]))
                match["referee_id"] = ev.get("referee_id")
                match["round_number"] = ev.get("round_number")
                match["weather"] = ev.get("weather") or {}
                match["head_to_head"] = ev.get("head_to_head") or {}
            except Exception:
                pass

            # Cotes si absentes
            if match["cote_over"] is None or match["cote_under"] is None:
                try:
                    odds = ctx["odds"].fetch_over_under(match)
                    if odds:
                        match["cote_over"] = odds.get("cote_over")
                        match["cote_under"] = odds.get("cote_under")
                except Exception:
                    pass

            # Calcul L1/L2/L47
            res = kengine.run_match(match, ctx, bankroll=1000.0)

            enriched_data = {
                "market": res["market"],
                "edge": res.get("edge"),
                "score": res["score"],
                "signal": res["signal"],
            }

            l2 = res["layer_results"].get("l02")
            if l2 and not l2.rejected:
                enriched_data["l2_meta"] = {
                    "expected_goals": l2.meta.get("expected_goals"),
                    "c1": l2.meta.get("c1"),
                    "c2": l2.meta.get("c2"),
                    "c3": l2.meta.get("c3"),
                    "consistency_score": l2.meta.get("consistency_score"),
                    "form_factor": l2.meta.get("form_factor"),
                    "h2h_factor": l2.meta.get("h2h_factor"),
                }
                enriched_data["h2h_avg_goals"] = match["head_to_head"].get("avg_total_goals")
                enriched_data["form_home_gf"] = l2.meta.get("home_form_gf")
                enriched_data["form_away_gf"] = l2.meta.get("away_form_gf")

            updates.append({
                "match_id": str(m["match_id"]),
                "match_data": json.dumps(enriched_data),
                "cote_over": match["cote_over"],
                "cote_under": match["cote_under"],
            })
            enriched += 1

        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  ! {m['match_id']} KO : {e}", flush=True)

        # Écriture batch
        if len(updates) >= BATCH_SIZE:
            print(f"  [DEBUG] Batch UPDATE de {len(updates)} matchs...", flush=True)
            try:
                for u in updates:
                    conn.run(
                        "UPDATE k_predictions SET match_data = :md::jsonb, cote_over = :co, cote_under = :cu WHERE match_id = :mid",
                        md=u["match_data"], mid=u["match_id"],
                        co=u["cote_over"], cu=u["cote_under"],
                    )
                print(f"  [DEBUG] Batch UPDATE OK", flush=True)
                updates = []
            except Exception as e:
                print(f"  ! Batch update KO : {e}", flush=True)

        if (i+1) % 10 == 0:
            print(f"  ... {i+1}/{len(matches)} traités ({enriched} OK, {errors} KO)", flush=True)

    # Dernier batch
    if updates:
        try:
            for u in updates:
                conn.run(
                    "UPDATE k_predictions SET match_data = :md::jsonb, cote_over = :co, cote_under = :cu WHERE match_id = :mid",
                    md=u["match_data"], mid=u["match_id"],
                    co=u["cote_over"], cu=u["cote_under"],
                )
        except Exception as e:
            print(f"  ! Dernier batch KO : {e}", flush=True)

    print(f"\n✅ Terminé : {enriched} enrichis, {errors} erreurs", flush=True)

    r = conn.run("SELECT COUNT(*) FROM k_predictions WHERE match_data->>'l2_meta' IS NOT NULL")
    print(f"Total matchs avec l2_meta : {r[0][0]}", flush=True)


if __name__ == "__main__":
    main()
