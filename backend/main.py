"""
Smart ETA Predictor — FastAPI Backend
"""
from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from eta_model import ETAModel
from graph_manager import GraphManager
from routing import astar

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App & CORS
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Smart ETA Predictor",
    description="Graph-based routing with ML-powered ETA prediction and live rerouting.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Singletons — created at import time, populated during startup
# ---------------------------------------------------------------------------

_graph_manager = GraphManager()
_eta_model = ETAModel()


def get_graph_manager() -> GraphManager:
    return _graph_manager


def get_eta_model() -> ETAModel:
    return _eta_model


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------


@app.on_event("startup")
async def startup() -> None:
    loop = asyncio.get_event_loop()

    logger.info("Loading road graph (this may take ~60 s on first run) …")
    try:
        await loop.run_in_executor(None, _graph_manager.load)
    except Exception as exc:
        logger.error("Graph load failed: %s — /route and /event will return 503.", exc)

    logger.info("Loading ETA model …")
    _eta_model.load()

    logger.info("Startup complete.")


# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------


class _ConnectionManager:
    def __init__(self) -> None:
        self._active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._active.append(ws)
        logger.debug("WS client connected (total=%d)", len(self._active))

    def disconnect(self, ws: WebSocket) -> None:
        self._active.remove(ws)
        logger.debug("WS client disconnected (total=%d)", len(self._active))

    async def broadcast(self, payload: dict) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._active):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._active.remove(ws)


ws_manager = _ConnectionManager()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class LatLng(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)


class RouteRequest(BaseModel):
    origin: LatLng
    destination: LatLng
    hour: int = Field(9, ge=0, le=23)
    day_of_week: int = Field(1, ge=0, le=6)


class RouteResponse(BaseModel):
    path: List[List[float]]   # [[lat, lng], …]
    eta_seconds: float
    distance_m: float


class ETARequest(BaseModel):
    path: List[List[float]]
    hour: int = Field(9, ge=0, le=23)
    day_of_week: int = Field(1, ge=0, le=6)


class ETAResponse(BaseModel):
    eta_seconds: float


class EventRequest(BaseModel):
    edge: List[float] = Field(..., min_length=2, max_length=2,
                              description="[lat, lng] of a point on the affected segment")
    severity: float = Field(2.0, ge=1.0, le=10.0,
                            description="Speed multiplier (1 = normal, 5 = very congested)")
    closed: bool = False
    # Optional: reroute context supplied by the client
    origin: Optional[LatLng] = None
    destination: Optional[LatLng] = None
    hour: int = Field(12, ge=0, le=23)
    day_of_week: int = Field(1, ge=0, le=6)


class EventResponse(BaseModel):
    status: str
    new_path: List[List[float]]
    new_eta_seconds: float


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_graph(gm: GraphManager) -> None:
    if not gm.is_loaded:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Road graph is not available. Check server logs.",
        )


def _nodes_to_latlng(nodes: List[int], gm: GraphManager) -> List[List[float]]:
    return [list(gm.get_node_coords(n)) for n in nodes]


def _path_distance_m(nodes: List[int], gm: GraphManager) -> float:
    G = gm.graph
    total = 0.0
    for u, v in zip(nodes[:-1], nodes[1:]):
        edges = G[u][v]
        total += min(d.get("length", 0.0) for d in edges.values())
    return total


def _build_segments(nodes: List[int], gm: GraphManager) -> list[dict]:
    """Assemble per-segment feature dicts for the ETA model."""
    segments: list[dict] = []
    for u, v in zip(nodes[:-1], nodes[1:]):
        data = gm.get_edge_data(u, v)
        highway = data.get("highway", "unclassified")
        if isinstance(highway, list):
            highway = highway[0]
        speed_limit = data.get("speed_kph", 50.0)
        segments.append({
            "road_type":            highway,
            "length":               data.get("length", 100.0),
            "speed_limit":          speed_limit,
            # Approximate historical average as 80 % of posted speed limit
            "historical_avg_speed": speed_limit * 0.8,
        })
    return segments


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------


