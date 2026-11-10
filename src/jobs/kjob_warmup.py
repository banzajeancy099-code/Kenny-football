"""
Kenny Football v3.0 — Préchauffage k_team_matches (avec reprise).

Boucle sur N jours (défaut 100), récupère tous les events Bzzoiro, écrit 2 lignes
par match dans k_team_matches (1 par équipe).

Fonctionnalités :
- Retry 3× par jour (backoff 2s, 5s, 10s) sur erreurs réseau.
- Checkpoint après chaque jour réussi dans .warmup_state.json.
- --resume : reprend au dernier jour réussi + 1.
- --from YYYY-MM-DD : force le point de départ (ignore --resume).
- --days N : nombre de jours en arrière (défaut 100, ignoré si --resume).
- Purge .warmup_state.json à la fin complète.

Usage :
    PYTHONPATH=src python -m jobs.kjob_warmup
    PYTHONPATH=src python -m jobs.kjob_warmup --days 30
    PYTHONPATH=src python -m jobs.kjob_warmup --resume
    PYTHONPATH=src python -m jobs.kjob_warmup --from 2026-09-01
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import kdb
from api.kbzzoiro import KBzzoiro


STATE_FILE = Path(__file__).resolve().parents[2] / ".warmup_state.json"
RETRY_DELAYS = [2, 5, 10]

COMP_MAP = {}


def _competition_type(league_id):
    return COMP_MAP.get(league_id, "league")


def _result_for(gf, ga):
    if gf > ga:
        return "W"
    if gf < ga:
        return "L"
    return "D"


def _load_state() -> dict | None:
    if not STATE_FILE.exists():
        return None
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def _save_state(data: dict) -> None:
    tmp = STATE_FILE.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, STATE_FILE)


def _clear_state() -> None:
    if STATE_FILE.exists():
        os.remove(STATE_FILE)


def _fetch_day_with_retry(bzz, date_str: str):
    last_exc = None
    for attempt, delay in enumerate(RETRY_DELAYS, start=1):
        try:
            return bzz.get_matches_range(date_str, date_str)
        except Exception as e:
            last_exc = e
            print(f"  ! jour {date_str} tentative {attempt}/{len(RETRY_DELAYS)} échouée : {e}")
            if attempt < len(RETRY_DELAYS):
                print(f"    retry dans {delay}s...")
                time.sleep(delay)
    raise last_exc


INSERT_SQL = """
    INSERT INTO k_team_matches (
        team_id, match_id, date, competition_type, opponent_id,
        goals_for, goals_against, result, is_home, league_id
    ) VALUES (
        :team_id, :match_id, :date, :competition_type, :opponent_id,
        :goals_for, :goals_against, :result, :is_home, :league_id
    )
    ON CONFLICT (team_id, match_id) DO UPDATE SET
        is_home = EXCLUDED.is_home,
        league_id = EXCLUDED.league_id
