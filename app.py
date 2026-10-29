# app.py — Kenny Football v1.3.1
# Flask + APScheduler + async jobs + pré-filtre + JSON + archive dynamique
import os
import sys
import json
import uuid
import logging
import threading
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from flask import Flask, render_template, jsonify, request
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import atexit
import yaml

from src.clients.bzzoiro import BzzoiroClient
from src.clients.api_football import APIFootballClient
from src.orchestrator import MatchPipeline, prefilter

# ========== LOGGER ==========
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("kenny-football")

# ========== FLASK ==========
app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0


@app.after_request
def add_no_cache_headers(response):
    if response.mimetype == "text/html":
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# ========== CONFIG ==========
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

with open(BASE_DIR / "config" / "settings.yaml", "r", encoding="utf-8") as f:
    SETTINGS = yaml.safe_load(f)
with open(BASE_DIR / "config" / "weights.json", "r", encoding="utf-8") as f:
    WEIGHTS = json.load(f)


def _build_league_over_rates(settings):
    raw = settings.get("leagues", {})
    out = {}
    if isinstance(raw, dict):
        for _name, cfg in raw.items():
            if isinstance(cfg, dict) and "id" in cfg:
                out[str(cfg["id"])] = float(cfg.get("over_rate", 0.5))
            elif isinstance(cfg, (int, float)):
                out[str(_name)] = float(cfg)
    elif isinstance(raw, list):
        for cfg in raw:
            if isinstance(cfg, dict) and "id" in cfg:
                out[str(cfg["id"])] = float(cfg.get("over_rate", 0.5))
    return out


LEAGUE_OVER_RATES = _build_league_over_rates(SETTINGS)
log.info(f"📊 league_over_rates: {LEAGUE_OVER_RATES}")

# ========== CLIENTS ==========
BZZOIRO_KEY = os.environ.get("BZZOIRO_API_KEY")
if not BZZOIRO_KEY:
    log.error("❌ BZZOIRO_API_KEY manquante")
    sys.exit(1)
bzzoiro = BzzoiroClient(api_key=BZZOIRO_KEY)

api_football = None
if os.environ.get("API_FOOTBALL_KEY"):
    api_football = APIFootballClient(api_key=os.environ["API_FOOTBALL_KEY"])
    log.info("✅ API-Football activé")
else:
    log.warning("⚠️  API-Football désactivé")

pipeline = MatchPipeline(
    bzzoiro=bzzoiro,
    api_football=api_football,
    weights=WEIGHTS,
    league_over_rates=LEAGUE_OVER_RATES,
)


# ========== STOCKAGE JSON ==========
def _pred_file(d=None):
    d = d or date.today()
    return DATA_DIR / f"predictions_{d.isoformat()}.json"


def load_predictions(d=None):
    f = _pred_file(d)
    if not f.exists():
        return {"date": (d or date.today()).isoformat(), "last_update": None, "matches": {}}
    try:
        with open(f, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as e:
        log.warning(f"Erreur lecture {f}: {e}")
        return {"date": (d or date.today()).isoformat(), "last_update": None, "matches": {}}


def save_predictions(data, d=None):
    f = _pred_file(d)
    tmp = f.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, default=str)
    tmp.replace(f)


# ========== JOB QUEUE ==========
ANALYSIS_JOBS = {}
JOBS_LOCK = threading.Lock()


def _run_analysis_job(job_id, matches):
    try:
        with JOBS_LOCK:
            ANALYSIS_JOBS[job_id] = {
                "status": "running", "total": len(matches), "done": 0,
                "retenus": 0, "started_at": datetime.now().isoformat(),
            }
        today = date.today()
        data = load_predictions(today)
        data["matches"] = {}
        data["last_update"] = datetime.now().isoformat()

        for i, m in enumerate(matches):
            try:
                result = pipeline.run(m)
                mid = str(result.get("match_id") or m.get("id"))
                data["matches"][mid] = result
                if result.get("retenu") or (result.get("mise_kelly") or 0) > 0 or (result.get("mise_under") or 0) > 0:
                    with JOBS_LOCK:
                        ANALYSIS_JOBS[job_id]["retenus"] += 1
            except Exception as e:
                log.warning(f"[JOB {job_id}] match {m.get('id')} : {e}")
            with JOBS_LOCK:
                ANALYSIS_JOBS[job_id]["done"] = i + 1
                done = ANALYSIS_JOBS[job_id]["done"]
            if done % 10 == 0:
                save_predictions(data, today)

        save_predictions(data, today)
        with JOBS_LOCK:
            ANALYSIS_JOBS[job_id]["status"] = "done"
            ANALYSIS_JOBS[job_id]["finished_at"] = datetime.now().isoformat()
            retenus = ANALYSIS_JOBS[job_id]["retenus"]
        log.info(f"✅ [JOB {job_id}] {len(matches)} matchs, {retenus} retenus")
    except Exception as e:
        with JOBS_LOCK:
            ANALYSIS_JOBS[job_id]["status"] = "error"
            ANALYSIS_JOBS[job_id]["error"] = str(e)
        log.error(f"❌ [JOB {job_id}] {e}", exc_info=True)


