# Smart ETA Predictor

A graph-based routing service with ML-powered ETA prediction and live rerouting.

The backend downloads a real city road network (San Francisco by default via OSM), runs a custom A\* algorithm with turn penalties, and predicts travel time per road segment using an XGBoost model. A WebSocket endpoint pushes reroute notifications to connected clients when congestion events are injected. The frontend is a Leaflet map served as static files.

---

## Architecture

```
frontend/           Static HTML + Leaflet map UI
backend/
  main.py           FastAPI app — REST + WebSocket endpoints
  graph_manager.py  osmnx/NetworkX wrapper, thread-safe event injection
  routing.py        Custom A* with haversine heuristic + turn penalties
  eta_model.py      XGBoost regressor (falls back to speed-limit heuristic)
  models/           Trained model artifact (.pkl) — produced by notebook
notebooks/
  train_eta_model.ipynb   Synthetic data generation + XGBoost training
tests/
  unit/             Graph, routing, model unit tests (no OSM download)
  integration/      Full API endpoint tests (fake graph injected via DI)
  performance/      A* benchmark suite (pytest-benchmark)
```

---

## Prerequisites

- Python 3.10+
- The `.venv` virtual environment is already present in the repo.

---

## Setup

```bash
# Activate the existing virtual environment
source .venv/bin/activate

# Install all dependencies
pip install -r requirements.txt
```

---

## Running the Backend

The backend modules use bare imports (`from eta_model import ...`), so the server **must be started from the `backend/` directory**.

```bash
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

On first run, startup will download the San Francisco road network from OpenStreetMap. This takes **~30–60 seconds** and requires an internet connection. Subsequent runs use the in-memory graph (no caching to disk by default).

To use a different city, set the `ETA_CITY` environment variable before starting:

```bash
ETA_CITY="Austin, Texas, USA" uvicorn main:app --reload
```

The server is ready when you see:

```
INFO  — Startup complete.
```

Interactive API docs are available at:
- Swagger UI: http://localhost:8000/docs
- ReDoc:       http://localhost:8000/redoc

---

## (Optional) Train the ETA Model

Without a trained model the service falls back to a speed-limit heuristic, which still works. To train the XGBoost model on synthetic data:

```bash
cd notebooks
jupyter notebook train_eta_model.ipynb
```

Run all cells in order. The final cell writes `backend/models/eta_model.pkl`. On the next server startup the model is loaded automatically and `/health` will show `"model_loaded": true`.

---

## Running the Frontend

The frontend is plain static files — no build step required. Open `frontend/index.html` directly in a browser:

```bash
open frontend/index.html        # macOS
# or just drag the file into a browser tab
```

The page connects to `http://localhost:8000` by default. Enter origin/destination coordinates (lat/lng), pick hour and day-of-week, then click **Find Route**.

---

## API Reference

All endpoints accept and return JSON.

### `GET /health`

Check whether the graph and model are loaded.

```bash
curl http://localhost:8000/health
```

```json
{ "status": "ok", "graph_loaded": true, "model_loaded": false }
```

---

### `POST /route`

Compute the optimal route and ETA between two coordinates.

**Request body**

| Field | Type | Default | Notes |
|---|---|---|---|
| `origin` | `{lat, lng}` | required | |
| `destination` | `{lat, lng}` | required | |
| `hour` | int 0–23 | `9` | Used for ETA prediction |
| `day_of_week` | int 0–6 | `1` | 0 = Sunday |

```bash
curl -X POST http://localhost:8000/route \
  -H "Content-Type: application/json" \
  -d '{
    "origin":      { "lat": 37.7749, "lng": -122.4194 },
    "destination": { "lat": 37.7849, "lng": -122.4094 },
    "hour": 9,
    "day_of_week": 1
  }'
```

**Response**

```json
{
  "path":        [[37.775, -122.419], [37.776, -122.415], ...],
  "eta_seconds": 312.5,
  "distance_m":  1840.0
}
```

`path` is an ordered list of `[lat, lng]` waypoints.

---

### `POST /eta`

Re-calculate ETA for an existing path (e.g. after conditions change) without re-running A\*.

