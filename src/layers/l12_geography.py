# src/layers/l12_geography.py — Couche 12 : Géographie / météo
from datetime import datetime
from src.layers.base import BaseLayer, LayerResult


class GeographyLayer(BaseLayer):
    id = 12
    name = "Géographie / météo"

    def __init__(self):
        pass

    def compute(self, match, context):
        weather = match.get("weather") or {}
        pitch = str(match.get("pitch_condition") or "").lower()

        temp = weather.get("temperature_c")
        wind = weather.get("wind_speed") or weather.get("wind_kmh")
        rain = weather.get("precipitation_mm") or weather.get("rain_mm")

        score = 5.0
        reasons = []
        adjustments = 0.0

        if pitch in ("wet", "muddy", "waterlogged"):
            adjustments -= 0.5
            reasons.append(f"terrain {pitch} → jeu haché")
        elif pitch in ("dry", "good", "excellent"):
            adjustments += 0.1
            reasons.append("terrain idéal")

        if temp is not None:
            try:
                t = float(temp)
                if t > 32:
                    adjustments -= 0.3
                    reasons.append(f"chaleur extrême ({t}°C)")
                elif t < 0:
                    adjustments -= 0.2
                    reasons.append(f"froid extrême ({t}°C)")
                elif 15 <= t <= 25:
                    adjustments += 0.2
                    reasons.append(f"température idéale ({t}°C)")
            except (TypeError, ValueError):
                pass

        if wind is not None:
            try:
                w = float(wind)
                if w > 8:
                    adjustments -= 0.3
                    reasons.append(f"vent fort ({w} m/s)")
                elif w > 5:
                    adjustments -= 0.1
                    reasons.append(f"vent modéré ({w} m/s)")
            except (TypeError, ValueError):
                pass

        if rain is not None:
            try:
                r = float(rain)
                if r > 5:
                    adjustments -= 0.3
                    reasons.append(f"pluie forte ({r} mm)")
                elif r > 1:
                    adjustments -= 0.1
                    reasons.append(f"pluie modérée ({r} mm)")
            except (TypeError, ValueError):
                pass

        if temp is None and wind is None and rain is None and not pitch:
            return LayerResult(
                layer_id=self.id,
                layer_name=self.name,
                score=5.0,
                confidence=0.0,
                raw={"reason": "pas de données météo"},
                features={},
                warnings=["pas de données météo/terrain"],
            )

        score += adjustments
        score = max(0.0, min(10.0, score))

        return LayerResult(
            layer_id=self.id,
            layer_name=self.name,
            score=score,
            confidence=0.5,
            raw={
                "temp_c": temp, "wind": wind, "rain": rain, "pitch": pitch,
                "adjustment": adjustments, "reasons": reasons,
            },
            features={"temp_c": temp, "wind": wind, "rain": rain, "pitch": pitch},
            warnings=[],
        )
