"""
Integration test: full routing pipeline without FastAPI.
Exercises GraphManager + A* + ETAModel together.
"""
from __future__ import annotations

import pytest

from routing import astar
from eta_model import ETAModel


def test_full_pipeline_returns_valid_eta(graph_manager, eta_model):
    """Route from node 0 to node 5, predict ETA — everything wired together."""
    path, cost = astar(graph_manager, 0, 5)
    assert path is not None, "A* should find a path on the grid"

    segments = []
    for u, v in zip(path[:-1], path[1:]):
        data = graph_manager.get_edge_data(u, v)
        highway = data.get("highway", "unclassified")
        if isinstance(highway, list):
            highway = highway[0]
        segments.append({
            "road_type":            highway,
            "length":               data.get("length", 100.0),
            "speed_limit":          data.get("speed_kph", 50.0),
            "historical_avg_speed": data.get("speed_kph", 50.0) * 0.8,
        })

    eta = eta_model.predict_path(segments, hour_of_day=9, day_of_week=1)
    assert eta > 0
    # Sanity: 0→5 is at least 2 km at 50 km/h = 144 s
    assert eta >= 100


def test_reroute_after_event_finds_alternate_path(graph_manager, eta_model):
    """Close the fastest path, reroute, confirm a valid alternate exists."""
    # Block 1→2 (the direct eastbound edge)
    graph_manager.graph[1][2][0]["current_weight"] = float("inf")
    graph_manager.graph[2][1][0]["current_weight"] = float("inf")

    path, cost = astar(graph_manager, 0, 2)
    assert path is not None
    # Direct path would be 0→1→2; blocked means route must deviate
    assert (1, 2) not in zip(path[:-1], path[1:]), "Blocked edge should not appear in rerouted path"


def test_congestion_increases_eta(graph_manager, eta_model):
    """Apply congestion; the ETA for the same route should increase."""
    path, _ = astar(graph_manager, 0, 2)
    assert path is not None

    def get_eta():
        segs = []
        for u, v in zip(path[:-1], path[1:]):
            data = graph_manager.get_edge_data(u, v)
            highway = data.get("highway", "unclassified")
            if isinstance(highway, list):
                highway = highway[0]
            eff_speed = data.get("speed_kph", 50.0) / max(
                data.get("current_weight", graph_manager._base_travel_time(data))
                / graph_manager._base_travel_time(data),
                1.0,
            )
            segs.append({
                "road_type":            highway,
                "length":               data.get("length", 100.0),
                "speed_limit":          data.get("speed_kph", 50.0),
                "historical_avg_speed": eff_speed,
            })
        return eta_model.predict_path(segs, 9, 1)

    eta_before = get_eta()
    graph_manager.apply_event((37.00, -121.99), severity=5.0, closed=False)
    eta_after  = get_eta()
    # With congestion the effective speed drops → ETA should be higher
    assert eta_after >= eta_before
