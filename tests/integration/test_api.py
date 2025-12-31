"""
Integration tests for the FastAPI endpoints.
The real GraphManager and ETAModel are replaced with lightweight fakes
using FastAPI's dependency_overrides — no OSM download required.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main
from eta_model import ETAModel
from graph_manager import GraphManager

# ── Dependency overrides ──────────────────────────────────────────────────────

# Re-use fixtures from conftest.py via indirection
_fake_gm: GraphManager | None = None
_fake_em: ETAModel | None = None


def _get_fake_gm():
    return _fake_gm


def _get_fake_em():
    return _fake_em


@pytest.fixture(autouse=True)
def inject_fakes(graph_manager, eta_model):
    global _fake_gm, _fake_em
    _fake_gm = graph_manager
    _fake_em = eta_model
    main.app.dependency_overrides[main.get_graph_manager] = _get_fake_gm
    main.app.dependency_overrides[main.get_eta_model]     = _get_fake_em
    yield
    main.app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(main.app)


# ── /health ───────────────────────────────────────────────────────────────────

def test_health_returns_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["graph_loaded"] is True


# ── POST /route ───────────────────────────────────────────────────────────────

def test_route_returns_path_and_eta(client):
    r = client.post("/route", json={
        "origin":      {"lat": 37.00, "lng": -122.00},   # node 0
        "destination": {"lat": 37.00, "lng": -121.98},   # node 2
        "hour": 9,
        "day_of_week": 1,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["path"]) >= 2
    assert body["eta_seconds"] > 0
    assert body["distance_m"]  > 0


def test_route_path_starts_at_origin_ends_at_dest(client):
    r = client.post("/route", json={
        "origin":      {"lat": 37.00, "lng": -122.00},
        "destination": {"lat": 37.01, "lng": -121.98},
        "hour": 17,
        "day_of_week": 4,
    })
    assert r.status_code == 200
    body = r.json()
    # First and last coords should be near origin and destination
    first = body["path"][0]
    last  = body["path"][-1]
    assert abs(first[0] - 37.00)  < 0.05
    assert abs(last[0]  - 37.01)  < 0.05


def test_route_same_origin_destination_returns_400(client):
    r = client.post("/route", json={
        "origin":      {"lat": 37.00, "lng": -122.00},
        "destination": {"lat": 37.00, "lng": -122.00},
    })
    assert r.status_code == 400


# ── POST /eta ─────────────────────────────────────────────────────────────────

def test_eta_returns_positive_value(client):
    r = client.post("/eta", json={
        "path": [[37.00, -122.00], [37.00, -121.99], [37.00, -121.98]],
        "hour": 9,
        "day_of_week": 1,
    })
    assert r.status_code == 200
    assert r.json()["eta_seconds"] > 0


# ── POST /event ───────────────────────────────────────────────────────────────

def test_event_without_reroute_context(client):
    r = client.post("/event", json={
        "edge":     [37.005, -121.995],
        "severity": 3.0,
        "closed":   False,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "event_applied"


def test_event_with_reroute_context_returns_new_path(client):
    r = client.post("/event", json={
        "edge":        [37.005, -121.995],
        "severity":    4.0,
        "closed":      False,
        "origin":      {"lat": 37.00, "lng": -122.00},
        "destination": {"lat": 37.01, "lng": -121.98},
        "hour": 9,
        "day_of_week": 1,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "event_applied"
    assert isinstance(body["new_path"], list)
    assert body["new_eta_seconds"] >= 0


# ── DELETE /event ─────────────────────────────────────────────────────────────

def test_reset_events(client):
    # Apply an event first
    client.post("/event", json={"edge": [37.005, -121.995], "severity": 5.0})
    # Then reset
    r = client.delete("/event")
    assert r.status_code == 200
    assert r.json()["status"] == "all_events_cleared"
