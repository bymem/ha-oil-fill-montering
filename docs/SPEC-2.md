# Oil Tank for Home Assistant - Specification

Status: draft for sign-off. Version 0.3 of this document, 2026-10-07.

Changes in 0.3: the needle (number entity, panel gauge, websocket `set_level`) and the fill-up "level after delivery" field use liters instead of percent; the needle moves in 10 L steps.

Changes in 0.2: distributed through HACS from a public repository; the fill history is no longer bundled with the integration and is imported through the panel instead; the real fill history is replaced by synthetic sample data in this document and in the tests; integration with its own panel confirmed.

This document is written to be handed to a development environment and built from, in a repository, iteratively. It is self-contained. Where a decision has not been confirmed by the owner it is marked **PROPOSED** and listed again in section 13.

Legend used throughout:

* **CONFIRMED** - stated by the owner.
* **PROPOSED** - suggested during scoping, not yet approved.
* **VERIFIED** - checked against real data or a running Home Assistant test instance during prototyping.

---

## 1. Purpose

A household heats with oil. Today there is no way to know (a) roughly how much oil is left, because the tank gauge is broken and unreliable, or (b) whether now is a good moment to order, given the supplier's daily price.

Build something for Home Assistant that:

1. follows the supplier's daily oil price,
2. estimates the oil left in the tank without a working gauge,
3. lets a person tell the system the real level by setting a gauge "needle" in the interface,
4. records deliveries ("fill-ups") with date, liters and price,
5. sends a notification when it is beneficial to top up, considering both the price and how much oil is left. **CONFIRMED**

### Non-goals

* No hardware level sensor support (the owner looked and found nothing feasible). **CONFIRMED**
* No automatic ordering, no supplier login, no payment.
* Single tank, single household, single supplier feed.
* No weather-forecast integration in v1 (see 13).

---

## 2. Facts and context

