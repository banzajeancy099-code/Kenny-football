"""Supprime les doublons dans leagues.json (garde le premier tier où l'ID apparaît)."""
import json

PATH = "config/leagues.json"
with open(PATH) as f:
    cfg = json.load(f)

seen_ids = set()
removed_total = 0

for tier_name, tier in cfg.items():
    if not isinstance(tier, dict) or "leagues" not in tier:
        continue
    cleaned = []
    removed = 0
    for l in tier["leagues"]:
        lid = l["id"]
        if lid in seen_ids:
            removed += 1
            removed_total += 1
            print(f"  Doublon retiré : {tier_name} (ID {lid} = {l.get('name', '?')})")
        else:
            seen_ids.add(lid)
            cleaned.append(l)
    tier["leagues"] = cleaned

cfg["total_active"] = len(seen_ids)

with open(PATH, "w") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)

print(f"\n✅ {removed_total} doublons retirés")
print(f"✅ {len(seen_ids)} ligues uniques restantes")
