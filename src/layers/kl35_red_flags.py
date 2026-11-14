"""
L35 — Red Flags.

Détecte les configurations à haut risque :
- Cotes anormales
- Météo extrême
- Arbitre suspect
- 0-0 récents

Score 0-10 : élevé = bon, bas = red flag détecté.

Rejet si score < 3.0.
"""

from __future__ import annotations

from .kbase import Layer, LayerResult


class KL35RedFlags(Layer):
    id = "l35"
    name = "Red Flags"
    weight_key = "l35"

    def run(self, match: dict, ctx: dict) -> LayerResult:
        res = LayerResult(confidence=1.0)
        warnings = []
        penalties = 0.0
        meta = {}

        # Red flag 1 : cote over anormale → VETO
        cote_over = match.get("cote_over")
        if cote_over is not None and (cote_over < 1.15 or cote_over > 2.50):
            res.rejected = True
            res.warnings = [f"L35: cote over anormale ({cote_over:.2f}) → match truqué"]
            res.meta = {"cote_anormal": True}
            return res

        # Red flag 2 : cote under anormale → VETO
        cote_under = match.get("cote_under")
        if cote_under is not None and (cote_under < 1.15 or cote_under > 3.50):
            res.rejected = True
            res.warnings = [f"L35: cote under anormale ({cote_under:.2f}) → match truqué"]
            res.meta = {"cote_under_anormal": True}
            return res

        # Red flag 3 : météo extrême
        weather = match.get("weather") or {}
        wind = weather.get("wind_speed") or weather.get("wind_kmh")
        if wind and wind > 50:
            penalties += 1.5
            warnings.append(f"L35: vent extrême ({wind} km/h)")
            meta["wind_extreme"] = True

        temp = weather.get("temperature_c") or weather.get("temp_c")
        if temp and (temp > 38 or temp < 0):
            penalties += 1.5
            warnings.append(f"L35: température extrême ({temp}°C)")
            meta["temp_extreme"] = True

        # Red flag 4 : arbitre à buts anormaux
        referee_id = match.get("referee_id")
        db = ctx.get("db")
        if referee_id and db:
            try:
                stats = db.kget_referee_stats(referee_id)
                if stats and stats.get("n", 0) >= 20:
                    goals_avg = stats.get("goals_avg", 2.5)
                    if goals_avg > 4.0:
                        penalties += 1.5
                        warnings.append(f"L35: arbitre buts élevés ({goals_avg:.1f})")
                        meta["referee_high"] = True
                    elif goals_avg < 1.5:
                        penalties += 1.0
                        warnings.append(f"L35: arbitre buts faibles ({goals_avg:.1f})")
                        meta["referee_low"] = True
            except Exception:
                pass

        # Red flag 5 : 0-0 récents
        h2h = match.get("head_to_head") or {}
        recent = h2h.get("recent_matches") or []
        zero_zero = sum(1 for m in recent[:5] if m.get("home_score") == 0 and m.get("away_score") == 0)
        if zero_zero >= 2:
            penalties += 1.5
            warnings.append(f"L35: {zero_zero} matchs 0-0 récents")
            meta["zero_zero"] = True
        score = max(0.0, 10.0 - penalties)

        if score < 3.0:
            res.rejected = True
            res.confidence = 0.0

        res.score = round(score, 2)
        res.warnings = warnings
        res.meta = {**meta, "penalties": penalties, "weight": 1.5}
        return res


layer = KL35RedFlags()
