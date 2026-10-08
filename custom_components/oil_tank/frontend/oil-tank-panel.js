/**
 * Oil Tank sidebar panel (spec 9.5).
 *
 * Plain web component, no framework, no build step. Talks to the integration
 * over its websocket commands (oil_tank/*). Home Assistant sets `hass` and
 * `narrow` on the element.
 *
 * Look and feel follows Home Assistant: a small set of local colour tokens
 * mapped onto HA's own theme variables (same token names as the
 * reolink-nvr-bridge frontend), plus HA's own elements (ha-menu-button,
 * ha-icon). Theme and light/dark changes flow through automatically.
 *
 * Rendering: the page skeleton is built once. Each section re-renders on its
 * own, and the fill-up form is never re-rendered, so the 60-second refresh
 * cannot wipe half-typed input.
 */

const REFRESH_MS = 60_000;
const TOAST_MS = 4_000;
const NEEDLE_STEP_L = 10;
const STALE_PRICE_DAYS = 2;
const CHART_RANGES = { "3m": 92, "1y": 366, all: Infinity };

// Gauge geometry (SVG units). The arc runs from `start` degrees (left,
// slightly below horizontal) clockwise over the top through `sweep` degrees.
const G = { cx: 160, cy: 150, r: 108, start: 190, sweep: 200 };

class OilTankPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._state = null;
    this._prices = [];
    this._pricesVersion = null;
    this._range = "3m";
    this._pending = null; // dragged needle value (liters), not saved yet
    this._pointerActive = false;
    this._timer = null;
    this.attachShadow({ mode: "open" });
  }

  // ---- Home Assistant hooks ------------------------------------------

  set hass(hass) {
    const first = this._hass === null;
    this._hass = hass;
    const menu = this.shadowRoot.querySelector("ha-menu-button");
    if (menu) {
      menu.hass = hass;
    }
    if (first && this.isConnected) {
      this._load();
    }
  }

  set narrow(value) {
    this._narrow = !!value;
    this.toggleAttribute("narrow", this._narrow);
    const menu = this.shadowRoot.querySelector("ha-menu-button");
    if (menu) {
      menu.narrow = this._narrow;
    }
  }

  connectedCallback() {
    if (!this.shadowRoot.firstChild) {
      this._buildSkeleton();
    }
    if (this._hass) {
      this._load();
    }
    this._timer = setInterval(() => this._load(), REFRESH_MS);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
  }

  // ---- Data ----------------------------------------------------------

  _ws(type, payload = {}) {
    return this._hass.callWS({ type: `oil_tank/${type}`, ...payload });
  }

  async _load() {
    try {
      this._setState(await this._ws("get_state"));
    } catch (err) {
      this._showError(`Could not load the oil tank: ${errorText(err)}`);
    }
  }

  /** Store a fresh state object and redraw everything except the form. */
  async _setState(state) {
    this._state = state;
    this._showError(null);
    // The full price history is only fetched when it actually changed.
    if (state.prices_version !== this._pricesVersion) {
      try {
        this._prices = (await this._ws("get_prices")).prices;
        this._pricesVersion = state.prices_version;
      } catch (err) {
        this._showError(`Could not load prices: ${errorText(err)}`);
      }
    }
    this._renderBanner();
    if (!this._pointerActive) {
      this._renderGauge();
    }
    this._renderOutlook();
    this._renderChart();
    this._renderHistory();
  }

  /** Run a state-changing command; returns true on success. */
  async _action(type, payload, successText) {
    try {
      const state = await this._ws(type, payload);
      await this._setState(state);
      this._toast(successText);
      return true;
    } catch (err) {
      this._toast(errorText(err), true);
      return false;
    }
  }

  // ---- Skeleton --------------------------------------------------------

  _buildSkeleton() {
    const today = isoToday();
    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <div class="toolbar">
        <ha-menu-button></ha-menu-button>
        <div class="title">Oil tank</div>
      </div>
      <div class="page">
        <div class="error" id="error" hidden></div>
        <div class="banner" id="banner"></div>

        <div class="grid">
          <section class="card">
            <h2>Tank level</h2>
            <div id="gauge"></div>
          </section>
          <section class="card">
            <div class="card-head">
              <h2>Outlook</h2>
              <button id="predict-open">Predict</button>
            </div>
            <div id="outlook"></div>
          </section>
        </div>

        <section class="card">
          <div class="card-head">
            <h2>Price</h2>
            <div class="segmented" id="ranges" role="group" aria-label="Chart range">
              <button data-range="3m">3M</button>
              <button data-range="1y">1Y</button>
              <button data-range="all">All</button>
            </div>
          </div>
          <div id="price-head"></div>
          <div class="chart-wrap" id="chart"></div>
          <div id="price-stats"></div>
        </section>

        <div class="grid">
          <section class="card">
            <h2>Log a fill-up</h2>
            <form id="fill-form" autocomplete="off">
              <label>Date<input type="date" name="date" value="${today}" max="${today}" required></label>
              <label>Liters<input type="number" name="liters" min="1" step="any" inputmode="decimal" required></label>
              <label>Total price (DKK)<input type="number" name="price" min="0" step="any" inputmode="decimal" required></label>
              <label>Level after delivery (L, optional)<input type="number" name="level_after" min="0" step="any" inputmode="decimal"></label>
              <div class="form-foot">
                <span class="muted" id="per-liter"></span>
                <button type="submit" class="primary">Save fill-up</button>
              </div>
            </form>
          </section>
          <section class="card">
            <div class="card-head">
              <h2>History</h2>
              <div class="actions">
                <button id="import">Import CSV</button>
                <button id="export">Export CSV</button>
                <input type="file" id="file" accept=".csv,text/csv,text/plain" hidden>
              </div>
            </div>
            <div id="history"></div>
          </section>
        </div>
      </div>
      <div class="toast" id="toast" hidden></div>
      <dialog id="predict-dialog" aria-labelledby="predict-title">
        <div class="dialog-head">
          <h2 id="predict-title">Predict an order</h2>
          <button class="icon" id="predict-close" title="Close"><ha-icon icon="mdi:close"></ha-icon></button>
        </div>
        <form id="predict-form" class="predict-form">
          <label>Liters to order
            <span class="row"><input type="number" name="liters" min="1" step="any" inputmode="numeric" required> L</span>
          </label>
          <button type="submit" class="primary">Predict</button>
        </form>
        <div id="predict-result"></div>
      </dialog>
    `;

    const menu = this.shadowRoot.querySelector("ha-menu-button");
    menu.hass = this._hass;
    menu.narrow = this._narrow;

    this._bindChartRanges();
    this._bindPredict();
    this._bindForm();
    this._bindHistory();
  }

  _el(id) {
    return this.shadowRoot.getElementById(id);
  }

  // ---- Banner ----------------------------------------------------------

  _renderBanner() {
    const rec = this._state.recommendation;
    const [kind, title] = rec.urgent
      ? ["bad", "Order now"]
      : rec.order
        ? ["good", "Good time to order"]
        : ["neutral", "No action needed"];
    const icon = { bad: "mdi:alert", good: "mdi:truck-delivery", neutral: "mdi:check-circle-outline" }[kind];
    const banner = this._el("banner");
    banner.className = `banner ${kind}`;
    banner.innerHTML = `
      <ha-icon icon="${icon}"></ha-icon>
      <div><strong>${esc(title)}</strong><div>${esc(rec.reason)}</div></div>
    `;
  }

  // ---- Gauge -----------------------------------------------------------
  //
  // The dial copies the physical gauge (a Titan-style square float gauge):
  // the same printed scale, a 200 degree arc and the red zone. It is only a
  // way to enter a number: what gets saved is real liters,
  //   real liters = gauge reading - gauge offset
  // where the offset is what the physical gauge shows when the tank is empty.
  // Above (scale max - offset) liters the needle rests on its end stop, like
  // the real one.

  /** Gauge settings from the state: offset, printed scale end, capacity. */
  _scale() {
    const s = this._state;
    return { offset: s.gauge.offset_l, max: s.gauge.scale_max, cap: s.capacity_l };
  }

  _readingToLiters(reading) {
    const { offset, cap } = this._scale();
    return Math.min(cap, Math.max(0, reading - offset));
  }

  _litersToReading(liters) {
    const { offset, max } = this._scale();
    return Math.min(max, Math.max(0, liters + offset));
  }

  _renderGauge() {
    const s = this._state;
    const { offset, max, cap } = this._scale();
    const major = niceStep(max / 12);
    const minor = major / 2;

    // Tick marks and printed labels, as on the physical dial.
    let scale = "";
    for (let v = 0; v <= max + 1e-6; v += minor) {
      const f = v / max;
      const isMajor = Math.abs(v / major - Math.round(v / major)) < 1e-6;
      const [x1, y1] = gaugePoint(f, G.r - (isMajor ? 16 : 9));
      const [x2, y2] = gaugePoint(f, G.r);
      scale += `<line class="tick${isMajor ? " major" : ""}" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"></line>`;
      if (isMajor) {
        const [tx, ty] = gaugePoint(f, G.r + 19);
        scale += `<text class="label" x="${tx}" y="${ty}">${v}</text>`;
      }
    }
    const [ux, uy] = gaugePoint(1, G.r + 19);

    // Red zone like the printed one: up to the offset (where the tank is
    // really empty), at least the bottom 15% of the scale.
    const redEnd = Math.max(offset, 0.15 * max) / max;
    // The owner's "0" line: where the physical gauge sits when empty.
    let zeroMark = "";
    if (offset > 0) {
      const f = offset / max;
      const [x1, y1] = gaugePoint(f, G.r - 34);
      const [x2, y2] = gaugePoint(f, G.r + 4);
      const [tx, ty] = gaugePoint(f, G.r - 44);
      zeroMark = `<line class="zero-mark" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"></line>
                  <text class="zero-label" x="${tx}" y="${ty}">0</text>`;
    }

    this._el("gauge").innerHTML = `
      <svg class="gauge" viewBox="0 8 320 214" role="slider" aria-label="Tank level needle">
        <path class="red-zone" d="${arcPath(0, redEnd, G.r - 27)}"></path>
        ${scale}
        <text class="label" x="${ux}" y="${uy + 18}">L</text>
        ${zeroMark}
        <text class="tank-text" x="${G.cx}" y="${G.cy + 62}">${fmtInt(cap)} L tank</text>
        <line id="estimate-mark" class="estimate-mark" hidden></line>
        <line id="needle" class="needle" hidden></line>
        <circle class="hub" cx="${G.cx}" cy="${G.cy}" r="13"></circle>
        <circle class="hub-dot" cx="${G.cx}" cy="${G.cy}" r="5"></circle>
      </svg>
      <div class="gauge-readout">
        <button class="step" id="minus" aria-label="Lower 10" hidden>−</button>
        <span id="readout"></span>
        <button class="step" id="plus" aria-label="Raise 10" hidden>+</button>
      </div>
      <div class="hint small" id="gauge-hint" hidden></div>
      <div class="gauge-buttons">
        <button id="adjust">Adjust</button>
        <button id="cancel" hidden>Cancel</button>
        <button id="save" class="primary" hidden>Save reading</button>
      </div>
      <div class="muted small" id="calibration"></div>
    `;

    // Adjust: start editing from where the needle is now, without moving it.
    this._el("adjust").addEventListener("click", () => {
      const s = this._state;
      this._pending = s.level_l === null ? offset : this._litersToReading(s.level_l);
      this._updateNeedle();
    });
    this._bindStepButton(this._el("minus"), -NEEDLE_STEP_L);
    this._bindStepButton(this._el("plus"), NEEDLE_STEP_L);

    const svg = this.shadowRoot.querySelector("svg.gauge");
    svg.addEventListener("pointerdown", (ev) => {
      this._pointerActive = true;
      svg.setPointerCapture(ev.pointerId);
      this._dragTo(svg, ev);
    });
    svg.addEventListener("pointermove", (ev) => {
      if (this._pointerActive) {
        this._dragTo(svg, ev);
      }
    });
    const end = () => {
      this._pointerActive = false;
    };
    svg.addEventListener("pointerup", end);
    svg.addEventListener("pointercancel", end);

    this._el("cancel").addEventListener("click", () => {
      this._pending = null;
      this._updateNeedle();
    });
    this._el("save").addEventListener("click", async () => {
      const liters = this._readingToLiters(this._pending);
      if (await this._action("set_level", { liters }, `Reading saved: ${fmtInt(liters)} L`)) {
        this._pending = null;
        this._updateNeedle();
      }
    });

    const cal = s.last_calibration;
    this._el("calibration").textContent = cal
      ? `Last reading: the model said ${fmtInt(cal.estimated_l)} L, you set ${fmtInt(cal.reading_l)} L.`
      : "";

    this._updateNeedle();
  }

  /** +/- button: one step per press, repeating while held (like a volume button). */
  _bindStepButton(button, delta) {
    let timer = null;
    const step = () => {
      const { max } = this._scale();
      this._pending = Math.min(max, Math.max(0, this._pending + delta));
      this._updateNeedle();
    };
    const stop = () => {
      clearTimeout(timer);
      clearInterval(timer);
      timer = null;
    };
    button.addEventListener("pointerdown", (ev) => {
      ev.preventDefault();
      step();
      timer = setTimeout(() => (timer = setInterval(step, 80)), 400);
    });
    for (const type of ["pointerup", "pointerleave", "pointercancel"]) {
      button.addEventListener(type, stop);
    }
    // Keyboard (Enter/Space) produces a click without a pointer press.
    button.addEventListener("click", (ev) => {
      if (ev.detail === 0) {
        step();
      }
    });
  }

  /** Pointer position -> gauge reading, snapped to 10. Outside the arc snaps to the nearest end. */
  _dragTo(svg, ev) {
    const pt = svg.createSVGPoint();
    pt.x = ev.clientX;
    pt.y = ev.clientY;
    const p = pt.matrixTransform(svg.getScreenCTM().inverse());
    let angle = (Math.atan2(G.cy - p.y, p.x - G.cx) * 180) / Math.PI;
    if (angle < -90) {
      angle += 360; // lower left belongs to the start of the arc
    }
    const fraction = Math.min(1, Math.max(0, (G.start - angle) / G.sweep));
    const { max } = this._scale();
    this._pending = Math.round((fraction * max) / NEEDLE_STEP_L) * NEEDLE_STEP_L;
    this._updateNeedle();
  }

  /** Move the needle and markers in place (no re-render, keeps pointer capture). */
  _updateNeedle() {
    const s = this._state;
    const { offset, max } = this._scale();
    const needle = this._el("needle");
    const mark = this._el("estimate-mark");
    const readout = this._el("readout");
    const hint = this._el("gauge-hint");
    const estimateReading = s.level_l === null ? null : this._litersToReading(s.level_l);
    const shown = this._pending ?? estimateReading;

    placeLine(needle, shown === null ? null : shown / max, -14, G.r - 10);
    // The estimate marker only appears while a new value is pending.
    placeLine(
      mark,
      this._pending !== null && estimateReading !== null ? estimateReading / max : null,
      G.r - 30,
      G.r + 4,
    );
    const editing = this._pending !== null;
    for (const id of ["cancel", "save", "minus", "plus"]) {
      this._el(id).hidden = !editing;
    }
    this._el("adjust").hidden = editing;
    hint.hidden = true;

    if (this._pending !== null) {
      const liters = this._readingToLiters(this._pending);
      // While editing, the gauge reading is what you match against the tank.
      readout.innerHTML = `<span class="big">${fmtInt(this._pending)}</span>
        <div class="muted small">= ${fmtInt(liters)} L · not saved yet</div>`;
    } else if (s.level_l === null) {
      readout.innerHTML = `<span class="big">Set the needle</span><div class="muted small">Drag to what your tank's gauge shows, then save.</div>`;
    } else {
      const atStop = s.level_l + offset > max;
      readout.innerHTML = `<span class="big">${fmtInt(s.level_l)} L</span>
        <span class="muted">· ${atStop ? "gauge at its stop" : `gauge ${fmtInt(estimateReading)}`}</span>`;
      if (s.needle_check_since) {
        hint.hidden = false;
        hint.textContent = `Estimated after the fill-up on ${fmtDate(s.needle_check_since)}. Adjust the needle to match your gauge and save.`;
      }
    }
  }

  // ---- Outlook ---------------------------------------------------------

  _renderOutlook() {
    const s = this._state;
    const c = s.consumption;
    const source =
      c.source === "history"
        ? `from ${c.fills_used} deliveries since ${c.since.slice(0, 4)}`
        : "default (not enough deliveries logged yet)";

    // Layout A: one big number per group plus one line of detail.
    const tank =
      s.level_l === null
        ? `<div class="hero"><span class="big">—</span><span class="line">set the needle to start tracking</span></div>`
        : `<div class="hero"><span class="big">${fmtInt(s.days_remaining)} days</span>
             <span class="line">of oil · <strong>${fmtInt(s.level_l)} L</strong> in the tank</span></div>
           <div class="line">Order by <strong>${esc(fmtDate(s.order_by))}</strong></div>`;

    this._el("outlook").innerHTML = `
      <div class="group">
        <div class="eyebrow">Tank</div>
        ${tank}
      </div>
      <div class="group">
        <div class="eyebrow">Usage</div>
        <div class="hero"><span class="big">${s.daily_l.toFixed(1)} L/day</span><span class="line">right now</span></div>
        <div class="line"><strong>${fmtInt(s.yearly_l)} L/year</strong> ${esc(source)} · burn-rate factor × ${s.scale.toFixed(2)}</div>
      </div>
    `;
  }

  // ---- Predict -----------------------------------------------------------
  //
  // "If I order X L now, when do I order again?" A modal opened from the
  // Outlook header. It lives outside the refreshed sections, so the 60-second
  // update never touches it while it is open.

  _bindPredict() {
    const dialog = this._el("predict-dialog");
    const form = this._el("predict-form");
    const input = form.liters;

    this._el("predict-open").addEventListener("click", () => {
      const s = this._state;
      if (!s || s.level_l === null) {
        this._toast("Set the tank level first", true);
        return;
      }
      // Prefill with the room in the tank right now.
      input.value = Math.max(0, Math.floor((s.capacity_l - s.level_l) / 10) * 10);
      this._el("predict-result").innerHTML = "";
      dialog.showModal();
      input.focus();
      input.select();
    });

    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      try {
        this._showPrediction(await this._ws("predict", { liters: parseFloat(input.value) }));
      } catch (err) {
        this._el("predict-result").innerHTML = `<div class="warning">${esc(errorText(err))}</div>`;
      }
    });

    this._el("predict-close").addEventListener("click", () => dialog.close());
    // A click on the backdrop (outside the dialog box) closes it.
    dialog.addEventListener("click", (ev) => {
      if (ev.target === dialog) {
        dialog.close();
      }
    });
  }

  _showPrediction(r) {
    const row = (label, value) => `<dt>${esc(label)}</dt><dd>${value}</dd>`;
    const cost =
      r.price_per_l === null
        ? "—"
        : `≈ ${fmtInt(r.ordered_l * r.price_per_l)} kr <span class="muted">(${fmtKr(r.price_per_l)} kr/L)</span>`;
    this._el("predict-result").innerHTML = `
      <dl>
        ${row(`After delivery (≈ ${fmtDate(r.delivery_date)})`, `${fmtInt(r.level_after_l)} L`)}
        ${row("Next order by", `<strong>${esc(fmtDate(r.order_by))}</strong> <span class="muted">(${fmtInt(r.days_left)} days of oil)</span>`)}
        ${row("Price watching from", esc(fmtDate(r.window_start)))}
        ${row("Cost at today's price", cost)}
      </dl>
      ${r.ordered_l > r.room_l ? `<div class="warning">Only about ${fmtInt(r.room_l)} L fits; the rest would not go in.</div>` : ""}
    `;
  }

  // ---- Price chart -----------------------------------------------------

  _bindChartRanges() {
    this._el("ranges").addEventListener("click", (ev) => {
      const range = ev.target.closest("button")?.dataset.range;
      if (range) {
        this._range = range;
        this._renderChart();
      }
    });
    // Redraw at the real pixel width so the labels stay readable on a phone.
    let lastWidth = 0;
    new ResizeObserver(([entry]) => {
      const width = Math.round(entry.contentRect.width);
      if (this._state && Math.abs(width - lastWidth) > 4) {
        lastWidth = width;
        this._renderChart();
      }
    }).observe(this._el("chart"));
  }

  /** Big price, change since the previous price, chips, freshness. */
  _renderPriceHead() {
    const s = this._state;
    const p = s.price;
    const head = this._el("price-head");
    const error = s.price_error ? `<div class="warning small">Price feed problem: ${esc(s.price_error)}</div>` : "";
    if (!p) {
      head.innerHTML = `${error}<div class="muted">No price yet.</div>`;
      this._el("price-stats").innerHTML = "";
      return;
    }

    const prev = this._prices.length > 1 ? this._prices[this._prices.length - 2] : null;
    const change = prev ? p.price_per_l - prev[1] / 1000 : 0;
    const age = daysBetween(p.price_date, isoToday());
    const pct = p.percent_vs_average;
    const longPct = p.percent_vs_stock_up_average;
    const trend = p.trend_percent;
    const chip = (cls, text, title = "") => `<span class="chip ${cls}"${title ? ` title="${esc(title)}"` : ""}>${text}</span>`;

    head.innerHTML = `
      ${error}
      <div class="price-top">
        <div>
          <div class="price-now">${fmtKr(p.price_per_l)} <small>kr/L</small></div>
          <div class="delta ${change < 0 ? "down" : change > 0 ? "up" : ""}">
            ${prev ? `${change < 0 ? "▼" : change > 0 ? "▲" : "■"} ${fmtKr(Math.abs(change))} since ${esc(fmtShortDate(prev[0]))} · ` : ""}updated ${esc(fmtShortDate(p.price_date))}
            ${age > STALE_PRICE_DAYS ? chip("bad", `${age} days old`) : ""}
          </div>
        </div>
        <div class="chips">
          ${chip(pct <= -3 ? "good" : pct >= 3 ? "bad" : "", `${signed(pct)}% vs ${p.lookback_days}-day avg`)}
          ${chip(longPct <= -p.stock_up_percent ? "good" : "", `${signed(longPct)}% vs ${p.stock_up_days}-day avg`)}
          ${
            trend === null
              ? ""
              : chip(
                  trend >= 2 ? "bad" : trend <= -2 ? "good" : "",
                  `${Math.abs(trend) < 0.5 ? "→" : trend > 0 ? "↑" : "↓"} ${signed(trend)}% / 14 d`,
                  "Last 14 days against the 14 before (information only)",
                )
          }
        </div>
      </div>
    `;

    this._el("price-stats").innerHTML = `
      <div class="stats">
        <div><div class="l">${p.lookback_days}-day low</div><div class="v">${fmtKr(p.low_per_l)}</div></div>
        <div><div class="l">${p.lookback_days}-day avg</div><div class="v">${fmtKr(p.average_per_l)}</div></div>
        <div><div class="l">${p.lookback_days}-day high</div><div class="v">${fmtKr(p.high_per_l)}</div></div>
        <div><div class="l">${p.stock_up_days}-day avg</div><div class="v">${fmtKr(p.stock_up_average_per_l)}</div></div>
      </div>
    `;
  }

  _renderChart() {
    for (const btn of this._el("ranges").querySelectorAll("button")) {
      btn.setAttribute("aria-pressed", String(btn.dataset.range === this._range));
    }
    this._renderPriceHead();
    const chart = this._el("chart");
    if (!this._prices.length) {
      chart.innerHTML = `<div class="muted">No price data yet.</div>`;
      return;
    }

    // Points: [epoch days, kr per liter].
    const all = this._prices.map(([d, v]) => [dayNumber(d), v / 1000]);
    const last = all[all.length - 1];
    const points = all.filter(([d]) => d > last[0] - CHART_RANGES[this._range]);
    const first = points[0][0];

    // Drawn at the container's pixel width, so text keeps its size.
    const W = Math.max(300, Math.round(chart.clientWidth) || 640);
    const H = W < 500 ? 210 : 250;
    const L = 8, R = 52, T = 18, B = 26;
    let lo = Math.min(...points.map((p) => p[1]));
    let hi = Math.max(...points.map((p) => p[1]));
    const pad = Math.max((hi - lo) * 0.1, 0.1);
    lo -= pad;
    hi += pad;
    const x = (d) => L + ((d - first) / Math.max(1, last[0] - first)) * (W - L - R);
    const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
    // Keep text labels inside the plot.
    const lx = (d) => Math.min(W - R - 34, Math.max(L + 34, x(d)));

    const line = points.map(([d, v], i) => `${i ? "L" : "M"}${x(d).toFixed(1)},${y(v).toFixed(1)}`).join("");
    const area = `${line}L${x(last[0]).toFixed(1)},${H - B}L${x(first).toFixed(1)},${H - B}Z`;
    const grid = [0, 1, 2, 3]
      .map((i) => {
        const v = lo + pad + ((hi - lo - 2 * pad) * i) / 3;
        return `<line class="gridline" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"></line>
                <text class="axis" x="${W - R + 8}" y="${y(v) + 4}">${v.toFixed(2)}</text>`;
      })
      .join("");
    const xLabels = [first, (first + last[0]) / 2, last[0]]
      .map((d, i) => `<text class="axis" x="${x(d)}" y="${H - 6}" text-anchor="${["start", "middle", "end"][i]}">${esc(fmtShortDate(isoFromDayNumber(Math.round(d)), this._range !== "3m"))}</text>`)
      .join("");

    const p = this._state.price;
    const avg = p?.average_per_l;
    const avgLine =
      avg && avg > lo && avg < hi
        ? `<line class="avg" x1="${L}" x2="${W - R}" y1="${y(avg)}" y2="${y(avg)}"></line>
           <text class="avg-label" x="${L + 4}" y="${y(avg) - 6}">${p.lookback_days}-day avg ${fmtKr(avg)}</text>`
        : "";

    const lowP = points.reduce((a, b) => (b[1] < a[1] ? b : a));
    const highP = points.reduce((a, b) => (b[1] > a[1] ? b : a));

    // The owner's fills inside the range: faint vertical line + dot on the price line.
    const byDay = new Map(points);
    const fills = this._state.fills
      .map((f) => [dayNumber(f.date), f])
      .filter(([d]) => d >= first && d <= last[0])
      .map(([d, f]) => {
        const v = byDay.get(d) ?? nearest(points, d)[1];
        const tip = `${fmtDate(f.date)}: ${fmtInt(f.liters)} L, paid ${fmtKr(f.price / f.liters)} kr/L`;
        return `<line class="fill-line" x1="${x(d)}" x2="${x(d)}" y1="${y(v)}" y2="${H - B}"></line>
                <circle class="fill-dot" cx="${x(d)}" cy="${y(v)}" r="5"><title>${esc(tip)}</title></circle>`;
      })
      .join("");

    chart.innerHTML = `
      <svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Price history">
        <defs><linearGradient id="price-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="var(--accent)" stop-opacity="0.28"></stop>
          <stop offset="1" stop-color="var(--accent)" stop-opacity="0"></stop>
        </linearGradient></defs>
        ${grid}${xLabels}
        <path d="${area}" fill="url(#price-fill)"></path>
        ${avgLine}${fills}
        <path class="price-line" d="${line}"></path>
        <text class="lowhigh" x="${lx(highP[0])}" y="${y(highP[1]) - 8}" text-anchor="middle">high ${fmtKr(highP[1])}</text>
        <text class="lowhigh" x="${lx(lowP[0])}" y="${y(lowP[1]) + 16}" text-anchor="middle">low ${fmtKr(lowP[1])}</text>
        <circle class="end-ring" cx="${x(last[0])}" cy="${y(last[1])}" r="10"></circle>
        <circle class="end-dot" cx="${x(last[0])}" cy="${y(last[1])}" r="5"></circle>
        <line id="hover-line" class="hover-line" y1="${T}" y2="${H - B}" hidden></line>
        <circle id="hover-dot" class="hover-dot" r="4.5" hidden></circle>
        <rect id="hover-area" x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="transparent"></rect>
      </svg>
      <div class="tip" id="chart-tip" hidden></div>
    `;

    // Hover / touch: nearest day's price under the pointer, in a floating tip.
    const svg = chart.querySelector("svg");
    const area_ = this._el("hover-area");
    const hoverLine = this._el("hover-line");
    const hoverDot = this._el("hover-dot");
    const tip = this._el("chart-tip");
    const show = (ev) => {
      const pt = svg.createSVGPoint();
      pt.x = ev.clientX;
      pt.y = ev.clientY;
      const px = pt.matrixTransform(svg.getScreenCTM().inverse()).x;
      const [d, v] = nearest(points, first + ((px - L) / (W - L - R)) * (last[0] - first));
      for (const [el, attr, val] of [
        [hoverLine, "x1", x(d)], [hoverLine, "x2", x(d)], [hoverDot, "cx", x(d)], [hoverDot, "cy", y(v)],
      ]) {
        el.setAttribute(attr, val);
      }
      hoverLine.removeAttribute("hidden");
      hoverDot.removeAttribute("hidden");
      const scale = svg.getBoundingClientRect().width / W;
      tip.style.left = `${x(d) * scale}px`;
      tip.style.top = `${y(v) * scale}px`;
      tip.textContent = `${fmtDate(isoFromDayNumber(d))} · ${fmtKr(v)} kr/L`;
      tip.hidden = false;
    };
    area_.addEventListener("pointermove", show);
    area_.addEventListener("pointerdown", show);
    area_.addEventListener("pointerleave", () => {
      hoverLine.setAttribute("hidden", "");
      hoverDot.setAttribute("hidden", "");
      tip.hidden = true;
    });
  }

  // ---- Fill-up form ----------------------------------------------------

  _bindForm() {
    const form = this._el("fill-form");
    const perLiter = this._el("per-liter");
    const updatePerLiter = () => {
      const liters = parseFloat(form.liters.value);
      const price = parseFloat(form.price.value);
      perLiter.textContent = liters > 0 && price >= 0 ? `= ${fmtKr(price / liters)} kr/L` : "";
    };
    form.addEventListener("input", updatePerLiter);

    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const payload = {
        date: form.date.value,
        liters: parseFloat(form.liters.value),
        price: parseFloat(form.price.value),
      };
      if (form.level_after.value !== "") {
        payload.level_after_liters = parseFloat(form.level_after.value);
      }
      if (await this._action("log_fill", payload, `Fill-up saved: ${fmtInt(payload.liters)} L`)) {
        // Only a successful own submit clears the form; refreshes never do.
        form.reset();
        form.date.value = isoToday();
        updatePerLiter();
      }
    });
  }

  // ---- History ---------------------------------------------------------

  _bindHistory() {
    this._el("history").addEventListener("click", async (ev) => {
      const button = ev.target.closest("button[data-fill]");
      if (!button) {
        return;
      }
      const fill = this._state.fills.find((f) => f.id === button.dataset.fill);
      if (fill && confirm(`Delete the delivery of ${fmtInt(fill.liters)} L on ${fmtDate(fill.date)}?`)) {
        await this._action("delete_fill", { fill_id: fill.id }, "Delivery deleted");
      }
    });

    const file = this._el("file");
    this._el("import").addEventListener("click", () => file.click());
    file.addEventListener("change", async () => {
      const chosen = file.files[0];
      file.value = "";
      if (!chosen) {
        return;
      }
      try {
        const result = await this._ws("import_csv", { text: await chosen.text() });
        const bad = result.errors.length;
        let text = `Imported: ${result.added} added, ${result.skipped} already there`;
        if (bad) {
          text += `, ${bad} bad row${bad === 1 ? "" : "s"} (${result.errors.slice(0, 3).join("; ")}${bad > 3 ? "; …" : ""})`;
        }
        this._toast(text, bad > 0);
        await this._load();
      } catch (err) {
        this._toast(errorText(err), true);
      }
    });

    this._el("export").addEventListener("click", async () => {
      try {
        const { text } = await this._ws("export_csv");
        const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
        const link = document.createElement("a");
        link.href = url;
        link.download = `oil-tank-fills-${isoToday()}.csv`;
        link.click();
        URL.revokeObjectURL(url);
      } catch (err) {
        this._toast(errorText(err), true);
      }
    });
  }

  _renderHistory() {
    const fills = this._state.fills;
    this._el("history").innerHTML = fills.length
      ? `<div class="table-wrap"><table>
          <thead><tr><th>Date</th><th class="num">Liters</th><th class="num">Paid</th><th class="num">kr/L</th><th></th></tr></thead>
          <tbody>${fills
            .map(
              (f) => `<tr>
                <td>${esc(fmtDate(f.date))}</td>
                <td class="num">${fmtInt(f.liters)}</td>
                <td class="num">${fmtInt(f.price)}</td>
                <td class="num">${fmtKr(f.price / f.liters)}</td>
                <td class="num"><button class="icon" data-fill="${esc(f.id)}" title="Delete"><ha-icon icon="mdi:delete-outline"></ha-icon></button></td>
              </tr>`,
            )
            .join("")}</tbody>
        </table></div>`
      : `<div class="muted">No deliveries yet. Log one, or import your history as CSV (date,liters,price). Your deliveries set the burn rate.</div>`;
  }

  // ---- Feedback --------------------------------------------------------

  _showError(text) {
    const el = this._el("error");
    if (el) {
      el.hidden = !text;
      el.textContent = text || "";
    }
  }

  _toast(text, isError = false) {
    const el = this._el("toast");
    el.textContent = text;
    el.className = `toast${isError ? " bad" : ""}`;
    el.hidden = false;
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => (el.hidden = true), isError ? TOAST_MS * 2 : TOAST_MS);
  }
}