# ========== JOBS CRON ==========
def job_analyse_quotidienne():
    log.info("🕛 [CRON] Analyse initiale quotidienne")
    try:
        today = date.today()
        all_matches = bzzoiro.get_matches_today(today.isoformat())
        matches = [m for m in all_matches if prefilter(m)]
        log.info(f"[CRON] {len(all_matches)} → {len(matches)} après pré-filtre")
        if not matches:
            log.warning("[CRON] Aucun match après pré-filtre")
            return
        job_id = "cron_" + today.isoformat()
        _run_analysis_job(job_id, matches)
    except Exception as e:
        log.error(f"❌ [CRON] Analyse échouée : {e}", exc_info=True)


def job_refresh_cotes():
    now = datetime.now()
    if now.hour >= 3:
        return
    log.info(f"🔄 [CRON] Refresh cotes {now.strftime('%H:%M')}")
    try:
        today = date.today()
        data = load_predictions(today)
        if not data.get("matches"):
            return
        changed = 0
        for mid, pred in list(data["matches"].items()):
            try:
                odds = bzzoiro.get_event_odds(mid)
                new_cote = _extract_over_odd(odds)
                if new_cote is None:
                    continue
                old_cote = pred.get("cote_over")
                if old_cote and abs(new_cote - old_cote) / old_cote > 0.05:
                    pred["cote_over"] = new_cote
                    proba = pred.get("proba_over", 0)
                    edge = proba * new_cote - 1
                    pred["edge"] = round(edge, 3)
                    mise = 0
                    if edge >= 0.10 and pred.get("score", 0) >= 5.2:
                        mise = min(round(1000 * edge * 0.05, 2), 30.0)
                    pred["mise_kelly"] = mise
                    if pred.get("score", 0) < 5.2:
                        pred["retenu"] = False
                    changed += 1
            except Exception as e:
                log.debug(f"[CRON] refresh {mid}: {e}")
        data["last_update"] = now.isoformat()
        save_predictions(data, today)
        log.info(f"✅ [CRON] Refresh : {changed} modifiés")
    except Exception as e:
        log.error(f"❌ [CRON] Refresh échoué : {e}", exc_info=True)


def _verifier_match(pred, event_id):
    try:
        event = bzzoiro.request("GET", f"/events/{event_id}/")
        data = event.get("results") if isinstance(event, dict) and "results" in event else event
        if isinstance(data, list) and data:
            data = data[0]
        if not isinstance(data, dict):
            return None
        status = str(data.get("status") or "").lower()
        if status not in ("finished", "ft", "aet", "pen"):
            return None
        hs = data.get("home_score")
        as_ = data.get("away_score")
        if hs is None or as_ is None:
            return None
        total = int(hs) + int(as_)
        over_real = total >= 3
        proba = pred.get("proba_over", 0.5)
        pred_over = proba >= 0.5
        verdict = "✓" if pred_over == over_real else "×"
        return {
            "home_score": int(hs), "away_score": int(as_),
            "total_goals": total, "over_2_5_real": over_real,
            "predicted_over": pred_over, "proba": proba,
            "verdict": verdict, "verified_at": datetime.now().isoformat(),
        }
    except Exception as e:
        log.debug(f"[VERIF] match {event_id}: {e}")
        return None


