#!/usr/bin/env python3
"""scripts/calibration_check.py — Diagnostic calibration + edge + Brier score"""
import os
import sys
import json
import glob
import logging
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("calib")


def load_archived_predictions():
    rows = []
    archive_dir = Path("data/archive")
    if not archive_dir.exists():
        log.warning(f"⚠️  {archive_dir} introuvable")
        return rows
    files = sorted(glob.glob(str(archive_dir / "*.json")))
    log.info(f"📂 {len(files)} fichiers d'archive trouvés")
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            matches = data.get("matches", {})
            for mid, pred in matches.items():
                if not pred.get("result_verdict"):
                    continue
                rows.append(pred)
        except Exception as e:
            log.debug(f"skip {fp}: {e}")
    return rows


def load_neon_predictions():
    rows = []
    try:
        from src.db import load_predictions
        from datetime import date, timedelta
        for i in range(30):
            d = date.today() - timedelta(days=i)
            try:
                data = load_predictions(d)
                for mid, pred in (data.get("matches") or {}).items():
                    if pred.get("result_verdict"):
                        rows.append(pred)
            except Exception:
                pass
    except Exception as e:
        log.debug(f"Neon indisponible : {e}")
    return rows


def dedupe(rows):
    seen = {}
    for r in rows:
        mid = r.get("match_id") or f"{r.get('home')}|{r.get('away')}"
        seen[mid] = r
    return list(seen.values())


def calibration_table(rows, proba_key="proba_over", verdict_key="result_verdict"):
    buckets = defaultdict(lambda: {"n": 0, "pred_sum": 0.0, "hits": 0})
    for r in rows:
        proba = r.get(proba_key)
        verdict = r.get(verdict_key)
        if proba is None or verdict is None:
            continue
        hit = 1 if verdict == "✓" else 0
        b = int(proba * 100) // 5 * 5
        b = min(b, 95)
        buckets[b]["n"] += 1
        buckets[b]["pred_sum"] += proba
        buckets[b]["hits"] += hit
    return buckets


def print_calibration(buckets):
    log.info("\n" + "=" * 78)
    log.info("📊 TABLE DE CALIBRATION (Over 2.5)")
    log.info("=" * 78)
    log.info(f"{'Tranche':<12} {'N':>5} {'Proba moy':>11} {'Réel':>8} {'Écart':>8} {'Statut':>10}")
    log.info("-" * 78)
    total_n = 0
    weighted_err = 0.0
    for b in sorted(buckets.keys()):
        stats = buckets[b]
        n = stats["n"]
        if n < 5:
            continue
        pred_avg = stats["pred_sum"] / n
        real = stats["hits"] / n
        err = real - pred_avg
        abs_err = abs(err)
        if abs_err < 0.05:
            status = "OK"
        elif abs_err < 0.10:
            status = "Leger"
        else:
            status = "BRISEE"
        log.info(
            f"{b:>3}-{b+5:<3}%     {n:>5} {pred_avg*100:>10.1f}% "
            f"{real*100:>7.1f}% {err*100:>+7.1f}% {status:>10}"
        )
        weighted_err += abs_err * n
        total_n += n
    log.info("-" * 78)
    if total_n > 0:
        mean_abs_err = weighted_err / total_n
        log.info(f"Erreur de calibration moyenne (pondérée) : {mean_abs_err*100:.2f}%")
        if mean_abs_err < 0.05:
            log.info("✅ Calibration BONNE — Kelly utilisable")
        elif mean_abs_err < 0.08:
            log.info("⚠️  Calibration MOYENNE — corriger avant réel")
        else:
            log.info("❌ Calibration BRISÉE — NE PAS miser en réel")
        log.info(f"Total matchs analysés : {total_n}")
    else:
        log.info("⚠️  Pas assez de données (N < 5 par tranche)")


