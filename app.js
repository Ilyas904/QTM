/* JALYN — frontend. Vanilla JS + Leaflet. Every number on screen comes from the backend (/api/*). */

const $ = (id) => document.getElementById(id);
const nf = (d) => new Intl.NumberFormat("en-US", { maximumFractionDigits: d });
const fmtInt = (n) => nf(0).format(n);
const fmtM = (n, d = 1) => nf(d).format(n / 1e6);
const fmtB = (n, d = 2) => nf(d).format(n / 1e9);
const fmtK = (n, d = 1) => nf(d).format(n / 1e3);

const state = { sites: [], markers: new Map(), selected: null, mode: "auto" };

// --- Map ----------------------------------------------------------------------
const map = L.map("map", { zoomControl: true, attributionControl: true }).setView([47.3, 60.0], 5);
// Vector base layer (country borders, Natural Earth via world-atlas) — renders even when raster tiles are unreachable.
const basePane = map.createPane("base"); basePane.style.zIndex = 200;
fetch("static/vendor/countries-region.json").then((r) => r.json()).then((geo) => {
  L.geoJSON(geo, { pane: "base", style: (f) => ({
    color: f.properties.name === "Kazakhstan" ? "#3a4b63" : "#1c2634", weight: f.properties.name === "Kazakhstan" ? 1.4 : 0.8,
    fillColor: f.properties.name === "Kazakhstan" ? "#141d2c" : "#0e141e", fillOpacity: 1,
  }) }).addTo(map);
}).catch(() => {});
// Raster tiles on top (CARTO dark); if the network is down the vector layer stays.
L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a> &middot; Natural Earth',
  subdomains: "abcd", maxZoom: 18, opacity: 0.9,
}).addTo(map);
const markerLayer = L.layerGroup().addTo(map);

function markerFor(site) {
  const r = 6 + Math.sqrt(site.frp_mean_mw) * 2.4;
  const glow = L.circleMarker([site.lat, site.lon], {
    radius: r * 2.2, color: "transparent", fillColor: "#ff6a1a", fillOpacity: 0.12, interactive: false,
  });
  const core = L.circleMarker([site.lat, site.lon], {
    radius: r, color: "#ffb347", weight: 1.5, fillColor: "#ff6a1a", fillOpacity: 0.85,
  });
  core.bindPopup(`<div><strong>${site.name}</strong><br>${site.region}<br>
    ${fmtM(site.economics.gas_m3_per_year)} M m³/year · <b>₸${fmtB(site.economics.methanol_value_kzt)} bn/year</b></div>`);
  core.on("click", () => select(site.id, false));
  return L.layerGroup([glow, core]);
}

// --- Loading ------------------------------------------------------------------
async function load() {
  const days = $("daysSelect").value;
  $("modeBadge").textContent = "loading…";
  try {
    let data;
    try {
      const res = await fetch(`api/flares?mode=${state.mode}&days=${days}`);
      if (!res.ok) throw new Error(await res.text());
      data = await res.json(); state.staticMode = false;
    } catch (e) {
      if (!window.JALYN_STATIC) throw e;
      data = window.JALYN_STATIC.flares(); state.staticMode = true;   // GitHub Pages / no backend
    }
    state.sites = data.sites;
    renderMode(data.mode);
    renderKpis(data.totals);
    renderList();
    renderMarkers();
    $("generatedAt").textContent = `Updated ${new Date(data.generated_at).toLocaleString("en-GB")} · window ${data.days} nights`;
    $("assumptions").textContent = JSON.stringify(data.assumptions, null, 2);
  } catch (err) {
    toast("Could not load data: " + err.message, true);
  }
}

function renderMode(mode) {
  const badge = $("modeBadge");
  badge.className = "badge " + (mode === "live" ? "badge-live" : "badge-demo");
  badge.textContent = mode === "live" ? "LIVE · NASA FIRMS" : (state.staticMode ? "DEMO DATA · STATIC" : "DEMO DATA");
  badge.title = mode === "live"
    ? "Real VIIRS detections for the selected window"
    : "Synthetic points in Kazakhstan's oil regions. Set FIRMS_MAP_KEY on the server and the map switches to real detections.";
}

function renderKpis(t) {
  $("kpiSites").textContent = t.sites;
  $("kpiGas").textContent = fmtM(t.gas_m3_per_year, 0);
  $("kpiValue").textContent = fmtB(t.methanol_value_kzt, 1);
  $("kpiCo2").textContent = fmtK(t.co2e_t_per_year, 0);
}

function renderList() {
  const list = $("siteList");
  list.innerHTML = "";
  $("listCount").textContent = `${state.sites.length} sites`;
  state.sites.forEach((s) => {
    const el = document.createElement("div");
    el.className = "site" + (state.selected === s.id ? " active" : "");
    el.innerHTML = `
      <div class="site-top"><span class="site-name">${s.name}</span><span class="site-value">₸${fmtB(s.economics.methanol_value_kzt)} bn</span></div>
      <div class="site-meta"><span>${s.region}</span><span>FRP ${s.frp_mean_mw} MW</span><span>${fmtM(s.economics.gas_m3_per_year)} M m³</span></div>
      <div class="bar"><div class="bar-fill" style="width:${Math.round(s.persistence * 100)}%"></div></div>`;
    el.onclick = () => select(s.id, true);
    list.appendChild(el);
  });
}