def _verifier_jour(target):
    try:
        data = load_predictions(target)
        matches_dict = data.get("matches") or {}
        if not isinstance(matches_dict, dict):
            return
        if not matches_dict:
            return
        verified = correct = wrong = pending = 0
        for mid, pred in matches_dict.items():
            if not isinstance(pred, dict):
                continue
            if pred.get("result"):
                verified += 1
                if pred["result"].get("verdict") == "✓":
                    correct += 1
                elif pred["result"].get("verdict") == "×":
                    wrong += 1
                continue
            try:
                eid = int(mid)
            except (ValueError, TypeError):
                continue
            res = _verifier_match(pred, eid)
            if res:
                pred["result"] = res
                verified += 1
                if res["verdict"] == "✓":
                    correct += 1
                elif res["verdict"] == "×":
                    wrong += 1
            else:
                pending += 1
        data["last_update"] = datetime.now().isoformat()
        data["verification_summary"] = {
            "date": target.isoformat(), "verified": verified,
            "correct": correct, "wrong": wrong, "pending": pending,
            "accuracy": round(correct / verified, 3) if verified else 0,
            "verified_at": datetime.now().isoformat(),
        }
        save_predictions(data, target)
        log.info(f"✅ [VERIF {target}] {verified} · {correct}✓ / {wrong}× · {pending} attente")
    except Exception as e:
        log.error(f"❌ [VERIF {target}] {e}", exc_info=True)


def job_verifier_resultats(d=None):
    if d is None:
        for delta in (0, 1):
            _verifier_jour(date.today() - timedelta(days=delta))
        return
    _verifier_jour(d)


def _extract_over_odd(odds_json):
    try:
        markets = odds_json.get("odds") or odds_json.get("markets") or []
        if isinstance(markets, dict):
            markets = markets.get("markets", [])
        for m in markets:
            if not isinstance(m, dict):
                continue
            name = (m.get("name") or m.get("market") or "").lower()
            if "over" in name and "2.5" in name:
                return float(m.get("odd") or m.get("price") or m.get("value"))
        for bk in odds_json.get("bookmakers", []):
            for bet in bk.get("bets", []):
                n = (bet.get("name") or "").lower()
                if "over" in n and "2.5" in n:
                    for v in bet.get("values", []):
                        if "over" in (v.get("value") or "").lower():
                            return float(v.get("odd"))
        return None
    except Exception:
        return None


# ========== SCHEDULER ==========
scheduler = BackgroundScheduler(timezone="Europe/Zurich")
scheduler.add_job(job_analyse_quotidienne, CronTrigger(hour=0, minute=0),
                  id="analyse_quotidienne", replace_existing=True, misfire_grace_time=3600)
scheduler.add_job(job_refresh_cotes, IntervalTrigger(minutes=30),
                  id="refresh_cotes", replace_existing=True, misfire_grace_time=600)
scheduler.add_job(job_verifier_resultats, IntervalTrigger(hours=1),
                  id="verification_resultats", replace_existing=True, misfire_grace_time=1800)

if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown())
    log.info("⏰ Scheduler démarré (00h analyse + 30min refresh + 1h vérif)")


# ========== ROUTES ==========
@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok", "version": "1.4.0", "layers": len(pipeline.layers),
        "api_football": "enabled" if api_football else "disabled",
        "scheduler": "running" if scheduler.running else "stopped",
        "jobs": [j.id for j in scheduler.get_jobs()] if scheduler.running else [],
        "active_jobs": sum(1 for j in ANALYSIS_JOBS.values() if j.get("status") == "running"),
    })


