"""
Backfill enrichi : recalcule L2 + L47 sur les 1172 matchs historiques
et met à jour k_predictions.match_data avec les vrais champs.

Usage :
    PYTHONPATH=src python -m kbackfill_enrich
"""

from __future__ import annotations

import json
from datetime import datetime

import kdb
from api.kbzzoiro import KBzzoiro
from api.kapi_football import KAPIFootball
from api.kodds import KOdds
from api.kpitchapi import KPitchAPI
from api.kpinnacle import KPinnacle
import kengine


def _load_matches_to_enrich():
    """Charge les matchs résolus qui n'ont pas encore de l2_meta enrichi."""
    sql = """
        SELECT match_id, date, league_id, home_team_id, away_team_id,
               home_team_name, away_team_name, kickoff, cote_over, cote_under,
               result_verdict, match_data
        FROM k_predictions
        WHERE result_verdict IS NOT NULL
          AND (match_data->>'l2_meta' IS NULL)
        ORDER BY date DESC
    """
    with kdb.get_conn() as conn:
        rows = conn.run(sql)
        cols = [c["name"] for c in conn.columns]
    return [dict(zip(cols, r)) for r in rows]


def main():
    bzz = KBzzoiro()
    ctx = {
        "bzzoiro": bzz,
        "api_football": KAPIFootball(),
        "odds": KOdds(bzzoiro=bzz),
        "pitchapi": KPitchAPI(),
        "pinnacle": KPinnacle(),
        "db": kdb,
    }

    matches = _load_matches_to_enrich()
    print(f"=== {len(matches)} matchs à enrichir ===\n")

    enriched = 0
    errors = 0

    for i, m in enumerate(matches):
        try:
            # Reconstruit le match à partir des données DB
            match = {
                "match_id": m["match_id"],
                "fixture_id": m["match_id"],
                "league_id": m["league_id"],
                "home_team_id": m["home_team_id"],
                "away_team_id": m["away_team_id"],
                "home_team_name": m["home_team_name"],
                "away_team_name": m["away_team_name"],
                "kickoff": m["kickoff"],
                "event_date": m["kickoff"],
                "cote_over": m["cote_over"],
                "cote_under": m["cote_under"],
                "cote_home": None,
                "cote_draw": None,
                "cote_away": None,
                "weather": {},
                "head_to_head": {},
                "previous_leg_event_id": None,
                "round_number": None,
                "referee_id": None,
                "league_nb_teams": 20,
                "over_rate": 0.52,
            }

            # Enrichit depuis Bzzoiro
            try:
                ev = bzz.get_event_detail(int(m["match_id"]))
                match["referee_id"] = ev.get("referee_id")
                match["round_number"] = ev.get("round_number")
                match["weather"] = ev.get("weather") or {}
                match["head_to_head"] = ev.get("head_to_head") or {}
                match["previous_leg_event_id"] = ev.get("previous_leg_event_id")
            except Exception:
                pass

            # Enrichit standings
            try:
                standings = bzz.fetch_league_standings(match["league_id"])
                pm = {s["team_id"]: s["position"] for s in standings if s.get("team_id")}
                match["home_position"] = pm.get(match["home_team_id"])
                match["away_position"] = pm.get(match["away_team_id"])
                if standings:
                    match["league_nb_teams"] = len(standings)
            except Exception:
                pass

            # Recalcule via kengine
            res = kengine.run_match(match, ctx, bankroll=1000.0)

            # Reconstruit match_data enrichi
            enriched_data = {
                "market": res["market"],
                "edge": res["edge"],
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
                    "xg_factor": l2.meta.get("xg_factor"),
                    "h2h_factor": l2.meta.get("h2h_factor"),
                    "context_adjustment": l2.meta.get("context_adjustment"),
                }
                enriched_data["xgf_home"] = l2.meta.get("xgf_home")
                enriched_data["xgf_away"] = l2.meta.get("xgf_away")
                enriched_data["h2h_avg_goals"] = match["head_to_head"].get("avg_total_goals")
                enriched_data["h2h_recent"] = (match["head_to_head"].get("recent_matches") or [])[:5]
                enriched_data["form_home_gf"] = l2.meta.get("home_form_gf")
                enriched_data["form_away_gf"] = l2.meta.get("away_form_gf")

            l47 = res["layer_results"].get("l47")
            if l47 and not l47.rejected:
                enriched_data["l47_meta"] = {
                    "raw_score": l47.meta.get("raw_score"),
                    "c1_stats": l47.meta.get("c1_stats"),
                    "c2_forme": l47.meta.get("c2_forme"),
                    "c3_meteo": l47.meta.get("c3_meteo"),
                    "c4_enjeu": l47.meta.get("c4_enjeu"),
                    "c5_pitchapi": l47.meta.get("c5_pitchapi"),
                    "c6_blessures": l47.meta.get("c6_blessures"),
                    "c7_clv": l47.meta.get("c7_clv"),
                }
                enriched_data["pitchapi"] = l47.meta.get("pitchapi_stats") or {}

            enriched_data["context"] = {
                "round_number": match.get("round_number"),
                "referee_id": match.get("referee_id"),
                "league_id": match.get("league_id"),
                "weather": match.get("weather"),
            }

            # Met à jour k_predictions
            sql = """
                UPDATE k_predictions
                SET match_data = :match_data,
                    score = :score,
                    confidence = :confidence,
                    proba_over = :proba_over,
                    proba_under = :proba_under
                WHERE match_id = :match_id
            """
            with kdb.get_conn() as conn:
                conn.run(
                    sql,
                    match_id=m["match_id"],
                    match_data=json.dumps(enriched_data),
                    score=res["score"],
                    confidence=max((r.confidence for r in res["layer_results"].values()), default=0.0),
                    proba_over=res["proba"] if res["market"] == "over" else None,
                    proba_under=res["proba"] if res["market"] == "under" else None,
                )

            enriched += 1
            if (i + 1) % 50 == 0:
                print(f"  ... {i+1}/{len(matches)} enrichis ({enriched} OK, {errors} KO)")

        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"  ! {m['match_id']} KO : {e}")

    print(f"\n✅ {enriched}/{len(matches)} enrichis, {errors} erreurs")


if __name__ == "__main__":
    main()
