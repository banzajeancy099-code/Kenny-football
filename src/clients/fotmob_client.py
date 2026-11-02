"""Client FotMob pour récupérer les photos de joueurs.
Version avec retry + fallback pour Render.
"""
import asyncio
import logging
import time

log = logging.getLogger("fotmob")

try:
    from fotmob import FotMob
    HAS_FOTMOB = True
except ImportError:
    HAS_FOTMOB = False
    log.warning("fotmob-wrapper non installé")


async def _search_player_async(name, retries=2):
    if not HAS_FOTMOB:
        return None
    for attempt in range(retries):
        try:
            async with FotMob() as fotmob:
                results = await fotmob.search_player(name)
                if results:
                    return results
        except Exception as e:
            log.warning(f"[FOTMOB] search {name} (attempt {attempt+1}): {e}")
            if attempt < retries - 1:
                await asyncio.sleep(1)
    return None


def search_player(name):
    """Sync wrapper pour search_player."""
    try:
        return asyncio.run(_search_player_async(name))
    except Exception as e:
        log.warning(f"[FOTMOB] search_player {name}: {e}")
        return None


async def _get_image_async(player_id, retries=2):
    if not HAS_FOTMOB:
        return None
    for attempt in range(retries):
        try:
            async with FotMob() as fotmob:
                url = fotmob.get_player_image(player_id)
                if url:
                    return url
        except Exception as e:
            log.warning(f"[FOTMOB] image {player_id} (attempt {attempt+1}): {e}")
            if attempt < retries - 1:
                await asyncio.sleep(1)
    return None


def get_image(player_id):
    return asyncio.run(_get_image_async(player_id))


def find_player_photo(player_name, team_name=None):
    """Cherche la photo d'un joueur sur FotMob (avec variantes + retry)."""
    # Essayer plusieurs variantes du nom
    candidates = [player_name]
    parts = player_name.split()
    if len(parts) >= 2:
        candidates.append(parts[-1])  # nom de famille seul
        candidates.append(f"{parts[0]} {parts[-1]}")
    
    for name in candidates:
        results = search_player(name)
        if not results:
            continue
        
        # Filtrer par équipe si fournie (priorité)
        if team_name:
            team_norm = team_name.lower().strip()
            for r in results:
                if r.get('type') != 'player':
                    continue
                r_team = (r.get('teamName') or '').lower()
                if team_norm and (team_norm in r_team or r_team in team_norm):
                    return {
                        'id': r['id'],
                        'name': r['name'],
                        'team': r.get('teamName'),
                    }
        
        # Sinon, prendre le premier joueur
        for r in results:
            if r.get('type') == 'player':
                return {
                    'id': r['id'],
                    'name': r['name'],
                    'team': r.get('teamName'),
                }
    
    return None


def direct_image_url(fotmob_id):
    """URL directe de l'image FotMob (sans passer par le wrapper)."""
    return f"https://images.fotmob.com/image_resources/playerimages/{fotmob_id}.png"
