from src.layers.base import BaseLayer, LayerResult
from datetime import datetime, timedelta
import logging

log = logging.getLogger("l48")


class PlayerContextLayer(BaseLayer):
    id = 48
    name = "Contexte Joueur"

    def __init__(self, bzzoiro):
        self.bzzoiro = bzzoiro

    def safe_compute(self, match, context):
        try:
            return self.compute(match, context)
        except Exception as e:
            log.warning(f"[L48] {e}")
            return LayerResult(layer_id=self.id, layer_name=self.name, score=5.0, confidence=0.3)

    def compute(self, match, context):
        home_id = match.get("home_team_id")
        away_id = match.get("away_team_id")
        match_id = match.get("id") or match.get("event_id")

        if not home_id or not away_id or not match_id:
            return LayerResult(layer_id=self.id, layer_name=self.name, score=5.0, confidence=0.0, warnings=["IDs manquants"])

        try:
            lineups = self.bzzoiro.get_event_lineups(match_id)
        except Exception:
            return LayerResult(layer_id=self.id, layer_name=self.name, score=5.0, confidence=0.3)

        if not lineups or "lineups" not in lineups:
            return LayerResult(layer_id=self.id, layer_name=self.name, score=5.0, confidence=0.3)

        total_score = 0
        total_players = 0
        warnings = []

        for side in ("home", "away"):
            team_lineup = lineups["lineups"].get(side, {})
            players = team_lineup.get("players", [])

            for p in players[:5]:  # Seulement les 5 joueurs clés (économie quota)
                pid = p.get("id")
                if not pid:
                    continue

                player_score = 5.0  # Base

                try:
                    # 1. Récupérer les stats de minutes jouées (proxy satisfaction)
                    stats = self.bzzoiro.request("GET", f"/players/{pid}/stats/", params={"limit": 5})
                    results_stats = stats.get("results", []) if isinstance(stats, dict) else []
                    total_minutes = sum(s.get("minutes_played", 0) or 0 for s in results_stats)
                    total_matches = len(results_stats)

                    if total_matches >= 3:
                        avg_minutes = total_minutes / total_matches
                        # Si le joueur joue moins de 45 min/match en moyenne, il est mécontent
                        if avg_minutes < 30:
                            player_score -= 1.5
                            warnings.append(f"{p.get('name')} joue peu ({avg_minutes:.0f} min/match)")
                        elif avg_minutes < 60:
                            player_score -= 0.5
                        elif avg_minutes > 80:
                            player_score += 0.5

                    # 2. Récupérer les transferts (adaptation)
                    transfers = self.bzzoiro.request("GET", f"/players/{pid}/transfers/")
                    transfers_list = transfers.get("results", []) if isinstance(transfers, dict) else []
                    if transfers_list:
                        # Chercher le dernier transfert
                        last_transfer = transfers_list[0] if transfers_list else None
                        if last_transfer:
                            transfer_date = last_transfer.get("date")
                            if transfer_date:
                                try:
                                    transfer_dt = datetime.fromisoformat(transfer_date.replace("Z", "+00:00"))
                                    days_since = (datetime.now(transfer_dt.tzinfo) - transfer_dt).days
                                    if days_since < 180:  # Moins de 6 mois
                                        player_score -= 0.5
                                        warnings.append(f"{p.get('name')} transféré récemment ({days_since}j)")
                                except Exception:
                                    pass
                except Exception:
                    pass

                total_score += player_score
                total_players += 1

        if total_players == 0:
            return LayerResult(layer_id=self.id, layer_name=self.name, score=5.0, confidence=0.3)

        final_score = total_score / total_players
        final_score = max(0, min(10, final_score))

        return LayerResult(
            layer_id=self.id,
            layer_name=self.name,
            score=round(final_score, 2),
            confidence=0.6,
            warnings=warnings[:3],
        )
