/**
 * events.js — Event injection panel logic
 *
 * Reads the clicked point from MapModule, calls POST /event, and updates
 * the UI with the rerouted path + new ETA.
 * Loaded before map.js so EventPanel is available when map.js initialises.
 */

const API_BASE_EVENTS = window.API_BASE || "http://localhost:8000";

// ── EventPanel ────────────────────────────────────────────────────────────────

const EventPanel = (() => {
  let _armed = false;   // true while waiting for a map click

  function arm() {
    _armed = true;
    const hint = document.querySelector("#event-panel .hint");
    if (hint) hint.style.color = "#c62828";
  }

  function disarm() {
    _armed = false;
    const hint = document.querySelector("#event-panel .hint");
    if (hint) hint.style.color = "";
  }

  return {
    isArmed: () => _armed,
    arm,
    disarm,
  };
})();

// ── Severity slider ───────────────────────────────────────────────────────────

const severitySlider = document.getElementById("severity-slider");
const severityValue  = document.getElementById("severity-value");

severitySlider.addEventListener("input", () => {
  severityValue.textContent = `${severitySlider.value}×`;
});

// ── Inject button ─────────────────────────────────────────────────────────────

document.getElementById("inject-btn").addEventListener("click", async () => {
  const ll = window.MapModule?.getClickedLatLng();
  if (!ll) {
    alert("Click on the map to choose a point on the route first.");
    return;
  }

  const btn      = document.getElementById("inject-btn");
  btn.disabled   = true;
  btn.textContent = "Firing…";

  const body = {
    edge:     [ll.lat, ll.lng],
    severity: parseFloat(severitySlider.value),
    closed:   document.getElementById("closed-checkbox").checked,
    // Supply current route context so the backend can reroute immediately
    origin:      window._currentOrigin      || null,
    destination: window._currentDestination || null,
    hour:        window._currentHour        ?? 9,
    day_of_week: window._currentDayOfWeek   ?? 1,
  };

  try {
    const res = await fetch(`${API_BASE_EVENTS}/event`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(body),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || res.statusText);
    }

    const data = await res.json();

    if (data.new_path && data.new_path.length > 1) {
      window.MapModule?.animateReroute(data.new_path);
      document.getElementById("eta-display").textContent =
        window.MapModule?.fmtSeconds(data.new_eta_seconds) ?? `${Math.round(data.new_eta_seconds / 60)} min`;
      document.getElementById("status-badge").textContent = "Rerouted!";
      document.getElementById("status-badge").className  = "badge rerouting";
      setTimeout(() => {
        document.getElementById("status-badge").textContent = "Route found";
        document.getElementById("status-badge").className  = "badge";
      }, 3000);
    } else {
      alert(`Event applied (status: ${data.status}). No reroute — supply origin/destination first.`);
    }

    window.MapModule?.clearEventMarker();
    btn.disabled   = false;
    btn.textContent = "Fire Event";
    EventPanel.disarm();

  } catch (e) {
    console.error("Event injection failed:", e);
    alert(`Failed: ${e.message}`);
    btn.disabled    = false;
    btn.textContent = "Fire Event";
  }
});

// ── Reset button ──────────────────────────────────────────────────────────────

document.getElementById("reset-btn").addEventListener("click", async () => {
  try {
    await fetch(`${API_BASE_EVENTS}/event`, { method: "DELETE" });
    document.getElementById("status-badge").textContent = "Events cleared";
    document.getElementById("status-badge").className  = "badge";
  } catch (e) {
    console.error("Reset failed:", e);
  }
});

// ── Arm map click when "Fire Event" panel is focused ─────────────────────────

document.getElementById("event-panel").addEventListener("mouseenter", () => EventPanel.arm());
document.getElementById("event-panel").addEventListener("mouseleave", () => {
  // Only disarm if inject button hasn't been clicked yet
  if (!window.MapModule?.getClickedLatLng()) EventPanel.disarm();
});

// ── Expose for map.js ─────────────────────────────────────────────────────────
window.EventPanel = EventPanel;
