"""
Custom A* Routing Engine
Implements A* from scratch on top of GraphManager — NetworkX's built-in
shortest_path is intentionally avoided to allow full control over turn
penalties and edge-weight logic.

Heuristic: Haversine distance to destination divided by a free-flow speed,
giving an admissible lower bound on remaining travel time.

Turn penalty model:
  straight   →  0 s
  right turn →  5 s
  left turn  → 15 s
  U-turn     → 30 s
"""
from __future__ import annotations

import heapq
import math
from typing import List, Optional, Tuple

from graph_manager import GraphManager

# -----------------------------------------------------------------------
# Turn penalties (seconds) — tuned to urban intersections
# -----------------------------------------------------------------------
TURN_PENALTIES: dict[str, float] = {
    "straight": 0.0,
    "right":    5.0,
    "left":    15.0,
    "u_turn":  30.0,
}

# Speed used for the A* heuristic: assume free-flow ~80 km/h for a lower bound
HEURISTIC_SPEED_KMH = 80.0


# -----------------------------------------------------------------------
# Geometry helpers
# -----------------------------------------------------------------------

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two (lat, lon) points."""
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def compute_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing (degrees, 0–360) from point 1 to point 2."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    x = math.sin(dlambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def classify_turn(bearing_in: float, bearing_out: float) -> str:
    """
    Classify the manoeuvre at an intersection.
    bearing_in  – direction of travel arriving at the node
    bearing_out – direction of travel leaving the node
    """
    diff = (bearing_out - bearing_in + 360) % 360
    if diff < 30 or diff > 330:
        return "straight"
    if 30 <= diff <= 150:
        return "right"
    if 210 <= diff <= 330:
        return "left"
    return "u_turn"


# -----------------------------------------------------------------------
# A* implementation
# -----------------------------------------------------------------------

def astar(
    graph_manager: GraphManager,
    origin: int,
    destination: int,
) -> Tuple[Optional[List[int]], float]:
    """
    Find the lowest-cost path from *origin* to *destination* using A*.

    Returns
    -------
    (path, cost)  where path is an ordered list of node ids and cost is the
    total travel time in seconds.  Returns (None, inf) if no path exists.
    """
    dest_lat, dest_lng = graph_manager.get_node_coords(destination)

    def heuristic(node: int) -> float:
        lat, lng = graph_manager.get_node_coords(node)
        dist_m = haversine(lat, lng, dest_lat, dest_lng)
        # Divide by free-flow speed (m/s) to get a time lower bound
        return dist_m / (HEURISTIC_SPEED_KMH / 3.6)

    INF = float("inf")

    # g_scores[node] = best known cost to reach node
    g_scores: dict[int, float] = {origin: 0.0}

    # came_from[node] = parent node on the best known path
    came_from: dict[int, int] = {}

    # arriving_bearing[node] = bearing of the segment that last updated g_scores[node]
    arriving_bearing: dict[int, Optional[float]] = {origin: None}

    # Heap entries: (f_score, tie_breaker, node)
    # We look up g_scores separately to avoid stale entries.
    counter = 0
    heap: list[tuple[float, int, int]] = [(heuristic(origin), counter, origin)]

    while heap:
        f, _, current = heapq.heappop(heap)

        # Early exit
        if current == destination:
            return _reconstruct(came_from, current), g_scores[current]

        g = g_scores.get(current, INF)

        # Stale entry — a better path was already found
        if f > g + heuristic(current) + 1e-9:
            continue

        cur_lat, cur_lng = graph_manager.get_node_coords(current)
        bearing_in = arriving_bearing.get(current)

        for neighbor in graph_manager.get_neighbors(current):
            edge_w = graph_manager.get_edge_weight(current, neighbor)
            if edge_w == INF:
                continue  # closed road

            nbr_lat, nbr_lng = graph_manager.get_node_coords(neighbor)
            bearing_out = compute_bearing(cur_lat, cur_lng, nbr_lat, nbr_lng)

            # Turn penalty
            turn_cost = 0.0
            if bearing_in is not None:
                turn_type = classify_turn(bearing_in, bearing_out)
                turn_cost = TURN_PENALTIES[turn_type]

            tentative_g = g + edge_w + turn_cost

            if tentative_g < g_scores.get(neighbor, INF):
                g_scores[neighbor] = tentative_g
                came_from[neighbor] = current
                arriving_bearing[neighbor] = bearing_out
                counter += 1
                heapq.heappush(
                    heap,
                    (tentative_g + heuristic(neighbor), counter, neighbor),
                )

    return None, INF


def _reconstruct(came_from: dict[int, int], current: int) -> List[int]:
    path: list[int] = []
    node: Optional[int] = current
    while node is not None:
        path.append(node)
        node = came_from.get(node)
    path.reverse()
    return path
