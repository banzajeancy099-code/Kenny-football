"""
Kenny Football v3.0 — Couche d'accès DB.

Sections :
  - Connexion (get_conn)
  - Prédictions (ksave_predictions, kload_predictions, kget_archive)
  - Tracking (klog_bet, ksettle_bet, kget_clv_stats, kget_roi_by_signal, kget_reliability)
  - Feedback loop (ksave_layer_perf, kupdate_layer_verdict, kget_layer_feedback)
  - Données dérivées (kget_team_streak, kget_late_goals_ratio, kget_referee_stats)
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from typing import Iterable

import pg8000.native


# ================================================================== #
#  Connexion
# ================================================================== #
def _parse_database_url(url: str) -> dict:
    """Parse postgresql://user:pass@host:port/db?sslmode=require."""
    from urllib.parse import urlparse
    u = urlparse(url)
    return {
        "user": u.username,
        "password": u.password,
        "host": u.hostname,
        "port": u.port or 5432,
        "database": (u.path or "/").lstrip("/"),
    }


def _connect() -> pg8000.native.Connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL manquante dans l'environnement")
    params = _parse_database_url(url)
    conn = pg8000.native.Connection(
        user=params["user"],
        password=params["password"],
        host=params["host"],
        database=params["database"],
        port=params["port"],
        ssl_context=True,
    )
    conn.autocommit = True
    return conn


@contextmanager
def get_conn():
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


# ================================================================== #
#  Prédictions
# ================================================================== #
def ksave_predictions(date: str, data: Iterable[dict]) -> None:
    sql = """
        INSERT INTO k_predictions (
            date, match_id, league_id, league_name,
            home_team_id, home_team_name, away_team_id, away_team_name,
            kickoff, score, confidence, proba_over, proba_under,
            cote_over, cote_under, edge_over, edge_under,
            signal_strength, mise_kelly, match_data
        ) VALUES (
            :date, :match_id, :league_id, :league_name,
            :home_team_id, :home_team_name, :away_team_id, :away_team_name,
            :kickoff, :score, :confidence, :proba_over, :proba_under,
            :cote_over, :cote_under, :edge_over, :edge_under,
            :signal_strength, :mise_kelly, :match_data
        )
        ON CONFLICT (date, match_id) DO UPDATE SET
            score = EXCLUDED.score,
            confidence = EXCLUDED.confidence,
            proba_over = EXCLUDED.proba_over,
            proba_under = EXCLUDED.proba_under,
            cote_over = EXCLUDED.cote_over,
            cote_under = EXCLUDED.cote_under,
            edge_over = EXCLUDED.edge_over,
            edge_under = EXCLUDED.edge_under,
            signal_strength = EXCLUDED.signal_strength,
            mise_kelly = EXCLUDED.mise_kelly,
            match_data = EXCLUDED.match_data
    """
    with get_conn() as conn:
        for row in data:
            conn.run(
                sql,
                date=date,
                match_id=row["match_id"],
                league_id=row.get("league_id"),
                league_name=row.get("league_name"),
                home_team_id=row.get("home_team_id"),
                home_team_name=row.get("home_team_name"),
                away_team_id=row.get("away_team_id"),
                away_team_name=row.get("away_team_name"),
                kickoff=row.get("kickoff"),
                score=row.get("score"),
                confidence=row.get("confidence"),
                proba_over=row.get("proba_over"),
                proba_under=row.get("proba_under"),
                cote_over=row.get("cote_over"),
                cote_under=row.get("cote_under"),
                edge_over=row.get("edge_over"),
                edge_under=row.get("edge_under"),
                signal_strength=row.get("signal_strength"),
                mise_kelly=row.get("mise_kelly"),
                match_data=json.dumps(row.get("match_data", {})),
            )


def kload_predictions(date: str) -> list:
    sql = """
        SELECT match_id, league_id, league_name,
               home_team_id, home_team_name, away_team_id, away_team_name,
               kickoff, score, confidence, proba_over, proba_under,
               cote_over, cote_under, edge_over, edge_under,
               signal_strength, mise_kelly, match_data, result_verdict
        FROM k_predictions
        WHERE date = :date
        ORDER BY kickoff
    """
    with get_conn() as conn:
        rows = conn.run(sql, date=date)
        cols = [c["name"] for c in conn.columns]
    return [dict(zip(cols, r)) for r in rows]


