"""Client API-Football (ciblé)."""
from src.clients.base import BaseClient


class APIFootballClient(BaseClient):
    def __init__(self, api_key: str):
        super().__init__(
            name="api_football",
            base_url="https://v3.football.api-sports.io",
            api_key=api_key,
            rate_limit_ms=1000,
            cache_ttl_s=3600,
        )

    def _default_headers(self) -> dict:
        return {
            'x-apisports-key': self.api_key,
            'Content-Type': 'application/json',
        }

    def get_injuries(self, fixture_id: int) -> list:
        data = self.get("/injuries", {"fixture": fixture_id})
        return data.get("response", [])

    def get_lineups(self, fixture_id: int) -> list:
        data = self.get("/fixtures/lineups", {"fixture": fixture_id})
        return data.get("response", [])

    def get_h2h(self, team1_id: int, team2_id: int, last: int = 5) -> list:
        data = self.get("/fixtures/headtohead", {
            "h2h": f"{team1_id}-{team2_id}",
            "last": last,
        })
        return data.get("response", [])

    def get_referee(self, fixture_id: int) -> str:
        data = self.get("/fixtures", {"id": fixture_id})
        fixtures = data.get("response", [])
        if fixtures:
            return fixtures[0].get("fixture", {}).get("referee", "")
        return ""
