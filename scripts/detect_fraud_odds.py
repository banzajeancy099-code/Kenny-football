"""
Détection fraude avancée via The Odds API + historique Bzzoiro.

5 signaux (comme les pros) :
1. Steam move (mouvement coordonné 3+ bookmakers)
2. Cote fantôme (cote isolée > 2σ)
3. Asymétrie temporelle (mouvement trop tôt/tard)
4. Corrélation marchés (1X2 stable mais O/U bouge)
5. Sharp vs Square (book square bouge avant sharp)

VETO si 2+ signaux.
"""
import os
import json
import statistics
import urllib.request
import urllib.parse
from datetime import datetime, timedelta


ODDS_API_BASE = "https://api.the-odds-api.com/v4"


def _fetch_the_odds_api(sport_key, markets="totals"):
    """Récupère les côtes de The Odds API."""
    api_key = os.environ.get("THE_ODDS_API_KEY")
    if not api_key:
        return []
    
    url = f"{ODDS_API_BASE}/sports/{sport_key}/odds"
    params = {
        "apiKey": api_key,
        "regions": "eu",
        "markets": markets,
        "oddsFormat": "decimal",
    }
    url += "?" + urllib.parse.urlencode(params)
    
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"⚠️ The Odds API KO : {e}")
        return []


def _match_league_to_sport_key(league_id):
    """Mapping league_id Bzzoiro -> sport_key The Odds API."""
    MAP = {
        1: "soccer_epl",
        3: "soccer_spain_la_liga",
        4: "soccer_italy_serie_a",
        5: "soccer_germany_bundesliga",
        6: "soccer_france_ligue_one",
        7: "soccer_uefa_champs_league",
        8: "soccer_uefa_europa_league",
        9: "soccer_brazil_campeonato",
        34: "soccer_brazil_serie_b",
    }
    return MAP.get(league_id)


def _normalize_name(s):
    """Normalise les noms pour matcher."""
    if not s:
        return ""
    s = s.lower().strip()
    for prefix in ("fc ", "as ", "ss ", "sc ", "ac ", "rc ", "cd "):
        if s.startswith(prefix):
            s = s[len(prefix):]
    return s.replace(" ", "").replace("-", "").replace(".", "")


def _find_match(events, home_team, away_team):
    """Trouve l'événement correspondant."""
    if not events:
        return None
    home_norm = _normalize_name(home_team)
    away_norm = _normalize_name(away_team)
    for ev in events:
        if (_normalize_name(ev.get("home_team")) == home_norm 
            and _normalize_name(ev.get("away_team")) == away_norm):
            return ev
    return None


def detect_steam_move(event, threshold=0.10, min_books=3):
    """Signal 1 : Steam move (3+ bookmakers avec écart-type > 10%)."""
    if not event:
        return False, "Pas de données"
    
    over_prices = []
    for book in event.get("bookmakers", []):
        for mkt in book.get("markets", []):
            if mkt.get("key") != "totals":
                continue
            for outcome in mkt.get("outcomes", []):
                if outcome.get("name", "").lower() == "over" and outcome.get("point") == 2.5:
                    over_prices.append(outcome.get("price"))
    
    if len(over_prices) < min_books:
        return False, f"Pas assez de bookmakers ({len(over_prices)})"
    
    mean = statistics.mean(over_prices)
    stdev = statistics.stdev(over_prices) if len(over_prices) > 1 else 0
    
    if mean > 0 and stdev / mean > threshold:
        return True, f"Steam move : σ {stdev:.2f} sur {mean:.2f} ({len(over_prices)} books)"
    
    return False, "Cohérent"


def detect_phantom_odds(event, threshold=None):
    """Signal 2 : Cote fantôme (seuil adaptatif selon taille échantillon)."""
    if not event:
        return False, "Pas de données"

    over_prices = []
    for book in event.get("bookmakers", []):
        for mkt in book.get("markets", []):
            if mkt.get("key") != "totals":
                continue
            for outcome in mkt.get("outcomes", []):
                if outcome.get("name", "").lower() == "over" and outcome.get("point") == 2.5:
                    over_prices.append(outcome.get("price"))

    if len(over_prices) < 3:
        return False, f"Pas assez de bookmakers ({len(over_prices)})"

    mean = statistics.mean(over_prices)
    stdev = statistics.stdev(over_prices)

    if stdev == 0:
        return False, "Pas de variance"

    # Seuil adaptatif selon taille de l'échantillon
    if threshold is None:
        if len(over_prices) >= 10:
            threshold = 1.5
        elif len(over_prices) >= 5:
            threshold = 1.2
        else:
            threshold = 1.0

    for price in over_prices:
        if abs(price - mean) > threshold * stdev:
            return True, f"Cote fantôme : {price:.2f} (moyenne {mean:.2f}, σ {stdev:.2f}, {len(over_prices)} books, {threshold}σ)"

    return False, "Cohérent"
    
    return False, "Cohérent"


