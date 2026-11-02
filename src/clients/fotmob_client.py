"""Client FotMob pour récupérer les photos de joueurs."""
import asyncio
import logging
from functools import lru_cache

log = logging.getLogger("fotmob")

try:
    from fotmob import FotMob
    HAS_FOTMOB = True
except ImportError:
    HAS_FOTMOB = False
    log.warning("fotmob-wrapper non installé")


async def _search_player_async(name):
    if not HAS_FOTMOB:
        return None
    try:
        async with FotMob() as fotmob:
            results = await fotmob.search_player(name)
            return results
    except Exception as e:
        log.warning(f"[FOTMOB] {name}: {e}")
        return None


def search_player(name):
    """Sync wrapper pour search_player."""
    return asyncio.run(_search_player_async(name))


async def _get_image_async(player_id):
    if not HAS_FOTMOB:
        return None
    try:
        async with FotMob() as fotmob:
            url = fotmob.get_player_image(player_id)
            return url
    except Exception as e:
        log.warning(f"[FOTMOB] image {player_id}: {e}")
        return None


def get_image(player_id):
    return asyncio.run(_get_image_async(player_id))


def find_player_photo(player_name, team_name=None):
    """Cherche la photo d'un joueur sur FotMob."""
    results = search_player(player_name)
    if not results:
        return None
    
    # Filtrer par équipe si fournie
    if team_name:
        team_norm = team_name.lower()
        for r in results:
            if r.get('type') == 'player' and team_norm in (r.get('teamName') or '').lower():
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
