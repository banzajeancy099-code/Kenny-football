"""Couche 10 — Facteur X (NLP news via atoma)."""
import json
import requests
import atoma
from src.layers.base import BaseLayer, LayerResult


class FacteurXLayer(BaseLayer):
    id = 10
    name = "facteur_x"

    PROMPT = """Analyse ces news sur {team} et retourne un score JSON STRICT :
{{"score": <-3..+3>, "reason": "<10 mots max>"}}

+3 = crise majeure, changement coach
+1.5 = tension transfert
0 = neutre
-1.5 = hommage, anniversaire
-3 = derby, finale

News:
{news}"""

    def __init__(self, gemini_client, news_rss=None):
        self.llm = gemini_client
        self.news = news_rss

    def compute(self, match: dict, context: dict) -> LayerResult:
        try:
            news_home = self._get_news(match["home_name"])
            news_away = self._get_news(match["away_name"])

            s_home = self._analyze(match["home_name"], news_home)
            s_away = self._analyze(match["away_name"], news_away)

            delta = s_away["score"] - s_home["score"]
            score = 5.0 + delta * 0.8
            score = max(0.0, min(10.0, score))

            return LayerResult(
                layer_id=self.id, layer_name=self.name,
                score=score, confidence=0.7,
                features={
                    "home_fx": s_home["score"],
                    "away_fx": s_away["score"],
                },
            )
        except Exception as e:
            return self.fallback(match, str(e))

    def _get_news(self, team: str) -> list:
        """Récupère les news Google News via RSS (atoma)."""
        try:
            url = (
                f"https://news.google.com/rss/search?"
                f"q={team}&hl=fr&gl=FR&ceid=FR:fr"
            )
            response = requests.get(url, timeout=10)
            feed = atoma.parse_rss_bytes(response.content)
            return [
                {"title": item.title, "published": str(item.pub_date)}
                for item in feed.items[:20]
            ]
        except Exception:
            return []

    def _analyze(self, team: str, news: list) -> dict:
        if not news:
            return {"score": 0.0, "reason": "no_news"}
        news_txt = "\n".join(f"- {n.get('title', '')}" for n in news[:10])
        try:
            raw = self.llm.generate(
                self.PROMPT.format(team=team, news=news_txt),
                temperature=0.1,
                json_mode=True,
            )
            return json.loads(raw)
        except Exception:
            return {"score": 0.0, "reason": "llm_fail"}
