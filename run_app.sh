#!/data/data/com.termux/files/usr/bin/bash
cd ~/football-engine
source .env
pkill -9 python 2>/dev/null
sleep 1
python app.py