```bash
curl -X POST http://localhost:8000/eta \
  -H "Content-Type: application/json" \
  -d '{
    "path": [[37.775, -122.419], [37.776, -122.415], [37.780, -122.410]],
    "hour": 17,
    "day_of_week": 3
  }'
```

```json
{ "eta_seconds": 427.0 }
```

---

### `POST /event`

Inject a congestion event or road closure on the segment nearest to the given point. If `origin` and `destination` are supplied, the server immediately reroutes and pushes the new path to all connected WebSocket clients.

| Field | Type | Default | Notes |
|---|---|---|---|
| `edge` | `[lat, lng]` | required | Any point on the affected segment |
| `severity` | float 1–10 | `2.0` | Travel-time multiplier (1 = normal, 5 = heavy congestion) |
| `closed` | bool | `false` | `true` makes the edge impassable |
| `origin` | `{lat, lng}` | optional | If set, triggers reroute |
| `destination` | `{lat, lng}` | optional | Required together with `origin` |
| `hour` | int 0–23 | `12` | |
| `day_of_week` | int 0–6 | `1` | |

```bash
# Moderate congestion, no reroute
curl -X POST http://localhost:8000/event \
  -H "Content-Type: application/json" \
  -d '{ "edge": [37.778, -122.413], "severity": 3.0 }'

# Road closure with automatic reroute
curl -X POST http://localhost:8000/event \
  -H "Content-Type: application/json" \
  -d '{
    "edge":        [37.778, -122.413],
    "severity":    1.0,
    "closed":      true,
    "origin":      { "lat": 37.7749, "lng": -122.4194 },
    "destination": { "lat": 37.7849, "lng": -122.4094 },
    "hour": 9,
    "day_of_week": 1
  }'
```

```json
{
  "status":          "event_applied",
  "new_path":        [[37.775, -122.419], ...],
  "new_eta_seconds": 498.0
}
```

---

### `DELETE /event`

Clear all active congestion/closure overrides and restore normal edge weights.

```bash
curl -X DELETE http://localhost:8000/event
```

```json
{ "status": "all_events_cleared" }
```

---

### `WebSocket /ws/route`

Connect to receive push notifications whenever a `/event` call triggers a reroute.

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/route');
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  // msg.type === "reroute"
  // msg.new_path — [[lat, lng], ...]
  // msg.new_eta_seconds — float
};
```

The frontend connects automatically and updates the map overlay on each reroute message.

---

## Running Tests

Tests import the backend modules directly, so `PYTHONPATH` must point at `backend/`.

```bash
# From the project root
PYTHONPATH=backend pytest
```

### Test suites

| Suite | Path | What it covers |
|---|---|---|
| Unit | `tests/unit/` | Haversine, bearing, turn classification, A\* algorithm, GraphManager event logic, ETAModel heuristic |
| Integration | `tests/integration/` | All REST endpoints via FastAPI `TestClient` with a fake in-memory graph (no OSM download) |
| Performance | `tests/performance/` | A\* benchmark via pytest-benchmark |

### Run a specific suite

```bash
# Unit tests only
PYTHONPATH=backend pytest tests/unit/

# Integration tests only
PYTHONPATH=backend pytest tests/integration/

# Performance benchmarks only
PYTHONPATH=backend pytest tests/performance/ --benchmark-only

# With verbose output and short tracebacks (matches pytest.ini defaults)
PYTHONPATH=backend pytest -v --tb=short
```

### What the tests do NOT require

- An internet connection — the synthetic 3×2 grid graph in `tests/conftest.py` replaces the OSM download.
- A trained model — the `ETAModel` fixture runs in heuristic-fallback mode.

---

## Key Design Notes

- **A\* turn penalties**: straight = 0 s, right = 5 s, left = 15 s, U-turn = 30 s (tunable in `routing.py:TURN_PENALTIES`).
- **ETA fallback**: if no model file exists, the service computes ETA as `distance / (0.8 × speed_limit)`. All endpoints still work.
- **Thread safety**: `GraphManager` uses a reentrant lock so `/event` mutations are safe while A\* reads the graph concurrently.
- **CORS**: all origins allowed — tighten `allow_origins` in `main.py` for production.
