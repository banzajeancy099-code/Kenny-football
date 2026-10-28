"""Base client HTTP résilient (retry + circuit breaker + cache)."""
import time
import hashlib
import requests
from typing import Optional
from src.utils import log


class BaseClient:
    def __init__(self, name: str, base_url: str, api_key: str,
                 rate_limit_ms: int = 100, cache_ttl_s: int = 300):
        self.name = name
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.rate_limit_ms = rate_limit_ms
        self.cache_ttl_s = cache_ttl_s
        self._last_call = 0
        self._cache = {}
        self._failures = 0
        self._circuit_open_until = 0
        self._session = requests.Session()

    def _rate_limit(self):
        elapsed = (time.time() - self._last_call) * 1000
        if elapsed < self.rate_limit_ms:
            time.sleep((self.rate_limit_ms - elapsed) / 1000)
        self._last_call = time.time()

    def _cache_key(self, method: str, path: str, params: dict) -> str:
        raw = f"{method}:{path}:{sorted((params or {}).items())}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _check_circuit(self):
        if time.time() < self._circuit_open_until:
            remaining = int(self._circuit_open_until - time.time())
            raise Exception(f"[{self.name}] Circuit breaker ouvert ({remaining}s)")

    def _record_failure(self):
        self._failures += 1
        if self._failures >= 5:
            self._circuit_open_until = time.time() + 60
            log.warning(f"[{self.name}] Circuit breaker OUVERT (5 échecs)")

    def _record_success(self):
        self._failures = 0

    def request(self, method: str, path: str, params: Optional[dict] = None,
                headers: Optional[dict] = None, max_retries: int = 3) -> dict:
        self._check_circuit()

        cache_key = self._cache_key(method, path, params or {})
        if cache_key in self._cache:
            cached_at, data = self._cache[cache_key]
            if time.time() - cached_at < self.cache_ttl_s:
                log.debug(f"[{self.name}] cache HIT {path}")
                return data

        url = f"{self.base_url}{path}"
        default_headers = self._default_headers()
        if headers:
            default_headers.update(headers)

        for attempt in range(max_retries):
            try:
                self._rate_limit()
                resp = self._session.request(
                    method, url, params=params, headers=default_headers,
                    timeout=15
                )
                if resp.status_code == 429:
                    wait = 2 ** attempt
                    log.warning(f"[{self.name}] 429, wait {wait}s")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                self._cache[cache_key] = (time.time(), data)
                self._record_success()
                return data
            except requests.exceptions.RequestException as e:
                log.error(f"[{self.name}] tentative {attempt+1}/{max_retries} échouée: {e}")
                if attempt == max_retries - 1:
                    self._record_failure()
                    raise
                time.sleep(2 ** attempt)

        raise Exception(f"[{self.name}] max_retries atteint")

    def get(self, path: str, params: Optional[dict] = None) -> dict:
        return self.request("GET", path, params=params)

    def _default_headers(self) -> dict:
        return {'Content-Type': 'application/json'}
