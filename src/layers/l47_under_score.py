from src.layers.base import BaseLayer, LayerResult


class UnderScoreLayer(BaseLayer):
    id = 47
    name = "Under Score"

    def __init__(self, bzzoiro):
        self.bzzoiro = bzzoiro

    def safe_compute(self, match, context):
        try:
            return self.compute(match, context)
        except Exception:
            return LayerResult(layer_id=self.id, layer_name=self.name, score=5.0, confidence=0.5)

    def compute(self, match, context):
        home_id = match.get("home_team_id")
        away_id = match.get("away_team_id")
        league_id = match.get("league_id")

        if not home_id or not away_id:
            return LayerResult(layer_id=self.id, layer_name=self.name, score=5.0, confidence=0.0, warnings=["team_id manquant"])

        def get_defense(team_id):
            """Récupère les buts encaissés moyens et les clean sheets."""
            try:
                standings = self.bzzoiro.get_standings(league_id) or []
                for row in standings:
                    if row.get("team_id") == team_id:
                        played = row.get("played") or 0
                        ga = row.get("goals_against") or 0
                        if played >= 5:
                            return (ga / played, row.get("clean_sheets") or 0)
            except Exception:
                pass
            return (1.5, 0)  # Valeur par défaut (moyenne)

        def get_attack(team_id):
            """Récupère les buts marqués moyens."""
            try:
                standings = self.bzzoiro.get_standings(league_id) or []
                for row in standings:
                    if row.get("team_id") == team_id:
                        played = row.get("played") or 0
                        gf = row.get("goals_for") or 0
                        if played >= 5:
                            return gf / played
            except Exception:
                pass
            return 1.2

        home_ga, home_cs = get_defense(home_id)
        away_ga, away_cs = get_defense(away_id)
        home_gf = get_attack(home_id)
        away_gf = get_attack(away_id)

        # Score Under : plus les défenses sont solides et les attaques faibles, plus le score est haut
        avg_ga = (home_ga + away_ga) / 2
        avg_gf = (home_gf + away_gf) / 2
        avg_cs = (home_cs + away_cs) / 2

        # === SIGNAUX POSITIFS UNDER (explicites) ===
        signals = []
        score = 5.0  # Base

        # Signal 1 : Défenses très solides (< 1.0 but encaissé/match)
        if avg_ga < 0.8:
            score += 2.5
            signals.append(f"défenses ultra-solides ({avg_ga:.2f} ga)")
        elif avg_ga < 1.0:
            score += 2.0
            signals.append(f"défenses solides ({avg_ga:.2f} ga)")
        elif avg_ga < 1.5:
            score += 1.0

        # Signal 2 : Attaques faibles (< 1.0 but marqué/match)
        if avg_gf < 0.8:
            score += 2.0
            signals.append(f"attaques faibles ({avg_gf:.2f} gf)")
        elif avg_gf < 1.0:
            score += 1.5
            signals.append(f"attaques moyennes ({avg_gf:.2f} gf)")
        elif avg_gf < 1.3:
            score += 0.8

        # Signal 3 : Beaucoup de clean sheets (>= 4 sur 10 matchs)
        if avg_cs >= 4:
            score += 1.5
            signals.append(f"clean sheets ({avg_cs:.1f})")
        elif avg_cs >= 3:
            score += 1.0
            signals.append(f"clean sheets ({avg_cs:.1f})")

        # Signal 4 : Matchs fermés (H2H avec peu de buts)
        h2h = match.get("head_to_head") or {}
        if isinstance(h2h, dict):
            h2h_matches = h2h.get("recent_matches") or h2h.get("matches") or []
            if h2h_matches:
                h2h_goals = sum((m.get("home_score") or 0) + (m.get("away_score") or 0) for m in h2h_matches) / len(h2h_matches)
                if h2h_goals < 1.5:
                    score += 1.0
                    signals.append(f"H2H fermés ({h2h_goals:.1f} buts/match)")
                elif h2h_goals < 2.0:
                    score += 0.5

        score = max(0, min(10, score))

        return LayerResult(
            layer_id=self.id,
            layer_name=self.name,
            score=round(score, 2),
            confidence=0.7,
            warnings=signals[:3],  # On renvoie les signaux comme warnings
        )
