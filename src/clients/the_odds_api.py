# src/clients/the_odds_api.py — Client The Odds API (closing lines historiques)
import os
import logging
import requests
from datetime import datetime, timedelta

log = logging.getLogger("the-odds-api")

BASE_URL = "https://api.the-odds-api.com/v4"


class TheOddsAPIClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def _get(self, path, params=None):
        params = params or {}
        params["apiKey"] = self.api_key
        r = self.session.get(f"{BASE_URL}{path}", params=params, timeout=15)
        r.raise_for_status()
        return r.json()

    def get_sports(self):
        """Liste les sports disponibles (gratuit, ne compte pas dans le quota)."""
        return self._get("/sports")

    def get_historical_odds(self, sport_key, date_iso, regions="eu", markets="totals", odds_format="decimal"):
        """Récupère les cotes historiques (closing line la plus proche avant `date_iso`).

        Args:
            sport_key: ex "soccer_usa_mls", "soccer_germany_bundesliga"
            date_iso: ISO 8601, ex "2026-10-25T14:30:00Z"
            regions: "eu" pour les bookmakers européens
            markets: "totals" pour Over/Under
        """
        params = {
            "regions": regions,
            "markets": markets,
            "oddsFormat": odds_format,
            "dateFormat": "iso",
            "date": date_iso,
        }
        return self._get(f"/historical/sports/{sport_key}/odds", params)

    def get_quota(self):
        """Vérifie le quota restant (via header de la dernière réponse)."""
        # The Odds API renvoie les headers X-Requests-* sur chaque réponse
        # On fait un appel minimal pour lire
        try:
            r = self.session.get(
                f"{BASE_URL}/sports",
                params={"apiKey": self.api_key},
                timeout=10,
            )
            return {
                "used": r.headers.get("x-requests-used"),
                "remaining": r.headers.get("x-requests-remaining"),
                "last_reset": r.headers.get("x-requests-last-reset"),
            }
        except Exception as e:
            return {"error": str(e)}