| Item | Value | Status |
| --- | --- | --- |
| Tank capacity | about 1,200 L (owner: "roughly"). The largest historical fill was 1,203 L, so the real capacity may be slightly larger or the tank was near empty at each fill. Must be configurable. | CONFIRMED (approx.) |
| Typical yearly consumption | about 1,790 L (range 1,645 to 1,928 L over 2017-2023) | VERIFIED from the owner's history |
| Typical delivery size | 800 to 1,200 L, normally two per year (January, plus May to September) | VERIFIED |
| Tank run-down habit | Historic data suggests the tank was usually run close to empty before a delivery | VERIFIED (inferred from the year-end splits in the source sheet) |
| Supplier | Uno-X heating oil, fyringsolie.dk | CONFIRMED |
| Delivery time | within 3 working days (faster costs a fee) | from supplier site |
| Price history available | 731 consecutive daily prices, 2024-10-07 to 2026-10-07, no gaps | VERIFIED |
| Price on 2026-10-07 | 22,321 DKK per 1000 L (22.32 DKK/L); 30-day average 22,811; 2-year range 16,237 to 23,521 | VERIFIED |
| Hot water | Share of oil used for hot water is unknown; default 20% (tunable) | PROPOSED |
| Platform | Home Assistant (current stable), Linux server; owner is a professional developer (PHP/WordPress primary, learning C#) | CONFIRMED |

---

## 3. Data sources

### 3.1 Price feed

* URL (default, configurable): `https://www.fyringsolie.dk/api/yx-xml/pg000015BULK.xml`
* **The URL ends in `.xml` but the body is JSON** (VERIFIED from a downloaded copy). Parse by content, not by content type. The shape is:

```json
{"prices":{"price":[{"@_date":"07.10.2024","value":16437.25}, {"@_date":"08.10.2024","value":16437.25}]}}
```

* `@_date` is `dd.mm.yyyy`. `value` is the **list price in DKK per 1000 litres, including whatever the supplier includes in the list price**, one entry per calendar day, oldest first, containing the full two-year history on every request.
* The supplier's web page also shows an "internet price" for the logged-in customer, which differs from the list price. The feed gives only the list price. The system compares list prices to list prices (trend), so the offset does not matter for the buy decision.
* Tolerate: BOM, single-row objects instead of arrays (XML-to-JSON converters do this), bad rows (skip them), and a feed with zero usable rows (treat as an error and keep the previous data).
* If the feed ever returns real XML, that is an error in v1 (surface "unexpected format"; do not guess).
* Poll at most every 3 hours (prices change once a day). After a failed fetch retry after 30 minutes. A failing feed must never break level tracking.
* A newest price older than 3 days is **stale**: the system must not give price-based advice from stale data.

### 3.2 Fill history: the one and only CSV

**There is exactly one CSV in this system: `fills.csv`, supplied by the owner. No other CSV file will ever be provided or required** (no readings file, no tank-level history, no price history file; prices come from the feed in 3.1 and levels come from the needle in FR-3).

* **Location:** kept by the owner, outside the repository (the repository is public). It is **not** bundled with the integration. The owner imports it once through the panel's Import CSV (FR-5); the history is empty until then.
* **Columns: exactly three, in this order, header row required:** `date,liters,price`. Nothing else: no bonus/rebate column, no opening-stock row, no notes column.
* **One row = one oil delivery.** `price` = total paid for that delivery in DKK. `liters` = litres delivered.
* **Delivered file format (the owner's real file):** comma-separated, dates written `dd.mm.yy` (two-digit year), plain integers for litres and price:

  ```
  date,liters,price
  12.01.16,950,6650
  26.08.26,870,19400
  ```

  Rows are in chronological order, but the system must not depend on that. Appendix A holds a synthetic sample in this format, used as the test fixture.
* **Two-digit years:** interpreted as 20yy (all deliveries are 2015 or later; pivot per Python `%y`, 00-68 = 2000s).
* **The parser is still tolerant** so that a re-saved file does not break: dates `YYYY-MM-DD`, `dd.mm.yyyy`, `dd-mm-yyyy`, `dd/mm/yyyy`, `dd.mm.yy`; delimiters `,` `;` tab; numbers like `12490`, `12.490`, `12 490,50`, `1,234.56`, trailing `kr`/`DKK`/`L`; header aliases (case-insensitive) date/dato, liters/litres/liter/l/amount, price/pris/total/kr/dkk; a headerless file is accepted if the first cell parses as a date. Tolerance is a safety net, not a second supported format.
* **Validation:** `0 < liters <= 20000`, `0 <= price <= 1,000,000`. A bad row is reported with its row number and skipped; good rows are still imported.
* **Identity of a fill** = same date and same liters (rounded to 0.1). Importing the same data twice changes nothing.
* **Tank level at the start is NOT in the CSV.** The first needle reading (FR-3) is where level tracking starts. The CSV is used for the history table, the cost/price-per-litre statistics and the calibration baseline, never to reconstruct the tank level.
* **After import, Home Assistant's own storage is the source of truth.** New deliveries are logged in the panel (FR-4). The panel's Export CSV writes the same three columns (ISO dates, dot decimals) as a backup; Import CSV in the panel accepts the same single format.
* **Privacy:** this file is the household's real purchase history. It must never be committed to the public repository (`docs/fills.csv` is gitignored), and the README must warn about it.

### 3.3 Outdoor temperature

* One Home Assistant sensor entity (temperature device class), chosen at setup, changeable later. **CONFIRMED**
* Fahrenheit sensors are converted to Celsius.

---

## 4. Functional requirements

### FR-1 Price tracking
1. Expose today's price (DKK/L) and statistics against a comparison window (default 30 days): average, low, high, percent versus average, whether today is the lowest of the window, and the age of the newest price in days.
2. "Lowest of the window" means: today is no more than 0.25% above the lowest of the *earlier* days in the window.
3. Expose the full price history to the panel.

### FR-2 Level estimate
1. The level is **unknown** until the first needle reading. Nothing may be guessed before that.
2. After a reading, the estimate is the reading minus modelled consumption since then (section 6), clamped to `[0, capacity]`.
3. Expose liters, percent of capacity, days of oil left, and the order-by date.

### FR-3 Needle (manual level reading)
1. In the panel: a semicircular gauge in liters, 0 L at the left, tank capacity at the right, with a draggable needle. Dragging does **not** save; a Save button records the reading and a Cancel button discards it.
2. While dragging, show the model's current estimate as a secondary marker so the person sees how far off the model was.
3. Also available as a Home Assistant `number` entity (slider, 0 to capacity in liters, step 10 L) whose state is the current estimate and whose write records a reading, so it can be used on dashboards and in automations.
4. Recording a reading: store `{time, liters, degree-day counter}` as the new baseline and (if enough time has passed) nudge the burn-rate scale (section 6.4).

### FR-4 Fill-up logging
1. Panel form: date (default today, not in the future), liters, total price (DKK), optional "tank level after delivery (L)". Also a service `oil_tank.log_fill`. **CONFIRMED**.
2. Rejected: duplicate (same date and liters), non-positive liters, negative price, future date.
3. Effect on the estimate:
   * with "level after" given: that value is recorded as a reading (a calibration point) and the delivered liters are accounted for in the learning step;
   * without it: if the delivery date is on or after the date of the last reading, the estimate is re-based to `min(capacity, current estimate + liters)`; if the delivery is older than the last reading it is history only (the reading already includes it);
   * with no reading yet: stored as history only.
4. A delivery can be deleted from the history. Deleting does not change the level estimate.

### FR-5 History import/export
1. First start: the history is empty. No file is bundled or read at startup.
2. Panel buttons: Import CSV (merge, report added/skipped/bad rows) and Export CSV (download). Importing the same file again changes nothing.

### FR-6 Recommendation and notification
1. A binary entity "order recommended" with a human-readable reason attribute (section 7).
2. The notification itself is a normal Home Assistant automation triggered by that entity; ship a documented example with a cool-down (at most one reminder per 3 days). The recipient is the owner's choice. **CONFIRMED** (wants a notification) / **PROPOSED** (mechanism).

### FR-7 Panel
A sidebar entry "Oil tank" containing: recommendation banner, gauge/needle, outlook statistics, price chart, fill-up form, fill history. Detailed behaviour in section 9. **CONFIRMED** (integration with its own panel).

### FR-8 Configuration
Setup screen: tank capacity (default 1,200 L), outdoor temperature sensor, feed URL. Options screen: all of those plus the tuning values in section 8. Changing options reloads the integration. **CONFIRMED** for capacity and temperature sensor; the rest PROPOSED.

---

## 5. Estimation of consumption

Per day, the oil burned is modelled as:

```
burn_per_day = scale * ( base_l_per_day + l_per_degree_day * degree_days_that_day )
degree_days  = max(0, base_temp - outdoor_temp)         # base_temp default 17 C
```

Rates are derived from one number the owner can sanity-check (yearly consumption):

```
base_l_per_day = annual_l * base_share / 365
l_per_dd       = annual_l * (1 - base_share) / annual_normal_dd
annual_normal_dd = sum over months( max(0, base_temp - normal_temp[m]) * days[m] )
```

Normal monthly mean temperatures (Danish, approximate), used for the annual normal and for forecasting:

| Month | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| deg C | 1.8 | 1.7 | 3.9 | 8.0 | 12.3 | 15.7 | 18.0 | 17.7 | 14.0 | 9.6 | 5.6 | 2.7 |

(days per month: 31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)

With the defaults (`annual_l` 1,790; `base_share` 0.2; `base_temp` 17): annual normal degree-days = **2,869**; `base_l_per_day` = **0.98 L/day**; `l_per_dd` = **0.499 L/DD**; typical burn is about 8.6 L/day in January, 5.5 in April, 1.0 in July, 4.7 in October. (VERIFIED against the prototype.)

### 5.1 Degree-day accumulation
* A single monotonic counter `dd` is kept in storage. Each time the temperature sensor changes (and on a 10-minute tick), add `max(0, base_temp - previous_temp) * elapsed_days` (step integral using the *previous* temperature for the elapsed interval, then read the new one).
* A temperature reading older than 6 hours is not trusted, and a gap longer than 2 days (e.g. Home Assistant down) is filled with the normal degree-days for the current month rather than stalling.
* A reading's baseline stores the counter value at that moment, so consumption since the baseline = `dd_now - dd_at_baseline`. No history of temperatures is needed.

### 5.2 Estimate since a baseline
```
burn_since = scale * ( base_l_per_day * days_since + l_per_dd * (dd_now - dd_baseline) )
level      = clamp(baseline_liters - burn_since, 0, capacity)
```

### 5.3 Days left (forecast)
Walk forward one day at a time from today using **normal** monthly temperatures (not recent temperatures), subtracting that day's modelled burn, until the level reaches zero. Return a fractional number of days, capped at 730. Reason: in autumn the recent temperatures understate what winter will burn, which would give a dangerously optimistic days-left figure.

Test vectors (tank 1,200 L, defaults, scale 1.0, today 2026-10-07): 150 L -> 30.0 days; 300 L -> 52.5; 450 L -> 71.4; 600 L -> 89.7; 800 L -> 113.0; 1,000 L -> 136.2. (VERIFIED.)

### 5.4 Learning from corrections (self-calibration)
On each reading after an earlier baseline:

```
predicted = burn_since(...)                 # at the current scale
actual    = baseline_liters + delivered_since - new_reading
if interval_days >= 14 and predicted >= 20:
    ratio = clamp(max(actual, 0) / predicted, 0.5, 2.0)
    scale = clamp(scale * (1 + 0.3 * (ratio - 1)), 0.5, 2.0)
```

Damped on purpose: the reading is an eyeballed gauge. Show the last correction in the UI ("the model said X L, you set Y L"). **PROPOSED**; must be switchable off (see 13).

---

## 6. Data model and persistence

One persisted document (Home Assistant `Store`, version 1):

```json
{
  "fills": [{"id": "a1b2c3d4", "date": "2026-01-08", "liters": 800.0, "price": 14000.0}],
  "baseline": {"ts": "2026-10-07T08:00:00+00:00", "liters": 600.0, "dd": 123.4},
  "dd": 130.2,
  "scale": 1.0,
  "last_ts": "...", "last_temp": 7.5, "last_temp_ts": "...",
  "last_calibration": {"ts": "...", "estimated_l": 700.0, "reading_l": 650.0}
}
```

* Save immediately after any user action; otherwise debounce (60 s).
* Prices are **not** persisted (the feed returns the full history each time). On restart before the first successful fetch, price entities are `unknown`; level tracking still works.
* `fills[].id` is a short random id used for deletion. Fills are returned newest first.

---

## 7. Recommendation logic

Inputs: level, days left, today, price statistics, settings (section 8).

```
slack      = days_left - lead_days - buffer_days
order_by   = today + floor(max(0, slack)) days
room       = capacity - level

1. no level yet                         -> order=false  "Set the tank level (needle) to start tracking."
2. slack <= 0                           -> order=TRUE, urgent   "Order now: about N days of oil left and delivery takes ~L days."
3. room < min_order                     -> false        "Tank has room for only R L (minimum order M L). Order by D."
4. slack > window_days                  -> false        "No need yet: order by D (about N days of oil left)."
5. no price data or price stale (>3 d)  -> false        "No fresh price data. Order by D."
6. good price:
     today is lowest of the window                        -> "cheapest in W days"
     or percent vs average <= -3                          -> "X% below the W-day average"
     or slack <= 7 and percent vs average <= 0            -> "below the recent average and the order-by date is close"
   -> order=TRUE        "Good time to order: P kr/L is <good>. Order by D."
7. otherwise                            -> false        "Waiting for a better price (P kr/L, +x% vs average). Order by D."
```

The checks run in that order, first match wins. The urgent case ignores price entirely.

Defaults: `lead_days` 5 (3 working days plus weekend slack), `buffer_days` 14, `min_order_l` 500, `window_days` 45, `lookback_days` 30.

Worked example on real data, 2026-10-07 (price 22,321 vs 30-day average 22,811 = -2.15%, not the lowest of the window; the cheaper days were 8 and 10 September):

| Level | Days left | Result |
| --- | --- | --- |
| 150 L | 30.0 | waiting for a better price, order by 17 Oct (slack 11 days, inside the window) |
| 300 L | 52.5 | waiting for a better price, order by 9 Nov |
| 450 L | 71.4 | no need yet, order by 28 Nov |
| 800 L | 113.0 | tank has room for only 400 L |

Note for the owner: because the tank is small compared with winter burn (about 8 to 9 L/day in January), the "room for a worthwhile order" rule is what mostly gates the opportunistic alert; the urgent rule is the safety net.

---

## 8. Configuration

| Key | Default | Where | Meaning |
| --- | --- | --- | --- |
| `capacity_l` | 1200 | setup + options | tank capacity in liters |
| `temperature_entity` | (required) | setup + options | outdoor temperature sensor |
| `feed_url` | the default feed | setup + options | price feed |
| `annual_consumption_l` | 1790 | options | typical yearly consumption |
| `base_load_share` | 0.2 | options | share of oil that is not space heating |
| `base_temp_c` | 17 | options | heating limit for degree-days (10 to 25) |
| `lead_days` | 5 | options | calendar days from order to delivery |
| `buffer_days` | 14 | options | safety margin |
| `min_order_l` | 500 | options | smallest worthwhile order |
| `window_days` | 45 | options | how long before the order-by date to look for a good price |
| `lookback_days` | 30 | options | price comparison window |

Setup validates the feed (reachable and parseable) and shows a clear error otherwise. Single instance only. Options changes reload the integration.

---

## 9. Home Assistant surface

### 9.1 Integration
* Domain `oil_tank`, custom integration in `custom_components/oil_tank/`, config-flow only (no YAML), `integration_type: service`, `iot_class: cloud_polling`, single config entry, no external Python requirements.
* One device "Oil tank" with `has_entity_name = true`.

### 9.2 Entities

| Entity | Notes |
| --- | --- |
| `sensor.oil_tank_price` | DKK/L, 2 decimals; attributes: price per 1000 L, price date, N-day average/low/high per L, percent vs average, lowest-in-window, age in days |
| `sensor.oil_tank_level` | liters, `unknown` until a reading exists |
| `sensor.oil_tank_level_percent` | percent of capacity |
| `sensor.oil_tank_days_remaining` | days (duration device class) |
| `sensor.oil_tank_order_by` | date device class |
| `number.oil_tank_tank_level_needle` | slider 0 to capacity in liters, step 10 L; state = estimate, write = record a reading |
| `binary_sensor.oil_tank_order_recommended` | attributes: `reason`, `urgent`, `order_by`, `days_remaining`, `level_liters`, `level_percent`, `price_per_l`, `percent_vs_average` |

Entities refresh every 10 minutes and immediately after any user action.

### 9.3 Services
* `oil_tank.log_fill` - `liters` (required), `price` (required), `date` (optional, default today in the HA time zone), `level_after_liters` (optional, 0 to capacity).

### 9.4 Websocket commands (used by the panel, available to any logged-in user)

| Command | Payload | Result |
| --- | --- | --- |
| `oil_tank/get_state` | - | state object (capacity, level, percent, days left, order-by, recommendation, price stats, fills newest-first, scale, last calibration, `prices_version`) |
| `oil_tank/get_prices` | - | `{prices: [[iso_date, price_per_1000_l], ...]}` |
| `oil_tank/set_level` | `liters` 0 to capacity | new state |
| `oil_tank/log_fill` | `date` (ISO), `liters`, `price`, optional `level_after_liters` | new state, or an error with a readable message |
| `oil_tank/delete_fill` | **`fill_id`** | new state |
| `oil_tank/import_csv` | `text` (max 1 MB) | `{added, skipped, errors[]}` |
| `oil_tank/export_csv` | - | `{text}` |

**Gotcha (hit during prototyping):** a payload field named `id` collides with the websocket message id and makes the command invalid. Use `fill_id`.

### 9.5 Panel behaviour
Plain custom element (web component), **no build step**, served from the integration folder as a static file, registered as a custom sidebar panel (`require_admin: false`), icon `mdi:barrel`. Uses Home Assistant theme CSS variables so it follows light/dark themes. Responsive down to phone width. All text inserted into the page is escaped.

1. **Banner**: title "Order now" (urgent), "Good time to order" or "No action needed", plus the `reason` text. Colour-coded.
2. **Gauge**: SVG semicircle labelled in liters (0 to capacity), red zone 0-15% of capacity, amber 15-30%, green 30-100%. The needle is draggable by pointer or touch; the value snaps to 10 L steps; dragging below the horizon snaps to the nearest end. While dragging show liters and "(not saved yet)", the dashed estimate marker, and Save/Cancel. Under the gauge: "Last reading: the model said X L, you set Y L". With no baseline: "Set the needle" and no needle drawn.
3. **Outlook**: days of oil left, order-by date, today's price with a chip showing percent vs the average (green at or below -3%, red at or above +3%), window range, price date (flag if older than 2 days), burn-rate factor.
4. **Price chart**: SVG line of the list price per liter. Range buttons 3 months / 1 year / all. Dashed horizontal line for the window average. A dot and faint vertical line for each of the owner's fills that fall inside the range. Hover shows the date and price. Refetch prices only when `prices_version` changes.
5. **Fill-up form**: date, liters, total price, optional level after (L), live "= x.xx kr/L". Success and error toasts. The form is not cleared by the 60-second state refresh.
6. **History**: table newest first (date, liters, paid, kr/L, delete with confirmation) plus Import CSV and Export CSV.
7. The panel polls `get_state` every 60 seconds and after every action; it must never wipe half-typed form input on refresh.

---

## 10. Failure behaviour

| Situation | Behaviour |
| --- | --- |
| Feed unreachable / not parseable | keep previous prices, show an error in the panel, retry in 30 min; level tracking unaffected; setup itself fails only if the feed is bad *at setup time* (clear message) |
| No fresh price (>3 days) | no price-based advice; urgent advice still works |
| Temperature sensor unavailable | use the last reading for up to 6 hours, then normal temperatures for the gap |
| Home Assistant down for days | the gap is filled with normal degree-days on restart |
| Estimate reaches 0 | level 0, days left 0, urgent order |
| Estimate above capacity | clamped to capacity |
| Duplicate fill / bad CSV row | rejected or skipped with a message; never corrupts the history |
| Integration reload/unload | state is saved; services and the sidebar entry are removed on unload and re-created on load |

---

## 11. Non-functional requirements

* **Performance:** the price feed is about 30 KB; fetch at most every 3 hours. Never block the event loop (read files in the executor). The 60-second panel poll must not include the price history. The model is O(days to forecast) with a 730-iteration cap - negligible.
* **Maintainability:** keep it simple. Put all pure logic (feed parser, CSV, model, decision) in modules that import nothing from Home Assistant so they can be unit tested without it. Comment the code well enough that the code documents itself. English for everything: code, comments, identifiers, UI text.
* **No personal names** in code, comments, README or commit messages; use "Author" or "Maintainer" if attribution is needed.
* **Privacy:** the owner's CSV is the household's real purchase history and is never committed (the repository is public). Tests and this document use synthetic data only.
* **Security:** websocket commands are open to all logged-in users (a household panel); document this. Never log full CSV contents.
* **Distribution:** HACS custom repository (public GitHub repository, type Integration). `hacs.json` in the repository root. Releases are GitHub releases with semver tags (`v0.1.0`); the `version` in `manifest.json` matches the tag. Development iterates on a test Home Assistant instance with `custom_components/oil_tank` mounted from the repository.

---

## 12. Test and acceptance criteria

### 12.1 Unit tests (no Home Assistant needed)
* Feed: parses and sorts; skips bad rows; accepts a single-row object; rejects non-JSON, `{}`, empty list.
* CSV (sample file `tests/fixtures/fills_sample.csv`, Appendix A): parses to exactly 22 rows with 0 errors, ascending after sorting, first 2016-01-12/950/6650, last 2026-08-26/870/19400, totals 20,660 L and 242,200 DKK; `dd.mm.yy` maps to 20yy. Also: Danish formats (`;`, `6.566,00`, `dd.mm.yyyy`), header aliases, BOM, headerless, bad rows reported while good rows kept, empty file, merge idempotent and sorted, export then import round-trips.
* Model: default rates reproduce the yearly consumption within 1% over a normal year; level burns and clamps at 0 and capacity; forecast shorter in autumn than summer for the same level; the test vectors in 5.3; calibration ignores short intervals and tiny predictions, is damped and capped.
* Prices: lowest-of-window detection, percent vs average, empty list, the real-data case (today not lowest because 22,121 was lower within 30 days).
* Decision: one test per branch in section 7.

### 12.2 Home Assistant integration tests
Use `pytest-homeassistant-custom-component`. Needed to make it work (hit during prototyping): `asyncio_mode = auto`, the `home-assistant-frontend` package at the version the installed Home Assistant requires (the `frontend` dependency fails to set up without it), and the `enable_custom_integrations` fixture. Cover: setup creates all entities; history empty at first start and the websocket import of the Appendix A file adds 22 rows; level unknown before a reading; needle write -> level; `log_fill` with and without level-after, capped at capacity, duplicate rejected; state survives a reload; degree-day integration (7 C for one day = 10 DD) and the long-gap fallback; websocket commands incl. import/export/delete; unload removes services; config flow success, `cannot_connect`, `invalid_feed`; a dead feed does not break setup; panel registered and the JS file served.

### 12.3 Panel smoke test
Run the component in jsdom against a stubbed `hass`: banner and escaping, gauge text, drag -> Save payload, Cancel, chart point counts per range (92 / 366 / all) and marker counts, hover, form submit payloads (with and without level-after), delete payload uses `fill_id`, import/export calls, no-baseline state, no uncaught errors.

### 12.4 Manual acceptance (on a real instance)
1. Install through HACS (custom repository), add the integration, set capacity and sensor; price sensor shows today's price.
2. Open the sidebar panel, drag the needle, Save; the level entity matches.
3. Log a fill-up; history and level update; Export gives back a valid CSV.
4. Make `binary_sensor.oil_tank_order_recommended` turn on (set a low level) and receive the example notification.
5. Import the owner's CSV in the panel; importing it a second time adds nothing.
6. Restart Home Assistant; nothing is lost.

---

## 13. Open decisions (owner sign-off needed)

| # | Decision | Recommendation |
| --- | --- | --- |
| 1 | Integration with its own panel, or a lighter YAML package with a standard dashboard card? | **Decided (0.2):** integration + panel. |
| 2 | Learning from needle corrections: on, off, or off by default? | On, damped, with an option to disable; the household's gauge is unreliable so corrections are noisy. |
| 3 | Is `price` in the CSV gross or net of any rebate? | Whatever was actually paid. |
| 4 | Exact tank capacity (1,200 vs slightly larger)? | Configurable; leave 1,200 until measured. |
| 5 | Notification: documented automation example, or a built-in notify target option in the integration? | Automation example; keeps the integration smaller. |
| 6 | Panel open to all users, or admin only? | All users (a household panel). |
| 7 | Use a weather forecast for days-left instead of normal temperatures? | Not in v1. Possible later via the Home Assistant weather entity. |
| 8 | Default hot-water share 20%? | Keep; it is only a starting point and self-calibration corrects it. |
| 9 | Keep the bundled seed file out of version control? | **Decided (0.2):** the repository is public, so nothing is bundled; the owner imports the CSV through the panel. |
| 10 | Compare against 30 days only, or also 60? | 30 default, configurable. At the time of writing the price was cheap versus the last month but about 150 DKK/1000 L above the 60-day average, so the window genuinely changes the advice. |

---

## 14. Suggested build order (iterative, in a repository)

1. **M1 - Foundation:** feed parser, CSV module, constants, tests. Integration skeleton: config flow (with feed validation), coordinator polling the feed, the price sensor and its attributes, placeholder sidebar panel.
2. **M2 - Level model:** storage, temperature integration, baseline, estimate, days left, order-by, level entities, needle number entity, `log_fill` service, calibration. Unit and Home Assistant tests.
3. **M3 - Recommendation:** decision logic, binary sensor, example automation in the README.
4. **M4 - Panel:** websocket API, gauge, outlook, fill form, history, CSV import/export, chart. jsdom smoke test.
5. **M5 - Polish:** options flow, error messages, README, translations, manual acceptance on a real instance.

Each milestone should leave a working, installable integration.

---

## 15. Prototype learnings worth keeping

* A throw-away prototype of this design was built and passed 44 automated tests (pure logic, a real Home Assistant test instance, and a jsdom panel smoke test), run on Home Assistant 2026.2.3. It has never been run on a live installation or in a real browser. It is optional reference material, not a dependency of this spec.
* The websocket `id` collision (9.4), the `home-assistant-frontend` test requirement (12.2), and reading files off the event loop were the only real defects found.
* The price feed's `.xml` URL returns JSON (3.1).
* The source sheet's year-end "meter reading" rows are eyeballed levels (round numbers like 300, 400, 500), which is why the model treats readings as noisy and damps its learning.

---

## Appendix A - Sample fill history (synthetic)

Made-up data in the owner's format, used as the test fixture `tests/fixtures/fills_sample.csv`. The owner's real file is never committed.

```
date,liters,price
12.01.16,950,6650
14.06.16,880,5900
18.01.17,1010,7480
22.07.17,900,6930
09.01.18,980,8040
05.06.18,940,8180
15.01.19,1005,8950
11.07.19,870,7920
13.01.20,960,8640
20.05.20,890,5790
08.01.21,995,7560
16.06.21,860,7740
11.01.22,970,10670
03.08.22,1080,18360
17.01.23,920,13800
24.08.23,860,12470
10.01.24,940,13160
19.06.24,890,12460
14.01.25,1000,16500
02.07.25,910,15020
13.01.26,980,20580
26.08.26,870,19400
```

Parsed: 22 rows, 0 errors; first 2016-01-12 / 950 L / 6,650 DKK; last 2026-08-26 / 870 L / 19,400 DKK; totals 20,660 L and 242,200 DKK.

## Appendix B - Price feed sample

```json
{"prices":{"price":[
  {"@_date":"07.10.2024","value":16437.25},
  {"@_date":"08.10.2024","value":16437.25},
  ...
  {"@_date":"06.10.2026","value":22521},
  {"@_date":"07.10.2026","value":22321}
]}}
```

Recent values: 2026-09-17 peak 23,521; 2026-10-01 22,521; 2026-10-05 22,721; 2026-10-06 22,521; 2026-10-07 22,321.
