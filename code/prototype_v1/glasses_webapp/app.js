const params = new URLSearchParams(window.location.search);
const apiOverride = params.get("api");
const token = params.get("token") || "";
const pollMs = 2500;
const defaultApi = new URL("/glasses/latest", window.location.origin).toString();
const apiUrl = apiOverride || defaultApi;

const headlineEl = document.getElementById("headline");
const nextActionEl = document.getElementById("next_action");
const blockedEl = document.getElementById("blocked");
const confidenceEl = document.getElementById("confidence");
const shortReasonEl = document.getElementById("short_reason");
const activeContextEl = document.getElementById("active_context");
const freshnessStateEl = document.getElementById("freshness_state");
const generatedAtEl = document.getElementById("generated_at");
const ageSecondsEl = document.getElementById("age_seconds");

function safeText(value, fallback = "") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  return String(value);
}

function truncateText(value, maxChars) {
  const text = safeText(value, "").replace(/\s+/g, " ").trim();
  if (!text) return "";
  if (text.length <= maxChars) return text;
  return `${text.slice(0, Math.max(0, maxChars - 1)).trim()}...`;
}

function stateClass(state) {
  const normalized = safeText(state, "stale").toLowerCase();
  if (normalized === "connected") return "state-connected";
  if (normalized === "error") return "state-error";
  return "state-stale";
}

function renderWaiting(message) {
  headlineEl.textContent = "Waiting for glasses data...";
  nextActionEl.textContent = message;
  blockedEl.textContent = "Unknown";
  confidenceEl.textContent = "0%";
  shortReasonEl.textContent = "No reason available";
  activeContextEl.textContent = "No active context";
  freshnessStateEl.textContent = "stale";
  freshnessStateEl.className = `state ${stateClass("stale")}`;
  generatedAtEl.textContent = "-";
  ageSecondsEl.textContent = "0s";
}

function renderPayload(payload) {
  const freshness = safeText(payload.freshness_state, "stale").toLowerCase();
  const blocked = Boolean(payload.blocked);
  const confidence = Number(payload.confidence_percent);

  headlineEl.textContent = safeText(payload.headline, "No headline");
  nextActionEl.textContent = truncateText(payload.next_action, 140) || "No next action";
  blockedEl.textContent = blocked ? "Blocked" : "Not blocked";
  confidenceEl.textContent = Number.isFinite(confidence) ? `${Math.max(0, Math.min(100, Math.round(confidence)))}%` : "0%";
  shortReasonEl.textContent = truncateText(payload.short_reason, 120) || "No reason available";
  activeContextEl.textContent = truncateText(payload.active_context, 80) || "No active context";

  freshnessStateEl.textContent = freshness;
  freshnessStateEl.className = `state ${stateClass(freshness)}`;

  generatedAtEl.textContent = safeText(payload.generated_at, "-");
  ageSecondsEl.textContent = `${safeText(payload.age_seconds, 0)}s`;
}

async function fetchLatest() {
  const headers = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(apiUrl, {
    cache: "no-store",
    headers,
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }

  return response.json();
}

async function tick() {
  try {
    const payload = await fetchLatest();
    renderPayload(payload);
  } catch (_err) {
    renderWaiting("Unable to reach glasses endpoint. Check local backend/API URL.");
  }
}

renderWaiting("Starting local glasses HUD...");
tick();
setInterval(tick, pollMs);
