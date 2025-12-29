"""Unit tests for routing.py — geometry helpers and A* algorithm."""
from __future__ import annotations

import math

import pytest

from routing import (
    astar,
    classify_turn,
    compute_bearing,
    haversine,
)


# ── haversine ─────────────────────────────────────────────────────────────────

def test_haversine_same_point():
    assert haversine(37.0, -122.0, 37.0, -122.0) == pytest.approx(0.0)


def test_haversine_sf_to_la():
    # San Francisco → Los Angeles ≈ 559 km
    d = haversine(37.7749, -122.4194, 34.0522, -118.2437)
    assert 550_000 < d < 570_000


def test_haversine_symmetry():
    d1 = haversine(37.0, -122.0, 38.0, -121.0)
    d2 = haversine(38.0, -121.0, 37.0, -122.0)
    assert d1 == pytest.approx(d2, rel=1e-9)


def test_haversine_non_negative():
    assert haversine(0.0, 0.0, 1.0, 1.0) > 0


# ── compute_bearing ───────────────────────────────────────────────────────────

def test_bearing_due_north():
    b = compute_bearing(0.0, 0.0, 1.0, 0.0)
    assert b == pytest.approx(0.0, abs=0.5)


def test_bearing_due_east():
    b = compute_bearing(0.0, 0.0, 0.0, 1.0)
    assert b == pytest.approx(90.0, abs=0.5)


def test_bearing_due_south():
    b = compute_bearing(1.0, 0.0, 0.0, 0.0)
    assert b == pytest.approx(180.0, abs=0.5)


def test_bearing_due_west():
    b = compute_bearing(0.0, 1.0, 0.0, 0.0)
    assert b == pytest.approx(270.0, abs=0.5)


# ── classify_turn ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("diff,expected", [
    (0,   "straight"),
    (15,  "straight"),
    (345, "straight"),
    (90,  "right"),
    (45,  "right"),
    (270, "left"),
    (315, "left"),
    (180, "u_turn"),
])
def test_classify_turn(diff, expected):
    # bearing_in = 0 (north), bearing_out = bearing_in + diff
    result = classify_turn(0.0, float(diff))
    assert result == expected


# ── A* routing ────────────────────────────────────────────────────────────────

def test_astar_finds_direct_path(graph_manager):
    """0 → 2 via the grid: expects path 0-1-2."""
    path, cost = astar(graph_manager, 0, 2)
    assert path is not None
    assert path[0] == 0
    assert path[-1] == 2
    assert cost > 0


def test_astar_origin_equals_destination(graph_manager):
    """Trivial path: same node."""
    path, cost = astar(graph_manager, 3, 3)
    # Some implementations return a single-element path; cost should be 0
    assert path is not None
    assert path[-1] == 3
    assert cost == pytest.approx(0.0, abs=1e-6)


def test_astar_no_path_on_disconnected_graph(graph_manager):
    """Add an isolated node — A* should return (None, inf)."""
    graph_manager.graph.add_node(99, y=38.0, x=-121.0)
    path, cost = astar(graph_manager, 0, 99)
    assert path is None
    assert cost == float("inf")


def test_astar_avoids_closed_edge(graph_manager):
    """Close the direct 0→1 edge; the path should go around (0→3→4→1)."""
    graph_manager.graph[0][1][0]["current_weight"] = float("inf")
    graph_manager.graph[1][0][0]["current_weight"] = float("inf")

    path, cost = astar(graph_manager, 0, 1)
    assert path is not None
    # Direct edge is closed, so path must be longer than 2 nodes
    assert len(path) > 2
    assert path[0] == 0
    assert path[-1] == 1


def test_astar_cost_is_positive(graph_manager):
    path, cost = astar(graph_manager, 0, 5)
    assert path is not None
    assert cost > 0


def test_astar_longer_path_has_higher_cost(graph_manager):
    _, cost_short = astar(graph_manager, 0, 1)
    _, cost_long  = astar(graph_manager, 0, 5)
    assert cost_long > cost_short
