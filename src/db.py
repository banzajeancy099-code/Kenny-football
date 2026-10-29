# src/db.py — Connexion Neon Postgres + schéma
import os
import logging
import json
from datetime import date, datetime
from contextlib import contextmanager

log = logging.getLogger("db")

DATABASE_URL = os.environ.get("DATABASE_URL")

try:
    import pg8000
    HAS_PSYCOPG2 = True
    log.info("✅ pg8000 disponible (pure Python)")
except ImportError:
    HAS_PSYCOPG2 = False
    log.warning("pg8000 non installé — fallback JSON")

DATABASE_URL = os.environ.get("DATABASE_URL")


def _parse_db_url(url):
    """Parse une URL postgres:// en dict pour pg8000."""
    from urllib.parse import urlparse, unquote
    if not url:
        return None
    # Accepter postgres:// et postgresql://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    parsed = urlparse(url)
    return {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "user": unquote(parsed.username) if parsed.username else None,
        "password": unquote(parsed.password) if parsed.password else None,
        "database": parsed.path.lstrip("/") if parsed.path else None,
    }


@contextmanager
def get_conn():
    """Context manager pour la connexion Postgres (pg8000)."""
    if not HAS_PSYCOPG2 or not DATABASE_URL:
        yield None
        return
    
    params = _parse_db_url(DATABASE_URL)
    if not params:
        yield None
        return
    
    try:
        conn = pg8000.connect(
            host=params["host"],
            port=params["port"],
            user=params["user"],
            password=params["password"],
            database=params["database"],
            ssl_context=True,  # obligatoire pour Neon
            timeout=15,
        )
        log.info(f"✅ Connecté à {params['host']}:{params['port']}/{params['database']}")
    except Exception as e:
        log.error(f"❌ Connexion échouée: {e}")
        yield None
        return
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    """Crée les tables si elles n'existent pas."""
    if not HAS_PSYCOPG2 or not DATABASE_URL:
        log.warning("⚠️  DB indisponible — mode JSON local")
        return False

    with get_conn() as conn:
        if conn is None:
            return False
        try:
            with conn.cursor() as cur:
                # Table principale
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS predictions (
                        id SERIAL PRIMARY KEY,
                        date DATE NOT NULL,
                        match_id TEXT NOT NULL,
                        match_data JSONB NOT NULL,
                        home TEXT,
                        away TEXT,
                        league_id INTEGER,
                        league_name TEXT,
                        kickoff TEXT,
                        score NUMERIC,
                        proba_over NUMERIC,
                        edge NUMERIC,
                        cote_over NUMERIC,
                        mise_kelly NUMERIC,
                        is_under_bet BOOLEAN DEFAULT FALSE,
                        proba_under NUMERIC,
                        edge_under NUMERIC,
                        mise_under NUMERIC,
                        score_btts NUMERIC,
                        cote_btts_yes NUMERIC,
                        edge_btts NUMERIC,
                        mise_btts NUMERIC,
                        retenu_btts BOOLEAN DEFAULT FALSE,
                        result JSONB,
                        result_verdict TEXT,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW(),
                        UNIQUE(date, match_id)
                    );
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_predictions_date ON predictions(date DESC);
                    CREATE INDEX IF NOT EXISTS idx_predictions_verdict ON predictions(result_verdict);
                """)
            conn.commit()
            log.info("✅ Table predictions prête")
            return True
        except Exception as e:
            log.error(f"❌ Erreur init_db: {e}")
            conn.rollback()
            return False


def save_predictions(d: date, data: dict):
    """Sauvegarde les prédictions d'un jour en base."""
    if not HAS_PSYCOPG2 or not DATABASE_URL:
        return False

    matches = data.get("matches", {})
    if not matches:
        return False

    with get_conn() as conn:
        if conn is None:
            return False
        try:
            with conn.cursor() as cur:
                for mid, pred in matches.items():
                    cur.execute("""
                        INSERT INTO predictions (
                            date, match_id, match_data, home, away,
                            league_id, league_name, kickoff, score,
                            proba_over, edge, cote_over, mise_kelly,
                            is_under_bet, proba_under, edge_under, mise_under,
                            score_btts, cote_btts_yes, edge_btts, mise_btts, retenu_btts,
                            result, result_verdict, updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s, %s, NOW()
                        )
                        ON CONFLICT (date, match_id) DO UPDATE SET
                            match_data = EXCLUDED.match_data,
                            score = EXCLUDED.score,
                            proba_over = EXCLUDED.proba_over,
                            edge = EXCLUDED.edge,
                            cote_over = EXCLUDED.cote_over,
                            mise_kelly = EXCLUDED.mise_kelly,
                            is_under_bet = EXCLUDED.is_under_bet,
                            proba_under = EXCLUDED.proba_under,
                            edge_under = EXCLUDED.edge_under,
                            mise_under = EXCLUDED.mise_under,
                            score_btts = EXCLUDED.score_btts,
                            cote_btts_yes = EXCLUDED.cote_btts_yes,
                            edge_btts = EXCLUDED.edge_btts,
                            mise_btts = EXCLUDED.mise_btts,
                            retenu_btts = EXCLUDED.retenu_btts,
                            result = EXCLUDED.result,
                            result_verdict = EXCLUDED.result_verdict,
                            updated_at = NOW()
                    """, (
                        d, mid, json.dumps(pred, default=str),
                        pred.get("home"), pred.get("away"),
                        pred.get("league_id"), pred.get("league_name"), pred.get("kickoff"), pred.get("score"),
                        pred.get("proba_over"), pred.get("edge"), pred.get("cote_over"), pred.get("mise_kelly"),
                        pred.get("is_under_bet", False), pred.get("proba_under"), pred.get("edge_under"), pred.get("mise_under"),
                        pred.get("score_btts"), pred.get("cote_btts_yes"), pred.get("edge_btts"), pred.get("mise_btts"), pred.get("retenu_btts", False),
                        json.dumps(pred.get("result"), default=str) if pred.get("result") else None,
                        (pred.get("result") or {}).get("verdict") if pred.get("result") else None,
                    ))
            conn.commit()
            return True
        except Exception as e:
            log.error(f"❌ Erreur save_predictions: {e}")
            conn.rollback()
            return False


