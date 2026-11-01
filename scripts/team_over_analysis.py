#!/usr/bin/env python3
"""Analyse Over/Under par équipe vs moyenne de ligue, avec xG.

Détecte :
  1. Équipes dont les buts réels sur-performent la ligue
  2. Si les xG confirment (signal fiable) ou pas (régression probable)
"""
import os
import sys
import logging

sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("team_over")

from src.clients.bzzoiro import BzzoiroClient


def analyze(bz, league_id, league_name):
    log.info("=" * 90)
    log.info(f"🏆 {league_name} (ligue {league_id})")
    log.info("=" * 90)

    try:
        standings = bz.get_standings(league_id)
    except Exception as e:
        log.error(f"Erreur: {e}")
        return

    if not standings:
        log.warning("Aucun classement")
        return

    rows = []
    for t in standings:
        played = t.get("played") or 0
        gf = t.get("gf") or 0
        ga = t.get("ga") or 0
        xgf = t.get("xgf") or 0
        xga = t.get("xga") or 0
        if not played:
            continue
        rows.append({
            "name": t.get("team_name", "?"),
            "played": played,
            "gf": gf, "ga": ga,
            "xgf": xgf, "xga": xga,
            "goals_avg": (gf + ga) / played,
            "xg_avg": (xgf + xga) / played if xgf else None,
            "attack_real": gf / played,
            "attack_xg": xgf / played if xgf else None,
        })

    if not rows:
        log.warning("Aucune équipe parsée")
        return

    # Moyennes de ligue
    n = len(rows)
    avg_played = sum(r["played"] for r in rows) / n
    league_goals_avg = sum(r["gf"] + r["ga"] for r in rows) / sum(r["played"] for r in rows)
    league_xg_avg = None
    if all(r["xg_avg"] for r in rows):
        league_xg_avg = sum(r["xgf"] + r["xga"] for r in rows) / sum(r["played"] for r in rows)

    log.info(f"Moyenne ligue : {league_goals_avg:.2f} buts/match"
             + (f" · {league_xg_avg:.2f} xG/match" if league_xg_avg else ""))
    log.info("")

    header = f"{'Équipe':<25} {'J':>3} {'GF':>4} {'GA':>4} {'Moy':>5} {'Ratio':>6} {'xG':>5} {'RatioXG':>7} {'Réal':>6} {'Verdict':>14}"
    log.info(header)
    log.info("-" * 90)

    rows.sort(key=lambda r: r["goals_avg"], reverse=True)
    for r in rows:
        ratio = r["goals_avg"] / league_goals_avg if league_goals_avg else 1

        xg_str = "—"
        ratio_xg_str = "—"
        overperf_str = "—"
        if r["xg_avg"] and league_xg_avg:
            xg_str = f"{r['xg_avg']:.2f}"
            ratio_xg = r["xg_avg"] / league_xg_avg
            ratio_xg_str = f"{ratio_xg:.2f}"
            # Sur/sous-performance attaque : buts réels vs xG
            overperf = r["attack_real"] - r["attack_xg"]
            overperf_str = f"{overperf:+.2f}"

        # Verdict combiné
        if r["xg_avg"] and league_xg_avg:
            ratio_xg = r["xg_avg"] / league_xg_avg
            # Confirmation par xG
            if ratio > 1.15 and ratio_xg > 1.10:
                verdict = "🔥 OVER CONFIRMÉ"
            elif ratio > 1.15 and ratio_xg < 0.95:
                verdict = "⚠️  OVER FAUX"
            elif ratio < 0.85 and ratio_xg < 0.90:
                verdict = "❄️  UNDER CONFIRMÉ"
            elif ratio < 0.85 and ratio_xg > 1.05:
                verdict = "⚠️  UNDER FAUX"
            else:
                verdict = "—"
        else:
            if ratio > 1.15:
                verdict = "✅ OVER"
            elif ratio < 0.85:
                verdict = "🔵 UNDER"
            else:
                verdict = "—"

        log.info(f"{r['name'][:23]:<25} {r['played']:>3} {r['gf']:>4} {r['ga']:>4} "
                 f"{r['goals_avg']:>5.2f} {ratio:>6.2f} {xg_str:>5} {ratio_xg_str:>7} "
                 f"{overperf_str:>6} {verdict:>14}")

    log.info("")
    log.info("🔥 OVER CONFIRMÉ : buts réels ET xG au-dessus de la ligue → signal fiable")
    log.info("⚠️  OVER FAUX     : buts réels élevés MAIS xG dans la moyenne → régression probable")
    log.info("❄️  UNDER CONFIRMÉ : buts réels ET xG sous la moyenne → signal fiable")
    log.info("   Réal = buts réels/match - xG for/match (positif = surperformance attaque)")
    log.info("")


if __name__ == "__main__":
    bz = BzzoiroClient(api_key=os.environ.get("BZZOIRO_API_KEY"))
    for lid, lname in [(9, "Brésil Série A"), (10, "Eredivisie"), (1, "Premier League")]:
        analyze(bz, lid, lname)
        log.info("")
