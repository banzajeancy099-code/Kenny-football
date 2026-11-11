"""
Kenny Football v3.0 — Client cotes (Over/Under 2.5).

Stratégie (Option A validée) :
  1. Bzzoiro /events/{id}/odds/  (priorité)
  2. The Odds API v4              (fallback)
  3. None                         (pas de cote → L2 gérera weak_nocote)

Marchés récupérés (Option A) : Over 2.5 / Under 2.5 uniquement.

Cache (Option C) :
  - mémoire  : 5 min par match_id (évite de spammer l'API)
  - DB       : chaque fetch écrit dans k_odds_snapshots (pour le CLV)
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

import kdb


ODDS_API_BASE = "https://api.the-odds-api.com/v4"
MEMORY_CACHE_TTL_S = 300  # 5 min
BZZOIRO_CACHE_TTL_S = 300


class KOdds:
    def __init__(self, bzzoiro=None, odds_api_key: str | None = None):
        self.bzzoiro = bzzoiro
        self.odds_api_key = odds_api_key or os.environ.get("THE_ODDS_API_KEY")
        self._mem_cache = {}  # match_id -> (ts, dict)

    # ------------------------------------------------------------------ #
    #  Interface L2
    # ------------------------------------------------------------------ #
    def fetch_over_under(self, match: dict) -> dict | None:
        """
        Retourne {"cote_over": float, "cote_under": float, "source": str}
        ou None si aucune cote trouvée.
        Écrit aussi dans k_odds_snapshots pour le CLV.
        """
        match_id = str(match.get("match_id") or match.get("fixture_id") or "")
        if not match_id:
            return None

        # Cache mémoire
        now = time.time()
        if match_id in self._mem_cache:
            ts, data = self._mem_cache[match_id]
            if now - ts < MEMORY_CACHE_TTL_S:
                return data

        # 1. Bzzoiro
        odds = self._try_bzzoiro(match)

        # 2. The Odds API
        if not odds:
            odds = self._try_the_odds_api(match)

        # 3. Écriture snapshot DB (si trouvé)
        if odds:
            try:
                kdb.ksave_odds_snapshot(
                    match_id=match_id,
                    bookmaker=odds.get("source", "unknown"),
                    market="over_2.5",
                    line=2.5,
                    price=odds["cote_over"],
                )
                kdb.ksave_odds_snapshot(
                    match_id=match_id,
                    bookmaker=odds.get("source", "unknown"),
                    market="under_2.5",
                    line=2.5,
                    price=odds["cote_under"],
                )
            except Exception as e:
                print(f"[kodds] warning snapshot DB : {e}")

        self._mem_cache[match_id] = (now, odds)
        return odds

    # ------------------------------------------------------------------ #
    #  Source 1 — Bzzoiro
    # ------------------------------------------------------------------ #
    def _try_bzzoiro(self, match: dict) -> dict | None:
        if not self.bzzoiro:
            return None
        event_id = match.get("fixture_id") or match.get("id")
        if not event_id:
            return None

        try:
            # get_event_odds() retourne DÉJÀ le format final {cote_over, cote_under, ...}
            # On ne doit PAS re-parser (ancien bug : double parsing)
            result = self.bzzoiro.get_event_odds(int(event_id))
        except Exception as e:
            print(f"[kodds] bzzoiro odds KO : {e}")
            return None

        if not result or not isinstance(result, dict):
            return None
        if result.get("cote_over") is None:
            return None

        return {
            "cote_over": float(result["cote_over"]),
            "cote_under": float(result["cote_under"]) if result.get("cote_under") else None,
            "source": "bzzoiro",
            "last_update_at": result.get("updated_at"),
        }

    def _parse_bzzoiro_odds(self, raw) -> dict | None:
        """
        Parse la réponse Bzzoiro /events/{id}/odds/.
        Format réel confirmé (event 10216) :
          {
            "event_id": 10216,
            "odds": {
              "home_win": 1.57, "draw": 3.79, "away_win": 5.23,
              "over_15_goals": 1.27, "over_25_goals": 1.89, "over_35_goals": 3.19,
              "under_15_goals": 3.45, "under_25_goals": 1.88, "under_35_goals": 1.31,
              "btts_yes": 1.87, "btts_no": 1.82
            },
            "last_update_at": "...",
            ...
          }
        On récupère over_25_goals et under_25_goals.
        """
        if not raw or not isinstance(raw, dict):
            return None

        odds = raw.get("odds") or {}
        c_over = odds.get("over_25_goals")
        c_under = odds.get("under_25_goals")

        if c_over is None or c_under is None:
            return None

        # Extrait aussi les cotes 1X2 si disponibles
        cote_home = odds.get("home_win")
        cote_draw = odds.get("draw")
        cote_away = odds.get("away_win")

        return {
            "cote_over": float(c_over),
            "cote_under": float(c_under),
            "cote_home": float(cote_home) if cote_home else None,
            "cote_draw": float(cote_draw) if cote_draw else None,
            "cote_away": float(cote_away) if cote_away else None,
            "source": "bzzoiro",
            "last_update_at": raw.get("last_update_at"),
            "all_markets": odds,
        }

    # ------------------------------------------------------------------ #
    #  Source 2 — The Odds API
    # ------------------------------------------------------------------ #
    def _try_the_odds_api(self, match: dict) -> dict | None:
        if not self.odds_api_key:
            return None

        sport_key = self._guess_sport_key(match)
        if not sport_key:
            return None

        try:
            data = self._get_the_odds_api(f"/sports/{sport_key}/odds", {
                "regions": "eu",
                "markets": "totals",
                "oddsFormat": "decimal",
            })
        except Exception as e:
            print(f"[kodds] the_odds_api KO : {e}")
            return None

        event = self._match_event(data, match)
        if not event:
            return None
        return self._parse_the_odds_api_event(event)

    def _guess_sport_key(self, match: dict) -> str | None:
        """
        Mapping league_id Bzzoiro -> sport_key The Odds API.
        À enrichir au fur et à mesure. Pour l'instant, quelques grands championnats.
        """
        LEAGUE_MAP = {
            1: "soccer_epl",
            3: "soccer_spain_la_liga",
            4: "soccer_italy_serie_a",
            5: "soccer_germany_bundesliga",
            6: "soccer_france_ligue_one",
            7: "soccer_uefa_champs_league",
            8: "soccer_uefa_europa_league",
            9: "soccer_brazil_campeonato",
            34: "soccer_brazil_serie_b",
        }
        return LEAGUE_MAP.get(match.get("league_id"))

    def _get_the_odds_api(self, path: str, params: dict) -> list:
        url = ODDS_API_BASE + path + "?" + urllib.parse.urlencode({
            **params,
            "apiKey": self.odds_api_key,
        })
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _normalize_name(self, s: str) -> str:
        if not s:
            return ""
        s = s.lower().strip()
        for prefix in ("fc ", "as ", "ss ", "sc ", "ac ", "rc ", "cd "):
            if s.startswith(prefix):
                s = s[len(prefix):]
        return s.replace(" ", "").replace("-", "").replace(".", "")

    def _match_event(self, events: list, match: dict) -> dict | None:
        if not isinstance(events, list):
            return None
        home_norm = self._normalize_name(match.get("home_team_name", ""))
        away_norm = self._normalize_name(match.get("away_team_name", ""))
        for ev in events:
            h = self._normalize_name(ev.get("home_team", ""))
            a = self._normalize_name(ev.get("away_team", ""))
            if h == home_norm and a == away_norm:
                return ev
        return None

    def _parse_the_odds_api_event(self, event: dict) -> dict | None:
        bookmakers = event.get("bookmakers") or []
        overs, unders = [], []
        for book in bookmakers:
            for mkt in book.get("markets") or []:
                if mkt.get("key") != "totals":
                    continue
                for outcome in mkt.get("outcomes") or []:
                    if outcome.get("point") != 2.5:
                        continue
                    name = (outcome.get("name") or "").lower()
                    price = outcome.get("price")
                    if price is None:
                        continue
                    if "over" in name:
                        overs.append(float(price))
                    elif "under" in name:
                        unders.append(float(price))
        if overs and unders:
            return {
                "cote_over": sum(overs) / len(overs),
                "cote_under": sum(unders) / len(unders),
                "source": "the_odds_api",
            }
        return None


def knew_client(bzzoiro=None, odds_api_key: str | None = None) -> KOdds:
    return KOdds(bzzoiro=bzzoiro, odds_api_key=odds_api_key)
