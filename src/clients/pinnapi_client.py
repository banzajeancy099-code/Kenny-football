# src/clients/pinnapi_client.py — Client Pinnacle via The Odds API
import os
import logging
import requests

log = logging.getLogger("pinnacle")

BASE_URL = "https://api.the-odds-api.com/v4"

# Mapping ligues Bzzoiro → The Odds API
LEAGUE_MAP = {
    1: "soccer_epl",
    2: "soccer_portugal_primeira_liga",
    3: "soccer_spain_la_liga",
    4: "soccer_italy_serie_a",
    5: "soccer_germany_bundesliga",
    6: "soccer_france_ligue_one",
    7: "soccer_uefa_champs_league",
    8: "soccer_uefa_europa_league",
    9: "soccer_brazil_campeonato",
    10: "soccer_netherlands_eredivisie",
    11: "soccer_turkey_super_league",
    12: "soccer_efl_champ",
    14: "soccer_belgium_first_div",
    15: "soccer_switzerland_superleague",
    17: "soccer_saudi_arabia_pro_league",
    18: "soccer_usa_mls",
    19: "soccer_mexico_ligamx",
    23: "soccer_romania_liga_1",
    25: "soccer_poland_ekstraklasa",
    26: "soccer_sweden_allsvenskan",
    34: "soccer_brazil_serie_b",
    38: "soccer_spain_segunda_division",
    52: "soccer_china_superleague",
    54: "soccer_norway_eliteserien",
    84: "soccer_denmark_superliga",
    85: "soccer_argentina_primera_division",
    89: "soccer_france_ligue_two",
    94: "soccer_germany_bundesliga2",
    96: "soccer_austria_bundesliga",
    100: "soccer_italy_serie_b",
    107: "soccer_turkey_super_league",
}


class PinnapiClient:
    """Client Pinnacle via The Odds API."""

    def __init__(self, api_key=None):
        self.api_key = api_key or os.environ.get("THE_ODDS_API_KEY")
        if not self.api_key:
            log.warning("⚠️  THE_ODDS_API_KEY manquante")
            self.available = False
        else:
            self.available = True
            log.info("✅ The Odds API client initialisé")

    def is_available(self):
        return self.available

    def get_prematch_fixtures(self, force_refresh=False):
        """Stub pour compatibilité."""
        return []

    def find_fixture_odds(self, home_name, away_name, league_id=None, fixtures=None):
        """Cherche les cotes Pinnacle pour un match (Over/Under 2.5 ET 2.75)."""
        if not self.available:
            return None

        if not league_id:
            log.warning(f"[PINNACLE] league_id manquant pour {home_name} vs {away_name}")
            return None

        sport_key = LEAGUE_MAP.get(int(league_id)) if str(league_id).isdigit() else LEAGUE_MAP.get(league_id)
        if not sport_key:
            log.warning(f"[PINNACLE] Ligue {league_id} non mappée")
            return None

        try:
            r = requests.get(
                f"{BASE_URL}/sports/{sport_key}/odds",
                params={
                    "apiKey": self.api_key,
                    "regions": "eu",
                    "markets": "totals",
                    "bookmakers": "pinnacle",
                    "oddsFormat": "decimal",
                },
                timeout=15,
            )
            if r.status_code != 200:
                log.warning(f"[PINNACLE] HTTP {r.status_code} pour {sport_key}")
                return None

            data = r.json()
            if not isinstance(data, list):
                return None

            home_l = home_name.lower().strip()
            away_l = away_name.lower().strip()

            def _match(a, b):
                if not a or not b:
                    return False
                if a in b or b in a:
                    return True
                a_words = [w for w in a.split() if len(w) > 3]
                b_words = [w for w in b.split() if len(w) > 3]
                return any(aw in b for aw in a_words) and any(bw in a for bw in b_words)

            for m in data:
                m_home = (m.get("home_team") or "").lower()
                m_away = (m.get("away_team") or "").lower()
                if not (_match(home_l, m_home) and _match(away_l, m_away)):
                    continue

                # Collecte tous les points disponibles puis choisit le plus proche de 2.5
                over_by_point = {}
                under_by_point = {}
                for bk in m.get("bookmakers", []):
                    if bk.get("key") != "pinnacle":
                        continue
                    for mkt in bk.get("markets", []):
                        if mkt.get("key") != "totals":
                            continue
                        for o in mkt.get("outcomes", []):
                            pt = o.get("point")
                            if pt in (2.25, 2.5, 2.75):
                                if o.get("name") == "Over":
                                    over_by_point[pt] = o.get("price")
                                elif o.get("name") == "Under":
                                    under_by_point[pt] = o.get("price")

                # Pinnacle ajuste sa ligne : on ne garde QUE si point == 2.5
                # Sinon la cote n'est pas comparable à Over/Under 2.5
                over_2_5 = None
                under_2_5 = None
                over_point = None
                if 2.5 in over_by_point:
                    over_2_5 = over_by_point[2.5]
                    over_point = 2.5
                if 2.5 in under_by_point:
                    under_2_5 = under_by_point[2.5]

                return {
                    "fixture_id": m.get("id"),
                    "home": m.get("home_team"),
                    "away": m.get("away_team"),
                    "over_2_5": over_2_5,
                    "under_2_5": under_2_5,
                    "point": over_point,
                    "available_points": list(over_by_point.keys()),
                    "btts_yes": None,
                }

            return None
        except Exception as e:
            log.error(f"[PINNACLE] Erreur {sport_key}: {e}")
            return None

    def get_quota_info(self):
        if not self.available:
            return {"error": "not available"}
        try:
            r = requests.get(
                f"{BASE_URL}/sports",
                params={"apiKey": self.api_key},
                timeout=10,
            )
            return {
                "used": r.headers.get("x-requests-used"),
                "remaining": r.headers.get("x-requests-remaining"),
            }
        except Exception as e:
            return {"error": str(e)}
