"""
Test L1 + L2 + L47 en réel sur un match Bzzoiro.

Usage :
    PYTHONPATH=src python -m ktest_l47
"""

from __future__ import annotations

from api.kbzzoiro import KBzzoiro
from api.kapi_football import KAPIFootball
from api.kodds import KOdds
from api.kpitchapi import KPitchAPI
from api.kpinnacle import KPinnacle
import kdb
from layers.kl01_strength import KL01Strength
from layers.kl02_over import KL02Over
from layers.kl47_under_score import KL47UnderScore


def build_ctx():
    bzz = KBzzoiro()
    return {
        "bzzoiro": bzz,
        "api_football": KAPIFootball(),
        "odds": KOdds(bzzoiro=bzz),
        "pitchapi": KPitchAPI(),
        "pinnacle": KPinnacle(),
        "db": kdb,
    }


def fetch_match(bzz, event_id: int) -> dict:
    ev = bzz.get_event_detail(event_id)
    match = {
        "match_id": str(ev.get("id")),
        "fixture_id": ev.get("id"),
        "league_id": ev.get("league_id"),
        "home_team_id": ev.get("home_team_id"),
        "away_team_id": ev.get("away_team_id"),
        "home_team_name": ev.get("home_team"),
        "away_team_name": ev.get("away_team"),
        "kickoff": ev.get("event_date"),
        "event_date": ev.get("event_date"),
        "referee_id": ev.get("referee_id"),
        "weather": ev.get("weather") or {},
        "head_to_head": ev.get("head_to_head") or {},
        "previous_leg_event_id": ev.get("previous_leg_event_id"),
        "cote_over": None,
        "cote_under": None,
        "league_nb_teams": 20,
        "over_rate": 0.52,
    }

    # Enrichir avec les positions (standings) pour c4_enjeu
    try:
        standings = bzz.fetch_league_standings(ev.get("league_id"))
        pos_map = {
            s["team_id"]: s["position"]
            for s in standings
            if s.get("team_id") and s.get("position")
        }
        match["home_position"] = pos_map.get(ev.get("home_team_id"))
        match["away_position"] = pos_map.get(ev.get("away_team_id"))
        if standings:
            match["league_nb_teams"] = len(standings)
    except Exception as e:
        print(f"[enrich] standings KO : {e}")

    return match


def main():
    bzz = KBzzoiro()
    ctx = build_ctx()

    event_id = 10216
    print(f"=== Test L1 + L2 + L47 sur event_id={event_id} ===\n")

    match = fetch_match(bzz, event_id)
    print(f"Match : {match['home_team_name']} vs {match['away_team_name']}")
    print(f"League : {match['league_id']} | fixture_id : {match['fixture_id']}")

    odds = ctx["odds"].fetch_over_under(match)
    if odds:
        match["cote_over"] = odds["cote_over"]
        match["cote_under"] = odds["cote_under"]
        print(f"Cotes : over={odds['cote_over']:.2f} | under={odds['cote_under']:.2f} | source={odds['source']}")
    else:
        print("Cotes : AUCUNE")
    print()

    # L1
    print("--- L1 STRENGTH ---")
    r1 = KL01Strength().run(match, ctx)
    print(f"  rejected={r1.rejected} score={r1.score} confidence={r1.confidence}")
    if r1.warnings:
        print(f"  warnings: {r1.warnings}")
    print()

    # L2
    print("--- L2 OVER 2.5 ---")
    r2 = KL02Over().run(match, ctx)
    print(f"  rejected={r2.rejected} score={r2.score} confidence={r2.confidence}")
    if r2.warnings:
        print(f"  warnings: {r2.warnings}")
    print(f"  meta: {r2.meta.get('expected_goals')}")
    print()

    # L47
    print("--- L47 UNDER ---")
    r47 = KL47UnderScore().run(match, ctx)
    print(f"  rejected={r47.rejected} score={r47.score} confidence={r47.confidence}")
    if r47.warnings:
        print(f"  warnings: {r47.warnings}")
    print(f"  meta:")
    for k in ("raw_score", "c1_stats", "c2_forme", "c3_meteo", "c4_enjeu",
              "c5_pitchapi", "c6_blessures", "c7_clv", "cote_under_final",
              "pinnacle_cote_under", "clv"):
        if k in r47.meta:
            print(f"    {k} = {r47.meta[k]}")
    print()

    # Cleanup
    try:
        ctx["pitchapi"].close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
