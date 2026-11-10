# Kenny Football v3.0

Moteur de prédiction Over/Under 2.5 basé sur 6 couches d'analyse.

## Architecture

- L1 (Strength) : force globale équipes
- L2 (Over) : score Over 2.5
- L31 (Negatives) : signaux négatifs (VETO)
- L35 (Red Flags) : red flags (VETO)
- L47 (Under) : score Under 2.5
- L49 (Signal Strength) : agrégation

## Filtres

- Ligues Over (18, 17, 14, 54, 25, 19) -> parier Over
- Ligues Under (34, 85, 89, 23, 53, 32) -> parier Under
- Cote [1.40, 1.80]
- Signal strong

## Backtest (2738 matchs)

- Taux : 82,4 %
- ROI : +29,58 %
- P&L : +775,10 EUR (10EUR/pari)

## Deploiement

### Render

1. Push sur GitHub
2. Connecter Render au repo
3. Configurer DATABASE_URL (Neon)
4. Deployer

### Local (Termux)

cd ~/Kenny_Football_v3
source .env
export PYTHONPATH=src
python kapp.py

## Routes API

- GET / -> Dashboard
- GET /api/predictions?date=YYYY-MM-DD -> Paris du jour
- GET /api/archive?limit=30 -> Historique
- GET /api/match/<id> -> Detail match
- GET /api/health -> Status
- GET /api/stats -> Stats globales

## Structure

Kenny_Football_v3/
  kapp.py              # Flask + dashboard
  config/
    leagues.json       # 37 ligues
  src/
    kengine.py         # Orchestrateur
    kdb.py             # DB access
    kkelly.py          # Kelly
    api/               # Clients API
    layers/            # Couches L1-L49
    jobs/              # Jobs cron
  scripts/             # Scripts backfill
  templates/
    kdashboard.html    # Dashboard
