"""
Kenny Football v3.0 — Stats par ligue (toutes les ligues détectées).

Analyse les 58 ligues présentes dans k_predictions :
- Nombre de matchs
- Taux Over réel
- Taux Under réel
- Nombre avec cotes
- Over_rate calibré

Usage :
    PYTHONPATH=src python -m kstats_ligues
    PYTHONPATH=src python -m kstats_ligues --min-matches 20
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import kdb


LEAGUES_PATH = Path(__file__).parent.parent / "config" / "leagues.json"


def _load_league_names() -> dict:
    """Charge les noms de ligues depuis leagues.json."""
    try:
        with open(LEAGUES_PATH) as f:
            cfg = json.load(f)
    except Exception:
        return {}

    names = {}
    for tier_name, tier in cfg.items():
        if not isinstance(tier, dict) or "leagues" not in tier:
            continue
        for l in tier["leagues"]:
            names[l["id"]] = l.get("name", f"Ligue {l['id']}")
    return names


def _fetch_stats(min_matches: int = 10) -> list:
    """Récupère les stats par ligue."""
    sql = """
        SELECT
            league_id,
            COUNT(*) AS n,
            COUNT(*) FILTER (WHERE result_verdict = '✓') AS over,
            COUNT(*) FILTER (WHERE result_verdict = '×') AS under,
            COUNT(*) FILTER (WHERE cote_over IS NOT NULL) AS avec_cote,
            COUNT(*) FILTER (WHERE match_data->>'l2_meta' IS NOT NULL) AS enrichis,
            COUNT(*) FILTER (WHERE match_data->>'signal' = 'strong') AS strong,
            ROUND(AVG(score)::numeric, 2) AS score_moy
        FROM k_predictions
        WHERE result_verdict IS NOT NULL
          AND league_id IS NOT NULL
          AND league_id NOT IN (79, 31, 57)
        GROUP BY league_id
        HAVING COUNT(*) >= :min_matches
        ORDER BY n DESC
    """
    with kdb.get_conn() as conn:
        rows = conn.run(sql, min_matches=min_matches)
        cols = [c["name"] for c in conn.columns]
    return [dict(zip(cols, r)) for r in rows]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--min-matches", type=int, default=10)
    p.add_argument("--sort", choices=["over", "n", "roi"], default="over")
    args = p.parse_args()

    names = _load_league_names()
    stats = _fetch_stats(min_matches=args.min_matches)

    print(f"=== {len(stats)} ligues avec >= {args.min_matches} matchs ===\n")

    # Trie
    if args.sort == "over":
        stats.sort(key=lambda x: (x["over"] or 0) / max(x["n"], 1), reverse=True)
    elif args.sort == "n":
        stats.sort(key=lambda x: x["n"], reverse=True)
    elif args.sort == "roi":
        def roi(x):
            if not x["avec_cote"] or not x["score_moy"]:
                return -999
            # Approximation : (over_rate * cote_moy - 1) — cote_moy supposée 1.60
            over_rate = (x["over"] or 0) / max(x["n"], 1)
            return over_rate * 1.60 - 1
        stats.sort(key=roi, reverse=True)

    # En-tête
    print(f"{'ID':>4} | {'Ligue':<30} | {'N':>4} | {'Over':>5} | {'Under':>5} | {'Taux':>6} | {'Cotes':>5} | {'Strong':>6} | {'Enrichis':>8}")
    print("-" * 110)

    total_over = 0
    total_under = 0
    total_n = 0

    for s in stats:
        lid = s["league_id"]
        name = names.get(lid, f"Ligue {lid}")[:30]
        n = s["n"]
        over = s["over"] or 0
        under = s["under"] or 0
        taux = (over / n * 100) if n > 0 else 0
        avec_cote = s["avec_cote"] or 0
        strong = s["strong"] or 0
        enrichis = s["enrichis"] or 0

        total_over += over
        total_under += under
        total_n += n

        print(f"{lid:>4} | {name:<30} | {n:>4} | {over:>5} | {under:>5} | {taux:>5.1f}% | {avec_cote:>5} | {strong:>6} | {enrichis:>8}")

    print("-" * 110)
    total_taux = (total_over / total_n * 100) if total_n > 0 else 0
    print(f"{'':>4} | {'TOTAL':<30} | {total_n:>4} | {total_over:>5} | {total_under:>5} | {total_taux:>5.1f}%")

    # Résumé par catégorie
    print()
    print("=== Résumé ===")

    offensives = [s for s in stats if (s["over"] or 0) / max(s["n"], 1) >= 0.58]
    fermees = [s for s in stats if (s["over"] or 0) / max(s["n"], 1) <= 0.42]
    neutres = [s for s in stats if s not in offensives and s not in fermees]

    print(f"  Offensives (Over >= 58%) : {len(offensives)} ligues")
    for s in offensives[:5]:
        name = names.get(s["league_id"], f"Ligue {s['league_id']}")
        taux = (s["over"] or 0) / max(s["n"], 1) * 100
        print(f"    {s['league_id']:>3} {name:<30} {taux:.1f}% ({s['n']} matchs)")

    print(f"\n  Fermées (Over <= 42%) : {len(fermees)} ligues")
    for s in fermees[:5]:
        name = names.get(s["league_id"], f"Ligue {s['league_id']}")
        taux = (s["over"] or 0) / max(s["n"], 1) * 100
        print(f"    {s['league_id']:>3} {name:<30} {taux:.1f}% ({s['n']} matchs)")

    print(f"\n  Neutres (42-58%) : {len(neutres)} ligues")


if __name__ == "__main__":
    main()
