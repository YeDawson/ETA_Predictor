"""
Performance benchmarks for the A* routing engine.
Run with: pytest tests/performance/ --benchmark-only
"""
from __future__ import annotations

import pytest

from routing import astar


# ── Benchmarks ────────────────────────────────────────────────────────────────

def test_astar_short_route_benchmark(benchmark, graph_manager):
    """A* on a ~2-edge path (node 0 → node 2)."""
    result = benchmark(astar, graph_manager, 0, 2)
    path, cost = result
    assert path is not None


def test_astar_long_route_benchmark(benchmark, graph_manager):
    """A* on the longest diagonal path (node 0 → node 5)."""
    result = benchmark(astar, graph_manager, 0, 5)
    path, cost = result
    assert path is not None


def test_astar_repeated_queries_benchmark(benchmark, graph_manager):
    """Simulate 10 sequential route queries."""
    def run_ten():
        for _ in range(10):
            astar(graph_manager, 0, 5)

    benchmark(run_ten)