def kget_archive(limit: int = 30) -> list:
    sql = """
        SELECT date,
               COUNT(*) AS n_matchs,
               SUM(CASE WHEN result_verdict = '✓' THEN 1 ELSE 0 END) AS won,
               SUM(CASE WHEN result_verdict = '×' THEN 1 ELSE 0 END) AS lost,
               SUM(mise_kelly) AS total_mise,
               AVG(score) AS avg_score
        FROM k_predictions
        WHERE result_verdict IS NOT NULL
        GROUP BY date
        ORDER BY date DESC
        LIMIT :limit
    """
    with get_conn() as conn:
        rows = conn.run(sql, limit=limit)
        cols = [c["name"] for c in conn.columns]
    return [dict(zip(cols, r)) for r in rows]


# ================================================================== #
#  Tracking (bets_log)
# ================================================================== #
def klog_bet(
    date, match_id, market, home_team, away_team, league_id,
    score_final, proba_predite, cote_prise, edge, signal, mise,
) -> None:
    sql = """
        INSERT INTO k_bets_log (
            date, match_id, market, home_team, away_team, league_id,
            score_final, proba_predite, cote_prise, edge, signal, mise
        ) VALUES (
            :date, :match_id, :market, :home_team, :away_team, :league_id,
            :score_final, :proba_predite, :cote_prise, :edge, :signal, :mise
        )
    """
    with get_conn() as conn:
        conn.run(
            sql,
            date=date, match_id=match_id, market=market,
            home_team=home_team, away_team=away_team, league_id=league_id,
            score_final=score_final, proba_predite=proba_predite,
            cote_prise=cote_prise, edge=edge, signal=signal, mise=mise,
        )


def ksettle_bet(match_id: str, resultat: str, cote_cloture=None) -> None:
    sql = """
        UPDATE k_bets_log
        SET resultat = :resultat,
            cote_cloture = COALESCE(:cote_cloture, cote_cloture),
            clv = CASE
                WHEN :cote_cloture IS NOT NULL AND cote_prise > 0
                THEN (:cote_cloture / cote_prise) - 1
                ELSE clv
            END,
            settled_at = NOW()
        WHERE match_id = :match_id AND resultat = 'pending'
    """
    with get_conn() as conn:
        conn.run(sql, match_id=match_id, resultat=resultat, cote_cloture=cote_cloture)


def kget_clv_stats() -> dict:
    sql = """
        SELECT
            COUNT(*) FILTER (WHERE resultat <> 'pending') AS n_settled,
            AVG(clv) FILTER (WHERE clv IS NOT NULL) AS avg_clv,
            AVG(CASE WHEN resultat = 'won' THEN 1.0 ELSE 0.0 END)
                FILTER (WHERE resultat IN ('won','lost')) AS win_rate
        FROM k_bets_log
    """
    with get_conn() as conn:
        r = conn.run(sql)[0]
    return {"n_settled": r[0], "avg_clv": r[1], "win_rate": r[2]}


def kget_roi_by_signal() -> list:
    sql = """
        SELECT signal,
               COUNT(*) FILTER (WHERE resultat IN ('won','lost')) AS n,
               SUM(CASE WHEN resultat = 'won' THEN mise * (cote_prise - 1)
                        WHEN resultat = 'lost' THEN -mise
                        ELSE 0 END) AS pnl,
               SUM(mise) FILTER (WHERE resultat IN ('won','lost')) AS volume
        FROM k_bets_log
        GROUP BY signal
        ORDER BY signal
    """
    with get_conn() as conn:
        rows = conn.run(sql)
        cols = [c["name"] for c in conn.columns]
    return [dict(zip(cols, r)) for r in rows]


def kget_reliability(n_bins: int = 5) -> list:
    sql = f"""
        WITH binned AS (
            SELECT WIDTH_BUCKET(proba_predite, 0, 1, {n_bins}) AS bin,
                   proba_predite,
                   CASE WHEN resultat = 'won' THEN 1 ELSE 0 END AS won
            FROM k_bets_log
            WHERE resultat IN ('won','lost')
        )
        SELECT bin, COUNT(*) AS n,
               AVG(proba_predite) AS proba_moy,
               AVG(won) AS freq_obs
        FROM binned
        GROUP BY bin
        ORDER BY bin
    """
    with get_conn() as conn:
        rows = conn.run(sql)
        cols = [c["name"] for c in conn.columns]
    return [dict(zip(cols, r)) for r in rows]


