"""Enrichissement NOMS SEULEMENT — 1 requête = 150 matchs (au lieu de 1 req/match)."""
import os, sys, json, time, psycopg2, psycopg2.extras, urllib.request, urllib.error

conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

# Rotation clés
KEYS = [k for k in [
    os.environ.get("BZZOIRO_API_KEY_5"),
    os.environ.get("BZZOIRO_API_KEY_3"),
    os.environ.get("BZZOIRO_API_KEY_4"),
] if k]
print(f"Clés disponibles : {len(KEYS)}")
key_idx = 0

def fetch_events(date_str):
    global key_idx
    for _ in range(len(KEYS)):
        key = KEYS[key_idx % len(KEYS)]
        key_idx += 1
        url = f"https://sports.bzzoiro.com/api/v2/events/?date_from={date_str}&date_to={date_str}&limit=200"
        req = urllib.request.Request(url, headers={"Authorization": f"Token {key}"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f"  ⚠️ Clé épuisée, suivante")
                continue
            raise
    return None

# Dates à enrichir
cur.execute("""
    SELECT DISTINCT date::text AS date FROM k_predictions
    WHERE result_verdict IS NOT NULL
      AND (home_team_name IS NULL OR home_team_name = '')
    ORDER BY date DESC
""")
dates = [r["date"] for r in cur.fetchall()]
print(f"Dates : {len(dates)}\n")

total = 0
for d in dates:
    print(f"📅 {d}...")
    data = fetch_events(d)
    if not data:
        continue
    for ev in data.get("results", []):
        ev_id = str(ev.get("id"))
        home, away = ev.get("home_team"), ev.get("away_team")
        if not home or not away:
            continue
        cur.execute("""
            UPDATE k_predictions SET home_team_name=%s, away_team_name=%s
            WHERE match_id=%s AND (home_team_name IS NULL OR home_team_name='')
        """, (home, away, ev_id))
        total += cur.rowcount
    conn.commit()
    print(f"  ✅ {total} enrichis cumulés")
    time.sleep(0.1)

cur.execute("""
    SELECT COUNT(*) AS reste FROM k_predictions
    WHERE result_verdict IS NOT NULL
      AND (home_team_name IS NULL OR home_team_name = '')
""")
print(f"\n🎉 {total} matchs enrichis. Reste sans noms : {cur.fetchone()['reste']}")
conn.close()
