"""The two-tier response cache."""

from __future__ import annotations

import json
import time

from app.cache import ResponseCache, cache_key


class TestKey:
    def test_is_stable_regardless_of_parameter_order(self):
        assert cache_key("/studies", {"a": "1", "b": "2"}) == cache_key(
            "/studies", {"b": "2", "a": "1"}
        )

    def test_differs_for_different_parameters(self):
        assert cache_key("/studies", {"a": "1"}) != cache_key("/studies", {"a": "2"})

    def test_differs_for_different_paths(self):
        assert cache_key("/studies", {"a": "1"}) != cache_key("/stats", {"a": "1"})


class TestRoundTrip:
    def test_stores_and_returns_a_value(self, cache):
        cache.set("k", {"hello": "world"})
        assert cache.get("k") == {"hello": "world"}

    def test_missing_key_is_none(self, cache):
        assert cache.get("absent") is None

    def test_survives_a_new_instance_via_disk(self, tmp_path):
        first = ResponseCache(tmp_path / "c", ttl_seconds=60)
        first.set("k", {"v": 1})
        second = ResponseCache(tmp_path / "c", ttl_seconds=60)
        assert second.get("k") == {"v": 1}

    def test_expired_entry_is_a_miss(self, tmp_path):
        cache = ResponseCache(tmp_path / "c", ttl_seconds=0)
        cache.set("k", {"v": 1})
        time.sleep(0.01)
        assert cache.get("k") is None

    def test_disabled_cache_stores_nothing(self, tmp_path):
        cache = ResponseCache(tmp_path / "c", ttl_seconds=60, enabled=False)
        cache.set("k", {"v": 1})
        assert cache.get("k") is None


class TestResilience:
    def test_corrupt_file_is_a_miss_not_a_crash(self, tmp_path):
        cache = ResponseCache(tmp_path / "c", ttl_seconds=60)
        cache.set("k", {"v": 1})
        cache._memory.clear()
        (tmp_path / "c" / "k.json").write_text("{not json")
        assert cache.get("k") is None

    def test_memory_tier_is_bounded(self, tmp_path):
        from app.cache import _MEMORY_MAX_ENTRIES

        cache = ResponseCache(tmp_path / "c", ttl_seconds=60)
        for i in range(_MEMORY_MAX_ENTRIES + 20):
            cache.set(f"k{i}", {"v": i})
        assert len(cache._memory) <= _MEMORY_MAX_ENTRIES

    def test_writes_are_atomic(self, tmp_path):
        cache = ResponseCache(tmp_path / "c", ttl_seconds=60)
        cache.set("k", {"v": 1})
        # No stray temp files left behind that a later read could pick up.
        assert list((tmp_path / "c").glob("*.tmp")) == []
        assert json.loads((tmp_path / "c" / "k.json").read_text())["value"] == {"v": 1}
