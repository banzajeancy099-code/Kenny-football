"""Recalibre leagues.json avec les vrais over_rate (hors amicaux)."""
import json
import kdb

# Ligues à exclure (amicaux, USL, etc.)
EXCLUDED = {79, 31, 57}

PATH = "config/leagues.json"
with open(PATH) as f:
    cfg = json.load(f)

print("=== Calcul des vrais over_rate ===")

sql = """
    SELECT
        league_id,
        COUNT(*) FILTER (WHERE result_verdict = '✓') AS over,
        COUNT(*) AS total
    FROM k_predictions
    WHERE result_verdict IS NOT NULL
      AND league_id IS NOT NULL
    GROUP BY league_id
    HAVING COUNT(*) >= 20
    ORDER BY total DESC
"""
with kdb.get_conn() as conn:
    rows = conn.run(sql)
    cols = [c["name"] for c in conn.columns]

real_rates = {}
for r in rows:
    d = dict(zip(cols, r))
    lid = d["league_id"]
    if lid in EXCLUDED:
        continue
    total = d["total"]
    over = d["over"]
    real_rates[lid] = {
        "n": total,
        "over": over,
        "taux": round(over / total, 4),
    }
    print(f"  Ligue {lid:>4}: {over}/{total} = {over/total*100:.1f}%")

print(f"\n{len(real_rates)} ligues recalibrées")

# Met à jour leagues.json
updated = 0
for tier_name, tier in cfg.items():
    if not isinstance(tier, dict) or "leagues" not in tier:
        continue
    for l in tier["leagues"]:
        lid = l["id"]
        if lid in real_rates:
            old = l.get("over_rate", 0.5)
            new = real_rates[lid]["taux"]
            l["over_rate_estimated"] = old
            l["over_rate"] = new
            l["n_matches"] = real_rates[lid]["n"]
            l["over_rate_source"] = "calibrated_real"
            # Reclassifie
            if new >= 0.55:
                l["tendance"] = "offensive"
            elif new <= 0.45:
                l["tendance"] = "closed"
            else:
                l["tendance"] = "neutral"
            updated += 1
            print(f"  Ligue {lid}: {old:.3f} → {new:.3f} ({l['tendance']})")

with open(PATH, "w") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)

print(f"\n✅ {updated} ligues mises à jour dans leagues.json")
