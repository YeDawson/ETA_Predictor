"""
Shared pytest fixtures.
Provides a lightweight in-memory graph so no real OSM download is needed.
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock

import networkx as nx
import pytest

from graph_manager import GraphManager
from eta_model import ETAModel


# ── Synthetic 3×2 grid graph ──────────────────────────────────────────────────
#
#   Node layout (lat increases northward, lng increases eastward):
#
#   3 ── 4 ── 5
#   |    |    |
#   0 ── 1 ── 2
#
#   All edges are bidirectional.  Edge 0→1 and 1→2 are "primary" (50 km/h).
#   Vertical edges are "residential" (40 km/h, slightly longer).

GRID_NODES = {
    0: (37.00, -122.00),
    1: (37.00, -121.99),
    2: (37.00, -121.98),
    3: (37.01, -122.00),
    4: (37.01, -121.99),
    5: (37.01, -121.98),
}

GRID_EDGES = [
    # horizontal — primary, 1 km each
    (0, 1, {"length": 1000.0, "speed_kph": 50.0, "highway": "primary"}),
    (1, 2, {"length": 1000.0, "speed_kph": 50.0, "highway": "primary"}),
    (3, 4, {"length": 1000.0, "speed_kph": 50.0, "highway": "primary"}),
    (4, 5, {"length": 1000.0, "speed_kph": 50.0, "highway": "primary"}),
    # vertical — residential, ~1.1 km each
    (0, 3, {"length": 1111.0, "speed_kph": 40.0, "highway": "residential"}),
    (1, 4, {"length": 1111.0, "speed_kph": 40.0, "highway": "residential"}),
    (2, 5, {"length": 1111.0, "speed_kph": 40.0, "highway": "residential"}),
]


def _make_grid_graph() -> nx.MultiDiGraph:
    G = nx.MultiDiGraph()
    for node_id, (lat, lng) in GRID_NODES.items():
        G.add_node(node_id, y=lat, x=lng)
    for u, v, data in GRID_EDGES:
        G.add_edge(u, v, **data)
        G.add_edge(v, u, **data)   # bidirectional
    return G


@pytest.fixture(scope="session")
def grid_graph() -> nx.MultiDiGraph:
    return _make_grid_graph()


@pytest.fixture
def graph_manager(grid_graph) -> GraphManager:
    """GraphManager pre-loaded with the synthetic grid (no OSM download)."""
    gm = GraphManager.__new__(GraphManager)
    gm._place   = "test"
    gm._lock    = threading.RLock()
    gm._graph   = grid_graph.copy()   # fresh copy per test
    gm._loaded  = True
    return gm


@pytest.fixture
def eta_model() -> ETAModel:
    """ETAModel without a trained model (heuristic fallback mode)."""
    em = ETAModel()
    # _loaded stays False → uses speed-limit heuristic
    return em
