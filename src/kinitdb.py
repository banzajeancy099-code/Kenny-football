"""
Kenny Football v3.0 — Initialisation du schéma DB (Neon / PostgreSQL).

Crée (idempotent, IF NOT EXISTS) :
  - predictions         : prédictions quotidiennes
  - odds_snapshots      : snapshots cotes (Pinnacle, CLV)
  - bets_log            : tracking pari par pari (CLV, ROI, reliability)
  - layer_performance   : feedback loop par couche (L1..L48)
  - team_matches        : cache local Bzzoiro (15 derniers matchs / équipe)

Usage :
    python -m src.kinitdb
"""

from __future__ import annotations

import os

import pg8000.native


DDL = """
CREATE TABLE IF NOT EXISTS k_predictions (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    match_id TEXT NOT NULL,
    league_id INTEGER,
    league_name TEXT,
    home_team_id INTEGER,
    home_team_name TEXT,
    away_team_id INTEGER,
    away_team_name TEXT,
    kickoff TIMESTAMPTZ,
    score NUMERIC,
    confidence NUMERIC,
    proba_over NUMERIC,
    proba_under NUMERIC,
    cote_over NUMERIC,
    cote_under NUMERIC,
    edge_over NUMERIC,
    edge_under NUMERIC,
    signal_strength TEXT,
    mise_kelly NUMERIC,
    match_data JSONB,
    result_verdict TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (date, match_id)
);

CREATE TABLE IF NOT EXISTS k_odds_snapshots (
    id SERIAL PRIMARY KEY,
    match_id TEXT NOT NULL,
    bookmaker TEXT NOT NULL,
    market TEXT NOT NULL,
    line NUMERIC,
    price NUMERIC,
    snapshot_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_odds_match ON k_odds_snapshots(match_id, snapshot_at DESC);

CREATE TABLE IF NOT EXISTS k_bets_log (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    match_id TEXT NOT NULL,
    market TEXT NOT NULL,
    home_team TEXT,
    away_team TEXT,
    league_id INTEGER,
    score_final NUMERIC,
    proba_predite NUMERIC,
    cote_prise NUMERIC,
    cote_cloture NUMERIC,
    edge NUMERIC,
    signal TEXT,
    mise NUMERIC,
    resultat TEXT DEFAULT 'pending',
    clv NUMERIC,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    settled_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_bets_date ON k_bets_log(date DESC);
CREATE INDEX IF NOT EXISTS idx_bets_signal ON k_bets_log(signal, resultat);

CREATE TABLE IF NOT EXISTS k_layer_performance (
    id SERIAL PRIMARY KEY,
    layer_id INTEGER NOT NULL,
    match_id TEXT NOT NULL,
    date DATE NOT NULL,
    score NUMERIC,
    confidence NUMERIC,
    rejected BOOLEAN DEFAULT FALSE,
    league_id INTEGER,
    match_type TEXT,
    result_verdict TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_layer_perf ON k_layer_performance(layer_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_layer_perf_league ON k_layer_performance(layer_id, league_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_layer_perf_type ON k_layer_performance(layer_id, match_type, date DESC);

CREATE TABLE IF NOT EXISTS k_team_matches (
    id SERIAL PRIMARY KEY,
    team_id INTEGER NOT NULL,
    match_id TEXT NOT NULL,
    date DATE NOT NULL,
    competition_type TEXT,
    opponent_id INTEGER,
    goals_for INTEGER,
    goals_against INTEGER,
    result TEXT,
    days_since_last_match INTEGER,
    late_goals_for INTEGER DEFAULT 0,
    late_goals_against INTEGER DEFAULT 0,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (team_id, match_id)
);
CREATE INDEX IF NOT EXISTS idx_team_matches ON k_team_matches(team_id, date DESC);
"""


def kinit_db(conn=None) -> None:
    own_conn = conn is None
    if own_conn:
        from urllib.parse import urlparse
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL manquante dans l'environnement")
        u = urlparse(url)
        conn = pg8000.native.Connection(
            user=u.username,
            password=u.password,
            host=u.hostname,
            database=(u.path or "/").lstrip("/"),
            port=u.port or 5432,
            ssl_context=True,
        )
    try:
        for statement in DDL.split(";"):
            stmt = statement.strip()
            if stmt and not stmt.startswith("--"):
                conn.run(stmt)
    finally:
        if own_conn:
            conn.close()


if __name__ == "__main__":
    kinit_db()
    print("✓ Schéma Kenny v3.0 initialisé.")
