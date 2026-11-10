"""
Test L1 + L2 en réel sur un match Bzzoiro.

Usage :
    PYTHONPATH=src python -m ktest_l1l2
"""

from __future__ import annotations

from api.kbzzoiro import KBzzoiro
from api.kapi_football import KAPIFootball
from api.kodds import KOdds
import kdb
from layers.kl01_strength import KL01Strength
from layers.kl02_over import KL02Over


def build_ctx():
    bzz = KBzzoiro()
    return {
        "bzzoiro": bzz,
        "api_football": KAPIFootball(),
        "odds": KOdds(bzzoiro=bzz),
        "db": kdb,
    }


def fetch_match(bzz, event_id: int) -> dict:
    """Récupère un event Bzzoiro et le normalise pour L1/L2."""
    ev = bzz.get_event_detail(event_id)

    # Normalisation vers les clés attendues par L1/L2
    return {
        "match_id": str(ev.get("id")),
        "fixture_id": ev.get("id"),
        "league_id": ev.get("league_id"),
        "home_team_id": ev.get("home_team_id"),
        "away_team_id": ev.get("away_team_id"),
        "home_team_name": ev.get("home_team"),
        "away_team_name": ev.get("away_team"),
        "kickoff": ev.get("event_date"),
        "referee_id": ev.get("referee_id"),
        "weather": ev.get("weather") or {},
        "head_to_head": ev.get("head_to_head") or {},
        "previous_leg_event_id": ev.get("previous_leg_event_id"),
        "has_xg": ev.get("has_xg"),
        "cote_over": None,
        "cote_under": None,
        "league_nb_teams": 20,
        "over_rate": 0.52,
    }


def main():
    bzz = KBzzoiro()
    ctx = build_ctx()

    event_id = 10216
    print(f"=== Test L1 + L2 sur event_id={event_id} ===\n")

    match = fetch_match(bzz, event_id)
    print(f"Match : {match['home_team_name']} vs {match['away_team_name']}")
    print(f"League : {match['league_id']} | fixture_id : {match['fixture_id']}")

    odds = ctx["odds"].fetch_over_under(match)
    if odds:
        match["cote_over"] = odds["cote_over"]
        match["cote_under"] = odds["cote_under"]
        print(f"Cotes : over={odds['cote_over']:.2f} | under={odds['cote_under']:.2f} | source={odds['source']}")
    else:
        print("Cotes : AUCUNE (fallback weak_nocote)")
    print()

    # L1
    print("--- L1 STRENGTH ---")
    l1 = KL01Strength()
    r1 = l1.run(match, ctx)
    print(f"  rejected : {r1.rejected}")
    print(f"  score    : {r1.score}")
    print(f"  confidence : {r1.confidence}")
    print(f"  warnings : {r1.warnings}")
    print(f"  meta     : {r1.meta}\n")

    # L2
    print("--- L2 OVER 2.5 ---")
    l2 = KL02Over()
    r2 = l2.run(match, ctx)
    print(f"  rejected : {r2.rejected}")
    print(f"  score    : {r2.score}")
    print(f"  confidence : {r2.confidence}")
    print(f"  warnings : {r2.warnings}")
    print(f"  meta (extrait) :")
    for k in ("expected_goals", "c1", "c2", "c3", "consistency_score",
              "feedback_adjustment", "weight"):
        if k in r2.meta:
            print(f"    {k} = {r2.meta[k]}")
    print()


if __name__ == "__main__":
    main()
