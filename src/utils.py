"""Utilitaires : logger + cache mémoire."""
import logging
import sys
import time


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("kenny_football")


class MemoryCache:
    def __init__(self, default_ttl: int = 300):
        self._data = {}
        self.default_ttl = default_ttl

    def get(self, key: str):
        if key in self._data:
            expires_at, value = self._data[key]
            if time.time() < expires_at:
                return value
            del self._data[key]
        return None

    def set(self, key: str, value, ttl: int = None):
        ttl = ttl or self.default_ttl
        self._data[key] = (time.time() + ttl, value)

    def clear(self):
        self._data.clear()
