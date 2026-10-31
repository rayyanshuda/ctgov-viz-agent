"""The web pages the server hands out: the React app, its fallback, and the old demo page."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.main import create_app

REACT_HTML = "<html><body>React app</body></html>"


@pytest.fixture
def built_frontend(tmp_path, monkeypatch):
    """A tiny fake `npm run build` folder, so the tests don't depend on a real build."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(REACT_HTML)
    (dist / "assets" / "app.js").write_text("console.log('hi')")
    monkeypatch.setattr(main, "FRONTEND_DIR", dist)
    return dist


@pytest.mark.parametrize("path", ["/", "/charts", "/c/abc123"])
def test_react_pages_return_index_html(built_frontend, path):
    # React draws these pages in the browser, so the server just hands over index.html.
    response = TestClient(create_app()).get(path)
    assert response.status_code == 200
    assert response.text == REACT_HTML


def test_built_assets_are_served(built_frontend):
    response = TestClient(create_app()).get("/assets/app.js")
    assert response.status_code == 200
    assert "console.log" in response.text


def test_legacy_page_is_still_available(built_frontend):
    response = TestClient(create_app()).get("/legacy")
    assert response.status_code == 200
    assert response.text == (main.DEMO_DIR / "index.html").read_text()


def test_mistyped_api_path_is_a_404_not_a_web_page(built_frontend):
    response = TestClient(create_app()).get("/api/v1/nope")
    assert response.status_code == 404
    assert "React app" not in response.text


def test_api_docs_still_work_next_to_the_react_fallback(built_frontend):
    client = TestClient(create_app())
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_without_a_frontend_build_the_root_shows_the_legacy_page(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "FRONTEND_DIR", tmp_path / "no-build-here")
    response = TestClient(create_app()).get("/")
    assert response.status_code == 200
    assert response.text == (main.DEMO_DIR / "index.html").read_text()
