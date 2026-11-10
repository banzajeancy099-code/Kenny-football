#!/bin/bash
# Reprend l'enrichissement si pas déjà en cours
if pgrep -f kbackfill_enrich_batch > /dev/null; then
    echo "✅ Enrichissement déjà en cours (PID $(pgrep -f kbackfill_enrich_batch))"
    exit 0
fi

cd ~/Kenny_Football_v3
export PYTHONPATH=src
source .env 2>/dev/null
export PYTHONPATH=src
termux-wake-lock
nohup python -m kbackfill_enrich_batch > logs/enrich_full.log 2>&1 &
echo "✅ Reprise auto (PID: $!)"

# Affiche la progression actuelle
sleep 2
ENRICHIS=$(python -c "
import sys; sys.path.insert(0, 'src')
import kdb
with kdb.get_conn() as conn:
    r = conn.run(\"SELECT COUNT(*) FROM k_predictions WHERE match_data->>'l2_meta' IS NOT NULL\")
    print(r[0][0])
" 2>/dev/null)
echo "📊 Matchs enrichis en DB : $ENRICHIS / 4939"
