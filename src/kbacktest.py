"""
Backtest Kenny v3.0 — analyse complète des matchs enrichis.

Filtres appliqués :
- signal = strong
- ligues typées (Over sur LEAGUES_OVER, Under sur LEAGUES_UNDER)
- cote [1.40, 1.80]
- market correct (Over pour LEAGUES_OVER, Under pour LEAGUES_UNDER)

Simulation :
- 10 € par pari
- P&L net, ROI, taux de réussite
- Détail par ligue

Usage :
    PYTHONPATH=src python -m kbacktest
"""
from __future__ import annotations
import math
import kdb


# Ligues importées depuis kengine (source unique de vérité)
from kengine import LEAGUES_OVER, LEAGUES_UNDER


def _load_matches():
    """Charge tous les matchs enrichis avec signal."""
    sql = """
        SELECT
            match_id, date, league_id, score, confidence,
            proba_over, cote_over, cote_under, result_verdict,
            match_data->>'total_goals' AS total_goals,
            match_data->>'l2_meta' AS l2_meta,
            match_data->>'signal' AS signal,
            match_data->>'market' AS market,
            match_data->>'edge' AS edge
        FROM k_predictions
        WHERE result_verdict IS NOT NULL
          AND (match_data->>'l2_meta') IS NOT NULL
        ORDER BY date DESC
    """
    with kdb.get_conn() as conn:
        rows = conn.run(sql)
        cols = [c["name"] for c in conn.columns]
    return [dict(zip(cols, r)) for r in rows]


def _brier(preds, acts):
    if not preds:
        return None
    return sum((p - a) ** 2 for p, a in zip(preds, acts)) / len(preds)


def _logloss(preds, acts):
    if not preds:
        return None
    eps = 1e-15
    total = 0.0
    for p, a in zip(preds, acts):
        p = max(eps, min(1 - eps, p))
        total -= a * math.log(p) + (1 - a) * math.log(1 - p)
    return total / len(preds)


def _auc(preds, acts):
    pairs = sorted(zip(preds, acts), key=lambda x: -x[0])
    if not pairs:
        return None
    n_pos = sum(a for _, a in pairs)
    n_neg = len(pairs) - n_pos
    if n_pos == 0 or n_neg == 0:
        return None
    tp = fp = 0
    auc = 0.0
    for _, a in pairs:
        if a == 1:
            tp += 1
        else:
            fp += 1
            auc += tp
    return auc / (n_pos * n_neg)


def _simulate(paris, label):
    """Simule 10€/pari sur une liste de paris."""
    if not paris:
        print(f"  {label} : Aucun pari")
        return 0, 0, 0.0, 0.0

    n = len(paris)
    won = 0
    pnl = 0.0
    total_stake = 0.0

    for m in paris:
        cote = float(m["cote"])
        stake = 10.0
        total_stake += stake
        won_bet = m["won"]
        if won_bet:
            pnl += stake * (cote - 1)
            won += 1
        else:
            pnl -= stake

    taux = 100 * won / n
    roi = 100 * pnl / total_stake

    print(f"  {label} :")
    print(f"    Paris    : {n}")
    print(f"    Gagnés   : {won} ({taux:.1f} %)")
    print(f"    Cote moy : {sum(float(m['cote']) for m in paris)/n:.2f}")
    print(f"    P&L net  : {pnl:+.2f} €")
    print(f"    ROI      : {roi:+.2f} %")
    return n, won, pnl, roi


