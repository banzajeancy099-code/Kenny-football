"""
Kenny Football v3.0 — Calibration des over_rate par ligue.

Parcourt k_team_matches, dédoublonne les matchs, calcule le taux d'Over 2.5
réel par ligue (matchs avec total_goals > 2.5 / total).

Sortie : config/leagues.json enrichi avec over_rate réels + tendance.

Usage :
    PYTHONPATH=src python -m kalibrate_leagues
"""

from __future__ import annotations

import json
from pathlib import Path

import kdb


LEAGUES_PATH = Path(__file__).parent.parent / "config" / "leagues.json"

# Shrinkage bayésien
SHRINKAGE_K = 10           # Force de la croyance a priori
PRIOR_OVER_RATE = 0.52     # Moyenne globale (ligue neutre)
MIN_SAMPLES_RELIABLE = 15  # Seuil de fiabilité pour classifier
OVER_RATE_MIN = 0.30       # Plancher anti-absurde
OVER_RATE_MAX = 0.75       # Plafond anti-absurde



def _load_leagues() -> dict:
    with open(LEAGUES_PATH) as f:
        return json.load(f)


def _all_league_ids(cfg: dict) -> set:
    ids = set()
    for tier in cfg.values():
        if isinstance(tier, dict) and "leagues" in tier:
            for l in tier["leagues"]:
                ids.add(l["id"])
    return ids


def _compute_over_rates() -> dict:
    """
    Pour chaque league_id, retourne :
      {"n_matches": int, "n_over": int, "over_rate": float}
    """
    # On dédoublonne via match_id (chaque match est en base 2 fois, 1 par équipe)
    sql = """
        WITH unique_matches AS (
            SELECT DISTINCT ON (match_id)
                match_id,
                date,
                -- league_id n'est pas stocké dans k_team_matches, on va l'inférer
                -- via k_predictions.match_data->>'league_id' plus tard
                -- ou on utilise une autre approche
                NULL::integer AS league_id
            FROM k_team_matches
        )
        SELECT 1
    """
    # NOTE : k_team_matches ne stocke pas league_id.
    # Solution : croiser avec k_predictions pour récupérer league_id par match_id.

    sql = """
        SELECT
            (p.match_data->>'league_id')::int AS league_id,
            COUNT(*) AS n_matches,
            SUM(
                CASE WHEN (
                    (p.match_data->>'home_score')::int +
                    (p.match_data->>'away_score')::int
                ) > 2 THEN 1 ELSE 0 END
            ) AS n_over
        FROM k_predictions p
        WHERE p.result_verdict IS NOT NULL
          AND p.match_data->>'home_score' IS NOT NULL
          AND p.match_data->>'away_score' IS NOT NULL
          AND p.match_data->>'league_id' IS NOT NULL
        GROUP BY (p.match_data->>'league_id')::int
    """
    with kdb.get_conn() as conn:
        rows = conn.run(sql)
        cols = [c["name"] for c in conn.columns]

    out = {}
    for r in rows:
        row = dict(zip(cols, r))
        lid = row["league_id"]
        n = row["n_matches"] or 0
        n_over = row["n_over"] or 0
        out[lid] = {
            "n_matches": n,
            "n_over": n_over,
            "over_rate": round(n_over / n, 4) if n > 0 else None,
        }
    return out


def _compute_over_rates_from_team_matches() -> dict:
    """
    Alternative : calcule over_rate depuis k_team_matches (sans league_id direct).
    On utilise les matchs où home_team_id < away_team_id pour ne compter qu'une fois.
    Mais league_id reste absent.

    → On NE PEUT PAS calculer par ligue sans league_id.
    → On retourne un dict vide, à améliorer plus tard avec un mapping team→league.
    """
    return {}


def _apply_shrinkage(over_rate: float, n: int) -> float:
    """Mélange over_rate observé avec prior global, pondéré par n."""
    if n <= 0:
        return PRIOR_OVER_RATE
    shrunk = (n * over_rate + SHRINKAGE_K * PRIOR_OVER_RATE) / (n + SHRINKAGE_K)
    # Bornes anti-absurde
    return max(OVER_RATE_MIN, min(OVER_RATE_MAX, shrunk))


def _classify(over_rate: float | None, n: int = 0) -> str:
    if over_rate is None:
        return "unknown"
    if n < MIN_SAMPLES_RELIABLE:
        return "unknown"  # pas assez de données pour classifier
    if over_rate >= 0.55:
        return "offensive"
    if over_rate <= 0.45:
        return "closed"
    return "neutral"


def _apply_calibration(cfg: dict, over_rates: dict) -> dict:
    updated = 0
    reliable = 0
    for tier_name, tier in cfg.items():
        if not isinstance(tier, dict) or "leagues" not in tier:
            continue
        for l in tier["leagues"]:
            lid = l["id"]
            if lid in over_rates and over_rates[lid]["over_rate"] is not None:
                raw = over_rates[lid]["over_rate"]
                n = over_rates[lid]["n_matches"]
                shrunk = _apply_shrinkage(raw, n)

                l["over_rate_estimated"] = l.get("over_rate")
                l["over_rate_raw"] = round(raw, 4)
                l["over_rate"] = round(shrunk, 4)
                l["over_rate_source"] = "calibrated"
                l["n_matches_observed"] = n
                l["shrinkage_applied"] = True
                l["tendance"] = _classify(shrunk, n)
                updated += 1
                if n >= MIN_SAMPLES_RELIABLE:
                    reliable += 1
            else:
                if "tendance" not in l:
                    l["tendance"] = "unknown"
    cfg["calibration"] = {
        "leagues_calibrated": updated,
        "leagues_reliable": reliable,
        "leagues_total": sum(
            len(t["leagues"]) for t in cfg.values()
            if isinstance(t, dict) and "leagues" in t
        ),
        "shrinkage_k": SHRINKAGE_K,
        "prior_over_rate": PRIOR_OVER_RATE,
        "min_samples_reliable": MIN_SAMPLES_RELIABLE,
    }
    return cfg


def main():
    cfg = _load_leagues()
    print(f"Chargement : {sum(len(t['leagues']) for t in cfg.values() if isinstance(t, dict) and 'leagues' in t)} ligues")

    print("Calcul des over_rate réels depuis k_predictions...")
    over_rates = _compute_over_rates()
    print(f"  → {len(over_rates)} ligues avec historique")

    print("Application de la calibration...")
    cfg = _apply_calibration(cfg, over_rates)

    with open(LEAGUES_PATH, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

    print(f"✓ Calibration terminée")
    print(f"  Ligues calibrées : {cfg['calibration']['leagues_calibrated']}")
    print(f"  Ligues totales   : {cfg['calibration']['leagues_total']}")

    # Affiche le résumé
    for tier_name, tier in cfg.items():
        if not isinstance(tier, dict) or "leagues" not in tier:
            continue
        print(f"\n{tier_name} :")
        for l in tier["leagues"]:
            src = l.get("over_rate_source", "estimated")
            tend = l.get("tendance", "?")
            rate = l.get("over_rate", "?")
            n = l.get("n_matches_observed", "-")
            print(f"  ID {l['id']:>4} | {l['name']:<30} | {rate} | {tend:<10} | n={n} ({src})")


if __name__ == "__main__":
    main()
