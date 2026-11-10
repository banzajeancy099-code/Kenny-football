"""
Kenny Football v3.0 — Client PitchAPI (via SDK officiel).

SDK     : from pitchapi import PitchAPI
Auth    : api_key passée au constructeur (variable PITCH_API_KEY)
Cache   : mémoire 1h par bzz_match_id (évite les appels redondants)

Mapping Bzzoiro <-> PitchAPI :
  Bzzoiro event_id = 10216 (numérique)
  PitchAPI match_id = "m_0R0u1r" (hash)
  → matching via client.date.get(date) + normalisation nom d'équipe.

Expose :
  fetch_match_stats(bzz_match) -> dict | None
  fetch_lineups(bzz_match)     -> dict | None
  fetch_h2h(bzz_match)         -> list | None
  close()                      -> libère le client SDK
"""

from __future__ import annotations

import os
import time

from pitchapi import PitchAPI


CACHE_TTL_S = 3600  # 1h


class KPitchAPI:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("PITCH_API_KEY")
        if not self.api_key:
            raise RuntimeError("PITCH_API_KEY manquante")
        self._client = PitchAPI(api_key=self.api_key)
        self._cache = {}  # bzz_match_id -> (ts, {"match": obj, "date": str})

    # ------------------------------------------------------------------ #
    #  Mapping Bzzoiro -> PitchAPI
    # ------------------------------------------------------------------ #
    def _normalize_name(self, s: str) -> str:
        if not s:
            return ""
        s = s.lower().strip()
        for prefix in ("fc ", "as ", "ss ", "sc ", "ac ", "rc ", "cd ", "ca "):
            if s.startswith(prefix):
                s = s[len(prefix):]
        return s.replace(" ", "").replace("-", "").replace(".", "").replace("'", "")

    def _find_pitch_match(self, bzz_match: dict):
        """
        Retourne l'objet match PitchAPI ou None.
        Utilise un cache 1h par bzz_match_id.
        """
        bzz_id = str(bzz_match.get("match_id") or bzz_match.get("fixture_id") or "")
        if not bzz_id:
            return None

        now = time.time()
        if bzz_id in self._cache:
            ts, cached = self._cache[bzz_id]
            if now - ts < CACHE_TTL_S:
                return cached.get("match")

        kickoff = bzz_match.get("kickoff") or bzz_match.get("event_date") or ""
        date_str = kickoff[:10] if kickoff else None
        if not date_str:
            return None

        home_norm = self._normalize_name(bzz_match.get("home_team_name", ""))
        away_norm = self._normalize_name(bzz_match.get("away_team_name", ""))

        try:
            day = self._client.date.get(date_str)
        except Exception as e:
            print(f"[kpitchapi] date.get({date_str}) KO : {e}")
            return None

        found = None
        for m in (getattr(day, "matches", None) or []):
            h = self._normalize_name(getattr(getattr(m, "home_team", None), "name", ""))
            a = self._normalize_name(getattr(getattr(m, "away_team", None), "name", ""))
            if h == home_norm and a == away_norm:
                found = m
                break

        self._cache[bzz_id] = (now, {"match": found, "date": date_str})
        return found

    # ------------------------------------------------------------------ #
    #  Stats avancées (Couche 5 L47)
    # ------------------------------------------------------------------ #
    def fetch_match_stats(self, bzz_match: dict) -> dict | None:
        """
        Retourne :
          {"xt_home":, "xt_away":, "vaep_home":, "vaep_away":,
           "xag_home":, "xag_away":, "ppda_home":, "ppda_away":,
           "source": "pitchapi"}
        ou None.
        """
        pm = self._find_pitch_match(bzz_match)
        if pm is None:
            return None

        try:
            adv = self._client.matches.advanced(pm.id)
        except Exception as e:
            print(f"[kpitchapi] advanced({pm.id}) KO : {e}")
            return None

        teams = getattr(adv, "teams", None) or []
        if len(teams) < 2:
            return None

        home_name = self._normalize_name(bzz_match.get("home_team_name", ""))
        away_name = self._normalize_name(bzz_match.get("away_team_name", ""))

        home_stat = None
        away_stat = None
        for t in teams:
            name = self._normalize_name(getattr(getattr(t, "team", None), "name", ""))
            if name == home_name:
                home_stat = t
            elif name == away_name:
                away_stat = t

        # Fallback : 1er = home, 2e = away (ordre PitchAPI)
        if home_stat is None and away_stat is None and len(teams) == 2:
            home_stat, away_stat = teams[0], teams[1]

        if home_stat is None or away_stat is None:
            return None

        def _extract(stat):
            pv = getattr(stat, "possession_value", None)
            cr = getattr(stat, "creation", None)
            df = getattr(stat, "defending", None)
            return {
                "xt":   getattr(pv, "xt_total", None) if pv else None,
                "vaep": getattr(pv, "vaep_total", None) if pv else None,
                "xag":  getattr(cr, "xag", None) if cr else None,
                "ppda": getattr(df, "ppda", None) if df else None,
            }

        h = _extract(home_stat)
        a = _extract(away_stat)
        return {
            "xt_home": h["xt"], "xt_away": a["xt"],
            "vaep_home": h["vaep"], "vaep_away": a["vaep"],
            "xag_home": h["xag"], "xag_away": a["xag"],
            "ppda_home": h["ppda"], "ppda_away": a["ppda"],
            "source": "pitchapi",
        }

    # ------------------------------------------------------------------ #
    #  Lineups (Couche 6 L47)
    # ------------------------------------------------------------------ #
    def fetch_lineups(self, bzz_match: dict) -> dict | None:
        """
        Retourne :
          {"is_confirmed": bool,
           "home_formation": str, "away_formation": str,
           "home_starters": [names], "away_starters": [names],
           "source": "pitchapi"}
        ou None.
        """
        pm = self._find_pitch_match(bzz_match)
        if pm is None:
            return None

        try:
            lu = self._client.matches.lineups(pm.id)
        except Exception as e:
            print(f"[kpitchapi] lineups({pm.id}) KO : {e}")
            return None

        home = getattr(lu, "home", None)
        away = getattr(lu, "away", None)
        if home is None or away is None:
            return None

        def _starters(team):
            return [getattr(p, "name", "") for p in (getattr(team, "starters", None) or [])]

        return {
            "is_confirmed": bool(getattr(home, "confirmed", False) and getattr(away, "confirmed", False)),
            "home_formation": getattr(home, "formation", None),
            "away_formation": getattr(away, "formation", None),
            "home_starters": _starters(home),
            "away_starters": _starters(away),
            "source": "pitchapi",
        }

    # ------------------------------------------------------------------ #
    #  H2H (Couche 1 L47 — fallback)
    # ------------------------------------------------------------------ #
    def fetch_h2h(self, bzz_match: dict) -> list | None:
        pm = self._find_pitch_match(bzz_match)
        if pm is None:
            return None

        try:
            h2h = self._client.matches.h2h(pm.id)
        except Exception as e:
            print(f"[kpitchapi] h2h({pm.id}) KO : {e}")
            return None

        matches = getattr(h2h, "matches", None) or []
        out = []
        for m in matches:
            home = getattr(getattr(m, "home_team", None), "name", "")
            away = getattr(getattr(m, "away_team", None), "name", "")
            hs = getattr(m, "score_home", None)
            as_ = getattr(m, "score_away", None)
            if hs is None or as_ is None:
                continue
            out.append({
                "home": home, "away": away,
                "home_score": hs, "away_score": as_,
                "total_goals": hs + as_,
            })
        return out

    # ------------------------------------------------------------------ #
    #  Fermeture
    # ------------------------------------------------------------------ #
    def close(self):
        try:
            self._client.close()
        except Exception:
            pass


def knew_client(api_key: str | None = None) -> KPitchAPI:
    return KPitchAPI(api_key=api_key)
