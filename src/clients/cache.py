# src/clients/cache.py — Cache disque pour les réponses API
"""
Cache disque simple et robuste.

Structure :
  data/cache/{service}/{hash}.json

Chaque fichier contient :
  {
    "key": "GET:/events/?date_from=2026-10-31&date_to=2026-10-31",
    "ts": 1730404800.0,
    "ttl": 86400,
    "data": {...}
  }

TTL par type d'endpoint :
  - events (matchs, classements) : 1h
  - players profile : 7 jours (change peu)
  - players stats : 24h (change après chaque match)
  - odds : 15 min (change souvent)
  - lineups : 1h (avant match)
"""
import os
import json
import time
import hashlib
import logging
from pathlib import Path

log = logging.getLogger("cache")

CACHE_ROOT = Path("data/cache")

# TTL par préfixe d'endpoint (en secondes)
TTL_MAP = {
    "/players/": 86400 * 7,       # 7 jours (profils/stats joueurs)
    "/teams/": 86400,              # 1 jour (formes)
    "/leagues/": 3600,             # 1 heure (classements)
    "/events/": 3600,              # 1 heure (matchs)
    "/odds": 900,                  # 15 min (cotes)
    "/lineups": 3600,              # 1 heure
}

DEFAULT_TTL = 3600  # 1 heure


def _get_ttl(endpoint):
    """Retourne le TTL approprié pour un endpoint."""
    for prefix, ttl in TTL_MAP.items():
        if prefix in endpoint:
            return ttl
    return DEFAULT_TTL


def _hash_key(method, endpoint, params):
    """Génère un hash MD5 unique pour une requête."""
    key_str = f"{method}:{endpoint}"
    if params:
        # Trier les params pour un hash stable
        sorted_params = sorted(params.items()) if isinstance(params, dict) else params
        key_str += ":" + str(sorted_params)
    return hashlib.md5(key_str.encode()).hexdigest()


def _get_service_dir(service):
    """Retourne le dossier de cache pour un service (ex: bzzoiro)."""
    service_dir = CACHE_ROOT / service
    service_dir.mkdir(parents=True, exist_ok=True)
    return service_dir


def get(service, method, endpoint, params=None):
    """Récupère une réponse depuis le cache. None si absent ou expiré."""
    key_hash = _hash_key(method, endpoint, params)
    service_dir = _get_service_dir(service)
    cache_file = service_dir / f"{key_hash}.json"

    if not cache_file.exists():
        return None

    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            entry = json.load(f)
    except Exception:
        return None

    # Vérifier TTL
    age = time.time() - entry.get("ts", 0)
    ttl = entry.get("ttl", DEFAULT_TTL)
    if age > ttl:
        log.debug(f"[cache] expired: {endpoint} (age={age:.0f}s > ttl={ttl}s)")
        return None

    log.debug(f"[cache] hit: {endpoint} (age={age:.0f}s)")
    return entry.get("data")


def set(service, method, endpoint, params, data):
    """Sauvegarde une réponse dans le cache."""
    key_hash = _hash_key(method, endpoint, params)
    service_dir = _get_service_dir(service)
    cache_file = service_dir / f"{key_hash}.json"

    ttl = _get_ttl(endpoint)
    entry = {
        "key": f"{method}:{endpoint}:{params}",
        "ts": time.time(),
        "ttl": ttl,
        "data": data,
    }

    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False)
        log.debug(f"[cache] saved: {endpoint} (ttl={ttl}s)")
    except Exception as e:
        log.warning(f"[cache] save failed: {e}")


def clear(service=None, older_than_hours=None):
    """Vide le cache (tout ou partiel)."""
    if service:
        service_dir = _get_service_dir(service)
        if older_than_hours is not None:
            cutoff = time.time() - (older_than_hours * 3600)
            count = 0
            for f in service_dir.glob("*.json"):
                try:
                    if f.stat().st_mtime < cutoff:
                        f.unlink()
                        count += 1
                except Exception:
                    pass
            log.info(f"[cache] cleared {count} files older than {older_than_hours}h from {service}")
        else:
            count = 0
            for f in service_dir.glob("*.json"):
                try:
                    f.unlink()
                    count += 1
                except Exception:
                    pass
            log.info(f"[cache] cleared {count} files from {service}")


def stats(service=None):
    """Retourne des stats sur le cache."""
    total_files = 0
    total_size = 0
    services = [service] if service else [d.name for d in CACHE_ROOT.glob("*") if d.is_dir()]

    for svc in services:
        svc_dir = CACHE_ROOT / svc
        if not svc_dir.exists():
            continue
        for f in svc_dir.glob("*.json"):
            total_files += 1
            try:
                total_size += f.stat().st_size
            except Exception:
                pass

    return {
        "files": total_files,
        "size_mb": round(total_size / 1024 / 1024, 2),
        "services": services,
    }
