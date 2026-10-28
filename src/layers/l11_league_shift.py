# src/layers/l11_league_shift.py — Couche 11 : Décalage ligue/coupe
from datetime import datetime
from src.layers.base import BaseLayer, LayerResult

CUP_LEAGUES = {39, 40, 41, 43, 44, 45, 46, 92, 93}
EUROPE_LEAGUES = {7, 8, 83, 90}
CAUTIOUS_STAGES = {"final", "semifinals", "quarterfinals", "playoffs", "relegation"}
OPEN_STAGES = {"group-stage", "regular-season", "league-stage"}


class LeagueShiftLayer(BaseLayer):
    id = 11
    name = "Décalage ligue/coupe"

    def __init__(self):
        pass

    def compute(self, match, context):
        lid = match.get("league_id")
        stage = str(match.get("stage") or match.get("stage_name") or "").lower()
        round_name = str(match.get("round_name") or "").lower()

        score = 5.0
        reasons = []

        if lid in CUP_LEAGUES:
            score += 0.5
            reasons.append("coupe nationale (rotations, matchs ouverts)")
        elif lid in EUROPE_LEAGUES:
            if any(k in stage for k in CAUTIOUS_STAGES):
                score -= 0.5
                reasons.append(f"Europe phase finale ({stage}) → prudence")
            elif any(k in stage for k in OPEN_STAGES):
                score += 0.3
                reasons.append(f"Europe phase de groupes ({stage}) → matchs ouverts")

        if any(k in stage or k in round_name for k in CAUTIOUS_STAGES):
            score -= 0.3
            reasons.append("phase à élimination (prudence)")

        score = max(0.0, min(10.0, score))

        return LayerResult(
            layer_id=self.id,
            layer_name=self.name,
            score=score,
            confidence=0.5,
            raw={
                "league_id": lid, "stage": stage,
                "is_cup": lid in CUP_LEAGUES,
                "is_europe": lid in EUROPE_LEAGUES,
                "reasons": reasons,
            },
            features={"is_cup": lid in CUP_LEAGUES, "is_europe": lid in EUROPE_LEAGUES},
            warnings=[],
        )
