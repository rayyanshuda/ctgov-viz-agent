# 2 tier TTL cache for the ClinicalTrials.gov responses
# Registry data changes almost daily, so caching allows repeated requests to not hammer a public API,
# and a question that spreads out into several cohort queries reuses the same pages

# In-memory (LRU cache) sits before the JSON-file, so the cache also survives restarts/reloads

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MEMORY_MAX_ENTRIES = 256


def cache_key(path: str, params: dict[str, str]) -> str:
    # Key for an endpoint plus its parameters
    # The paramets are sorted so that the dictionary ordering doesn't produce more than 2 keys for request

    payload = json.dumps({"path": path, "params": dict(sorted(params.items()))}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


class ResponseCache:
    # TTL cache with in-memory tier that has precedence over the JSON-file

    def __init__(self, directory: str | Path, ttl_seconds: int, enabled: bool = True) -> None:
        self.directory = Path(directory)
        self.ttl_seconds = ttl_seconds
        self.enabled = enabled
        self._memory: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        if self.enabled:
            self.directory.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str) -> Any | None:
        # Return the cached value, or if there is none or it's expired, return "None"
        if not self.enabled:
            return None
        now = time.time()

        hit = self._memory.get(key)
        if hit is not None:
            expires_at, value = hit
            if expires_at > now:
                self._memory.move_to_end(key)
                return value
            del self._memory[key]

        path = self._path_for(key)
        if not path.exists():
            return None
        try:
            envelope = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            # A truncated or unreadable cache file is a miss, never a failure.
            logger.debug("Discarding unreadable cache entry %s", key)
            return None
        if envelope.get("expires_at", 0) <= now:
            return None
        value = envelope.get("value")
        self._remember(key, value, envelope["expires_at"])
        return value

    def set(self, key: str, value: Any) -> None:
        # Store a value in both tiers. Any disk failures are logged
        if not self.enabled:
            return
        expires_at = time.time() + self.ttl_seconds
        self._remember(key, value, expires_at)
        try:
            # Write to a temporary file then rename, so a crash mid-write cannot leave a
            # half-written entry that a later read would treat as valid.
            tmp = self._path_for(key).with_suffix(".tmp")
            tmp.write_text(json.dumps({"expires_at": expires_at, "value": value}))
            tmp.replace(self._path_for(key))
        except OSError:
            logger.warning("Could not persist cache entry %s", key, exc_info=True)

    def _remember(self, key: str, value: Any, expires_at: float) -> None:
        self._memory[key] = (expires_at, value)
        self._memory.move_to_end(key)
        while len(self._memory) > _MEMORY_MAX_ENTRIES:
            self._memory.popitem(last=False)

    def clear(self) -> None:
        # Drop every entry, this is used by tests
        self._memory.clear()
        if self.enabled and self.directory.exists():
            for path in self.directory.glob("*.json"):
                path.unlink(missing_ok=True)
