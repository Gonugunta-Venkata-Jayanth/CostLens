/* CostLens dashboard. Reads the API, or a precomputed snapshot in static demo mode. */
(function () {
  "use strict";

  const cfg = Object.assign({ mode: "api", apiBase: "" }, window.COSTLENS_CONFIG || {});
  const PALETTE = ["#ff9900", "#4f8cff", "#3ecf8e", "#c678dd", "#ff5d6c", "#56b6c2", "#e5c07b", "#98a2b3"];
  const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
  const $ = (id) => document.getElementById(id);
  const charts = {};
  let state = { mode: cfg.mode, snapshot: null, daily: null };

  async function getJSON(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
    return res.json();
  }

  async function loadAll() {
    if (state.mode === "api") {
      try {
        const base = cfg.apiBase.replace(/\/$/, "");
        const [summary, daily, forecast, anomalies] = await Promise.all([
          getJSON(`${base}/api/summary`),
          getJSON(`${base}/api/daily`),
          getJSON(`${base}/api/forecast`),
          getJSON(`${base}/api/anomalies?threshold=${$("threshold").value}`),
        ]);
        return { summary, daily, forecast, anomalies: anomalies.anomalies, source: "api" };
      } catch (err) {
        console.warn("API unavailable, falling back to snapshot", err);
        state.mode = "snapshot";
      }
    }
    if (!state.snapshot) state.snapshot = await getJSON("snapshot.json");
    return Object.assign({}, state.snapshot, { source: state.snapshot.source || "snapshot" });
  }

  function filterAnomalies(list, threshold) {
    return list.filter((a) => a.z_score >= threshold).map((a) =>
      Object.assign({}, a, { severity: a.z_score >= 2 * threshold ? "high" : "medium" }));
  }

  function renderKpis(d, anomalies) {
    const s = d.summary, f = d.forecast;
    $("kpi-period").textContent = usd.format(s.period_spend);
    if (s.change_pct !== null) {
      const up = s.change_pct >= 0;
      $("kpi-change").innerHTML = `<span class="${up ? "up" : "down"}">${up ? "+" : ""}${s.change_pct.toFixed(1)}%</span> vs previous 30 days`;
    }
    $("kpi-mtd").textContent = usd.format(f.month_to_date);
    $("kpi-month").textContent = `${f.month}, as of ${f.as_of}`;
    $("kpi-projected").textContent = usd.format(f.projected_total);
    $("kpi-range").textContent = `95% range ${usd.format(f.lower)} – ${usd.format(f.upper)}`;
    $("kpi-anomalies").textContent = anomalies.length;
    const excess = anomalies.reduce((t, a) => t + a.excess, 0);
    $("kpi-excess").textContent = `${usd.format(excess)} above baseline`;
  }

  function renderDaily(daily, service) {
    const names = Object.keys(daily.series).filter((n) => !service || n === service);
    const datasets = names.map((n, i) => ({
      label: n, data: daily.series[n], borderColor: PALETTE[i % PALETTE.length],
      backgroundColor: PALETTE[i % PALETTE.length] + "33", fill: !service, tension: 0.25,
      pointRadius: 0, borderWidth: 1.6, stack: service ? undefined : "spend",
    }));
    charts.daily && charts.daily.destroy();
    charts.daily = new Chart($("daily-chart"), {
      type: "line",
      data: { labels: daily.days, datasets },
      options: chartOptions({ stacked: !service }),
    });
  }

  function renderForecast(daily, f) {
    const days = daily.days.slice(-45);
    const totals = days.map((_, i) => {
      const idx = daily.days.length - days.length + i;
      return Object.values(daily.series).reduce((t, arr) => t + arr[idx], 0);
    });
    const labels = days.concat(f.projection.map((p) => p.day));
    const actual = totals.map((v) => +v.toFixed(2)).concat(f.projection.map(() => null));
    const proj = days.map((_, i) => (i === days.length - 1 ? actual[i] : null))
      .concat(f.projection.map((p) => p.cost));
    charts.forecast && charts.forecast.destroy();
    charts.forecast = new Chart($("forecast-chart"), {
      type: "line",
      data: {
        labels,
        datasets: [
          { label: "Actual daily total", data: actual, borderColor: "#4f8cff", pointRadius: 0, borderWidth: 2 },
          { label: "Projected", data: proj, borderColor: "#ff9900", borderDash: [6, 4], pointRadius: 0, borderWidth: 2 },
        ],
      },
      options: chartOptions({ stacked: false }),
    });
  }

  function chartOptions({ stacked }) {
    const grid = { color: "#22304f" }, ticks = { color: "#8b98b5", maxTicksLimit: 10 };
    return {
      responsive: true, interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { color: "#e6ebf5", boxWidth: 12 } },
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${usd.format(c.parsed.y)}` } },
      },
      scales: {
        x: { grid, ticks },
        y: { grid, ticks: Object.assign({}, ticks, { callback: (v) => "$" + v }), stacked, beginAtZero: true },
      },
    };
  }

  function renderServices(s) {
    $("services-table").querySelector("tbody").innerHTML = s.services.map((r) =>
      `<tr><td>${esc(r.service)}</td><td class="num">${usd.format(r.cost)}</td><td class="num">${r.share_pct.toFixed(1)}%</td></tr>`).join("");
  }

  function renderAnomalies(list) {
    const body = $("anomaly-table").querySelector("tbody");
    body.innerHTML = list.length ? list.slice().reverse().map((a) =>
      `<tr><td>${a.day}</td><td>${esc(a.service)}</td><td class="num">${usd.format(a.cost)}</td>` +
      `<td class="num">${usd.format(a.expected)}</td><td class="num">${usd.format(a.excess)}</td>` +
      `<td class="num">${a.z_score.toFixed(1)}</td><td><span class="badge ${a.severity}">${a.severity}</span></td></tr>`).join("")
      : `<tr><td colspan="7" class="muted">No anomalies at this sensitivity.</td></tr>`;
  }

  function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

  async function refresh() {
    const d = await loadAll();
    const threshold = parseFloat($("threshold").value);
    const anomalies = d.source === "api" ? d.anomalies : filterAnomalies(d.anomalies, threshold);
    state.daily = d.daily;
    renderKpis(d, anomalies);
    renderServices(d.summary);
    renderAnomalies(anomalies);
    renderDaily(d.daily, $("service-filter").value);
    renderForecast(d.daily, d.forecast);
    const select = $("service-filter");
    if (select.options.length === 1) {
      Object.keys(d.daily.series).forEach((n) => select.add(new Option(n, n)));
    }
    const live = d.source === "api";
    $("upload-panel").hidden = !live;
    $("status").textContent = live ? "Live API" : "Static demo · synthetic data";
    $("source-note").textContent = live
      ? `${d.summary.days} days of data, ${d.summary.first_day} to ${d.summary.last_day}`
      : `Synthetic CUR dataset (${d.line_items.toLocaleString()} line items, ${d.summary.days} days), precomputed by the CostLens pipeline`;
  }

  $("threshold").addEventListener("input", (e) => { $("threshold-value").textContent = (+e.target.value).toFixed(1); });
  $("threshold").addEventListener("change", () => refresh().catch(showError));
  $("service-filter").addEventListener("change", (e) => state.daily && renderDaily(state.daily, e.target.value));
  $("upload-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const file = $("upload-file").files[0];
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    const res = await fetch(`${cfg.apiBase.replace(/\/$/, "")}/api/ingest`, { method: "POST", body });
    const out = await res.json();
    $("upload-result").textContent = res.ok ? `Ingested ${out.ingested_service_days} service-days.` : `Error: ${out.detail}`;
    if (res.ok) refresh().catch(showError);
  });

  function showError(err) { $("status").textContent = "Error loading data"; console.error(err); }
  refresh().catch(showError);
})();