"""


def _insert_match(conn, ev, seen_ids) -> tuple[int, int]:
    """Retourne (n_events_ajoutés, n_lignes_ajoutées)."""
    mid = ev.get("id")
    if mid is None or mid in seen_ids:
        return 0, 0
    seen_ids.add(mid)

    home_id = ev.get("home_team_id")
    away_id = ev.get("away_team_id")
    home_score = ev.get("home_score")
    away_score = ev.get("away_score")
    event_date = ev.get("event_date")
    league_id = ev.get("league_id")

    if home_id is None or away_id is None:
        return 0, 0
    if home_score is None or away_score is None:
        return 0, 0
    if event_date is None:
        return 0, 0

    try:
        ev_date = datetime.fromisoformat(event_date.replace("Z", "+00:00")).date()
    except Exception:
        return 0, 0

    comp = _competition_type(league_id)
    rows = [
        (home_id, str(mid), ev_date, comp, away_id,
         home_score, away_score, _result_for(home_score, away_score), True),
        (away_id, str(mid), ev_date, comp, home_id,
         away_score, home_score, _result_for(away_score, home_score), False),
    ]

    n_rows = 0
    for r in rows:
        conn.run(
            INSERT_SQL,
            team_id=r[0], match_id=r[1], date=r[2],
            competition_type=r[3], opponent_id=r[4],
            goals_for=r[5], goals_against=r[6], result=r[7],
            is_home=r[8], league_id=league_id,
        )
        n_rows += 1
    return 1, n_rows


def _fill_days_since(conn) -> None:
    sql = """
        WITH ordered AS (
            SELECT id, team_id, date,
                   LAG(date) OVER (PARTITION BY team_id ORDER BY date) AS prev_date
            FROM k_team_matches
        )
        UPDATE k_team_matches t
        SET days_since_last_match = (o.date - o.prev_date)
        FROM ordered o
        WHERE t.id = o.id AND o.prev_date IS NOT NULL
    """
    conn.run(sql)


def warmup(date_from, date_to, resume: bool = False) -> dict:
    bzz = KBzzoiro()
    conn = kdb._connect()
    seen_ids = set()
    total_events = 0
    total_rows = 0

    try:
        cur = date_from
        while cur <= date_to:
            d_str = cur.isoformat()
            print(f"[warmup] fetching {d_str}...")
            try:
                events = _fetch_day_with_retry(bzz, d_str)
            except Exception as e:
                print(f"[warmup] ABANDON jour {d_str} après retries : {e}")
                print(f"[warmup] état sauvegardé. Relance avec --resume pour reprendre.")
                _save_state({
                    "last_success_date": (cur - timedelta(days=1)).isoformat(),
                    "current_failed_date": d_str,
                    "date_from": date_from.isoformat(),
                    "date_to": date_to.isoformat(),
                    "failed_at": datetime.now(timezone.utc).isoformat(),
                })
                raise

            day_events = 0
            day_rows = 0
            for ev in events:
                ne, nr = _insert_match(conn, ev, seen_ids)
                day_events += ne
                day_rows += nr

            total_events += day_events
            total_rows += day_rows
            print(f"  → {day_events} events, {day_rows} lignes (cumul {total_events} / {total_rows})")

            _save_state({
                "last_success_date": d_str,
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })

            cur += timedelta(days=1)

        print("[warmup] remplissage days_since_last_match...")
        _fill_days_since(conn)
        print("[warmup] OK terminé")
        _clear_state()

        return {"events": total_events, "rows": total_rows}
    finally:
        conn.close()


def _parse_date(s: str):
    return datetime.strptime(s, "%Y-%m-%d").date()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=100)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--from", dest="from_date", type=str, default=None)
    args = p.parse_args()

    today = datetime.now(timezone.utc).date()

    if args.from_date:
        date_from = _parse_date(args.from_date)
        date_to = today
        print(f"[warmup] mode --from {date_from} (jusqu'à {date_to})")
        resume_flag = False
    elif args.resume:
        state = _load_state()
        if state and state.get("last_success_date"):
            last = _parse_date(state["last_success_date"])
            date_from = last + timedelta(days=1)
            date_to = _parse_date(state["date_to"]) if state.get("date_to") else today
            print(f"[warmup] mode --resume depuis {date_from} (jusqu'à {date_to})")
            if date_from > date_to:
                print("[warmup] rien à faire, tout est déjà fait.")
                _clear_state()
                return
        else:
            date_from = today - timedelta(days=args.days - 1)
            date_to = today
            print(f"[warmup] --resume sans état, mode {args.days} jours depuis {date_from}")
        resume_flag = True
    else:
        date_from = today - timedelta(days=args.days - 1)
        date_to = today
        print(f"[warmup] mode {args.days} jours depuis {date_from} (jusqu'à {date_to})")
        resume_flag = False

    res = warmup(date_from, date_to, resume=resume_flag)
    print(f"✓ warmup terminé : {res['events']} events, {res['rows']} lignes k_team_matches")


if __name__ == "__main__":
    main()
