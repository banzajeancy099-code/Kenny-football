"""
Kenny Football v3.0 — Job de vérification des résultats.

Vérifie les scores des matchs J-1 et marque result_verdict.
Appelé par /api/resultats/<date> (Render).

Usage :
    python -m jobs.kjob_verif
    python -m jobs.kjob_verif 2026-11-10
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta

import kdb
from api.kbzzoiro import KBzzoiro


def verifier_resultats(date_str: str = None):
    """Récupère les résultats réels et marque les prédictions."""

    if date_str is None:
        yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
        date_str = yesterday.isoformat()

    print(f"=== Vérification du {date_str} ===", flush=True)

    # Récupère les prédictions en attente
    try:
        predictions = kdb.kload_predictions(date_str)
    except Exception as e:
        print(f"❌ Load KO : {e}", flush=True)
        return

    pending = [p for p in predictions if not p.get("result_verdict")]
    print(f"{len(pending)} prédictions à vérifier", flush=True)

    if not pending:
        print("✅ Rien à vérifier", flush=True)
        return

    # Récupère les matchs réels via Bzzoiro
    bzz = KBzzoiro()
    try:
        events = bzz.get_matches_today(date_str)
    except Exception as e:
        print(f"❌ Bzzoiro KO : {e}", flush=True)
        return

    scores = {str(e.get("id")): (e.get("home_score"), e.get("away_score")) for e in events}

    won = 0
    lost = 0

    for p in pending:
        mid = str(p.get("match_id"))
        if mid not in scores:
            continue

        home_score, away_score = scores[mid]
        if home_score is None or away_score is None:
            continue

        total_goals = home_score + away_score
        real_over = total_goals > 2.5

        # Détermine le marché prédit
        market = (p.get("match_data") or {}).get("market")
        if market == "over":
            verdict = "✓" if real_over else "×"
        elif market == "under":
            verdict = "✓" if not real_over else "×"
        else:
            continue

        try:
            with kdb.get_conn() as conn:
                conn.run(
                    "UPDATE k_predictions SET result_verdict = :v WHERE match_id = :mid AND date = :date",
                    v=verdict, mid=mid, date=date_str,
                )
            if verdict == "✓":
                won += 1
            else:
                lost += 1
            print(f"  {mid} : {home_score}-{away_score} → {verdict}", flush=True)
        except Exception as e:
            print(f"  {mid} KO : {e}", flush=True)

    print(f"\n✅ {won} gagnés, {lost} perdus", flush=True)


if __name__ == "__main__":
    date = sys.argv[1] if len(sys.argv) > 1 else None
    verifier_resultats(date)
