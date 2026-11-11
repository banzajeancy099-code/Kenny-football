"""
Kenny Football v3.0 — Serveur Flask + Dashboard.

Routes :
  GET  /                      → dashboard HTML
  GET  /api/predictions       → paris du jour (k_predictions)
  GET  /api/archive           → historique 30 jours
  GET  /api/match/<id>        → détail match
  GET  /api/match-lineup/<id> → lineups (stub)
  GET  /api/health            → status DB
  GET  /api/stats             → stats globales
  POST /api/analyze/start     → lancer analyse (stub)
  GET  /api/resultats/<date>  → vérifier résultats (stub)

Usage :
    PYTHONPATH=src python kapp.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request

# Ajoute src/ au PYTHONPATH
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR / "src"))

import kdb


app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)


# ================================================================== #
#  Helpers
# ================================================================== #
def _today_str() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _db_ok() -> bool:
    try:
        with kdb.get_conn() as conn:
            conn.run("SELECT 1")
        return True
    except Exception:
        return False


# ================================================================== #
#  Dashboard
# ================================================================== #
@app.route("/")
def index():
    return render_template("kdashboard.html")


# ================================================================== #
#  API — Paris du jour
# ================================================================== #
@app.route("/api/predictions")
def api_predictions():
    date = request.args.get("date", _today_str())
    try:
        matches = kdb.kload_predictions(date)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # Enrichit avec match_data
    enriched = []
    for m in matches:
        md = m.get("match_data") or {}
        if isinstance(md, str):
            import json as _json
            try:
                md = _json.loads(md)
            except Exception:
                md = {}

        home = m.get("home_team_name") or md.get("home_team_name") or md.get("home")
        away = m.get("away_team_name") or md.get("away_team_name") or md.get("away")
        kickoff = m.get("kickoff") or md.get("kickoff") or md.get("event_date")

        sig = m.get("signal_strength") or md.get("signal")
        market = md.get("market")
        edge = md.get("edge")

        mise_val = m.get("mise_kelly")
        if mise_val is None:
            mise_val = 10.0 if sig == "strong" else (5.0 if sig == "medium" else 0.0)
        else:
            mise_val = float(mise_val)

        enriched.append({
            "match_id": m.get("match_id"),
            "league_id": m.get("league_id"),
            "league_name": m.get("league_name") or md.get("league_name"),
            "home": home,
            "away": away,
            "home_team_id": m.get("home_team_id"),
            "away_team_id": m.get("away_team_id"),
            "kickoff": kickoff,
            "score": m.get("score") or md.get("score"),
            "confidence": m.get("confidence"),
            "proba_over": m.get("proba_over") or md.get("proba_over"),
            "proba_under": m.get("proba_under") or md.get("proba_under"),
            "cote_over": float(m.get("cote_over") or 0) or None,
            "cote_under": float(m.get("cote_under") or 0) or None,
            "edge": edge,
            "signal": sig,
            "market": market,
            "mise": mise_val,
            "result_verdict": m.get("result_verdict"),
        })

    # ─────────────────────────────────────────
    # SÉLECTION PARIS DU JOUR (top 10 par edge)
    # ─────────────────────────────────────────
    TOP_N = 10
    EDGE_MIN = 0.08

    # Filtre sur le marché réel (over ou under)
    def _cote_for_market(m):
        market = m.get("market") or "over"
        return m.get("cote_under") if market == "under" else m.get("cote_over")
    
    eligible = [
        m for m in enriched
        if m["signal"] == "strong"
        and m["edge"] is not None
        and m["edge"] >= EDGE_MIN
        and _cote_for_market(m) is not None
        and 1.40 <= (_cote_for_market(m) or 0) <= 2.30
    ]

    # Trie par edge décroissant
    eligible.sort(key=lambda m: m["edge"] or 0, reverse=True)

    # Top 10
    paris_du_jour = eligible[:TOP_N]
    pj_ids = {m["match_id"] for m in paris_du_jour}

    # Confiance moyenne = les autres matchs (strong hors top, medium, etc.)
    confiance_moyenne = [
        m for m in enriched
        if m["match_id"] not in pj_ids
        and m["signal"] in ("strong", "medium")
        and m["result_verdict"] is None
    ]

    # Historique = uniquement les matchs avec verdict (J-1 et avant)
    corrects = [m for m in enriched if m["result_verdict"] == "✓"]
    rates = [m for m in enriched if m["result_verdict"] == "×"]
    rejetes = [m for m in enriched if m["signal"] == "rejected"]

    return jsonify({
        "date": date,
        "paris_du_jour": paris_du_jour,
        "confiance_moyenne": confiance_moyenne,
        "corrects": corrects,
        "rates": rates,
        "rejetes": rejetes,
        "n_paris_du_jour": len(paris_du_jour),
        "n_eligible": len(eligible),
    })

@app.route("/api/archive")
def api_archive():
    limit = request.args.get("limit", 30, type=int)
    try:
        with kdb.get_conn() as conn:
            rows = conn.run("""
                SELECT DISTINCT date::text AS date
                FROM k_predictions
                WHERE result_verdict IS NOT NULL
                GROUP BY date
                ORDER BY date DESC
                LIMIT :limit
            """, limit=limit)
            dates = [r[0] for r in rows]
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    days = []
    for date_str in dates:
        try:
            with kdb.get_conn() as conn:
                rows = conn.run("""
                    SELECT match_id, home_team_name AS home, away_team_name AS away,
                           league_id, league_name,
                           score, cote_over, cote_under,
                           mise_kelly, 0 AS mise_under,
                           result_verdict, match_data
                    FROM k_predictions
                    WHERE date = :date AND result_verdict IS NOT NULL
                    ORDER BY kickoff
                """, date=date_str)
                cols = [c["name"] for c in conn.columns]
                matches = [dict(zip(cols, r)) for r in rows]
        except Exception as e:
            matches = []

        # Formate les matchs
        formatted = []
        for m in matches:
            md = m.get("match_data") or {}
            if isinstance(md, str):
                import json as _json
                try:
                    md = _json.loads(md)
                except Exception:
                    md = {}
            score_val = m["score"] or md.get("score")
            sig = md.get("signal") or "unknown"
            market = md.get("market")
            
            # Calcule la mise
            mise_val = m["mise_kelly"]
            if mise_val is None:
                mise_val = 10.0 if sig == "strong" else (5.0 if sig == "medium" else 0.0)
            else:
                mise_val = float(mise_val)

            formatted.append({
                "match_id": str(m["match_id"]),
                "home": m["home"],
                "away": m["away"],
                "league_id": m["league_id"],
                "league_name": m["league_name"],
                "score": float(score_val) if score_val else None,
                "cote_over": float(m["cote_over"]) if m["cote_over"] else None,
                "cote_under": float(m["cote_under"]) if m["cote_under"] else None,
                "mise_kelly": mise_val if market == "over" else 0,
                "mise_under": mise_val if market == "under" else 0,
                "signal": sig,
                "market": market,
                "result_verdict": m["result_verdict"],
            })

        correct = sum(1 for m in formatted if m["result_verdict"] == "✓")
        wrong = sum(1 for m in formatted if m["result_verdict"] == "×")

        days.append({
            "date": date_str,
            "correct": correct,
            "wrong": wrong,
            "total": len(formatted),
            "won": correct,
            "lost": wrong,
            "n_matchs": len(formatted),
            "matches": formatted,
        })

    return jsonify({"days": days})


# ================================================================== #
#  API — Détail match
# ================================================================== #
@app.route("/api/match/<match_id>")
def api_match(match_id):
    try:
        with kdb.get_conn() as conn:
            rows = conn.run("""
                SELECT match_id, date, league_id, league_name,
                       home_team_id, home_team_name,
                       away_team_id, away_team_name,
                       kickoff, score, confidence,
                       proba_over, proba_under,
                       cote_over, cote_under,
                       edge_over, edge_under,
                       signal_strength, mise_kelly, match_data, result_verdict
                FROM k_predictions
                WHERE match_id = :mid
                LIMIT 1
            """, mid=str(match_id))
            cols = [c["name"] for c in conn.columns]
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if not rows:
        return jsonify({"error": "Match non trouvé"}), 404

    m = dict(zip(cols, rows[0]))
    md = m.get("match_data") or {}
    if isinstance(md, str):
        import json
        try:
            md = json.loads(md)
        except Exception:
            md = {}

    # Enrichit avec les infos de match_data
    m["market"] = md.get("market")
    m["signal"] = m.get("signal_strength") or md.get("signal")
    m["l2_meta"] = md.get("l2_meta")
    m["h2h_avg_goals"] = md.get("h2h_avg_goals")
    m["form_home_gf"] = md.get("form_home_gf")
    m["form_away_gf"] = md.get("form_away_gf")

    return jsonify(m)


# ================================================================== #
#  API — Lineups (stub, car PitchAPI désactivé)
# ================================================================== #
@app.route("/api/match-lineup/<match_id>")
def api_match_lineup(match_id):
    return jsonify({
        "match_id": match_id,
        "lineups": None,
        "message": "PitchAPI désactivé (données non disponibles)",
    })


# ================================================================== #
#  API — Health
# ================================================================== #
@app.route("/api/health")
def api_health():
    db_ok = _db_ok()
    return jsonify({
        "status": "ok" if db_ok else "degraded",
        "db": "ok" if db_ok else "ko",
        "time": datetime.now(timezone.utc).isoformat(),
        "version": "3.0",
    })


# ================================================================== #
#  API — Stats globales
# ================================================================== #
@app.route("/api/stats")
def api_stats():
    try:
        with kdb.get_conn() as conn:
            r = conn.run("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE result_verdict = '✓') AS won,
                    COUNT(*) FILTER (WHERE result_verdict = '×') AS lost,
                    COUNT(*) FILTER (WHERE result_verdict IS NULL) AS pending,
                    COUNT(*) FILTER (WHERE match_data->>'l2_meta' IS NOT NULL) AS enrichis
                FROM k_predictions
            """)
            row = r[0]
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    total, won, lost, pending, enrichis = row
    settled = (won or 0) + (lost or 0)
    taux = round(100 * won / settled, 1) if settled else 0

    return jsonify({
        "total": total,
        "won": won,
        "lost": lost,
        "pending": pending,
        "enrichis": enrichis,
        "taux_reussite": taux,
    })


# ================================================================== #
#  API — Analyze (stub)
# ================================================================== #
@app.route("/api/analyze/start", methods=["POST"])
def api_analyze_start():
    try:
        from jobs.kjob_analyse import analyse_du_jour
        matches = analyse_du_jour()
        return jsonify({
            "status": "ok",
            "n_matchs": len(matches),
            "matchs": [{"home": m["home_team_name"], "away": m["away_team_name"]} for m in matches],
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ================================================================== #
#  API — Vérifier résultats (stub)
# ================================================================== #
@app.route("/api/resultats/<date>")
def api_resultats(date):
    try:
        from jobs.kjob_verif import verifier_resultats
        verifier_resultats(date)
        return jsonify({"status": "ok", "date": date})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ================================================================== #
#  Main
# ================================================================== #
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    print(f"[kapp] Démarrage sur le port {port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
