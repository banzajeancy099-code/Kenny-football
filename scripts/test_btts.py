#!/usr/bin/env python3
"""Test BTTS isolément (avec 2e clé API)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.clients.bzzoiro import BzzoiroClient
from src.layers.base import LayerResult


class BTTSContextLayer:
    """L32 : BTTS Context (déjà existante, mais testée isolément)."""
    id = 32
    name = "BTTS Context"

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

        standings = self._get_standings_cached(league_id)
        home = next((t for t in standings if t.get("team_id") == home_id), None)
        away = next((t for t in standings if t.get("team_id") == away_id), None)

        if not home or not away:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.1,
                warnings=["stats indisponibles"],
            )

        hp = home.get("played", 0) or 1
        ap = away.get("played", 0) or 1
        hgf = (home.get("gf", 0) or 0) / hp
        hga = (home.get("ga", 0) or 0) / hp
        agf = (away.get("gf", 0) or 0) / ap
        aga = (away.get("ga", 0) or 0) / ap

        # Pour BTTS, il faut :
        # 1. Home marque (gf_home > 0.8)
        # 2. Away marque (gf_away > 0.8)
        # 3. Les 2 défenses encaissent (ga_home > 0.8, ga_away > 0.8)

        score = 5.0
        reasons = []

        # Home marque-t-il ?
        if hgf >= 1.5:
            score += 0.5
            reasons.append(f"home attaque forte ({hgf:.2f})")
        elif hgf >= 1.0:
            score += 0.2
        elif hgf < 0.7:
            score -= 0.5
            reasons.append(f"home attaque faible ({hgf:.2f})")

        # Away marque-t-il ?
        if agf >= 1.5:
            score += 0.5
            reasons.append(f"away attaque forte ({agf:.2f})")
        elif agf >= 1.0:
            score += 0.2
        elif agf < 0.7:
            score -= 0.5
            reasons.append(f"away attaque faible ({agf:.2f})")

        # Les 2 défenses encaissent-elles ?
        if hga >= 1.2:
            score += 0.3
            reasons.append(f"home défense faible ({hga:.2f})")
        elif hga < 0.6:
            score -= 0.5
            reasons.append(f"home défense solide ({hga:.2f})")

        if aga >= 1.2:
            score += 0.3
            reasons.append(f"away défense faible ({aga:.2f})")
        elif aga < 0.6:
            score -= 0.5
            reasons.append(f"away défense solide ({aga:.2f})")

        score = max(0.0, min(10.0, score))

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=round(score, 2),
            confidence=0.7,
            raw={"reasons": reasons},
            warnings=reasons,
        )


def main():
    api_key = os.environ.get("BZZOIRO_API_KEY_TEST") or os.environ.get("BZZOIRO_API_KEY")
    print(f"Clé utilisée : ...{api_key[-8:]}")
    bz = BzzoiroClient(api_key=api_key)
    l32 = BTTSContextLayer(bz)

    from datetime import date, timedelta
    total = 0
    over_correct = 0
    over_predicted = 0

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
        for m in finished[:8]:
            r = l32.safe_compute(m, {})
            home = (m.get("home_team") or "?")[:16]
            away = (m.get("away_team") or "?")[:16]
            hs = m.get("home_score", 0) or 0
            as_ = m.get("away_score", 0) or 0
            actual_btts = hs >= 1 and as_ >= 1
            pred_btts = r.score >= 5.5
            total += 1
            if actual_btts: over_correct += 1
            if pred_btts: over_predicted += 1
            flag = '✅' if pred_btts == actual_btts else '❌'
            print(f"  {home:16s} vs {away:16s} | {hs}-{as_} {'BTTS' if actual_btts else 'NO-BTTS':8s} | L32={r.score:.2f} → {'BTTS' if pred_btts else 'NO-BTTS':8s} {flag}")

    print(f"\n{'='*60}")
    print(f"TOTAL : {total} matchs")
    print(f"BTTS réels : {over_correct} ({over_correct/total*100:.0f}%)")
    print(f"BTTS prédits : {over_predicted} ({over_predicted/total*100:.0f}%)")


if __name__ == "__main__":
    main()
