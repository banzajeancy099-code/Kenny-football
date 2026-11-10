"""Nettoie leagues.json : retire les ligues à petit échantillon + ajoute les nouvelles."""
import json

PATH = "config/leagues.json"
with open(PATH) as f:
    cfg = json.load(f)

# Ligues à retirer (échantillon trop petit pour être fiable)
TO_REMOVE = {70, 56, 29}

# Ligues à ajouter au tier 1 (fiables, n >= 40)
TO_ADD_TIER_1 = {
    32: {"name": "Copa Libertadores", "country": "SAM", "over_rate": 0.347, "tendance": "closed"},
}

# Nettoie les tiers
for tier_name, tier in cfg.items():
    if not isinstance(tier, dict) or "leagues" not in tier:
        continue
    original_len = len(tier["leagues"])
    tier["leagues"] = [l for l in tier["leagues"] if l["id"] not in TO_REMOVE]
    removed = original_len - len(tier["leagues"])
    if removed > 0:
        print(f"  {tier_name}: {removed} ligues retirées")

# Ajoute Copa Libertadores au tier_3_closed
if "tier_3_closed" in cfg:
    existing_ids = {l["id"] for l in cfg["tier_3_closed"]["leagues"]}
    for lid, info in TO_ADD_TIER_1.items():
        if lid not in existing_ids:
            cfg["tier_3_closed"]["leagues"].append({"id": lid, **info})
            print(f"  + Copa Libertadores (ID 32) ajoutée")

# Recalcule total
total = sum(len(t["leagues"]) for t in cfg.values() if isinstance(t, dict) and "leagues" in t)
cfg["total_active"] = total

with open(PATH, "w") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)

print(f"\n✅ {total} ligues actives après nettoyage")