def load_predictions(d: date):
    """Charge les prédictions d'un jour depuis la base."""
    if not HAS_PSYCOPG2 or not DATABASE_URL:
        return None

    with get_conn() as conn:
        if conn is None:
            return None
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT match_id, match_data, result, result_verdict FROM predictions WHERE date = %s",
                (d,)
            )
            rows = cur.fetchall()
            cur.close()

            matches = {}
            for row in rows:
                match_id, match_data, result, result_verdict = row
                data = match_data
                if isinstance(data, str):
                    data = json.loads(data)
                if result:
                    data["result"] = result if isinstance(result, dict) else json.loads(result)
                matches[match_id] = data

            return {
                "date": d.isoformat(),
                "matches": matches,
                "last_update": datetime.now().isoformat(),
            }
        except Exception as e:
            log.error(f"❌ Erreur load_predictions: {e}")
            return None

    with get_conn() as conn:
        if conn is None:
            return None
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT match_id, match_data, result, result_verdict
                    FROM predictions WHERE date = %s
                """, (d,))
                rows = cur.fetchall()

            matches = {}
            for row in rows:
                data = row["match_data"]
                if isinstance(data, str):
                    data = json.loads(data)
                if row["result"]:
                    data["result"] = row["result"] if isinstance(row["result"], dict) else json.loads(row["result"])
                matches[row["match_id"]] = data

            return {
                "date": d.isoformat(),
                "matches": matches,
                "last_update": datetime.now().isoformat(),
            }
        except Exception as e:
            log.error(f"❌ Erreur load_predictions: {e}")
            return None


def get_archive(limit=90):
    """Retourne la liste des jours avec stats."""
    if not HAS_PSYCOPG2 or not DATABASE_URL:
        return []

    with get_conn() as conn:
        if conn is None:
            return []
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT 
                    date::text AS date,
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE is_under_bet = FALSE) AS over_count,
                    COUNT(*) FILTER (WHERE is_under_bet = TRUE) AS under_count,
                    COUNT(*) FILTER (WHERE result_verdict = '✓') AS correct,
                    COUNT(*) FILTER (WHERE result_verdict = '×') AS wrong,
                    COUNT(*) FILTER (WHERE result_verdict IS NOT NULL) AS verified,
                    MAX(updated_at)::text AS last_update
                FROM predictions
                WHERE result_verdict IS NOT NULL
                GROUP BY date
                ORDER BY date DESC
                LIMIT %s
            """, (limit,))
            rows = cur.fetchall()
            cur.close()

            out = []
            for row in rows:
                out.append({
                    "date": row[0],
                    "total": row[1],
                    "over_count": row[2],
                    "under_count": row[3],
                    "correct": row[4],
                    "wrong": row[5],
                    "verified": row[6],
                    "last_update": row[7],
                })
            return out
        except Exception as e:
            log.error(f"❌ Erreur get_archive: {e}")
            return []

    with get_conn() as conn:
        if conn is None:
            return []
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT 
                        date::text AS date,
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE is_under_bet = FALSE) AS over_count,
                        COUNT(*) FILTER (WHERE is_under_bet = TRUE) AS under_count,
                        COUNT(*) FILTER (WHERE result_verdict = '✓') AS correct,
                        COUNT(*) FILTER (WHERE result_verdict = '×') AS wrong,
                        COUNT(*) FILTER (WHERE result_verdict IS NOT NULL) AS verified,
                        MAX(updated_at)::text AS last_update
                    FROM predictions
                    WHERE result_verdict IS NOT NULL
                    GROUP BY date
                    ORDER BY date DESC
                    LIMIT %s
                """, (limit,))
                return cur.fetchall()
        except Exception as e:
            log.error(f"❌ Erreur get_archive: {e}")
            return []
