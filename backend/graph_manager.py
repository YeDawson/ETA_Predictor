"""
Road Graph Manager
Wraps osmnx + NetworkX. Downloads a city road network, caches it in memory,
computes traffic-weighted edge costs, and applies/reverts congestion events.
All reads and writes are protected by a single reentrant lock so the FastAPI
event loop (plus any background threads) can safely share the graph.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Optional, Tuple

import networkx as nx
import osmnx as ox

logger = logging.getLogger(__name__)

# Default bounding box: downtown San Francisco
DEFAULT_PLACE = os.getenv("ETA_CITY", "San Francisco, California, USA")

# Speed used when no speed attribute is present on an edge (km/h)
FALLBACK_SPEED_KMH = 50.0


class GraphManager:
    """Thread-safe wrapper around an osmnx MultiDiGraph."""

    def __init__(self, place: str = DEFAULT_PLACE) -> None:
        self._place = place
        self._lock = threading.RLock()
        self._graph: Optional[nx.MultiDiGraph] = None
        self._loaded = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def load(self, place: str | None = None) -> None:
        """Download and cache the road network.  Blocks until complete."""
        target = place or self._place
        logger.info("Downloading road network for '%s' …", target)
        G = ox.graph_from_place(target, network_type="drive")
        G = ox.add_edge_speeds(G)          # fills 'speed_kph' from OSM maxspeed tags
        G = ox.add_edge_travel_times(G)    # fills 'travel_time' (seconds)
        with self._lock:
            self._graph = G
            self._loaded = True
        logger.info(
            "Graph loaded: %d nodes, %d edges",
            G.number_of_nodes(),
            G.number_of_edges(),
        )

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def graph(self) -> nx.MultiDiGraph:
        return self._graph  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Coordinate helpers
    # ------------------------------------------------------------------

    def snap_to_node(self, lat: float, lng: float) -> int:
        """Return the graph node id nearest to (lat, lng)."""
        self._require_loaded()
        with self._lock:
            # ox.nearest_nodes expects (X=lng, Y=lat)
            return ox.nearest_nodes(self._graph, X=lng, Y=lat)

    def get_node_coords(self, node: int) -> Tuple[float, float]:
        """Return (lat, lng) for a graph node."""
        with self._lock:
            d = self._graph.nodes[node]
            return d["y"], d["x"]   # osmnx stores y=lat, x=lng

    # ------------------------------------------------------------------
    # Edge weights
    # ------------------------------------------------------------------

    def _base_travel_time(self, edge_data: dict) -> float:
        """Compute travel time in seconds from raw edge attributes."""
        length = edge_data.get("length", 100.0)         # metres
        speed = edge_data.get("speed_kph", FALLBACK_SPEED_KMH)  # km/h
        if speed <= 0:
            speed = FALLBACK_SPEED_KMH
        # length(m) / (speed(km/h) * 1000/3600)  →  seconds
        return length / (speed / 3.6)

    def get_edge_weight(self, u: int, v: int) -> float:
        """
        Return the effective travel time (seconds) for the best parallel edge
        between u and v.  Returns inf if the edge has been closed.
        """
        with self._lock:
            parallel = self._graph[u][v]           # dict of {key: edge_data}
            best = float("inf")
            for data in parallel.values():
                w = data.get("current_weight", self._base_travel_time(data))
                if w < best:
                    best = w
            return best

    def get_edge_data(self, u: int, v: int) -> dict:
        """Return the attributes of the lowest-weight parallel edge."""
        with self._lock:
            parallel = self._graph[u][v]
            return min(
                parallel.values(),
                key=lambda d: d.get("current_weight", self._base_travel_time(d)),
            )

    def get_neighbors(self, node: int) -> list[int]:
        with self._lock:
            return list(self._graph.successors(node))

    # ------------------------------------------------------------------
    # Event injection
    # ------------------------------------------------------------------

    def apply_event(
        self,
        latlng: Tuple[float, float],
        severity: float,
        closed: bool,
    ) -> Tuple[int, int, int]:
        """
        Find the road segment nearest to *latlng* and apply a congestion
        event or closure.  Mutates edges in both directions.

        Returns the (u, v, key) tuple of the affected edge.
        """
        self._require_loaded()
        lat, lng = latlng
        with self._lock:
            u, v, k = ox.nearest_edges(self._graph, X=lng, Y=lat)
            for src, dst in ((u, v), (v, u)):
                if not self._graph.has_edge(src, dst):
                    continue
                for key, data in self._graph[src][dst].items():
                    base = self._base_travel_time(data)
                    data["current_weight"] = float("inf") if closed else base * severity
        logger.info(
            "Event applied — edge (%s→%s), severity=%.1f, closed=%s",
            u, v, severity, closed,
        )
        return u, v, k

    def reset_event(self, u: int, v: int) -> None:
        """Remove the current_weight override from both directions of an edge."""
        with self._lock:
            for src, dst in ((u, v), (v, u)):
                if self._graph.has_edge(src, dst):
                    for data in self._graph[src][dst].values():
                        data.pop("current_weight", None)

    def reset_all_events(self) -> None:
        """Clear every current_weight override on the graph."""
        with self._lock:
            for _, _, data in self._graph.edges(data=True):
                data.pop("current_weight", None)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _require_loaded(self) -> None:
        if not self._loaded:
            raise RuntimeError(
                "Graph not loaded. Call graph_manager.load() first."
            )
