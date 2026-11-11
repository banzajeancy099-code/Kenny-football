"""
Audit calibration v2 — utilise expected_goals L2 (pas le score écrasé).
Compare Poisson P(Over 2.5) vs réel sur les prédictions résolues.
"""
import os, sys, math, psycopg2, psycopg2.extras
from collections import defaultdict

conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

# 1. Toutes les lignes avec expected_goals
cur.execute("""
    SELECT 
        (match_data->'l2_meta'->>'expected_goals')::float AS eg,
        proba_over,
        cote_over,
        result_verdict
    FROM k_predictions
    WHERE result_verdict IN ('✓','×')
      AND cote_over IS NOT NULL
      AND match_data->'l2_meta'->>'expected_goals' IS NOT NULL
""")
rows = cur.fetchall()
print(f"Lignes exploitables (avec expected_goals) : {len(rows)}\n")

if not rows:
    print("❌ Aucune ligne — vérifie la structure match_data")
    sys.exit(0)

# 2. Calibration par tranche de expected_goals
print("=" * 70)
print("CALIBRATION : expected_goals → P(Over 2.5) Poisson vs réel")
print("=" * 70)
buckets = defaultdict(lambda: {"n":0,"wins":0,"poisson_sum":0,"proba_sum":0,"roi":0,"stake":0})

for r in rows:
    eg = r["eg"]
    b = round(eg * 2) / 2   # arrondi à 0.5
    p0 = math.exp(-eg)
    p_over_poisson = 1 - p0 * (1 + eg + eg**2 / 2)
    
    buckets[b]["n"] += 1
    buckets[b]["poisson_sum"] += p_over_poisson
    if r["proba_over"]:
        buckets[b]["proba_sum"] += float(r["proba_over"])
    buckets[b]["stake"] += 10
    
    won = r["result_verdict"] == "✓"
    cote = float(r["cote_over"])
    if won:
        buckets[b]["wins"] += 1
        buckets[b]["roi"] += 10 * (cote - 1)
    else:
        buckets[b]["roi"] -= 10

print(f"{'EG':>5} | {'N':>4} | {'Poisson':>8} | {'proba_old':>9} | {'Réel':>6} | {'Écart':>7} | {'ROI%':>6} |")
print("-" * 75)
for b in sorted(buckets.keys()):
    d = buckets[b]
    if d["n"] < 5: continue
    poisson_moy = d["poisson_sum"] / d["n"]
    proba_old = (d["proba_sum"] / d["n"]) if d["proba_sum"] else 0
    win_reel = d["wins"] / d["n"]
    ecart = win_reel - poisson_moy
    roi = 100 * d["roi"] / d["stake"] if d["stake"] else 0
    flag = "✅" if abs(ecart) < 0.05 else "⚠️"
    print(f"{b:>5.1f} | {d['n']:>4} | {poisson_moy:>7.1%} | {proba_old:>8.1%} | {win_reel:>5.1%} | {ecart:>+6.1%} {flag} | {roi:>+5.1f}%")

# 3. Global
total_n = sum(d["n"] for d in buckets.values() if d["n"] >= 5)
total_wins = sum(d["wins"] for d in buckets.values() if d["n"] >= 5)
total_poisson = sum(d["poisson_sum"] for d in buckets.values() if d["n"] >= 5)
total_roi = sum(d["roi"] for d in buckets.values() if d["n"] >= 5)
total_stake = sum(d["stake"] for d in buckets.values() if d["n"] >= 5)

print("\n" + "=" * 70)
print("GLOBAL")
print("=" * 70)
if total_n:
    print(f"N={total_n}, win_reel={total_wins/total_n:.1%}, poisson_moy={total_poisson/total_n:.1%}, ROI={100*total_roi/total_stake:+.1f}%")

# 4. Top 10 meilleurs / pires matchs (par ROI)
cur.execute("""
    SELECT 
        home_team_name, away_team_name,
        (match_data->'l2_meta'->>'expected_goals')::float AS eg,
        proba_over, cote_over, result_verdict
    FROM k_predictions
    WHERE result_verdict IN ('✓','×')
      AND cote_over IS NOT NULL
      AND match_data->'l2_meta'->>'expected_goals' IS NOT NULL
      AND proba_over > 0.60
    ORDER BY (CASE WHEN result_verdict='✓' THEN 1 ELSE 0 END) DESC, cote_over DESC
    LIMIT 5
""")
print("\n=== TOP 5 pronostics forts (proba > 60%) ===")
for r in cur.fetchall():
    won = "✅" if r["result_verdict"] == "✓" else "❌"
    print(f"  {won} {r['home_team_name']} vs {r['away_team_name']} : EG={r['eg']:.2f}, proba={float(r['proba_over']):.1%}, cote={float(r['cote_over']):.2f}")

conn.close()
