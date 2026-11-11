"""
Détecte les matchs truqués via l'historique de côtes (k_odds_snapshots).
Signaux :
- Chute brutale de côte (> 15% en < 2h) → argent intelligent massif
- Hausse brutale (> 20% en < 2h) → piège
- Côte figée > 24h → suspect
"""
import os
from datetime import datetime, timedelta
import psycopg2
import psycopg2.extras


def detect_fraud(match_id: str, conn=None) -> tuple[bool, list]:
    """
    Analyse l'historique de côtes d'un match.
    Retourne (is_fraud, reasons).
    """
    close_conn = False
    if conn is None:
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        close_conn = True
    
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    # Récupère les snapshots des dernières 24h
    cur.execute("""
        SELECT market, price, snapshot_at
        FROM k_odds_snapshots
        WHERE match_id = %s
          AND snapshot_at > NOW() - INTERVAL '24 hours'
        ORDER BY snapshot_at ASC
    """, (str(match_id),))
    
    snapshots = cur.fetchall()
    
    if close_conn:
        conn.close()
    
    reasons = []
    is_fraud = False
    
    if len(snapshots) < 2:
        return False, ["Pas assez de snapshots (< 2)"]
    
    # Groupe par marché
    by_market = {}
    for s in snapshots:
        m = s["market"]
        if m not in by_market:
            by_market[m] = []
        by_market[m].append({"price": float(s["price"]), "at": s["snapshot_at"]})
    
    now = datetime.now(snapshots[0]["snapshot_at"].tzinfo)
    
    for market, prices in by_market.items():
        if len(prices) < 2:
            continue
        
        first = prices[0]
        last = prices[-1]
        first_price = first["price"]
        last_price = last["price"]
        
        if first_price <= 0:
            continue
        
        variation = (last_price - first_price) / first_price
        duration = (last["at"] - first["at"]).total_seconds() / 3600  # heures
        
        # Règle 1 : chute brutale > 15% en < 2h
        if variation < -0.15 and duration < 2:
            is_fraud = True
            reasons.append(f"{market}: chute {variation:.1%} en {duration:.1f}h (argent massif)")
        
        # Règle 2 : hausse brutale > 20% en < 2h
        if variation > 0.20 and duration < 2:
            is_fraud = True
            reasons.append(f"{market}: hausse {variation:.1%} en {duration:.1f}h (piège)")
        
        # Règle 3 : côte figée > 24h
        age = (now - last["at"]).total_seconds() / 3600
        if age > 24:
            reasons.append(f"{market}: côte figée {age:.0f}h (suspect)")
    
    return is_fraud, reasons


def get_fraud_stats(match_id: str, conn=None) -> dict:
    """Retourne les stats détaillées pour debug."""
    close_conn = False
    if conn is None:
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        close_conn = True
    
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT market, price, snapshot_at
        FROM k_odds_snapshots
        WHERE match_id = %s
          AND snapshot_at > NOW() - INTERVAL '48 hours'
        ORDER BY snapshot_at ASC
    """, (str(match_id),))
    rows = cur.fetchall()
    
    if close_conn:
        conn.close()
    
    return {
        "match_id": match_id,
        "n_snapshots": len(rows),
        "snapshots": [dict(r) for r in rows],
    }