// ---- Helpers -------------------------------------------------------------

/** Escape text for insertion into HTML. */
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function errorText(err) {
  return err?.message || String(err);
}

/** Point on the gauge arc for a scale fraction (0 = start, 1 = end). */
function gaugePoint(fraction, radius) {
  const angle = ((G.start - G.sweep * fraction) * Math.PI) / 180;
  return [G.cx + radius * Math.cos(angle), G.cy - radius * Math.sin(angle)];
}

/** Arc along the dial between two scale fractions. */
function arcPath(from, to, radius) {
  const [x1, y1] = gaugePoint(from, radius);
  const [x2, y2] = gaugePoint(to, radius);
  const large = (to - from) * G.sweep > 180 ? 1 : 0;
  return `M${x1},${y1} A${radius},${radius} 0 ${large} 1 ${x2},${y2}`;
}

/** A round label step that gives about a dozen labels (100 for a 1200 L scale). */
function niceStep(rough) {
  for (const step of [10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 2500, 5000]) {
    if (step >= rough) {
      return step;
    }
  }
  return 10000;
}

/** Point a radial line at `fraction`, or hide it when fraction is null. */
function placeLine(line, fraction, inner, outer) {
  if (fraction === null) {
    line.setAttribute("hidden", "");
    return;
  }
  const [x1, y1] = gaugePoint(fraction, inner);
  const [x2, y2] = gaugePoint(fraction, outer);
  line.setAttribute("x1", x1);
  line.setAttribute("y1", y1);
  line.setAttribute("x2", x2);
  line.setAttribute("y2", y2);
  line.removeAttribute("hidden");
}

