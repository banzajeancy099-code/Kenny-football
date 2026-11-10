"""
Kenny Football v3.0 — Job d'analyse quotidienne.

Lance l'analyse des matchs du jour sur les 18 ligues typées.
Appelé par /api/analyze/start (Render).

Usage :
    python -m jobs.kjob_analyse
    python -m jobs.kjob_analyse 2026-11-11
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

import kdb
import kengine
from api.kbzzoiro import KBzzoiro
from api.kodds import KOdds


# Ligues typées (identiques à kengine.py)
LEAGUES_OVER = {18, 17, 14, 54, 25, 19, 10, 108, 7, 8}
LEAGUES_UNDER = {34, 85, 89, 23, 53, 32, 94, 84}


def analyse_du_jour(date_str: str = None):
    """Analyse les matchs du jour et stocke les paris retenus."""

    if date_str is None:
        date_str = datetime.now(timezone.utc).date().isoformat()

    print(f"=== Analyse du {date_str} ===", flush=True)

    bzz = KBzzoiro()
    ctx = {
        "bzzoiro": bzz,
        "api_football": None,
        "odds": KOdds(bzzoiro=bzz),
        "pitchapi": None,
        "pinnacle": None,
        "db": kdb,
        "skip_layer_perf": True,
    }

    # Récupère les matchs du jour
    try:
        events = bzz.get_matches_today(date_str)
    except Exception as e:
        print(f"❌ Bzzoiro KO : {e}", flush=True)
        return []

    print(f"{len(events)} matchs trouvés", flush=True)

    # Filtre ligues typées + matchs non joués
    events_typed = [
        e for e in events
        if e.get("league_id") in LEAGUES_OVER | LEAGUES_UNDER
        and e.get("home_score") is None
    ]
    print(f"{len(events_typed)} matchs dans les ligues typées", flush=True)

    matches_to_save = []

    for ev in events_typed:
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
            "cote_over": None,
            "cote_under": None,
            "weather": ev.get("weather") or {},
            "head_to_head": ev.get("head_to_head") or {},
            "league_nb_teams": 20,
            "over_rate": 0.52,
        }

        # Récupère les cotes
        try:
            odds = ctx["odds"].fetch_over_under(match)
            if odds:
                match["cote_over"] = odds.get("cote_over")
                match["cote_under"] = odds.get("cote_under")
        except Exception:
            pass

        # Calcule les couches
        try:
            res = kengine.run_match(match, ctx, bankroll=1000.0)
        except Exception as e:
            print(f"  {match['home_team_name']} vs {match['away_team_name']} KO: {e}", flush=True)
            continue

        # Filtre final
        if res["signal"] != "strong":
            continue
        if res["cote"] is None or not (1.40 <= res["cote"] <= 1.80):
            continue

        matches_to_save.append({
            "match_id": res["match_id"],
            "league_id": match["league_id"],
            "league_name": None,
            "home_team_id": match["home_team_id"],
            "home_team_name": match["home_team_name"],
            "away_team_id": match["away_team_id"],
            "away_team_name": match["away_team_name"],
            "kickoff": match["kickoff"],
            "score": res["score"],
            "confidence": 0.85,
            "proba_over": res["proba"] if res["market"] == "over" else None,
            "proba_under": res["proba"] if res["market"] == "under" else None,
            "cote_over": match["cote_over"],
            "cote_under": match["cote_under"],
            "edge_over": res["edge"] if res["market"] == "over" else None,
            "edge_under": res["edge"] if res["market"] == "under" else None,
            "signal_strength": res["signal"],
            "mise_kelly": res["mise"],
            "match_data": {
                "market": res["market"],
                "signal": res["signal"],
                "score": res["score"],
                "edge": res["edge"],
                "mise": res["mise"],
            },
        })

        print(
            f"  ✅ {match['home_team_name']} vs {match['away_team_name']}: "
            f"{res['market']} @ {res['cote']:.2f} (mise {res['mise']:.2f}€)",
            flush=True,
        )

    # Sauvegarde
    if matches_to_save:
        try:
            kdb.ksave_predictions(date_str, matches_to_save)
            print(f"\n✅ {len(matches_to_save)} paris enregistrés", flush=True)
        except Exception as e:
            print(f"❌ Save KO : {e}", flush=True)
    else:
        print("\n⚠️ Aucun pari retenu", flush=True)

    return matches_to_save


if __name__ == "__main__":
    date = sys.argv[1] if len(sys.argv) > 1 else None
    analyse_du_jour(date)