def detect_temporal_asymmetry(match_id, kickoff, conn=None):
    """Signal 3 : Asymétrie temporelle (mouvement trop tôt/tard)."""
    if not conn:
        return False, "Pas de DB"
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT market, price, snapshot_at
            FROM k_odds_snapshots
            WHERE match_id = %s
            AND snapshot_at > NOW() - INTERVAL '72 hours'
            ORDER BY snapshot_at ASC
        """, (str(match_id),))
        snapshots = cur.fetchall()
        cur.close()
    except Exception as e:
        return False, f"DB KO : {e}"
    
    if len(snapshots) < 2:
        return False, "Pas assez de snapshots"
    
    kickoff_dt = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
    
    for i in range(1, len(snapshots)):
        prev = snapshots[i-1]
        curr = snapshots[i]
        
        hours_before = (kickoff_dt - curr[2]).total_seconds() / 3600
        
        if prev[1] and prev[1] > 0:
            variation = (curr[1] - prev[1]) / prev[1]
            
            if hours_before < 0.08 and abs(variation) > 0.05:
                return True, f"Mouvement tardif ({hours_before*60:.0f} min avant) : {variation:.1%}"
            
            if hours_before > 48 and abs(variation) > 0.10:
                return True, f"Mouvement précoce ({hours_before:.0f}h avant) : {variation:.1%}"
    
    return False, "Cohérent"


def detect_market_correlation(event):
    """Signal 4 : Corrélation marchés (1X2 stable mais O/U bouge)."""
    if not event:
        return False, "Pas de données"
    
    h2h_prices = []
    totals_prices = []
    
    for book in event.get("bookmakers", []):
        for mkt in book.get("markets", []):
            if mkt.get("key") == "h2h":
                for outcome in mkt.get("outcomes", []):
                    h2h_prices.append(outcome.get("price"))
            elif mkt.get("key") == "totals":
                for outcome in mkt.get("outcomes", []):
                    if outcome.get("name", "").lower() == "over" and outcome.get("point") == 2.5:
                        totals_prices.append(outcome.get("price"))
    
    if not h2h_prices or not totals_prices:
        return False, "Marchés insuffisants"
    
    h2h_stdev = statistics.stdev(h2h_prices) if len(h2h_prices) > 1 else 0
    totals_stdev = statistics.stdev(totals_prices) if len(totals_prices) > 1 else 0
    
    if h2h_stdev < 0.05 and totals_stdev > 0.20:
        return True, f"Incohérence : 1X2 σ {h2h_stdev:.2f}, O/U σ {totals_stdev:.2f}"
    
    return False, "Cohérent"


def detect_sharp_square(event):
    """Signal 5 : Sharp (Pinnacle) vs Square (Bet365/Unibet)."""
    if not event:
        return False, "Pas de données"
    
    sharp_price = None
    square_prices = []
    
    SHARP_BOOKS = {"pinnacle", "betfair_ex_eu"}
    SQUARE_BOOKS = {"bet365", "unibet", "williamhill", "betsson", "unibet_se", "unibet_nl"}
    
    for book in event.get("bookmakers", []):
        key = book.get("key", "")
        for mkt in book.get("markets", []):
            if mkt.get("key") != "totals":
                continue
            for outcome in mkt.get("outcomes", []):
                if outcome.get("name", "").lower() == "over" and outcome.get("point") == 2.5:
                    if key in SHARP_BOOKS:
                        sharp_price = outcome.get("price")
                    elif key in SQUARE_BOOKS:
                        square_prices.append(outcome.get("price"))
    
    if sharp_price is None or not square_prices:
        return False, "Book sharp/square absent"
    
    for sq in square_prices:
        variation = (sq - sharp_price) / sharp_price
        if abs(variation) > 0.10:
            return True, f"Sharp {sharp_price:.2f} vs Square {sq:.2f} ({variation:.1%})"
    
    return False, "Cohérent"


def detect_fraud(match_id, home_team, away_team, league_id, kickoff, conn=None):
    """
    Détection fraude complète (5 signaux).
    VETO si 2+ signaux.
    """
    reasons = []
    
    sport_key = _match_league_to_sport_key(league_id)
    if not sport_key:
        return False, ["League non mappée"]
    
    events = _fetch_the_odds_api(sport_key, markets="totals,h2h")
    event = _find_match(events, home_team, away_team)
    
    if event:
        steam, steam_reason = detect_steam_move(event)
        if steam:
            reasons.append(f"🚨 Steam : {steam_reason}")
        
        phantom, phantom_reason = detect_phantom_odds(event)
        if phantom:
            reasons.append(f"🚨 Fantôme : {phantom_reason}")
        
        corr, corr_reason = detect_market_correlation(event)
        if corr:
            reasons.append(f"🚨 Corrélation : {corr_reason}")
        
        sharp, sharp_reason = detect_sharp_square(event)
        if sharp:
            reasons.append(f"🚨 Sharp/Square : {sharp_reason}")
    
    temporal, temporal_reason = detect_temporal_asymmetry(match_id, kickoff, conn)
    if temporal:
        reasons.append(f"🚨 Temporel : {temporal_reason}")
    
    is_fraud = len(reasons) >= 2
    
    return is_fraud, reasons