@app.post("/route", response_model=RouteResponse, summary="Compute optimal route + ETA")
async def route_endpoint(
    req: RouteRequest,
    gm: GraphManager = Depends(get_graph_manager),
    em: ETAModel = Depends(get_eta_model),
) -> RouteResponse:
    _require_graph(gm)

    origin_node = gm.snap_to_node(req.origin.lat, req.origin.lng)
    dest_node   = gm.snap_to_node(req.destination.lat, req.destination.lng)

    if origin_node == dest_node:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Origin and destination map to the same graph node.",
        )

    path_nodes, _ = astar(gm, origin_node, dest_node)
    if path_nodes is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No route found between the given coordinates.",
        )

    segments  = _build_segments(path_nodes, gm)
    eta       = em.predict_path(segments, req.hour, req.day_of_week)
    distance  = _path_distance_m(path_nodes, gm)

    return RouteResponse(
        path=_nodes_to_latlng(path_nodes, gm),
        eta_seconds=round(eta, 1),
        distance_m=round(distance, 1),
    )


@app.post("/eta", response_model=ETAResponse, summary="Refine ETA for an existing path")
async def eta_endpoint(
    req: ETARequest,
    gm: GraphManager = Depends(get_graph_manager),
    em: ETAModel = Depends(get_eta_model),
) -> ETAResponse:
    _require_graph(gm)

    # Snap each lat/lng point to the nearest graph node
    nodes    = [gm.snap_to_node(p[0], p[1]) for p in req.path]
    segments = _build_segments(nodes, gm)
    eta      = em.predict_path(segments, req.hour, req.day_of_week)

    return ETAResponse(eta_seconds=round(eta, 1))


@app.post("/event", response_model=EventResponse, summary="Inject a congestion/closure event")
async def event_endpoint(
    req: EventRequest,
    gm: GraphManager = Depends(get_graph_manager),
    em: ETAModel = Depends(get_eta_model),
) -> EventResponse:
    _require_graph(gm)

    lat, lng = req.edge
    gm.apply_event((lat, lng), req.severity, req.closed)

    # Reroute if origin + destination were supplied
    new_path: list[list[float]] = []
    new_eta = 0.0

    if req.origin and req.destination:
        origin_node = gm.snap_to_node(req.origin.lat, req.origin.lng)
        dest_node   = gm.snap_to_node(req.destination.lat, req.destination.lng)
        new_nodes, _ = astar(gm, origin_node, dest_node)

        if new_nodes:
            segments = _build_segments(new_nodes, gm)
            new_eta  = em.predict_path(segments, req.hour, req.day_of_week)
            new_path = _nodes_to_latlng(new_nodes, gm)

            # Push the updated route to all connected WebSocket clients
            await ws_manager.broadcast({
                "type":            "reroute",
                "new_path":        new_path,
                "new_eta_seconds": round(new_eta, 1),
            })

    return EventResponse(
        status="event_applied",
        new_path=new_path,
        new_eta_seconds=round(new_eta, 1),
    )


@app.delete("/event", summary="Reset all active congestion events")
async def reset_events(
    gm: GraphManager = Depends(get_graph_manager),
) -> dict:
    _require_graph(gm)
    gm.reset_all_events()
    return {"status": "all_events_cleared"}


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


@app.websocket("/ws/route")
async def ws_route(websocket: WebSocket) -> None:
    """
    Clients connect here to receive push notifications when the server
    detects a reroute-triggering event.  The connection is kept alive;
    the server pushes JSON messages of the form:
        { "type": "reroute", "new_path": [...], "new_eta_seconds": 540 }
    """
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep the connection open; we don't need to process inbound msgs
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/health")
async def health(gm: GraphManager = Depends(get_graph_manager)) -> dict:
    return {
        "status":       "ok",
        "graph_loaded": gm.is_loaded,
        "model_loaded": _eta_model.is_loaded,
    }