/** Today's date in the browser's time zone as YYYY-MM-DD. */
function isoToday() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** YYYY-MM-DD -> whole days since the epoch (time-zone free). */
function dayNumber(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y, m - 1, d) / 86_400_000;
}

function isoFromDayNumber(n) {
  return new Date(n * 86_400_000).toISOString().slice(0, 10);
}

function daysBetween(fromIso, toIso) {
  return dayNumber(toIso) - dayNumber(fromIso);
}

/** Point whose day is closest to `day`. Points are sorted by day. */
function nearest(points, day) {
  let best = points[0];
  for (const p of points) {
    if (Math.abs(p[0] - day) < Math.abs(best[0] - day)) {
      best = p;
    }
  }
  return best;
}

/** One decimal with an explicit sign: +2.4 / -1.0. */
function signed(value) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)}`;
}

function fmtInt(value) {
  return Math.round(value).toLocaleString();
}

function fmtKr(value) {
  return value.toFixed(2);
}

/** "8 Oct", or "8 Oct 2026" with the year. Takes an ISO date. */
function fmtShortDate(iso, withYear = false) {
  const [y, m, d] = iso.split("-").map(Number);
  const options = withYear ? { day: "numeric", month: "short", year: "numeric" } : { day: "numeric", month: "short" };
  return new Date(y, m - 1, d).toLocaleDateString(undefined, options);
}

function fmtDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

// ---- Styles ----------------------------------------------------------------

const STYLES = `
  /* Local tokens mapped onto Home Assistant's theme variables, so the panel
     follows whatever theme (and light/dark mode) is in force. Literal values
     are fallbacks only. Derived colours use color-mix, with a plain colour
     first for browsers that lack it. */
  :host {
    --bg: var(--primary-background-color, #111418);
    --panel: var(--card-background-color, var(--ha-card-background, #1c2026));
    --panel-2: var(--secondary-background-color, #252a32);
    --line: var(--divider-color, #333a44);
    --text: var(--primary-text-color, #e3e6eb);
    --muted: var(--secondary-text-color, #8b94a3);
    --accent: var(--primary-color, #03a9f4);
    --good: var(--success-color, #43a047);
    --warn: var(--warning-color, #ffa600);
    --bad: var(--error-color, #db4437);
    --radius: var(--ha-card-border-radius, 12px);
    --shadow: var(--ha-card-box-shadow, none);
    --accent-wash: rgba(3, 169, 244, 0.16);
    --accent-wash: color-mix(in srgb, var(--accent) 16%, transparent);
    --accent-ring: rgba(3, 169, 244, 0.35);
    --accent-ring: color-mix(in srgb, var(--accent) 35%, transparent);
    --hairline: color-mix(in srgb, var(--line) 45%, transparent);

    display: block;
    min-height: 100vh;
    background: var(--bg);
    color: var(--text);
    font-family: var(--ha-font-family-body, var(--paper-font-body1_-_font-family, system-ui, sans-serif));
  }
  * { box-sizing: border-box; }
  [hidden] { display: none !important; }

  .toolbar {
    display: flex; align-items: center; gap: 4px;
    height: var(--header-height, 56px); padding: 0 12px;
    background: var(--app-header-background-color, var(--panel));
    color: var(--app-header-text-color, var(--text));
    border-bottom: var(--app-header-border-bottom, 1px solid var(--line));
    position: sticky; top: 0; z-index: 2;
  }
  .title { font-size: 20px; margin-left: 8px; }
  .page { max-width: 1100px; margin: 0 auto; padding: 16px; display: flex; flex-direction: column; gap: 16px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  :host([narrow]) .page { padding: 8px; gap: 8px; }
  @media (max-width: 760px) { .grid { grid-template-columns: 1fr; } }

  .card {
    background: var(--panel); border-radius: var(--radius); box-shadow: var(--shadow);
    border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--line));
    padding: 16px; min-width: 0;
  }
  h2 { font-size: 16px; font-weight: 500; margin: 0 0 12px; }
  .card-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
  .card-head h2 { margin: 0; }
  .muted { color: var(--muted); }
  .small { font-size: 13px; }

  button {
    font: inherit; color: var(--text); background: var(--panel-2);
    border: 1px solid var(--line); border-radius: 6px; padding: 6px 12px; cursor: pointer;
  }
  button:hover { border-color: var(--accent); }
  button:focus-visible, input:focus-visible { outline: 2px solid var(--accent-ring); outline-offset: 1px; }
  button.primary { background: var(--accent); color: var(--text-primary-color, #fff); border-color: transparent; }
  button.icon { background: none; border: none; padding: 4px; color: var(--muted); }
  button.icon:hover { color: var(--bad); }
  /* Pill-shaped range switch. */
  .segmented { display: inline-flex; padding: 3px; gap: 2px; border-radius: 999px; background: var(--panel-2); }
  .segmented button { border: 0; border-radius: 999px; padding: 4px 12px; background: transparent; font-size: 13px; }
  .segmented button[aria-pressed="true"] { background: var(--panel); box-shadow: 0 1px 3px rgba(0, 0, 0, 0.18); }
  .actions { display: flex; gap: 6px; }

  .error { background: var(--bad); color: #fff; padding: 10px 14px; border-radius: 8px; }
  .warning { color: var(--warn); margin-bottom: 8px; }

  .banner {
    display: flex; gap: 12px; align-items: center; padding: 14px 16px;
    border-radius: var(--radius); border: 1px solid var(--line); background: var(--panel);
    border-left: 6px solid var(--muted);
  }
  .banner.good { border-left-color: var(--good); }
  .banner.bad { border-left-color: var(--bad); background: color-mix(in srgb, var(--bad) 12%, var(--panel)); }
  .banner ha-icon { flex: none; }
  .banner.good ha-icon { color: var(--good); }
  .banner.bad ha-icon { color: var(--bad); }
  .banner.neutral ha-icon { color: var(--muted); }

  /* Dial: layout copied from the physical gauge, colours from the theme
     (printed scale in the accent colour, like the gauge's blue print). */
  .gauge { width: 100%; max-width: 460px; display: block; margin: 0 auto; touch-action: none; cursor: pointer; user-select: none; }
  .tick { stroke: var(--accent); stroke-width: 2.5; }
  .tick.major { stroke-width: 4; }
  .label { fill: var(--accent); font-size: 14px; font-weight: 600; text-anchor: middle; dominant-baseline: middle; }
  .red-zone { fill: none; stroke: var(--bad); stroke-width: 10; opacity: 0.85; }
  .zero-mark { stroke: var(--bad); stroke-width: 3; }
  .zero-label { fill: var(--bad); font-size: 13px; font-weight: 700; text-anchor: middle; dominant-baseline: middle; }
  .tank-text { fill: var(--muted); font-size: 12px; text-anchor: middle; letter-spacing: 0.04em; }
  .needle { stroke: var(--text); stroke-width: 6; stroke-linecap: round; }
  .estimate-mark { stroke: var(--text); stroke-width: 3; stroke-dasharray: 4 3; opacity: 0.6; }
  .hub { fill: var(--panel); stroke: var(--text); stroke-width: 7; }
  .hub-dot { fill: var(--muted); }
  .gauge-readout { display: flex; align-items: center; justify-content: center; gap: 14px; margin-top: 4px; text-align: center; min-height: 48px; }
  .hint { color: var(--warn); margin-top: 6px; text-align: center; }
  /* Round +/- buttons, big enough to hit on a phone; no text selection
     or double-tap zoom while holding. */
  button.step {
    width: 44px; height: 44px; border-radius: 50%; padding: 0; flex: none;
    font-size: 24px; line-height: 1; touch-action: manipulation; user-select: none; -webkit-user-select: none;
  }
  .big { font-size: 22px; font-weight: 500; }
  .gauge-buttons { display: flex; justify-content: center; gap: 8px; margin: 10px 0 4px; }
  #calibration { text-align: center; margin-top: 8px; }

  /* Outlook: groups with one big number and one line of detail. */
  #outlook { font-variant-numeric: tabular-nums; }
  .group + .group { border-top: 1px solid var(--hairline); padding-top: 12px; margin-top: 12px; }
  .eyebrow { font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); margin-bottom: 6px; }
  .hero { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
  .hero .big { font-size: 28px; font-weight: 500; }
  .line { color: var(--muted); font-size: 14px; }
  .line strong { color: var(--text); font-weight: 500; }
  dialog {
    width: min(460px, calc(100vw - 32px)); padding: 16px 20px 20px; border: 1px solid var(--line);
    border-radius: var(--radius); background: var(--panel); color: var(--text);
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
  }
  dialog::backdrop { background: rgba(0, 0, 0, 0.5); }
  .dialog-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
  .dialog-head h2 { margin: 0; }
  .predict-form { display: flex; align-items: flex-end; gap: 10px; grid-template-columns: none; }
  .predict-form label { flex: 1; }
  .predict-form .row { display: flex; align-items: center; gap: 6px; color: var(--text); }
  .predict-form input { flex: 1; }
  #predict-result dl { display: grid; grid-template-columns: auto auto; gap: 8px 16px; margin: 16px 0 0; }
  #predict-result dt { color: var(--muted); }
  #predict-result dd { margin: 0; text-align: right; }
  #predict-result .warning { margin-top: 12px; }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; }
  .chip { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; background: var(--hairline); white-space: nowrap; }
  .chip.good { background: color-mix(in srgb, var(--good) 22%, transparent); color: var(--good); }
  .chip.bad { background: color-mix(in srgb, var(--bad) 22%, transparent); color: var(--bad); }

  /* Price card: big price, area chart, key numbers. */
  #price-head, #price-stats { font-variant-numeric: tabular-nums; }
  .price-top { display: flex; justify-content: space-between; align-items: flex-end; gap: 12px 24px; flex-wrap: wrap; }
  .price-now { font-size: 34px; font-weight: 500; line-height: 1.1; }
  .price-now small { font-size: 16px; font-weight: 400; color: var(--muted); }
  .delta { font-size: 14px; color: var(--muted); }
  .delta.down { color: var(--good); }
  .delta.up { color: var(--bad); }
  .chart-wrap { position: relative; margin-top: 14px; }
  .chart { width: 100%; height: auto; display: block; overflow: visible; touch-action: pan-y; }
  .gridline { stroke: var(--hairline); }
  .axis { fill: var(--muted); font-size: 11px; }
  .price-line { fill: none; stroke: var(--accent); stroke-width: 2.25; stroke-linejoin: round; }
  .avg { stroke: var(--muted); stroke-dasharray: 5 4; }
  .avg-label, .lowhigh { fill: var(--muted); font-size: 11px; }
  .lowhigh { font-size: 10px; }
  .end-dot { fill: var(--accent); stroke: var(--panel); stroke-width: 3; }
  .end-ring { fill: none; stroke: var(--accent); opacity: 0.35; }
  .fill-line { stroke: var(--good); opacity: 0.35; }
  .fill-dot { fill: var(--panel); stroke: var(--good); stroke-width: 2.5; }
  .hover-line { stroke: var(--muted); stroke-width: 1; }
  .hover-dot { fill: var(--accent); stroke: var(--panel); stroke-width: 2; }
  .tip {
    position: absolute; pointer-events: none; transform: translate(-50%, -120%); white-space: nowrap;
    background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 6px 10px; font-size: 12px;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.2);
  }
  .stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; margin-top: 14px; border-radius: 10px; overflow: hidden; background: var(--hairline); }
  .stats > div { background: var(--panel); padding: 8px 12px; }
  .stats .l { font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); }
  .stats .v { font-size: 16px; font-weight: 500; }
  @media (max-width: 480px) { .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); } .price-now { font-size: 28px; } }

  form { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: var(--muted); }
  input {
    font: inherit; color: var(--text); background: var(--panel-2);
    border: 1px solid var(--line); border-radius: 6px; padding: 8px;
    min-width: 0; color-scheme: light dark;
  }
  .form-foot { grid-column: 1 / -1; display: flex; justify-content: space-between; align-items: center; gap: 8px; }
  @media (max-width: 420px) { form { grid-template-columns: 1fr; } }

  .table-wrap { max-height: 360px; overflow: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th { text-align: left; font-weight: 500; color: var(--muted); position: sticky; top: 0; background: var(--panel); }
  th, td { padding: 6px 8px; border-bottom: 1px solid var(--hairline); }
  .num { text-align: right; white-space: nowrap; }

  .toast {
    position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%); z-index: 10;
    max-width: min(560px, calc(100vw - 32px));
    background: var(--panel-2); color: var(--text); border: 1px solid var(--line);
    border-left: 4px solid var(--good); border-radius: 8px; padding: 10px 14px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
  }
  .toast.bad { border-left-color: var(--bad); }
`;

customElements.define("oil-tank-panel", OilTankPanel);
