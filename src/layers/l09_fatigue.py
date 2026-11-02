# src/layers/l09_fatigue.py — Couche 9 : Fatigue (matchs des 14 derniers jours)
from datetime import datetime, timedelta
from src.layers.base import BaseLayer, LayerResult


class FatigueLayer(BaseLayer):
    id = 9
    name = "Fatigue"

    def __init__(self, bzzoiro):
        self.bzzoiro = bzzoiro
        self._cache = {}

    def _get_recent_matches(self, team_id):
        if team_id in self._cache:
            return self._cache[team_id]
        try:
            r = self.bzzoiro.request("GET", "/events/", params={"team_id": team_id, "limit": 20})
            results = r.get("results", []) if isinstance(r, dict) else []
            # Garder uniquement les matchs terminés
            results = [m for m in results if str(m.get("status", "")).lower() in ("finished", "ft", "aet", "pen")]
            # Trier par date
            results.sort(key=lambda x: x.get("event_date") or "", reverse=True)
        except Exception:
            results = []
        self._cache[team_id] = results
        return results

    def _compute_fatigue(self, team_id):
        events = self._get_recent_matches(team_id)
        if not events:
            return None

        now = datetime.now()
        cutoff = now - timedelta(days=14)

        recent = 0
        for ev in events:
            date_str = ev.get("event_date") or ev.get("date") or ev.get("kickoff")
            if not date_str:
                continue
            try:
                d = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
                if d.tzinfo:
                    d = d.replace(tzinfo=None)
                if d > cutoff:
                    recent += 1
            except Exception:
                pass

        # 0-2 matchs = frais (0), 5+ matchs = épuisé (10)
        fatigue = min(10.0, recent * 2.0)
        return {"fatigue": fatigue, "recent_matches": recent}

    def compute(self, match, context):
        home_id = match.get("home_team_id")
        away_id = match.get("away_team_id")

        if not home_id or not away_id:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.0,
                warnings=["team_id manquant"],
            )

        home_fatigue = self._compute_fatigue(home_id)
        away_fatigue = self._compute_fatigue(away_id)

        if home_fatigue is None or away_fatigue is None:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.1,
                warnings=["matchs indisponibles"],
            )

        avg_fatigue = (home_fatigue["fatigue"] + away_fatigue["fatigue"]) / 2

        # Score inversé : frais = Over (score haut), fatigué = Under (score bas)
        score = 10.0 - avg_fatigue

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=round(score, 2),
            confidence=0.7,
            raw={
                "home_recent": home_fatigue["recent_matches"],
                "away_recent": away_fatigue["recent_matches"],
                "avg_fatigue": round(avg_fatigue, 2),
            },
            features={
                "home_recent": home_fatigue["recent_matches"],
                "away_recent": away_fatigue["recent_matches"],
            },
            warnings=[],
        )
