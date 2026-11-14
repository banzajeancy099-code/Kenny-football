"""
L31 — Negatives (signaux négatifs).

Détecte les configurations à risque :
- 2 attaques faibles
- 2 défenses faibles
- 2 formes récentes faibles
- H2H très fermés
- Match en fin de saison

Score 0-10 : élevé = bon (pas de signal négatif), bas = mauvais (rejet).

Rejet si score < 3.0.
"""

from __future__ import annotations

from .kbase import Layer, LayerResult


class KL31Negatives(Layer):
    id = "l31"
    name = "Negatives"
    weight_key = "l31"

    def run(self, match: dict, ctx: dict) -> LayerResult:
        res = LayerResult(confidence=1.0)
        warnings = []
        penalties = 0.0
        meta = {}

        bzz = ctx.get("bzzoiro")
        if bzz is None:
            res.rejected = True
            res.confidence = 0.0
            res.warnings = ["L31: bzzoiro indisponible"]
            return res

        # Splits
        try:
            home = bzz.fetch_team_splits(match["home_team_id"])
            away = bzz.fetch_team_splits(match["away_team_id"])
        except Exception:
            home = away = None

        if not home or not away:
            # Rejet strict si données manquantes (pas de fallback)
            res.rejected = True
            res.confidence = 0.0
            res.warnings = ["L31: splits indisponibles → rejet"]
            return res

        # Seuil minimum : 5 matchs par équipe
        played_h = home.get("played", 0)
        played_a = away.get("played", 0)
        if min(played_h, played_a) < 5:
            res.score = 3.0
            res.confidence = 0.5
            res.warnings = [f"L31: données insuffisantes ({min(played_h, played_a)} matchs, <5) → score neutre"]
            return res

        # Signal 1 : 2 attaques faibles
        home_gf = home.get("home_gf_avg", 1.5)
        away_gf = away.get("away_gf_avg", 1.5)
        if home_gf < 1.0 and away_gf < 1.0:
            penalties += 2.0
            warnings.append(f"L31: 2 attaques faibles ({home_gf:.2f}/{away_gf:.2f})")
            meta["attack_weak"] = True

        # Signal 2 : 2 défenses faibles
        home_ga = home.get("home_ga_avg", 1.5)
        away_ga = away.get("away_ga_avg", 1.5)
        if home_ga > 1.8 and away_ga > 1.8:
            penalties += 2.0
            warnings.append(f"L31: 2 défenses faibles ({home_ga:.2f}/{away_ga:.2f})")
            meta["defense_weak"] = True

        # Signal 3 : 2 formes récentes faibles
        home_form = home.get("form_gf", 1.5)
        away_form = away.get("form_gf", 1.5)
        if home_form < 0.8 and away_form < 0.8:
            penalties += 1.5
            warnings.append("L31: 2 formes récentes faibles")
            meta["form_weak"] = True

        # Signal 4 : H2H très fermés
        h2h = match.get("head_to_head") or {}
        h2h_avg = h2h.get("avg_total_goals")
        if h2h_avg is not None and h2h_avg < 1.8:
            penalties += 1.0
            warnings.append(f"L31: H2H très fermé ({h2h_avg:.2f})")
            meta["h2h_closed"] = True

        # Signal 5 : fin de saison
        round_number = match.get("round_number")
        if round_number is not None and round_number > 30:
            penalties += 1.0
            warnings.append("L31: match en fin de saison")
            meta["end_season"] = True

        score = max(0.0, 10.0 - penalties)

        if score < 3.0:
            res.rejected = True
            res.confidence = 0.0

        res.score = round(score, 2)
        res.warnings = warnings
        res.meta = {**meta, "penalties": penalties, "weight": 1.5}
        return res


layer = KL31Negatives()
