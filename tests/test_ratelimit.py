# The per-IP rate limiter that protects the public demo from burning API credits

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from app.api.ratelimit import SlidingWindowLimiter, client_key


class TestSlidingWindow:
    def test_allows_up_to_the_limit(self):
        limiter = SlidingWindowLimiter(limit=3, window_seconds=60)
        assert [limiter.check("ip")[0] for _ in range(3)] == [True, True, True]

    def test_refuses_once_the_window_is_full(self):
        limiter = SlidingWindowLimiter(limit=2, window_seconds=60)
        limiter.check("ip")
        limiter.check("ip")
        allowed, retry_after = limiter.check("ip")
        assert allowed is False
        assert 0 < retry_after <= 61

    def test_each_caller_has_their_own_allowance(self):
        limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
        assert limiter.check("a")[0] is True
        assert limiter.check("b")[0] is True, "one caller must not exhaust another's quota"
        assert limiter.check("a")[0] is False

    def test_old_hits_fall_out_of_the_window(self):
        limiter = SlidingWindowLimiter(limit=1, window_seconds=1)
        assert limiter.check("ip")[0] is True
        assert limiter.check("ip")[0] is False
        time.sleep(1.05)
        assert limiter.check("ip")[0] is True, "the window should slide, not reset hourly"

    def test_retry_after_is_never_zero(self):
        # A client told to retry in 0 seconds would hammer the endpoint.
        limiter = SlidingWindowLimiter(limit=1, window_seconds=1)
        limiter.check("ip")
        _, retry_after = limiter.check("ip")
        assert retry_after >= 1


class TestClientKey:
    def _request(self, headers: dict[str, str], host: str | None = "10.0.0.1"):
        return SimpleNamespace(
            headers=headers, client=SimpleNamespace(host=host) if host else None
        )

    def test_prefers_the_forwarded_header(self):
        # Behind Render's proxy every request has the same request.client.host, so
        # without this one visitor would exhaust the limit for everyone.
        request = self._request({"x-forwarded-for": "203.0.113.5"})
        assert client_key(request) == "203.0.113.5"

    def test_takes_the_original_client_from_a_proxy_chain(self):
        request = self._request({"x-forwarded-for": "203.0.113.5, 70.41.3.18, 10.0.0.1"})
        assert client_key(request) == "203.0.113.5"

    def test_falls_back_to_the_socket_address(self):
        assert client_key(self._request({})) == "10.0.0.1"

    def test_handles_a_missing_client(self):
        assert client_key(self._request({}, host=None)) == "unknown"


class TestEndpointIntegration:
    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        from fastapi.testclient import TestClient

        from app.agent.planner import PlanningResult
        from app.config import get_settings
        from app.main import create_app
        from app.models.plan import AnalysisPlan

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setenv("CTGOV_VIZ_CACHE_ENABLED", "false")
        monkeypatch.setenv("CTGOV_VIZ_RATE_LIMIT_PER_HOUR", "2")
        get_settings.cache_clear()

        plan = AnalysisPlan.model_validate({
            "interpretation": "Phase distribution.",
            "retrieval": {"cohorts": [{"name": "A", "filters": {"conditions": ["melanoma"]}}]},
            "analysis": {"kind": "group_by", "dimension": "phase"},
            "visualization": {"type": "bar_chart", "title": "Trials by Phase"},
        })

        async def fake_plan(self, request):
            return PlanningResult(plan=plan.model_copy(deep=True))

        monkeypatch.setattr("app.agent.planner.LLMPlanner.plan", fake_plan)
        with TestClient(create_app()) as c:
            yield c
        get_settings.cache_clear()

    def test_plan_endpoint_refuses_past_the_limit(self, client):
        body = {"query": "How are melanoma trials distributed across phases?"}
        assert client.post("/api/v1/plan", json=body).status_code == 200
        assert client.post("/api/v1/plan", json=body).status_code == 200

        response = client.post("/api/v1/plan", json=body)
        assert response.status_code == 429
        payload = response.json()
        assert payload["error"] == "rate_limited"
        assert "remedy" in payload, "a 429 should say when to come back"

    def test_free_endpoints_are_never_limited(self, client):
        # These cost nothing to serve, so a limit would only hurt the demo.
        for _ in range(6):
            assert client.get("/api/v1/health").status_code == 200
            assert client.get("/api/v1/capabilities").status_code == 200

    def test_separate_clients_are_tracked_separately(self, client):
        body = {"query": "How are melanoma trials distributed across phases?"}
        for _ in range(3):
            client.post("/api/v1/plan", json=body, headers={"x-forwarded-for": "1.1.1.1"})
        # A different visitor should still get through.
        response = client.post(
            "/api/v1/plan", json=body, headers={"x-forwarded-for": "2.2.2.2"}
        )
        assert response.status_code == 200
