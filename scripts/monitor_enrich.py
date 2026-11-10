"""Monitoring temps réel de l'enrichissement."""
import sys
import time
import os
sys.path.insert(0, 'src')
import kdb

def get_counts():
    with kdb.get_conn() as conn:
        r = conn.run("""
            SELECT
                COUNT(*) FILTER (WHERE match_data->>'l2_meta' IS NOT NULL) AS enrichis,
                COUNT(*) FILTER (WHERE cote_over IS NOT NULL) AS avec_cote,
                COUNT(*) AS total
            FROM k_predictions
            WHERE result_verdict IS NOT NULL AND league_id NOT IN (79, 31, 57)
        """)
        return r[0][0], r[0][1], r[0][2]

def get_last_log_lines(n=3):
    try:
        with open("logs/enrich_full.log", "r") as f:
            lines = f.readlines()
        return [l.strip() for l in lines[-n:] if l.strip()]
    except FileNotFoundError:
        return []

def is_running():
    import subprocess
    result = subprocess.run(["pgrep", "-f", "kbackfill_enrich_batch"], capture_output=True)
    return result.returncode == 0

print("=== Monitoring enrichissement (Ctrl+C pour arrêter) ===\n")

prev_enrichis = None
prev_time = None

while True:
    try:
        enrichis, avec_cote, total = get_counts()
        now = time.time()

        # Calcule le rythme
        if prev_enrichis is not None and prev_time is not None:
            delta_match = enrichis - prev_enrichis
            delta_sec = now - prev_time
            if delta_sec > 0:
                rate_per_hour = delta_match * 3600 / delta_sec
                restant = total - enrichis
                eta_hours = restant / rate_per_hour if rate_per_hour > 0 else 0
            else:
                rate_per_hour = 0
                eta_hours = 0
        else:
            rate_per_hour = 0
            eta_hours = 0

        prev_enrichis = enrichis
        prev_time = now

        os.system("clear")
        print(f"=== {time.strftime('%H:%M:%S')} ===\n")
        print(f"📊 Progression : {enrichis} / {total} ({100*enrichis/total:.1f}%)")
        print(f"💰 Avec cote   : {avec_cote}")
        print(f"⚡ Rythme      : {rate_per_hour:.0f} matchs/h")
        print(f"⏱️  ETA         : {eta_hours:.1f}h")
        print(f"🔧 Processus   : {'✅ actif' if is_running() else '⚠️ MORT'}")
        print(f"\n--- Log ---")
        for line in get_last_log_lines(3):
            print(f"  {line}")

        time.sleep(60)
    except KeyboardInterrupt:
        print("\n⏹️  Arrêt")
        break