def main():
    print("=== BACKTEST KENNY v3.0 ===\n")
    matches = _load_matches()
    n = len(matches)
    print(f"Matchs enrichis : {n}\n")

    if n == 0:
        print("⚠️ Aucun match enrichi")
        return

    # ─────────────────────────────────────────
    # 1. Résultats bruts
    # ─────────────────────────────────────────
    over_total = sum(1 for m in matches if m["result_verdict"] == "✓")
    under_total = sum(1 for m in matches if m["result_verdict"] == "×")
    print(f"=== Résultats bruts (sur {n} matchs enrichis) ===")
    print(f"  Over (✓)  : {over_total} ({100*over_total/n:.1f} %)")
    print(f"  Under (×) : {under_total} ({100*under_total/n:.1f} %)")

    # ─────────────────────────────────────────
    # 2. Distribution des signaux
    # ─────────────────────────────────────────
    print(f"\n=== Distribution des signaux ===")
    signals = {}
    for m in matches:
        sig = m["signal"] or "unknown"
        signals[sig] = signals.get(sig, 0) + 1
    for sig, count in sorted(signals.items(), key=lambda x: -x[1]):
        print(f"  {sig:<20} : {count}")

    # ─────────────────────────────────────────
    # 3. Filtres
    # ─────────────────────────────────────────
    paris_all = []
    paris_over = []
    paris_under = []
    by_league = {}

    for m in matches:
        if m["signal"] != "strong":
            continue
        if not m["market"] or not m["cote_over"]:
            continue

        league_id = m["league_id"]
        market = m["market"]

        # Cote correspondante
        if market == "over":
            cote = m["cote_over"]
            won = m["result_verdict"] == "✓"
        elif market == "under":
            cote = m["cote_under"]
            won = m["result_verdict"] == "×"
        else:
            continue

        if cote is None:
            continue
        cote = float(cote)
        if not (1.40 <= cote <= 1.80):
            continue

        # Filtre ligues typées
        if league_id in LEAGUES_OVER and market != "over":
            continue
        if league_id in LEAGUES_UNDER and market != "under":
            continue
        if league_id not in LEAGUES_OVER and league_id not in LEAGUES_UNDER:
            continue

        pari = {"match": m, "cote": cote, "won": won, "market": market}
        paris_all.append(pari)
        if market == "over":
            paris_over.append(pari)
        else:
            paris_under.append(pari)

        by_league.setdefault(league_id, []).append(pari)

    # ─────────────────────────────────────────
    # 4. Simulation
    # ─────────────────────────────────────────
    print(f"\n=== Simulation (10 €/pari, strong + ligues typées + cote [1.40, 1.80]) ===")
    n_all, won_all, pnl_all, roi_all = _simulate(paris_all, "TOTAL")
    print()
    _simulate(paris_over, "OVER (ligues offensives)")
    print()
    _simulate(paris_under, "UNDER (ligues fermées)")

    # ─────────────────────────────────────────
    # 5. Détail par ligue
    # ─────────────────────────────────────────
    print(f"\n=== Détail par ligue ===")
    print(f"{'Ligue':>6} {'N':>4} {'Taux':>7} {'Cote':>6} {'P&L':>10} {'ROI':>8}")
    print("-" * 50)

    for league_id in sorted(by_league.keys()):
        paris = by_league[league_id]
        if len(paris) < 5:
            continue
        n_l = len(paris)
        won_l = sum(1 for p in paris if p["won"])
        taux_l = 100 * won_l / n_l
        cote_l = sum(float(p["cote"]) for p in paris) / n_l
        pnl_l = sum(10 * (float(p["cote"]) - 1) if p["won"] else -10 for p in paris)
        roi_l = 100 * pnl_l / (10 * n_l)
        print(f"{league_id:>6} {n_l:>4} {taux_l:>6.1f}% {cote_l:>6.2f} {pnl_l:>+9.2f}€ {roi_l:>+7.2f}%")

    # ─────────────────────────────────────────
    # 6. Métriques de calibration
    # ─────────────────────────────────────────
    print(f"\n=== Calibration (Brier, LogLoss, AUC) ===")
    valid = [m for m in matches if m["l2_meta"] and m["proba_over"]]
    if valid:
        preds = [float(m["proba_over"]) for m in valid]
        acts = [1 if m["result_verdict"] == "✓" else 0 for m in valid]
        print(f"  Échantillon : {len(valid)}")
        print(f"  Brier score : {_brier(preds, acts):.4f} (0.25 = hasard)")
        print(f"  Log loss    : {_logloss(preds, acts):.4f} (0.693 = hasard)")
        print(f"  AUC         : {_auc(preds, acts):.4f} (0.5 = hasard)")
    else:
        print("  ⚠️ Pas assez de matchs avec proba_over")


if __name__ == "__main__":
    main()