def edge_vs_market(rows):
    log.info("\n" + "=" * 78)
    log.info("💰 EDGE VS MARCHÉ")
    log.info("=" * 78)
    edges_bz = []
    edges_pin = []
    for r in rows:
        proba = r.get("proba_over")
        if proba is None:
            continue
        cote_bz = r.get("cote_over")
        cote_pin = r.get("cote_pinnacle_over")
        if cote_bz and cote_bz > 1.01:
            edges_bz.append(proba * cote_bz - 1)
        if cote_pin and cote_pin > 1.01:
            edges_pin.append(proba * cote_pin - 1)

    def _report(name, edges, threshold=0.03):
        if not edges:
            log.info(f"{name:<20} : aucune donnée")
            return
        avg = sum(edges) / len(edges)
        win = sum(1 for e in edges if e > threshold)
        log.info(
            f"{name:<20} : N={len(edges):>4}  "
            f"Edge moyen={avg*100:>+6.2f}%  "
            f"Edge > {threshold*100:.0f}% : {win}/{len(edges)} ({win/len(edges)*100:.0f}%)"
        )
        if avg < 0.02:
            log.info(f"  ❌ Edge trop faible (<2%) — pas exploitable")
        elif avg < 0.05:
            log.info(f"  ⚠️  Edge marginal (2-5%) — risqué")
        else:
            log.info(f"  ✅ Edge intéressant (>5%)")

    _report("Bzzoiro", edges_bz)
    _report("Pinnacle", edges_pin)


def brier_score(rows):
    log.info("\n" + "=" * 78)
    log.info("📐 BRIER SCORE (Over 2.5)")
    log.info("=" * 78)
    sq_errs = []
    for r in rows:
        proba = r.get("proba_over")
        verdict = r.get("result_verdict")
        if proba is None or verdict is None:
            continue
        outcome = 1.0 if verdict == "✓" else 0.0
        sq_errs.append((proba - outcome) ** 2)
    if not sq_errs:
        log.info("Aucune donnée")
        return
    bs = sum(sq_errs) / len(sq_errs)
    log.info(f"Brier score : {bs:.4f}  (N={len(sq_errs)})")
    if bs < 0.20:
        log.info("✅ Bon (< 0.20)")
    elif bs < 0.24:
        log.info("⚠️  Moyen (0.20-0.24) — proche du hasard (0.25)")
    else:
        log.info("❌ Mauvais (≥ 0.24) — pas meilleur que le hasard")


def signal_breakdown(rows):
    log.info("\n" + "=" * 78)
    log.info("🎯 RÉSULTATS PAR SIGNAL")
    log.info("=" * 78)
    by_signal = defaultdict(lambda: {"n": 0, "wins": 0, "proba_sum": 0.0})
    for r in rows:
        sig = r.get("signal_strength") or "unknown"
        verdict = r.get("result_verdict")
        if verdict is None:
            continue
        by_signal[sig]["n"] += 1
        by_signal[sig]["wins"] += 1 if verdict == "✓" else 0
        by_signal[sig]["proba_sum"] += r.get("proba_over") or 0.0
    for sig in ["strong", "medium", "weak", "rejected", "unknown"]:
        stats = by_signal.get(sig)
        if not stats or stats["n"] == 0:
            continue
        n = stats["n"]
        acc = stats["wins"] / n
        proba_avg = stats["proba_sum"] / n
        log.info(
            f"{sig:<12} : N={n:>4}  Accuracy={acc*100:>5.1f}%  "
            f"Proba moy={proba_avg*100:>5.1f}%"
        )


def main():
    log.info("🔬 Diagnostic calibration moteur Kenny Football")
    log.info("")
    rows_archive = load_archived_predictions()
    log.info(f"   -> {len(rows_archive)} predictions archivees")
    rows_neon = load_neon_predictions()
    log.info(f"   -> {len(rows_neon)} predictions Neon")
    rows = dedupe(rows_archive + rows_neon)
    log.info(f"   -> {len(rows)} predictions uniques apres dedoublonnage")
    if len(rows) < 10:
        log.error("\n❌ Pas assez de donnees pour diagnostiquer (N < 10)")
        log.error("   Attends d'avoir plus de paris resolus.")
        return
    buckets = calibration_table(rows)
    print_calibration(buckets)
    edge_vs_market(rows)
    brier_score(rows)
    signal_breakdown(rows)
    log.info("\n" + "=" * 78)
    log.info("✅ Diagnostic termine")
    log.info("=" * 78)


if __name__ == "__main__":
    main()
