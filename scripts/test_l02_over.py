#!/usr/bin/env python3
"""Test L2 (Over dynamique) isolément."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.clients.bzzoiro import BzzoiroClient
from src.layers.base import LayerResult


class OverLayer:
    """L2 : Taux Over dynamique basé sur les vrais buts de la ligue."""
    id = 2
    name = "Over 2.5"

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

    def _compute_league_stats(self, league_id):
        standings = self._get_standings_cached(league_id)
        if not standings:
            return None

        total_goals = 0
        total_matches = 0
        for t in standings:
            played = t.get("played", 0) or 0
            if played == 0:
                continue
            total_goals += (t.get("gf", 0) or 0)
            total_matches += played

        if total_matches == 0:
            return None

        goals_per_match = (total_goals / total_matches) * 2
        over_rate = min(0.95, max(0.30, (goals_per_match / 2.70) * 0.55))

        return {
            "goals_per_match": round(goals_per_match, 2),
            "over_rate": round(over_rate, 3),
            "matches": int(total_matches / 2),
        }

    def _get_team_stats(self, team_id, league_id):
        for t in self._get_standings_cached(league_id):
            if t.get("team_id") == team_id:
                played = t.get("played", 0) or 1
                return {
                    "gf_avg": (t.get("gf", 0) or 0) / played,
                    "ga_avg": (t.get("ga", 0) or 0) / played,
                    "played": played,
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

        league = self._compute_league_stats(league_id)
        if league is None or league["matches"] < 20:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.1,
                warnings=["pas assez de matchs dans la ligue"],
            )

        home = self._get_team_stats(home_id, league_id)
        away = self._get_team_stats(away_id, league_id)

        if home is None or away is None:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.2,
                warnings=["stats équipes indisponibles"],
            )

        # Score basé sur le taux Over de la ligue (amplifié × 15)
        base_score = 5.0 + (league["over_rate"] - 0.55) * 15.0

        # Ajustement selon les équipes (xG attendu du match)
        home_attack = home["gf_avg"]
        away_attack = away["gf_avg"]
        home_defense = home["ga_avg"]
        away_defense = away["ga_avg"]
        expected_goals = (home_attack + away_defense) / 2 + (away_attack + home_defense) / 2

        if expected_goals > 3.5:
            base_score += 0.5
        elif expected_goals > 3.0:
            base_score += 0.2
        elif expected_goals < 2.0:
            base_score -= 0.5
        elif expected_goals < 2.5:
            base_score -= 0.2

        score = max(0.0, min(10.0, base_score))

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=round(score, 2),
            confidence=0.8 if league["matches"] >= 50 else 0.5,
            raw={
                "league_id": league_id,
                "league_over_rate": league["over_rate"],
                "league_goals_per_match": league["goals_per_match"],
                "league_matches": league["matches"],
                "expected_goals": round(expected_goals, 2),
            },
            features={
                "league_over_rate": league["over_rate"],
                "expected_goals": round(expected_goals, 2),
            },
            warnings=[],
        )


def main():
    api_key = os.environ.get("BZZOIRO_API_KEY_TEST") or os.environ.get("BZZOIRO_API_KEY")
    print(f"Clé utilisée : ...{api_key[-8:]}")
    bz = BzzoiroClient(api_key=api_key)
    l2 = OverLayer(bz)

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
            r = l2.safe_compute(m, {})
            home = (m.get("home_team") or "?")[:18]
            away = (m.get("away_team") or "?")[:18]
            hs = m.get("home_score", 0) or 0
            as_ = m.get("away_score", 0) or 0
            actual_over = (hs + as_) >= 3
            total += 1
            print(f"  {home:18s} vs {away:18s} | {hs}-{as_} {'OVER' if actual_over else 'UNDER'} | L2={r.score:.2f}")
            if r.raw:
                print(f"    taux ligue: {r.raw.get('league_over_rate')}, xG attendu: {r.raw.get('expected_goals')}")

    print(f"\nTOTAL : {total} matchs")


if __name__ == "__main__":
    main()
