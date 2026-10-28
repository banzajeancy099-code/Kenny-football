"""Client Bzzoiro Sports Data — API v2 (endpoints /events/)."""
from src.clients.base import BaseClient


class BzzoiroClient(BaseClient):
    def __init__(self, api_key: str):
        super().__init__(
            name="bzzoiro",
            base_url="https://sports.bzzoiro.com/api/v2",
            api_key=api_key,
            rate_limit_ms=150,
            cache_ttl_s=300,
        )

    def _default_headers(self) -> dict:
        return {
            'Authorization': f'Token {self.api_key}',
            'Content-Type': 'application/json',
        }

    def get_matches_today(self, date: str) -> list:
        """Matchs du jour (retourne des dicts complets)."""
        data = self.get("/events/", {
            "date_from": date,
            "date_to": date,
        })
        return data.get("results", [])

    def get_event_detail(self, event_id: int) -> dict:
        return self.get(f"/events/{event_id}/")

    def get_event_stats(self, event_id: int) -> dict:
        """Stats xG, possession, tirs."""
        return self.get(f"/events/{event_id}/stats/")

    def get_event_odds(self, event_id: int) -> dict:
        return self.get(f"/events/{event_id}/odds/")

    def get_event_incidents(self, event_id: int) -> list:
        data = self.get(f"/events/{event_id}/incidents/")
        return data.get("results", [])

    def get_event_lineups(self, event_id: int) -> dict:
        return self.get(f"/events/{event_id}/lineups/")

    def get_standings(self, league_id: int) -> list:
        data = self.get(f"/leagues/{league_id}/standings/")
        return data.get("results", [])
