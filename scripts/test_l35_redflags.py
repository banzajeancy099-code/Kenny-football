#!/usr/bin/env python3
"""Test L35 Red Flags isolément, avec 2e clé API Bzzoiro."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.clients.bzzoiro import BzzoiroClient
from src.layers.base import LayerResult


# === 1. La nouvelle couche L35 (en mémoire, pas dans le pipeline) ===
class RedFlagsLayer:
    """L35 : Red Flags (hard reject uniquement)."""
    id = 35
    name = "Red Flags"

    def __init__(self, bzzoiro):
        self.bzzoiro = bzzoiro
        self._cache = {}

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

        # Cache standings
        if league_id not in self._cache:
            try:
                self._cache[league_id] = self.bzzoiro.get_standings(league_id) or []
            except Exception:
                self._cache[league_id] = []
        standings = self._cache[league_id]

        home = next((t for t in standings if t.get("team_id") == home_id), None)
        away = next((t for t in standings if t.get("team_id") == away_id), None)

        if not home or not away:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.1,
                warnings=["stats indisponibles"],
            )

        score = 5.0
        reasons = []

        hp = home.get("played", 0) or 1
        ap = away.get("played", 0) or 1
        hgf = (home.get("gf", 0) or 0) / hp
        hga = (home.get("ga", 0) or 0) / hp
        agf = (away.get("gf", 0) or 0) / ap
        aga = (away.get("ga", 0) or 0) / ap

        # Red flag 1 : 2 défenses < 0.9
        if hga < 0.9 and aga < 0.9:
            score -= 1.5
            reasons.append(f"2 défenses < 0.9 ({hga:.2f}/{aga:.2f})")

        # Red flag 2 : 2 attaques < 1.2 (pénalité simple)
        if hgf < 1.2 and agf < 1.2:
            score -= 0.5
            reasons.append(f"2 attaques < 1.2 ({hgf:.2f}/{agf:.2f})")

        # Red flag 3 : défenses d'élite < 0.6
        if hga < 0.6 and aga < 0.6:
            score -= 1.0
            reasons.append(f"défenses d'élite ({hga:.2f}/{aga:.2f})")

        # Red flag 4 : sur-performance xG > 0.25
        for label, team, played in (("home", home, hp), ("away", away, ap)):
            gf = (team.get("gf", 0) or 0) / played
            xgf = (team.get("xgf", 0) or 0) / played
            if xgf > 0:
                overperf = gf - xgf
                if overperf > 0.25:
                    score -= 0.3
                    reasons.append(f"{label} sur-perf xG (+{overperf:.2f})")

        # Red flag 5 : défense très faible ET attaque très faible
        if (hga < 0.5 or aga < 0.5) and (hgf < 0.8 or agf < 0.8):
            score -= 0.5
            reasons.append(f"défense faible + attaque faible")

        # === SEUILS DE REJET DIRECT (score forcé à 2.5) ===
        # 2 attaques < 1.1 = match très fermé
        if hgf < 1.1 and agf < 1.1:
            score = min(score, 2.5)
            reasons.append("REJET: 2 attaques < 1.1")
        # 2 défenses < 0.9 = match verrouillé
        if hga < 0.9 and aga < 0.9:
            score = min(score, 2.5)
            reasons.append("REJET: 2 défenses < 0.9")
        # 2 défenses < 0.5 ET 2 attaques < 0.8 = déséquilibre extrême
        if (hga < 0.5 and aga < 0.5) and (hgf < 0.8 and agf < 0.8):
            score = min(score, 2.5)
            reasons.append("REJET: 2 défenses < 0.5 + 2 attaques < 0.8")

        # === SEUILS DE REJET DIRECT (score forcé à 2.5) ===
        # 2 attaques < 1.1 = match très fermé
        if hgf < 1.1 and agf < 1.1:
            score = min(score, 2.5)
            reasons.append("REJET: 2 attaques < 1.1")
        # 2 défenses < 0.9 = match verrouillé
        if hga < 0.9 and aga < 0.9:
            score = min(score, 2.5)
            reasons.append("REJET: 2 défenses < 0.9")
        # 2 défenses < 0.5 ET 2 attaques < 0.8 = déséquilibre extrême
        if (hga < 0.5 and aga < 0.5) and (hgf < 0.8 and agf < 0.8):
            score = min(score, 2.5)
            reasons.append("REJET: 2 défenses < 0.5 + 2 attaques < 0.8")

        score = max(0.0, min(10.0, score))

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=round(score, 2), confidence=0.75 if reasons else 0.5,
            raw={"reasons": reasons},
            features={"red_flags": len(reasons)},
            warnings=reasons if reasons else [],
        )


# === 2. Test isolé ===
def main():
    # Utiliser la 2e clé API
    api_key = os.environ.get("BZZOIRO_API_KEY_TEST") or os.environ.get("BZZOIRO_API_KEY")
    if not api_key:
        print("ERREUR : aucune clé Bzzoiro trouvée")
        sys.exit(1)

    print(f"Clé utilisée : ...{api_key[-8:]}")
    bz = BzzoiroClient(api_key=api_key)
    l35 = RedFlagsLayer(bz)

    from datetime import date, timedelta
    total = 0
    rejets = 0

    for days_back in range(1, 10):
        d = (date.today() - timedelta(days=days_back)).isoformat()
        try:
            matches = bz.get_matches_today(d)
        except Exception as e:
            print(f"  {d} : erreur {e}")
            continue

        finished = [m for m in matches if m.get("status") == "finished"]
        if not finished:
            continue

        print(f"\n=== {d} ({len(finished)} matchs terminés) ===")
        for m in finished[:8]:
            r = l35.safe_compute(m, {})
            home = (m.get("home_team") or "?")[:18]
            away = (m.get("away_team") or "?")[:18]
            hs = m.get("home_score", 0) or 0
            as_ = m.get("away_score", 0) or 0
            total += 1
            if r.score < 3.0:
                rejets += 1
            flag = "🚨 REJET" if r.score < 3.0 else ""
            reasons = ", ".join(r.warnings[:2]) if r.warnings else "—"
            print(f"  {home:18s} vs {away:18s} | {hs}-{as_} | L35={r.score:.2f} {flag}")
            if r.warnings:
                print(f"    {reasons}")

    print(f"\n{'='*60}")
    print(f"TOTAL : {total} matchs testés")
    print(f"REJETS (L35 < 3.0) : {rejets} ({rejets/total*100:.1f}%)" if total else "Aucun match")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
