/**
 * map.js — Leaflet map, route rendering, and WebSocket handler
 *
 * Depends on: Leaflet (global L), events.js (global EventPanel)
 * Backend base URL is read from window.API_BASE or defaults to localhost:8000.
 */

const API_BASE = window.API_BASE || "http://localhost:8000";

// ── Map initialisation ────────────────────────────────────────────────────────

const map = L.map("map").setView([37.7749, -122.4194], 14);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  maxZoom: 19,
}).addTo(map);

// ── Map state ─────────────────────────────────────────────────────────────────

let routeLayer    = null;    // L.Polyline for the current route
let originMarker  = null;    // green pin
let destMarker    = null;    // red pin
let clickedLatLng = null;    // lat/lng captured by event-inject click

// ── Marker helpers ────────────────────────────────────────────────────────────

function makeIcon(color) {
  // Inline SVG circle pin — no image assets needed
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="36" viewBox="0 0 24 36">
    <path d="M12 0C5.373 0 0 5.373 0 12c0 9 12 24 12 24S24 21 24 12C24 5.373 18.627 0 12 0z" fill="${color}"/>
    <circle cx="12" cy="12" r="5" fill="white"/>
  </svg>`;
  return L.divIcon({
    html: svg,
    className: "",
    iconSize:   [24, 36],
    iconAnchor: [12, 36],
    popupAnchor:[0, -36],
  });
}

const ORIGIN_ICON = makeIcon("#1565c0");
const DEST_ICON   = makeIcon("#c62828");
const EVENT_ICON  = makeIcon("#ff8f00");

// ── Route drawing ─────────────────────────────────────────────────────────────

/**
 * Draw (or replace) the route polyline and origin/destination markers.
 * @param {number[][]} path  — [[lat,lng], …]
 */
function drawRoute(path) {
  if (routeLayer)   { map.removeLayer(routeLayer);   routeLayer   = null; }
  if (originMarker) { map.removeLayer(originMarker); originMarker = null; }
  if (destMarker)   { map.removeLayer(destMarker);   destMarker   = null; }

  if (!path || path.length < 2) return;

  routeLayer = L.polyline(path, {
    color:  "#0d47a1",
    weight: 5,
    opacity: 0.85,
    lineJoin: "round",
    lineCap:  "round",
  }).addTo(map);

  originMarker = L.marker(path[0],              { icon: ORIGIN_ICON }).addTo(map).bindPopup("Origin");
  destMarker   = L.marker(path[path.length - 1], { icon: DEST_ICON   }).addTo(map).bindPopup("Destination");

  map.fitBounds(routeLayer.getBounds(), { padding: [40, 40] });
}

/**
 * Animate a route update by briefly highlighting the new polyline in orange
 * before settling to the default blue.
 * @param {number[][]} newPath
 */
function animateReroute(newPath) {
  if (routeLayer) map.removeLayer(routeLayer);

  routeLayer = L.polyline(newPath, {
    color:  "#e65100",
    weight: 6,
    opacity: 0.9,
  }).addTo(map);

  setTimeout(() => {
    if (routeLayer) {
      routeLayer.setStyle({ color: "#0d47a1", weight: 5, opacity: 0.85 });
    }
  }, 1800);
}

// ── ETA / distance formatting ─────────────────────────────────────────────────

function fmtSeconds(s) {
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  return rem > 0 ? `${h} h ${rem} min` : `${h} h`;
}

function fmtMetres(m) {
  return m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`;
}

// ── /route call ───────────────────────────────────────────────────────────────

async function findRoute() {
  const btn = document.getElementById("find-route-btn");
  btn.disabled = true;
  btn.textContent = "Loading…";
  setStatus("Routing…", "");

  const body = {
    origin:      { lat: parseFloat(document.getElementById("origin-lat").value),
                   lng: parseFloat(document.getElementById("origin-lng").value) },
    destination: { lat: parseFloat(document.getElementById("dest-lat").value),
                   lng: parseFloat(document.getElementById("dest-lng").value) },
    hour:        parseInt(document.getElementById("hour").value, 10),
    day_of_week: parseInt(document.getElementById("day-of-week").value, 10),
  };

  try {
    const res  = await fetch(`${API_BASE}/route`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(body),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || res.statusText);
    }

    const data = await res.json();
    drawRoute(data.path);

    document.getElementById("route-info").style.display = "block";
    document.getElementById("eta-display").textContent  = fmtSeconds(data.eta_seconds);
    document.getElementById("dist-display").textContent = fmtMetres(data.distance_m);
    setStatus("Route found", "");

    // Store current route endpoints for event rerouting
    window._currentOrigin      = body.origin;
    window._currentDestination = body.destination;
    window._currentHour        = body.hour;
    window._currentDayOfWeek   = body.day_of_week;

  } catch (e) {
    setStatus(`Error: ${e.message}`, "error");
    console.error(e);
  } finally {
    btn.disabled = false;
    btn.textContent = "Find Route";
  }
}

// ── Status badge ──────────────────────────────────────────────────────────────

function setStatus(text, modifier) {
  const el = document.getElementById("status-badge");
  el.textContent = text;
  el.className   = "badge" + (modifier ? ` ${modifier}` : "");
}

// ── Button wiring ─────────────────────────────────────────────────────────────

document.getElementById("find-route-btn").addEventListener("click", findRoute);

// ── Map click for event injection ─────────────────────────────────────────────

let eventMarker = null;

map.on("click", (e) => {
  if (!EventPanel.isArmed()) return;

  clickedLatLng = e.latlng;
  if (eventMarker) map.removeLayer(eventMarker);
  eventMarker = L.marker(e.latlng, { icon: EVENT_ICON })
    .addTo(map)
    .bindPopup("Event injection point")
    .openPopup();

  document.getElementById("inject-btn").disabled = false;
});

// ── WebSocket ─────────────────────────────────────────────────────────────────

function connectWS() {
  const wsUrl = API_BASE.replace(/^http/, "ws") + "/ws/route";
  const ws    = new WebSocket(wsUrl);

  const indicator = document.getElementById("ws-status");

  ws.onopen = () => {
    indicator.textContent = "WS: connected";
    indicator.className   = "ws-indicator connected";
  };

  ws.onmessage = (evt) => {
    const msg = JSON.parse(evt.data);
    if (msg.type === "reroute") {
      animateReroute(msg.new_path);
      document.getElementById("eta-display").textContent = fmtSeconds(msg.new_eta_seconds);
      setStatus("Rerouted!", "rerouting");
      setTimeout(() => setStatus("Route found", ""), 3000);
    }
  };

  ws.onclose = () => {
    indicator.textContent = "WS: disconnected";
    indicator.className   = "ws-indicator disconnected";
    // Reconnect after 3 s
    setTimeout(connectWS, 3000);
  };

  ws.onerror = (e) => console.warn("WebSocket error", e);
}

connectWS();

// ── Exports for events.js ─────────────────────────────────────────────────────

window.MapModule = {
  getClickedLatLng: () => clickedLatLng,
  clearEventMarker: () => { if (eventMarker) { map.removeLayer(eventMarker); eventMarker = null; } },
  animateReroute,
  fmtSeconds,
};
