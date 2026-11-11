"""
Kenny Football v3.0 — Client Bzzoiro v2.

Base URL : https://sports.bzzoiro.com/api/v2
Auth     : header "Authorization: Token <key>"

Deux couches :
  Couche 1 — API brute (miroir du client football-engine) :
    get_matches_today, get_event_detail, get_event_stats,
    get_event_odds, get_event_lineups, get_standings

  Couche 2 — Interface attendue par L1/L2 :
    fetch_league_standings(league_id)   -> normalise get_standings
    fetch_team_matches(team_id, limit)  -> LIT k_team_matches (local)
    fetch_team_splits(team_id)          -> CALCULE depuis k_team_matches
    fetch_h2h(home_id, away_id, match)  -> utilise match["head_to_head"]
    fetch_absences                      -> délégué à API-Football (pas ici)

Le préchauffage de k_team_matches est assuré par src/jobs/kjob_warmup.py.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import kdb


BASE_URL = "https://sports.bzzoiro.com/api/v2"
RATE_LIMIT_MS = 150
CACHE_TTL_S = 300


class KBzzoiro:
    def __init__(self, api_key: str | None = None, conn=None):
        self.api_key = api_key or os.environ.get("BZZOIRO_API_KEY")
        if not self.api_key:
            raise RuntimeError("BZZOIRO_API_KEY manquante")
        self.api_key_backup = os.environ.get("BZZOIRO_API_KEY_5")
        self._last_call_ts = 0.0
        self._cache = {}
        self._odds_cache = {}
        self._conn = conn
        self._team_matches_cache = {}
        self._team_splits_cache = {}
        self._standings_cache = {}
        self._team_matches_cache = {}
        self._team_splits_cache = {}
        # Cache équipes (évite les requêtes redondantes)
        self._team_matches_cache = {}
        self._team_splits_cache = {}  # Connexion persistante optionnelle

    # ------------------------------------------------------------------ #
    #  Couche 1 — API brute
    # ------------------------------------------------------------------ #
    def _headers(self) -> dict:
        return {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json",
        }

    def _rate_limit(self):
        elapsed = (time.time() - self._last_call_ts) * 1000
        if elapsed < RATE_LIMIT_MS:
            time.sleep((RATE_LIMIT_MS - elapsed) / 1000.0)
        self._last_call_ts = time.time()

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = BASE_URL + path
        if params:
            url += "?" + urllib.parse.urlencode(params)

        now = time.time()
        if url in self._cache:
            ts, data = self._cache[url]
            if now - ts < CACHE_TTL_S:
                return data

        self._rate_limit()
        try:
            req = urllib.request.Request(url, headers=self._headers())
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and self.api_key_backup:
                print(f"⚠️ Clé 1 épuisée, bascule clé 5 sur {path}")
                headers = {
                    "Authorization": f"Token {self.api_key_backup}",
                    "Content-Type": "application/json",
                }
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            else:
                raise
        self._cache[url] = (now, data)
        return data

    def get_matches_today(self, date: str) -> list:
        """Récupère TOUS les matchs du jour via pagination (toutes ligues)."""
        all_matches = []
        page = 1
        max_pages = 20  # Sécurité anti-boucle infinie

        while page <= max_pages:
            try:
                data = self._get("/events/", {
                    "date_from": date,
                    "date_to": date,
                    "limit": 200,
                    "page": page,
                })
                results = data.get("results", [])
                if not results:
                    break
                all_matches.extend(results)

                if not data.get("next"):
                    break

                page += 1
                time.sleep(0.05)

            except Exception as e:
                print(f"Pagination KO page {page}: {e}")
                break

        return all_matches

    def get_matches_range(self, date_from: str, date_to: str) -> list:
        data = self._get("/events/", {"date_from": date_from, "date_to": date_to})
        return data.get("results", [])

    def get_event_detail(self, event_id: int) -> dict:
        return self._get(f"/events/{event_id}/")

    def get_event_stats(self, event_id: int) -> dict:
        return self._get(f"/events/{event_id}/stats/")

    def get_event_odds(self, event_id: int) -> dict:
        return self._get(f"/events/{event_id}/odds/")

    def get_event_lineups(self, event_id: int) -> dict:
        return self._get(f"/events/{event_id}/lineups/")

    def get_standings(self, league_id: int) -> list:
        data = self._get(f"/leagues/{league_id}/standings/")
        return data.get("standings", [])

    # ------------------------------------------------------------------ #
    #  Couche 2 — Interface L1/L2
    # ------------------------------------------------------------------ #
    def fetch_league_standings(self, league_id: int) -> list:
        if league_id in self._standings_cache:
            return self._standings_cache[league_id]
        raw = self.get_standings(league_id)
        out = []
        for row in raw:
            team_id = row.get("team_id") or row.get("team", {}).get("id")
            position = row.get("position") or row.get("rank")
            if team_id is None or position is None:
                continue
            out.append({
                "team_id": int(team_id),
                "position": int(position),
                "points": row.get("points"),
                "played": row.get("played") or row.get("matches"),
                "goals_for": row.get("goals_for") or row.get("scored"),
                "goals_against": row.get("goals_against") or row.get("conceded"),
            })
        self._standings_cache[league_id] = out
        return out

    def fetch_team_matches(self, team_id: int, limit: int = 15) -> list:
        """
        LIT k_team_matches (local, alimenté par kjob_warmup).
        Cache mémoire par team_id pour éviter les requêtes redondantes.
        """
        cache_key = (team_id, limit)
        if cache_key in self._team_matches_cache:
            return self._team_matches_cache[cache_key]

        sql = """
            SELECT match_id, date, competition_type, opponent_id,
                   goals_for, goals_against, result, days_since_last_match,
                   late_goals_for, late_goals_against
            FROM k_team_matches
            WHERE team_id = :team_id
            ORDER BY date DESC
            LIMIT :limit
        """
        if self._conn is not None:
            rows = self._conn.run(sql, team_id=team_id, limit=limit)
            cols = [c["name"] for c in self._conn.columns]
        else:
            with kdb.get_conn() as conn:
                rows = conn.run(sql, team_id=team_id, limit=limit)
                cols = [c["name"] for c in conn.columns]
        result = [dict(zip(cols, r)) for r in rows]
        self._team_matches_cache[cache_key] = result
        return result

    def fetch_team_splits(self, team_id: int) -> dict | None:
        """
        CALCULE les splits depuis k_team_matches.
        Cache mémoire par team_id.
        """
        if team_id in self._team_splits_cache:
            return self._team_splits_cache[team_id]

        sql = """
            SELECT match_id, date, competition_type, opponent_id,
                   goals_for, goals_against, result, days_since_last_match,
                   is_home
            FROM k_team_matches
            WHERE team_id = :team_id
            ORDER BY date DESC
            LIMIT 20
        """
        if self._conn is not None:
            rows = self._conn.run(sql, team_id=team_id)
            cols = [c["name"] for c in self._conn.columns]
        else:
            with kdb.get_conn() as conn:
                rows = conn.run(sql, team_id=team_id)
                cols = [c["name"] for c in conn.columns]
        matches = [dict(zip(cols, r)) for r in rows]
        if len(matches) < 3:
            self._team_splits_cache[team_id] = None
            return None

        home_m = [m for m in matches if m.get("is_home") is True]
        away_m = [m for m in matches if m.get("is_home") is False]

        if len(home_m) < 2 or len(away_m) < 2:
            self._team_splits_cache[team_id] = None
            return None

        def avg(lst, key):
            vals = [m[key] for m in lst if m.get(key) is not None]
            return sum(vals) / len(vals) if vals else None

        home_gf_avg = avg(home_m, "goals_for")
        home_ga_avg = avg(home_m, "goals_against")
        away_gf_avg = avg(away_m, "goals_for")
        away_ga_avg = avg(away_m, "goals_against")

        if None in (home_gf_avg, home_ga_avg, away_gf_avg, away_ga_avg):
            self._team_splits_cache[team_id] = None
            return None

        form_gf = avg(matches[:5], "goals_for")
        form_gf_3 = avg(matches[:3], "goals_for")
        form_gf_dom = home_gf_avg
        form_gf_ext = away_gf_avg

        result = {
            "played": len(matches),
            "home_gf_avg": home_gf_avg,
            "home_ga_avg": home_ga_avg,
            "away_gf_avg": away_gf_avg,
            "away_ga_avg": away_ga_avg,
            "form_gf": form_gf,
            "form_gf_3": form_gf_3,
            "form_gf_dom": form_gf_dom,
            "form_gf_ext": form_gf_ext,
            "xgf": None,
        }
        self._team_splits_cache[team_id] = result
        return result
        self._team_splits_cache[team_id] = result
        return result

    def fetch_h2h(self, home_id: int, away_id: int, match: dict | None = None) -> list:
        """
        Utilise head_to_head.recent_matches fourni par Bzzoiro dans /events/.
        Si `match` n'est pas fourni, retourne [] (pas d'endpoint H2H dédié en v2).
        """
        if not match:
            return []
        h2h = match.get("head_to_head") or {}
        recent = h2h.get("recent_matches") or []
        out = []
        for m in recent:
            out.append({
                "event_id": m.get("event_id"),
                "date": m.get("date"),
                "home": m.get("home"),
                "away": m.get("away"),
                "home_score": m.get("home_score"),
                "away_score": m.get("away_score"),
                "total_goals": (m.get("home_score") or 0) + (m.get("away_score") or 0),
            })
        return out


    def get_event_odds(self, event_id: int) -> dict | None:
        """Récupère les cotes Over/Under 2.5 depuis /events/{id}/odds/ (cache 1h)."""
        now = time.time()
        cached = self._odds_cache.get(event_id)
        if cached and (now - cached[0]) < 3600:
            return cached[1]

        try:
            data = self._get(f"/events/{event_id}/odds/")
        except Exception as e:
            print(f"get_event_odds KO event {event_id}: {e}")
            return None

        raw = data.get("odds") if isinstance(data.get("odds"), dict) else data
        cote_over = raw.get("over_25_goals") or raw.get("over_2_5")
        cote_under = raw.get("under_25_goals") or raw.get("under_2_5")

        if not cote_over:
            return None

        result = {
            "cote_over": float(cote_over),
            "cote_under": float(cote_under) if cote_under else None,
            "source": "bzzoiro",
            "updated_at": data.get("last_update_at"),
        }
        self._odds_cache[event_id] = (now, result)
        return result


def knew_client(api_key: str | None = None) -> KBzzoiro:
    return KBzzoiro(api_key=api_key)