# ================================================================== #
#  Feedback loop (layer_performance)
# ================================================================== #
def ksave_layer_perf(
    layer_id, match_id, date, score, confidence, rejected, league_id, match_type,
) -> None:
    sql = """
        INSERT INTO k_layer_performance (
            layer_id, match_id, date, score, confidence,
            rejected, league_id, match_type
        ) VALUES (
            :layer_id, :match_id, :date, :score, :confidence,
            :rejected, :league_id, :match_type
        )
        ON CONFLICT DO NOTHING
    """
    # Nettoie la date : "None" (string), "null", "" → None (Python)
    if date in ("None", "null", "", None):
        date = None

    with get_conn() as conn:
        conn.run(
            sql, layer_id=layer_id, match_id=match_id, date=date,
            score=score, confidence=confidence, rejected=rejected,
            league_id=league_id, match_type=match_type,
        )


def kupdate_layer_verdict(match_id: str, result_verdict: str) -> None:
    sql = """
        UPDATE k_layer_performance
        SET result_verdict = :v
        WHERE match_id = :match_id
    """
    with get_conn() as conn:
        conn.run(sql, v=result_verdict, match_id=match_id)


def kget_layer_feedback(layer_id, scope="global", league_id=None, match_type=None, limit=15) -> dict:
    where = ["layer_id = :layer_id", "result_verdict IS NOT NULL"]
    params = {"layer_id": layer_id, "limit": limit}
    if scope == "league":
        where.append("league_id = :league_id")
        params["league_id"] = league_id
    elif scope == "type":
        where.append("match_type = :match_type")
        params["match_type"] = match_type

    sql = f"""
        SELECT COUNT(*) AS n,
               AVG(CASE WHEN result_verdict = '✓' THEN 1.0 ELSE 0.0 END) AS precision
        FROM (
            SELECT result_verdict
            FROM k_layer_performance
            WHERE {' AND '.join(where)}
            ORDER BY date DESC
            LIMIT :limit
        ) t
    """
    with get_conn() as conn:
        r = conn.run(sql, **params)[0]
    return {"n": r[0], "precision": r[1]}


# ================================================================== #
#  Données dérivées (team_matches)
# ================================================================== #
def kget_team_streak(team_id: int) -> int:
    sql = """
        SELECT goals_for
        FROM k_team_matches
        WHERE team_id = :team_id
        ORDER BY date DESC
    """
    with get_conn() as conn:
        rows = conn.run(sql, team_id=team_id)
    streak = 0
    for (gf,) in rows:
        if gf and gf > 0:
            streak += 1
        else:
            break
    return streak


def kget_late_goals_ratio(team_id: int):
    sql = """
        SELECT SUM(late_goals_for) AS late,
               SUM(goals_for) AS total
        FROM (
            SELECT late_goals_for, goals_for
            FROM k_team_matches
            WHERE team_id = :team_id
            ORDER BY date DESC
            LIMIT 15
        ) t
    """
    with get_conn() as conn:
        r = conn.run(sql, team_id=team_id)[0]
    late, total = r[0] or 0, r[1] or 0
    return (late / total) if total > 0 else None


def kget_referee_stats(referee_id: int):
    sql = """
        SELECT COUNT(*) AS n,
               AVG((match_data->>'total_goals')::numeric) AS goals_avg
        FROM k_predictions
        WHERE (match_data->>'referee_id')::int = :referee_id
          AND result_verdict IS NOT NULL
    """
    with get_conn() as conn:
        r = conn.run(sql, referee_id=referee_id)[0]
    if not r[0]:
        return None
    return {"n": r[0], "goals_avg": float(r[1]) if r[1] is not None else None}


# ================================================================== #
#  Odds snapshots (k_odds_snapshots)
# ================================================================== #
def ksave_odds_snapshot(match_id, bookmaker, market, line, price) -> None:
    sql = """
        INSERT INTO k_odds_snapshots (match_id, bookmaker, market, line, price)
        VALUES (:match_id, :bookmaker, :market, :line, :price)
    """
    with get_conn() as conn:
        conn.run(sql, match_id=match_id, bookmaker=bookmaker,
                 market=market, line=line, price=price)


def kload_latest_odds(match_id):
    """Retourne les dernières cotes connues pour un match, par (bookmaker, market)."""
    sql = """
        SELECT DISTINCT ON (bookmaker, market)
            bookmaker, market, line, price, snapshot_at
        FROM k_odds_snapshots
        WHERE match_id = :match_id
        ORDER BY bookmaker, market, snapshot_at DESC
    """
    with get_conn() as conn:
        rows = conn.run(sql, match_id=match_id)
        cols = [c["name"] for c in conn.columns]
    return [dict(zip(cols, r)) for r in rows]
