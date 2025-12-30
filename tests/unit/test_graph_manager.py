"""Unit tests for graph_manager.py."""
from __future__ import annotations

import pytest


# ── Edge weight computation ───────────────────────────────────────────────────

def test_base_travel_time_known_values(graph_manager):
    # 1000 m at 50 km/h = 72 s
    data = {"length": 1000.0, "speed_kph": 50.0}
    t = graph_manager._base_travel_time(data)
    assert t == pytest.approx(72.0, rel=1e-4)


def test_base_travel_time_fallback_speed(graph_manager):
    """Missing speed_kph should fall back to 50 km/h."""
    data = {"length": 500.0}
    t = graph_manager._base_travel_time(data)
    assert t == pytest.approx(36.0, rel=1e-4)


def test_base_travel_time_zero_speed_uses_fallback(graph_manager):
    """Zero speed must not cause ZeroDivisionError."""
    data = {"length": 1000.0, "speed_kph": 0.0}
    t = graph_manager._base_travel_time(data)
    assert t > 0


# ── get_edge_weight ───────────────────────────────────────────────────────────

def test_get_edge_weight_normal(graph_manager):
    w = graph_manager.get_edge_weight(0, 1)
    assert w == pytest.approx(72.0, rel=1e-4)


def test_get_edge_weight_after_event(graph_manager):
    severity = 3.0
    graph_manager.apply_event((37.005, -121.995), severity, closed=False)
    # At least some edge should have increased weight (the nearest one)
    # We check overall that no weight goes negative
    for u, v, _ in graph_manager.graph.edges(data=False):
        w = graph_manager.get_edge_weight(u, v)
        assert w > 0


def test_get_edge_weight_closed_is_inf(graph_manager):
    # Manually close a specific edge
    graph_manager.graph[0][1][0]["current_weight"] = float("inf")
    assert graph_manager.get_edge_weight(0, 1) == float("inf")


# ── apply_event / reset_event ─────────────────────────────────────────────────

def test_apply_event_increases_weight(graph_manager):
    """Severity > 1 must produce a higher cost than the baseline."""
    # Baseline weight of any edge
    base_weights = {
        (u, v): graph_manager._base_travel_time(
            min(graph_manager.graph[u][v].values(),
                key=lambda d: d.get("length", 1e9))
        )
        for u, v in graph_manager.graph.edges()
    }

    graph_manager.apply_event((37.005, -121.995), severity=2.0, closed=False)

    changed = False
    for u, v in graph_manager.graph.edges():
        new_w = graph_manager.get_edge_weight(u, v)
        if new_w > base_weights[(u, v)] + 0.01:
            changed = True
            break
    assert changed, "apply_event should have increased at least one edge weight"


def test_apply_event_closed_sets_inf(graph_manager):
    graph_manager.apply_event((37.005, -121.995), severity=1.0, closed=True)

    found_inf = any(
        graph_manager.get_edge_weight(u, v) == float("inf")
        for u, v in graph_manager.graph.edges()
    )
    assert found_inf


def test_reset_all_events_restores_weights(graph_manager):
    graph_manager.apply_event((37.005, -121.995), severity=5.0, closed=False)
    graph_manager.reset_all_events()

    for _, _, data in graph_manager.graph.edges(data=True):
        assert "current_weight" not in data


# ── Coordinate helpers ────────────────────────────────────────────────────────

def test_get_node_coords_returns_latlong(graph_manager):
    lat, lng = graph_manager.get_node_coords(0)
    assert lat == pytest.approx(37.00, abs=0.001)
    assert lng == pytest.approx(-122.00, abs=0.001)


def test_snap_to_node_finds_nearest(graph_manager):
    # Coordinates very close to node 0 should snap to node 0
    node = graph_manager.snap_to_node(37.0001, -122.0001)
    assert node == 0


def test_get_neighbors_returns_connected_nodes(graph_manager):
    neighbors = graph_manager.get_neighbors(0)
    assert set(neighbors) >= {1, 3}   # 0 connects to 1 (east) and 3 (north)
