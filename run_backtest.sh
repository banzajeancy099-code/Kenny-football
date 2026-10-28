#!/data/data/com.termux/files/usr/bin/bash
cd ~/football-engine
source .env
python scripts/backtest.py "$@"
