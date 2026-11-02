#!/usr/bin/env python3
"""Test L44 (Profil Offensif/Défensif) isolément."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.clients.bzzoiro import BzzoiroClient
from src.layers.base import LayerResult


class ProfileLayer:
    """L44 : Profil offensif/défensif des 2 équipes (sans cotes)."""
    id = 44
    name = "Profil Off/Déf"

    def __init__(self, bzzoiro):
        self.bzzoiro = bzzoiro
        self._cache = {}

    def _get_standings_cached(self, league_id):
        if league_id in self._cache:
            return self._cache[league_id]
        try:
            standings = self.bzzoiro.get_standings(league_id) or []
        except Exception:
            standings = []
        self._cache[league_id] = standings
        return standings

    def _get_team_profile(self, team_id, league_id):
        for t in self._get_standings_cached(league_id):
            if t.get("team_id") == team_id:
                played = t.get("played", 0) or 0
                if played < 5:
                    return None
                gf = t.get("gf", 0) or 0
                ga = t.get("ga", 0) or 0
                xgf = t.get("xgf", 0) or 0
                xga = t.get("xga", 0) or 0
                xg_games = t.get("xg_games", 0) or 0

                return {
                    "team_name": t.get("team_name", "?"),
                    "played": played,
                    "gf_avg": gf / played,
                    "ga_avg": ga / played,
                    "xgf_avg": xgf / xg_games if xg_games > 0 else 0,
                    "xga_avg": xga / xg_games if xg_games > 0 else 0,
                    "attack_index": (gf / played) if played > 0 else 0,
                    "defense_index": (ga / played) if played > 0 else 0,
                }
        return None

    def safe_compute(self, match, context=None):
        home_id = match.get("home_team_id")
        away_id = match.get("away_team_id")
        league_id = match.get("league_id")

        if not home_id or not away_id or not league_id:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.0,
                warnings=["données manquantes"],
            )

        home = self._get_team_profile(home_id, league_id)
        away = self._get_team_profile(away_id, league_id)

        if home is None or away is None:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.1,
                warnings=["profils indisponibles"],
            )

        # Buts attendus : attaque + défense adverse (moyenne simple)
        home_attack = home["attack_index"]
        away_defense = away["defense_index"]
        away_attack = away["attack_index"]
        home_defense = home["defense_index"]

        home_expected = (home_attack + away_defense) / 2
        away_expected = (away_attack + home_defense) / 2
        expected_goals = home_expected + away_expected

        # Score basé sur les buts attendus
        # 2.5 = neutre, 3.5+ = Over, 1.5- = Under
        score = 5.0 + (expected_goals - 2.5) * 2.5

        # Ajustement : si les 2 attaques sont fortes → bonus
        if home_attack >= 1.8 and away_attack >= 1.8:
            score += 0.3
        elif home_attack >= 1.5 and away_attack >= 1.5:
            score += 0.15

        # Pénalité : si les 2 attaques sont faibles
        if home_attack <= 0.9 and away_attack <= 0.9:
            score -= 0.4

        score = max(0.0, min(10.0, score))

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=round(score, 2),
            confidence=0.75,
            raw={
                "home": home,
                "away": away,
                "home_attack": round(home_attack, 2),
                "away_attack": round(away_attack, 2),
                "home_defense": round(home_defense, 2),
                "away_defense": round(away_defense, 2),
                "expected_goals": round(expected_goals, 2),
            },
            features={
                "expected_goals": round(expected_goals, 2),
            },
            warnings=[],
        )


def main():
    api_key = os.environ.get("BZZOIRO_API_KEY_TEST") or os.environ.get("BZZOIRO_API_KEY")
    print(f"Clé utilisée : ...{api_key[-8:]}")
    bz = BzzoiroClient(api_key=api_key)
    l44 = ProfileLayer(bz)

    from datetime import date, timedelta
    total = 0

    for days_back in range(1, 6):
        d = (date.today() - timedelta(days=days_back)).isoformat()
        try:
            matches = bz.get_matches_today(d)
        except Exception:
            continue
        finished = [m for m in matches if m.get("status") == "finished"]
        if not finished:
            continue

        print(f"\n=== {d} ({len(finished)} matchs) ===")
        for m in finished[:5]:
            r = l44.safe_compute(m, {})
            home = (m.get("home_team") or "?")[:18]
            away = (m.get("away_team") or "?")[:18]
            hs = m.get("home_score", 0) or 0
            as_ = m.get("away_score", 0) or 0
            actual_over = (hs + as_) >= 3
            total += 1
            print(f"  {home:18s} vs {away:18s} | {hs}-{as_} {'OVER' if actual_over else 'UNDER'} | L44={r.score:.2f}")
            if r.raw:
                print(f"    home_attack={r.raw['home_attack']}, away_attack={r.raw['away_attack']}, xG={r.raw['expected_goals']}")

    print(f"\nTOTAL : {total} matchs")


if __name__ == "__main__":
    main()
