"""
Kenny Football v3.0 — Client Pinnacle via The Odds API.

Auth    : THE_ODDS_API_KEY (déjà dans .env)
Base URL: https://api.the-odds-api.com/v4
Marché  : totals (Over/Under 2.5)

Filtre : bookmakers[].key == "pinnacle"
Si Pinnacle ne couvre pas le match : retourne None.

Expose :
  fetch_pinnacle_ou(bzz_match, line=2.5) -> dict | None
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request


BASE_URL = "https://api.the-odds-api.com/v4"
CACHE_TTL_S = 300


LEAGUE_TO_SPORT_KEY = {
    1:  "soccer_epl",
    3:  "soccer_spain_la_liga",
    4:  "soccer_italy_serie_a",
    5:  "soccer_germany_bundesliga",
    6:  "soccer_france_ligue_one",
    7:  "soccer_uefa_champs_league",
    8:  "soccer_uefa_europa_league",
    9:  "soccer_brazil_campeonato",
    12: "soccer_efl_champ",
    14: "soccer_belgium_first_div",
    17: "soccer_turkey_super_league",
    18: "soccer_usa_mls",
    19: "soccer_mexico_ligamx",
    26: "soccer_sweden_allsvenskan",
    34: "soccer_brazil_serie_b",
    38: "soccer_spain_segunda_division",
    54: "soccer_norway_eliteserien",
    85: "soccer_argentina_primera_division",
    96: "soccer_austria_bundesliga",
    100: "soccer_italy_serie_b",
    89: "soccer_france_ligue_two",
    84: "soccer_denmark_superliga",
    25: "soccer_poland_ekstraklasa",
    16: "soccer_spl",  # Scottish Premiership
}


class KPinnacle:
    def __init__(self, odds_api_key: str | None = None):
        self.api_key = odds_api_key or os.environ.get("THE_ODDS_API_KEY")
        if not self.api_key:
            raise RuntimeError("THE_ODDS_API_KEY manquante")
        self._cache = {}  # sport_key -> (ts, list_events)

    def _normalize_name(self, s: str) -> str:
        if not s:
            return ""
        s = s.lower().strip()
        for prefix in ("fc ", "as ", "ss ", "sc ", "ac ", "rc ", "cd ", "ca "):
            if s.startswith(prefix):
                s = s[len(prefix):]
        return s.replace(" ", "").replace("-", "").replace(".", "").replace("'", "")

    def _get_events(self, sport_key: str) -> list:
        now = time.time()
        if sport_key in self._cache:
            ts, events = self._cache[sport_key]
            if now - ts < CACHE_TTL_S:
                return events

        params = {
            "regions": "eu",
            "markets": "totals",
            "oddsFormat": "decimal",
            "apiKey": self.api_key,
        }
        url = f"{BASE_URL}/sports/{sport_key}/odds/?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if not isinstance(data, list):
            data = []
        self._cache[sport_key] = (now, data)
        return data

    def _find_event(self, events: list, bzz_match: dict) -> dict | None:
        home_norm = self._normalize_name(bzz_match.get("home_team_name", ""))
        away_norm = self._normalize_name(bzz_match.get("away_team_name", ""))
        for ev in events:
            h = self._normalize_name(ev.get("home_team", ""))
            a = self._normalize_name(ev.get("away_team", ""))
            if h == home_norm and a == away_norm:
                return ev
        return None

    def fetch_pinnacle_ou(self, bzz_match: dict, line: float = 2.5) -> dict | None:
        """
        Retourne :
          {"cote_over": float, "cote_under": float,
           "timestamp": str, "source": "pinnacle"}
        ou None si Pinnacle ne couvre pas le match.
        """
        sport_key = LEAGUE_TO_SPORT_KEY.get(bzz_match.get("league_id"))
        if not sport_key:
            return None

        try:
            events = self._get_events(sport_key)
        except Exception as e:
            print(f"[kpinnacle] fetch({sport_key}) KO : {e}")
            return None

        ev = self._find_event(events, bzz_match)
        if not ev:
            return None

        # Cherche Pinnacle parmi les bookmakers
        for book in ev.get("bookmakers", []):
            if book.get("key") != "pinnacle":
                continue
            for mkt in book.get("markets", []):
                if mkt.get("key") != "totals":
                    continue
                over = under = None
                for outcome in mkt.get("outcomes", []):
                    if outcome.get("point") != line:
                        continue
                    name = (outcome.get("name") or "").lower()
                    price = outcome.get("price")
                    if price is None:
                        continue
                    if name == "over":
                        over = float(price)
                    elif name == "under":
                        under = float(price)
                if over and under:
                    return {
                        "cote_over": over,
                        "cote_under": under,
                        "timestamp": ev.get("commence_time") or book.get("last_update"),
                        "source": "pinnacle",
                    }
        return None


def knew_client(odds_api_key: str | None = None) -> KPinnacle:
    return KPinnacle(odds_api_key=odds_api_key)
