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

// Gauge geometry (SVG units).
const G = { cx: 150, cy: 150, r: 118, width: 22 };

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
            <h2>Outlook</h2>
            <div id="outlook"></div>
          </section>
        </div>

        <section class="card">
          <div class="card-head">
            <h2>Price</h2>
            <div class="segmented" id="ranges">
              <button data-range="3m">3 months</button>
              <button data-range="1y">1 year</button>
              <button data-range="all">All</button>
            </div>
          </div>
          <div id="chart"></div>
        </section>

        <div class="grid">
          <section class="card">
            <h2>Log a fill-up</h2>
            <form id="fill-form" autocomplete="off">
              <label>Date<input type="date" name="date" value="${today}" max="${today}" required></label>
              <label>Liters<input type="number" name="liters" min="1" step="any" inputmode="decimal" required></label>
              <label>Total price (DKK)<input type="number" name="price" min="0" step="any" inputmode="decimal" required></label>
              <label>Level after delivery (L, optional)<input type="number" name="level_after" min="0" step="10" inputmode="decimal"></label>
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
    `;

    const menu = this.shadowRoot.querySelector("ha-menu-button");
    menu.hass = this._hass;
    menu.narrow = this._narrow;

    this._bindChartRanges();
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

  _renderGauge() {
    const s = this._state;
    const cap = s.capacity_l;
    const zone = (from, to, cls) =>
      `<path class="zone ${cls}" d="${arcPath(from, to)}"></path>`;
    const ticks = [0, 0.25, 0.5, 0.75, 1]
      .map((f) => {
        const [x, y] = gaugePoint(f, G.r + G.width / 2 + 14);
        return `<text class="tick" x="${x}" y="${y}" text-anchor="middle">${fmtInt(f * cap)}</text>`;
      })
      .join("");

    this._el("gauge").innerHTML = `
      <svg class="gauge" viewBox="0 -12 300 182" role="slider" aria-label="Tank level needle">
        ${zone(0, 0.15, "bad")}${zone(0.15, 0.3, "warn")}${zone(0.3, 1, "good")}
        ${ticks}
        <line id="estimate-mark" class="estimate-mark" hidden></line>
        <line id="needle" class="needle" hidden></line>
        <circle cx="${G.cx}" cy="${G.cy}" r="7" class="hub"></circle>
      </svg>
      <div class="gauge-readout" id="readout"></div>
      <div class="gauge-buttons" id="gauge-buttons" hidden>
        <button id="cancel">Cancel</button>
        <button id="save" class="primary">Save reading</button>
      </div>
      <div class="muted small" id="calibration"></div>
    `;

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
      const liters = this._pending;
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

  /** Pointer position -> liters, snapped to 10 L. Below the horizon snaps to an end. */
  _dragTo(svg, ev) {
    const pt = svg.createSVGPoint();
    pt.x = ev.clientX;
    pt.y = ev.clientY;
    const p = pt.matrixTransform(svg.getScreenCTM().inverse());
    const dx = p.x - G.cx;
    const dy = G.cy - p.y;
    const fraction = dy < 0 ? (dx < 0 ? 0 : 1) : 1 - Math.atan2(dy, dx) / Math.PI;
    const cap = this._state.capacity_l;
    this._pending = Math.min(cap, Math.round((fraction * cap) / NEEDLE_STEP_L) * NEEDLE_STEP_L);
    this._updateNeedle();
  }

  /** Move the needle and markers in place (no re-render, keeps pointer capture). */
  _updateNeedle() {
    const s = this._state;
    const cap = s.capacity_l;
    const needle = this._el("needle");
    const mark = this._el("estimate-mark");
    const readout = this._el("readout");
    const buttons = this._el("gauge-buttons");
    const shown = this._pending ?? s.level_l;

    placeLine(needle, shown === null ? null : shown / cap, 18, G.r - 4);
    // The estimate marker only appears while a new value is pending.
    placeLine(mark, this._pending !== null && s.level_l !== null ? s.level_l / cap : null, G.r - G.width / 2 - 6, G.r + G.width / 2 + 4);
    buttons.hidden = this._pending === null;

    if (this._pending !== null) {
      readout.innerHTML = `<span class="big">${fmtInt(this._pending)} L</span> <span class="muted">(not saved yet)</span>`;
    } else if (s.level_l === null) {
      readout.innerHTML = `<span class="big">Set the needle</span><div class="muted small">Drag to the level on your tank's gauge, then save.</div>`;
    } else {
      readout.innerHTML = `<span class="big">${fmtInt(s.level_l)} L</span> <span class="muted">${fmtInt(s.level_percent)}% · estimate</span>`;
    }
  }

  // ---- Outlook ---------------------------------------------------------

  _renderOutlook() {
    const s = this._state;
    const p = s.price;
    const tile = (label, value, extra = "") =>
      `<div class="tile"><div class="muted small">${esc(label)}</div><div class="value">${value}</div>${extra}</div>`;

    let priceTiles = tile("Today's price", "—");
    if (p) {
      const pct = p.percent_vs_average;
      const chipClass = pct <= -3 ? "good" : pct >= 3 ? "bad" : "neutral";
      const age = daysBetween(p.price_date, isoToday());
      const stale = age > STALE_PRICE_DAYS;
      priceTiles =
        tile(
          "Today's price",
          `${fmtKr(p.price_per_l)} kr/L`,
          `<span class="chip ${chipClass}">${pct >= 0 ? "+" : ""}${pct.toFixed(1)}% vs ${p.lookback_days}-day avg</span>`,
        ) +
        tile(`${p.lookback_days}-day range`, `${fmtKr(p.low_per_l)}–${fmtKr(p.high_per_l)}`) +
        tile(
          "Price date",
          esc(fmtDate(p.price_date)),
          stale ? `<span class="chip bad">${age} days old</span>` : "",
        );
    }

    this._el("outlook").innerHTML = `
      ${s.price_error ? `<div class="warning small">Price feed problem: ${esc(s.price_error)}</div>` : ""}
      <div class="tiles">
        ${tile("Days of oil left", s.days_remaining === null ? "—" : fmtInt(s.days_remaining))}
        ${tile("Order by", s.order_by ? esc(fmtDate(s.order_by)) : "—")}
        ${priceTiles}
        ${tile("Burn-rate factor", `× ${s.scale.toFixed(2)}`)}
      </div>
    `;
  }

  // ---- Price chart -----------------------------------------------------

  _bindChartRanges() {
    this._el("ranges").addEventListener("click", (ev) => {
      const range = ev.target.dataset?.range;
      if (range) {
        this._range = range;
        this._renderChart();
      }
    });
  }

  _renderChart() {
    for (const btn of this._el("ranges").querySelectorAll("button")) {
      btn.classList.toggle("on", btn.dataset.range === this._range);
    }
    const chart = this._el("chart");
    if (!this._prices.length) {
      chart.innerHTML = `<div class="muted">No price data yet.</div>`;
      return;
    }

    // Points: [epoch days, kr per liter].
    const all = this._prices.map(([d, v]) => [dayNumber(d), v / 1000]);
    const last = all[all.length - 1][0];
    const span = CHART_RANGES[this._range];
    const points = all.filter(([d]) => d > last - span);
    const first = points[0][0];

    const W = 640, H = 240, L = 44, R = 12, T = 12, B = 26;
    let lo = Math.min(...points.map((p) => p[1]));
    let hi = Math.max(...points.map((p) => p[1]));
    const pad = Math.max((hi - lo) * 0.08, 0.05);
    lo -= pad;
    hi += pad;
    const x = (d) => L + ((d - first) / Math.max(1, last - first)) * (W - L - R);
    const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);

    const line = points.map(([d, v], i) => `${i ? "L" : "M"}${x(d).toFixed(1)},${y(v).toFixed(1)}`).join("");
    const grid = [0, 1, 2, 3]
      .map((i) => {
        const v = lo + ((hi - lo) * i) / 3;
        return `<line class="gridline" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"></line>
                <text class="axis" x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${v.toFixed(2)}</text>`;
      })
      .join("");
    const xLabels = [first, (first + last) / 2, last]
      .map((d, i) => `<text class="axis" x="${x(d)}" y="${H - 6}" text-anchor="${["start", "middle", "end"][i]}">${esc(fmtDate(isoFromDayNumber(Math.round(d))))}</text>`)
      .join("");

    const avg = this._state.price?.average_per_l;
    const avgLine =
      avg && avg > lo && avg < hi
        ? `<line class="avg" x1="${L}" x2="${W - R}" y1="${y(avg)}" y2="${y(avg)}"><title>${this._state.price.lookback_days}-day average ${fmtKr(avg)} kr/L</title></line>`
        : "";

    // The owner's fills inside the range: faint vertical line + dot on the price line.
    const byDay = new Map(points);
    const fills = this._state.fills
      .map((f) => [dayNumber(f.date), f])
      .filter(([d]) => d >= first && d <= last)
      .map(([d, f]) => {
        const v = byDay.get(d) ?? nearest(points, d)[1];
        const tip = `${fmtDate(f.date)}: ${fmtInt(f.liters)} L, paid ${fmtKr(f.price / f.liters)} kr/L`;
        return `<line class="fill-line" x1="${x(d)}" x2="${x(d)}" y1="${T}" y2="${H - B}"></line>
                <circle class="fill-dot" cx="${x(d)}" cy="${y(v)}" r="5"><title>${esc(tip)}</title></circle>`;
      })
      .join("");

    chart.innerHTML = `
      <svg class="chart" viewBox="0 0 ${W} ${H}">
        ${grid}${xLabels}${avgLine}${fills}
        <path class="price-line" d="${line}"></path>
        <line id="hover-line" class="hover-line" y1="${T}" y2="${H - B}" hidden></line>
        <circle id="hover-dot" class="hover-dot" r="4" hidden></circle>
        <rect id="hover-area" x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="transparent"></rect>
      </svg>
      <div class="muted small" id="hover-text">&nbsp;</div>
    `;

    // Hover / touch: nearest day's price under the pointer.
    const svg = chart.querySelector("svg");
    const area = this._el("hover-area");
    const hoverLine = this._el("hover-line");
    const hoverDot = this._el("hover-dot");
    const hoverText = this._el("hover-text");
    area.addEventListener("pointermove", (ev) => {
      const pt = svg.createSVGPoint();
      pt.x = ev.clientX;
      pt.y = ev.clientY;
      const px = pt.matrixTransform(svg.getScreenCTM().inverse()).x;
      const day = first + ((px - L) / (W - L - R)) * (last - first);
      const [d, v] = nearest(points, day);
      hoverLine.setAttribute("x1", x(d));
      hoverLine.setAttribute("x2", x(d));
      hoverDot.setAttribute("cx", x(d));
      hoverDot.setAttribute("cy", y(v));
      hoverLine.removeAttribute("hidden");
      hoverDot.removeAttribute("hidden");
      hoverText.textContent = `${fmtDate(isoFromDayNumber(d))}: ${fmtKr(v)} kr/L`;
    });
    area.addEventListener("pointerleave", () => {
      hoverLine.setAttribute("hidden", "");
      hoverDot.setAttribute("hidden", "");
      hoverText.innerHTML = "&nbsp;";
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
      : `<div class="muted">No deliveries yet. Log one, or import your history as CSV (date,liters,price).</div>`;
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

/** Point on the gauge arc for a fill fraction (0 = left, 1 = right). */
function gaugePoint(fraction, radius) {
  const angle = Math.PI * (1 - fraction);
  return [G.cx + radius * Math.cos(angle), G.cy - radius * Math.sin(angle)];
}

function arcPath(from, to) {
  const [x1, y1] = gaugePoint(from, G.r);
  const [x2, y2] = gaugePoint(to, G.r);
  return `M${x1},${y1} A${G.r},${G.r} 0 0 1 ${x2},${y2}`;
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

function fmtInt(value) {
  return Math.round(value).toLocaleString();
}

function fmtKr(value) {
  return value.toFixed(2);
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
  .segmented { display: flex; gap: 4px; }
  .segmented button.on { background: var(--accent-wash); border-color: var(--accent); }
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

  .gauge { width: 100%; max-width: 380px; display: block; margin: 0 auto; touch-action: none; cursor: pointer; user-select: none; }
  .zone { fill: none; stroke-width: ${G.width}; }
  .zone.bad { stroke: var(--bad); }
  .zone.warn { stroke: var(--warn); }
  .zone.good { stroke: var(--good); }
  .tick { fill: var(--muted); font-size: 11px; }
  .needle { stroke: var(--text); stroke-width: 4; stroke-linecap: round; }
  .estimate-mark { stroke: var(--text); stroke-width: 3; stroke-dasharray: 4 3; opacity: 0.7; }
  .hub { fill: var(--text); }
  .gauge-readout { text-align: center; margin-top: 4px; }
  .big { font-size: 22px; font-weight: 500; }
  .gauge-buttons { display: flex; justify-content: center; gap: 8px; margin: 10px 0 4px; }
  #calibration { text-align: center; margin-top: 8px; }

  .tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; }
  .tile { background: var(--panel-2); border-radius: 8px; padding: 10px 12px; }
  .value { font-size: 18px; font-weight: 500; margin-top: 2px; }
  .chip { display: inline-block; margin-top: 6px; padding: 2px 8px; border-radius: 10px; font-size: 12px; background: var(--hairline); }
  .chip.good { background: color-mix(in srgb, var(--good) 22%, transparent); color: var(--good); }
  .chip.bad { background: color-mix(in srgb, var(--bad) 22%, transparent); color: var(--bad); }

  .chart { width: 100%; display: block; touch-action: pan-y; }
  .gridline { stroke: var(--hairline); }
  .axis { fill: var(--muted); font-size: 11px; }
  .price-line { fill: none; stroke: var(--accent); stroke-width: 2; }
  .avg { stroke: var(--muted); stroke-dasharray: 5 4; }
  .fill-line { stroke: var(--good); opacity: 0.25; }
  .fill-dot { fill: var(--good); stroke: var(--panel); stroke-width: 2; }
  .hover-line { stroke: var(--muted); stroke-width: 1; }
  .hover-dot { fill: var(--accent); stroke: var(--panel); stroke-width: 2; }

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