@app.route("/api/prefilter/preview")
def prefilter_preview():
    try:
        today = date.today().isoformat()
        all_m = bzzoiro.get_matches_today(today)
        filtered = [m for m in all_m if prefilter(m)]
        return jsonify({
            "success": True, "date": today,
            "total_bzzoiro": len(all_m), "after_prefilter": len(filtered),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/analyze/start", methods=["POST", "GET"])
def analyze_start():
    try:
        limit = int(request.args.get("limit", 200))
        today = date.today().isoformat()
        all_m = bzzoiro.get_matches_today(today)
        filtered = [m for m in all_m if prefilter(m)][:limit]
        if not filtered:
            return jsonify({"success": False, "error": "Aucun match après pré-filtre",
                            "total_bzzoiro": len(all_m)}), 200
        job_id = str(uuid.uuid4())[:8]
        ANALYSIS_JOBS[job_id] = {"status": "queued", "total": len(filtered)}
        t = threading.Thread(target=_run_analysis_job, args=(job_id, filtered), daemon=True)
        t.start()
        return jsonify({
            "success": True, "job_id": job_id,
            "total_bzzoiro": len(all_m), "filtered": len(filtered),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/analyze/status/<job_id>")
def analyze_status(job_id):
    with JOBS_LOCK:
        job = ANALYSIS_JOBS.get(job_id)
        if not job:
            return jsonify({"success": False, "error": "job inconnu"}), 404
        return jsonify({"success": True, "job_id": job_id, **job})


@app.route("/api/analyze")
def analyze_sync():
    try:
        today = date.today().isoformat()
        all_m = bzzoiro.get_matches_today(today)
        filtered = [m for m in all_m if prefilter(m)][:20]
        results = []
        for m in filtered:
            try:
                results.append(pipeline.run(m))
            except Exception as e:
                log.warning(f"Erreur match {m.get('id')}: {e}")
        retenus = [r for r in results if r.get("retenu")]
        rejetes = [r for r in results if not r.get("retenu")]
        return jsonify({"success": True, "date": today, "total": len(results),
                        "retenus": retenus, "rejetes": rejetes,
                        "total_bzzoiro": len(all_m), "filtered": len(filtered)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/predictions")
def predictions_today():
    """Renvoie les prédictions ACTIVES (matchs pas encore terminés)."""
    today = date.today()
    data = load_predictions(today)
    matches_dict = data.get("matches") or {}
    if not isinstance(matches_dict, dict):
        matches_dict = {}
    matches = list(matches_dict.values())

    now = datetime.now(timezone.utc)
    active = []
    for m in matches:
        if not isinstance(m, dict):
            continue
        if m.get("result"):
            continue
        ko = m.get("kickoff")
        if ko:
            try:
                ko_dt = datetime.fromisoformat(ko.replace("Z", "+00:00"))
                if (now - ko_dt).total_seconds() > 2.5 * 3600:
                    continue
            except Exception:
                pass
        active.append(m)

    retenus_count = sum(
        1 for m in active
        if m.get("retenu") or (m.get("mise_kelly") or 0) > 0 or (m.get("mise_under") or 0) > 0
    )
    return jsonify({
        "date": today.isoformat(),
        "is_today": True,
        "last_update": data.get("last_update"),
        "total": len(active),
        "retenus": retenus_count,
        "matches": active,
    })


@app.route("/api/predictions/filtered")
def predictions_filtered():
    kind = request.args.get("kind", "all")
    today = date.today()
    data = load_predictions(today)
    matches_dict = data.get("matches") or {}
    if not isinstance(matches_dict, dict):
        matches_dict = {}
    matches = list(matches_dict.values())

    now = datetime.now(timezone.utc)
    active = []
    for m in matches:
        if not isinstance(m, dict):
            continue
        if m.get("result"):
            continue
        ko = m.get("kickoff")
        if ko:
            try:
                ko_dt = datetime.fromisoformat(ko.replace("Z", "+00:00"))
                if (now - ko_dt).total_seconds() > 2.5 * 3600:
                    continue
            except Exception:
                pass
        active.append(m)

    if kind == "over":
        active = [m for m in active if not m.get("is_under_bet")]
    elif kind == "under":
        active = [m for m in active if m.get("is_under_bet")]

    return jsonify({
        "date": today.isoformat(), "kind": kind,
        "total": len(active), "matches": active,
    })


@app.route("/api/predictions/<date_str>")
def predictions_by_date(date_str):
    try:
        d = date.fromisoformat(date_str)
        data = load_predictions(d)
        matches_dict = data.get("matches") or {}
        if not isinstance(matches_dict, dict):
            matches_dict = {}
        matches = list(matches_dict.values())
        return jsonify({"date": data.get("date"), "last_update": data.get("last_update"),
                        "total": len(matches),
                        "retenus": sum(1 for m in matches if isinstance(m, dict) and (
                            m.get("retenu") or (m.get("mise_kelly") or 0) > 0 or (m.get("mise_under") or 0) > 0)),
                        "matches": matches})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/archive")
def archive():
    """Liste des jours avec AU MOINS UN match terminé."""
    files = sorted(DATA_DIR.glob("predictions_*.json"), reverse=True)
    out = []
    for f in files:
        try:
            d_str = f.stem.replace("predictions_", "")
            d_obj = date.fromisoformat(d_str)
            data = load_predictions(d_obj)
            matches_dict = data.get("matches") or {}
            if not isinstance(matches_dict, dict):
                continue
            matches = list(matches_dict.values())
            finished = [m for m in matches if isinstance(m, dict) and m.get("result")]
            if not finished:
                continue
            over = [m for m in finished if not m.get("is_under_bet")]
            under = [m for m in finished if m.get("is_under_bet")]
            correct = sum(1 for m in finished if m.get("result", {}).get("verdict") == "✓")
            wrong = sum(1 for m in finished if m.get("result", {}).get("verdict") == "×")
            out.append({
                "date": d_str,
                "last_update": data.get("last_update"),
                "total": len(finished),
                "over_count": len(over),
                "under_count": len(under),
                "verified": correct + wrong,
                "correct": correct,
                "wrong": wrong,
                "accuracy": round(correct / (correct + wrong), 3) if (correct + wrong) else None,
            })
        except Exception:
            pass
    return jsonify({"archive": out, "total_days": len(out)})


@app.route("/api/stats")
def stats_globales():
    files = sorted(DATA_DIR.glob("predictions_*.json"), reverse=True)
    tv = tc = tw = 0
    by_day = []
    for f in files:
        try:
            d_str = f.stem.replace("predictions_", "")
            data = load_predictions(date.fromisoformat(d_str))
            matches_dict = data.get("matches") or {}
            if not isinstance(matches_dict, dict):
                continue
            matches = matches_dict
            correct = sum(1 for m in matches.values() if isinstance(m, dict) and m.get("result", {}).get("verdict") == "✓")
            wrong = sum(1 for m in matches.values() if isinstance(m, dict) and m.get("result", {}).get("verdict") == "×")
            verified = correct + wrong
            if verified > 0 or len(matches) > 0:
                by_day.append({
                    "date": d_str, "total": len(matches), "verified": verified,
                    "correct": correct, "wrong": wrong,
                    "accuracy": round(correct / verified, 3) if verified else None,
                })
                tv += verified
                tc += correct
                tw += wrong
        except Exception:
            pass
    return jsonify({
        "total_verified": tv, "total_correct": tc, "total_wrong": tw,
        "accuracy": round(tc / tv, 3) if tv else None,
        "by_day": by_day,
    })


@app.route("/api/resultats/<date_str>", methods=["POST", "GET"])
def verifier_resultats(date_str):
    try:
        d = date.fromisoformat(date_str)
        job_verifier_resultats(d)
        data = load_predictions(d)
        return jsonify({"success": True, "date": date_str,
                        "summary": data.get("verification_summary", {})})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/cron/status")
def cron_status():
    jobs = []
    if scheduler.running:
        for j in scheduler.get_jobs():
            jobs.append({"id": j.id,
                         "next_run": j.next_run_time.isoformat() if j.next_run_time else None,
                         "trigger": str(j.trigger)})
    today_data = load_predictions()
    matches_dict = today_data.get("matches") or {}
    if not isinstance(matches_dict, dict):
        matches_dict = {}
    matches = list(matches_dict.values())
    return jsonify({"scheduler_running": scheduler.running, "jobs": jobs,
                    "active_analysis_jobs": [
                        {"job_id": k, **v} for k, v in ANALYSIS_JOBS.items()
                        if v.get("status") in ("running", "queued")
                    ],
                    "today": {"date": today_data.get("date"),
                              "last_update": today_data.get("last_update"),
                              "total_matches": len(matches),
                              "retenus": sum(1 for m in matches if isinstance(m, dict) and (
                                  m.get("retenu") or (m.get("mise_kelly") or 0) > 0 or (m.get("mise_under") or 0) > 0))}})


@app.route("/api/cron/trigger/<job_id>", methods=["POST", "GET"])
def cron_trigger(job_id):
    if job_id == "analyse":
        t = threading.Thread(target=job_analyse_quotidienne, daemon=True)
        t.start()
        return jsonify({"success": True, "job": "analyse"})
    if job_id == "refresh":
        job_refresh_cotes()
        return jsonify({"success": True, "job": "refresh"})
    if job_id == "verif":
        d = request.args.get("date")
        target = date.fromisoformat(d) if d else None
        t = threading.Thread(target=job_verifier_resultats, args=(target,), daemon=True)
        t.start()
        return jsonify({"success": True, "job": "verif"})
    return jsonify({"success": False, "error": "unknown job"}), 404


# ========== MAIN ==========
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    log.info(f"🚀 Kenny Football v1.3.1 sur http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
