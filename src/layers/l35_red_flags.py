# src/layers/l35_red_flags.py — Couche 35 : Red Flags (hard reject)
from src.layers.base import LayerResult


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