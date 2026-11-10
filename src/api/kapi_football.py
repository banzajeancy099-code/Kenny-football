"""
Kenny Football v3.0 — Client API-Football (ciblé).

Base URL : https://v3.football.api-sports.io
Auth     : header "x-apisports-key: <key>"

Utilisé par L1 pour les absences et L2 pour les lineups/arbitre.
L1 appelle fetch_absences(fixture_id, team_id).
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request


BASE_URL = "https://v3.football.api-sports.io"
RATE_LIMIT_MS = 1000
CACHE_TTL_S = 12 * 3600  # 12h — Option A validée


class KAPIFootball:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("API_FOOTBALL_KEY")
        if not self.api_key:
            raise RuntimeError("API_FOOTBALL_KEY manquante")
        self._last_call_ts = 0.0
        self._cache = {}

    def _headers(self) -> dict:
        return {
            "x-apisports-key": self.api_key,
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
        req = urllib.request.Request(url, headers=self._headers())
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        self._cache[url] = (now, data)
        return data

    def get_injuries(self, fixture_id: int) -> list:
        data = self._get("/injuries", {"fixture": fixture_id})
        return data.get("response", [])

    def fetch_absences(self, fixture_id: int, team_id: int) -> list | None:
        """
        Interface L1 : retourne la liste des absents pour `team_id`
        dans le match `fixture_id`.
        Retourne None si l'API échoue (déclenche rejet L1).
        """
        try:
            injuries = self.get_injuries(fixture_id)
        except Exception:
            return None

        if injuries is None:
            return None

        out = []
        for inj in injuries:
            team = inj.get("team") or {}
            if team.get("id") != team_id:
                continue
            player = inj.get("player") or {}
            # API-Football ne distingue pas starter/rotation de façon fiable.
            # On utilise "type" (Missing Fixture / Questionable) comme proxy.
            inj_type = (inj.get("type") or "").lower()
            role = "starter" if "missing" in inj_type or "out" in inj_type else "rotation"
            out.append({
                "player_id": player.get("id"),
                "player_name": player.get("name"),
                "player_role": role,
                "reason": inj.get("reason"),
                "type": inj.get("type"),
            })
        return out

    def get_lineups(self, fixture_id: int) -> list:
        data = self._get("/fixtures/lineups", {"fixture": fixture_id})
        return data.get("response", [])

    def get_h2h(self, team1_id: int, team2_id: int, last: int = 5) -> list:
        data = self._get("/fixtures/headtohead", {
            "h2h": f"{team1_id}-{team2_id}",
            "last": last,
        })
        return data.get("response", [])

    def get_referee(self, fixture_id: int) -> str:
        data = self._get("/fixtures", {"id": fixture_id})
        fixtures = data.get("response", [])
        if fixtures:
            return fixtures[0].get("fixture", {}).get("referee", "") or ""
        return ""


def knew_client(api_key: str | None = None) -> KAPIFootball:
    return KAPIFootball(api_key=api_key)
