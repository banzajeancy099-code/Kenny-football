# src/layers/l13_smart_money.py — Couche 13 : Smart Money (mouvement des cotes)
import json
import logging
from datetime import datetime
from pathlib import Path
from src.layers.base import BaseLayer, LayerResult

log = logging.getLogger("l13_smart_money")

# Dossier des snapshots
SNAPSHOTS_DIR = Path(__file__).parent.parent.parent / "data" / "odds_snapshots"


class SmartMoneyLayer(BaseLayer):
    id = 13
    name = "Smart Money"

    def __init__(self):
        pass

    def _find_odds_history(self, home_name, away_name):
        """Cherche les cotes dans les snapshots (par nom d'équipes)."""
        if not SNAPSHOTS_DIR.exists():
            return []

        snapshots = sorted(SNAPSHOTS_DIR.glob("*.json"))
        if len(snapshots) < 2:
            return []

        home_l = home_name.lower().strip()
        away_l = away_name.lower().strip()

        history = []
        for snap_file in snapshots:
            try:
                with open(snap_file) as f:
                    snap = json.load(f)
                for sport, matches in snap.get("odds", {}).items():
                    for m in matches:
                        h = (m.get("home") or "").lower().strip()
                        a = (m.get("away") or "").lower().strip()
                        # Matching flou
                        if (home_l in h or h in home_l) and (away_l in a or a in away_l):
                            history.append({
                                "timestamp": snap.get("timestamp"),
                                "cote": m.get("best_over_2_5"),
                                "bookmaker": m.get("bookmaker"),
                            })
            except Exception:
                continue

        return history

    def compute(self, match, context):
        home = match.get("home_team") or match.get("home") or ""
        away = match.get("away_team") or match.get("away") or ""

        if not home or not away:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.0,
                warnings=["noms équipes manquants"],
            )

        # Cherche l'historique des cotes
        history = self._find_odds_history(home, away)

        if len(history) < 2:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.0,
                warnings=["historique cotes insuffisant (< 2 snapshots)"],
            )

        # Trie par timestamp
        try:
            history.sort(key=lambda x: x.get("timestamp", ""))
        except Exception:
            pass

        cote_open = history[0].get("cote")
        cote_actuelle = history[-1].get("cote")

        if not cote_open or not cote_actuelle or cote_open <= 1.01:
            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=5.0, confidence=0.1,
                warnings=["cotes invalides"],
            )

        # Calcul du mouvement
        mouvement_pct = (cote_actuelle - cote_open) / cote_open  # % de variation

        # Logique :
        # - Cote a BAISSÉ (mouvement < -5%) → argent sur Over → score HAUT
        # - Cote a MONTÉ (mouvement > +5%) → argent sur Under → score BAS
        # - Mouvement faible (|x| < 2%) → neutre

        if mouvement_pct <= -0.05:
            # Cote baissé de 5%+ → signal Over fort
            score = 7.5 + min(2.5, abs(mouvement_pct) * 20)  # 7.5 à 10
        elif mouvement_pct <= -0.02:
            # Cote baissé de 2-5% → signal Over modéré
            score = 6.0 + (abs(mouvement_pct) - 0.02) * 50  # 6 à 7.5
        elif mouvement_pct >= 0.05:
            # Cote montée de 5%+ → signal Under fort
            score = 2.5 - min(2.5, (mouvement_pct - 0.05) * 20)  # 0 à 2.5
        elif mouvement_pct >= 0.02:
            # Cote montée de 2-5% → signal Under modéré
            score = 4.0 - (mouvement_pct - 0.02) * 50  # 2.5 à 4
        else:
            # Mouvement faible → neutre
            score = 5.0

        score = max(0.0, min(10.0, score))

        # Confiance : plus de snapshots = plus fiable
        confidence = min(0.9, 0.5 + len(history) * 0.05)

        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=round(score, 2),
            confidence=confidence,
            raw={
                "snapshots": len(history),
                "cote_open": cote_open,
                "cote_actuelle": cote_actuelle,
                "mouvement_pct": round(mouvement_pct * 100, 2),
                "history": history[:5],  # premiers 5 snapshots
            },
            features={
                "mouvement_pct": round(mouvement_pct * 100, 2),
                "cote_open": cote_open,
                "cote_actuelle": cote_actuelle,
            },
            warnings=[],
        )