function renderMarkers() {
  markerLayer.clearLayers();
  state.markers.clear();
  state.sites.forEach((s) => {
    const m = markerFor(s).addTo(markerLayer);
    state.markers.set(s.id, m);
  });
  if (state.sites.length) {
    const b = L.latLngBounds(state.sites.map((s) => [s.lat, s.lon]));
    map.fitBounds(b.pad(0.25));
  }
}

// --- Detail -------------------------------------------------------------------
async function select(id, fly) {
  const s = state.sites.find((x) => x.id === id);
  if (!s) return;
  state.selected = id;
  renderList();
  if (fly) map.setView([s.lat, s.lon], Math.max(map.getZoom(), 8), { animate: false });

  const e = s.economics;
  $("dName").textContent = s.name;
  $("dRegion").textContent = `${s.region} · ${s.lat}, ${s.lon} · ${s.source}`;
  $("dGas").textContent = fmtInt(e.gas_m3_per_year);
  $("dMeth").textContent = fmtInt(e.methanol_t_per_year);
  $("dValue").textContent = fmtInt(e.methanol_value_kzt);
  $("dCo2").textContent = fmtInt(e.co2e_t_per_year);
  $("dPersistText").textContent = `${s.nights_detected} of ${s.nights_total} nights (${Math.round(s.persistence * 100)}%)`;
  $("dPersistBar").style.width = `${Math.round(s.persistence * 100)}%`;
  $("dFrp").textContent = `Mean radiated power ${e.frp_mw} MW · peak ${s.frp_max_mw} MW · ${s.detections} detections · as electricity: ${fmtInt(e.electricity_mwh_per_year)} MWh/year (₸${fmtB(e.electricity_value_kzt)} bn)`;
  $("reportBtn").href = `api/sites/${s.id}/report`;
  $("reportBtn").onclick = state.staticMode ? (ev) => { ev.preventDefault(); toast("Static demo: the PDF report is generated by the backend — open the Render deployment.", true); } : null;
  $("techList").classList.add("hidden");
  $("techList").innerHTML = "";
  $("subForm").classList.add("hidden");
  $("listView").classList.add("hidden");
  $("detailView").classList.remove("hidden");
}

async function loadTech() {
  if (!state.selected) return;
  const box = $("techList");
  box.classList.remove("hidden");
  box.innerHTML = '<div class="muted small">Calculating payback…</div>';
  let data;
  if (state.staticMode) { const site = state.sites.find((x) => x.id === state.selected); data = { technologies: window.JALYN_STATIC.match(site.economics.gas_m3_per_year) }; }
  else { const res = await fetch(`api/sites/${state.selected}/economics`); data = await res.json(); }
  box.innerHTML = "";
  data.technologies.forEach((t) => {
    const el = document.createElement("div");
    el.className = "tech " + (t.fit ? "fit" : "nofit");
    el.innerHTML = `
      <div class="tech-top"><span class="tech-name">${t.name}</span>
        <span class="tech-payback">${t.payback_years ? t.payback_years + " yr payback" : (t.fit ? "no revenue" : "out of range")}</span></div>
      <div class="tech-short">${t.short}</div>
      <div class="tech-row">
        <span>CAPEX: <b>₸${fmtB(t.capex_kzt)} bn</b></span>
        <span>Net income: <b>₸${fmtM(t.net_kzt_per_year, 0)} M/year</b></span>
        <span>Range: <b>${fmtM(t.min_m3_per_year, 0)}–${fmtM(t.max_m3_per_year, 0)} M m³</b></span>
        <span>Product: <b>${t.product}</b></span>
      </div>
      <div class="tech-note">${t.assumption}<br>Vendor example: ${t.vendor_example}</div>`;
    box.appendChild(el);
  });
}

async function subscribe(ev) {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const payload = { site_id: state.selected, company: fd.get("company"), email: fd.get("email") };
  if (state.staticMode) { toast("Static demo: subscriptions are stored by the backend — open the Render deployment to try it.", true); return; }
  const res = await fetch("api/subscriptions", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
  if (!res.ok) { toast("Error: " + (await res.text()), true); return; }
  const data = await res.json();
  toast(`Monitoring started: ${data.site} for ${data.company} · ₸${fmtInt(data.plan_kzt_per_month)}/month · subscription #${data.id}`);
  ev.target.reset();
  $("subForm").classList.add("hidden");
}

function toast(msg, isError = false) {
  const t = $("toast");
  t.textContent = msg;
  t.style.borderColor = isError ? "#ff5c5c" : "";
  t.classList.remove("hidden");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.add("hidden"), 5000);
}

// --- Events -------------------------------------------------------------------
$("daysSelect").addEventListener("change", load);
$("backBtn").addEventListener("click", () => { $("detailView").classList.add("hidden"); $("listView").classList.remove("hidden"); state.selected = null; renderList(); });
$("techBtn").addEventListener("click", loadTech);
$("subBtn").addEventListener("click", () => $("subForm").classList.toggle("hidden"));
$("subForm").addEventListener("submit", subscribe);
$("methodBtn").addEventListener("click", () => $("methodModal").classList.remove("hidden"));
$("methodClose").addEventListener("click", () => $("methodModal").classList.add("hidden"));
$("methodModal").addEventListener("click", (e) => { if (e.target === $("methodModal")) $("methodModal").classList.add("hidden"); });

load();
