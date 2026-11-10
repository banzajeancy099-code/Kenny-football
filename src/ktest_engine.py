"""
Test pipeline complet : L1 + L2 + L47 + kengine + kkelly.
Sur plusieurs matchs du jour, affiche marché / signal / mise.
"""

from __future__ import annotations

from api.kbzzoiro import KBzzoiro
from api.kapi_football import KAPIFootball
from api.kodds import KOdds
from api.kpitchapi import KPitchAPI
from api.kpinnacle import KPinnacle
import kdb
import kengine


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


def fetch_and_enrich(bzz, odds_client, event: dict) -> dict:
    """Normalise + enrichit un event Bzzoiro."""
    match = {
        "match_id": str(event.get("id")),
        "fixture_id": event.get("id"),
        "league_id": event.get("league_id"),
        "home_team_id": event.get("home_team_id"),
        "away_team_id": event.get("away_team_id"),
        "home_team_name": event.get("home_team"),
        "away_team_name": event.get("away_team"),
        "kickoff": event.get("event_date"),
        "event_date": event.get("event_date"),
        "referee_id": event.get("referee_id"),
        "weather": event.get("weather") or {},
        "head_to_head": event.get("head_to_head") or {},
        "previous_leg_event_id": event.get("previous_leg_event_id"),
        "round_number": event.get("round_number"),
        "cote_over": None,
        "cote_under": None,
        "league_nb_teams": 20,
        "over_rate": 0.52,
    }

    # Standings
    try:
        standings = bzz.fetch_league_standings(event.get("league_id"))
        pos_map = {s["team_id"]: s["position"] for s in standings
                   if s.get("team_id") and s.get("position")}
        match["home_position"] = pos_map.get(event.get("home_team_id"))
        match["away_position"] = pos_map.get(event.get("away_team_id"))
        if standings:
            match["league_nb_teams"] = len(standings)
    except Exception:
        pass

    # Cotes
    odds = odds_client.fetch_over_under(match)
    if odds:
        match["cote_over"] = odds["cote_over"]
        match["cote_under"] = odds["cote_under"]
        match["cote_home"] = odds.get("cote_home")
        match["cote_draw"] = odds.get("cote_draw")
        match["cote_away"] = odds.get("cote_away")

    return match


def main():
    bzz = KBzzoiro()
    ctx = build_ctx()

    print("=== Test pipeline complet (L1 + L2 + L47 + kengine) ===\n")

    # Récupère les events du jour
    from datetime import datetime, timezone, timedelta
    date = datetime.now(timezone.utc).date().isoformat()
    events = bzz.get_matches_today(date)

    # Filtre : matchs à venir (pas encore joués)
    events = [e for e in events if e.get("home_score") is None]

    # Filtre horaire : 19h-23h59 heure locale (Africa/Kinshasa = UTC+1)
    TZ_OFFSET = 1  # Congo-Kinshasa
    filtered = []
    for e in events:
        ed = e.get("event_date")
        if not ed:
            continue
        try:
            dt = datetime.fromisoformat(ed.replace("Z", "+00:00"))
            local_hour = (dt.hour + TZ_OFFSET) % 24
            if 19 <= local_hour <= 23:
                filtered.append(e)
        except Exception:
            continue

    events = filtered[:15]
    print(f"{len(events)} matchs du soir (19h-23h59 locale) sur {date}\n")

    counts = {"strong": 0, "medium": 0, "weak": 0, "nocote": 0, "rejected": 0}
    total_mise = 0.0

    for ev in events:
        match = fetch_and_enrich(bzz, ctx["odds"], ev)
        res = kengine.run_and_save(match, ctx, bankroll=1000.0)

        name = f"{match['home_team_name']} vs {match['away_team_name']}"
        print(f"{name[:50]:<52} {res['market']:<7} {res['signal']:<14} score={res['score']:.2f} cote={res['cote']} mise={res['mise']:.2f}")
        if res["signal"] == "rejected":
            for lid, r in res.get("layer_results", {}).items():
                if r.rejected:
                    warn_str = " | ".join(str(w) for w in r.warnings[:2])
                    print(f"    ⤷ {lid} REJETÉ: {warn_str}")
                else:
                    print(f"    ⤷ {lid}: score={r.score:.2f} conf={r.confidence:.2f}")

        if res["signal"] in ("strong", "medium", "weak"):
            counts[res["signal"]] += 1
            total_mise += res["mise"]
        elif res["signal"] in ("weak_nocote", "medium_nocote"):
            counts["nocote"] += 1
        else:
            counts["rejected"] += 1

    print()
    print(f"Résumé : strong={counts['strong']} medium={counts['medium']} weak={counts['weak']} nocote={counts['nocote']} rejected={counts['rejected']}")
    print(f"Mise totale théorique : {total_mise:.2f}€")

    try:
        ctx["pitchapi"].close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
