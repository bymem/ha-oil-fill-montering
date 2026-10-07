# Oil Tank for Home Assistant

Keeps track of an oil tank without a working gauge. It estimates the oil left from outdoor temperature, follows the supplier's daily price, and tells you when it is a good moment to order.

- **Level estimate:** you set the gauge "needle" once; from then on the level is modelled from degree-days (outdoor temperature). Every new needle reading corrects the estimate and, slowly, the model itself.
- **Price:** today's list price from the supplier's feed, compared with the recent average.
- **Recommendation:** "order now" when oil runs low, "good time to order" when the price is good and the tank has room.
- **Panel:** a sidebar page with the gauge, outlook, price chart, fill-up form and history.

Built for the Uno-X heating oil feed (fyringsolie.dk), prices in DKK. Full specification: [`docs/SPEC-2.md`](docs/SPEC-2.md).

## Install (HACS)

1. HACS → ⋮ (top right) → **Custom repositories** → add `https://github.com/bymem/ha-oil-fill-montering`, type **Integration**.
2. Find **Oil Tank** in HACS, **Download**, then restart Home Assistant.
3. Settings → Devices & services → **Add integration** → **Oil Tank**.

Requires Home Assistant 2025.8 or newer and an outdoor temperature sensor.

## Setup

The setup screen asks for:

- **Tank capacity** in liters (default 1,200).
- **Outdoor temperature sensor** - any sensor with the temperature device class. Fahrenheit sensors are converted.
- **Price feed URL** - keep the default. Setup checks that the feed answers.

Then open **Oil tank** in the sidebar:

1. Drag the needle to what your tank's gauge shows and press **Save reading**. Level tracking starts here; before the first reading the level is unknown on purpose.
2. Optional: **Import CSV** in the History card to load your past deliveries (see below).

Everything else is under Settings → Devices & services → Oil Tank → **Configure**: yearly consumption, hot-water share, heating limit, delivery time, safety buffer, smallest worthwhile order, order window, price comparison window, and whether needle readings adjust the burn rate. Saving reloads the integration; readings and history are kept.

## Entities

| Entity | What it shows |
| --- | --- |
| `sensor.oil_tank_price` | Today's price in DKK/L. Attributes: average, low, high, % vs average, lowest-in-window, price age. |
| `sensor.oil_tank_level` | Estimated liters left. Always liters, also on US-unit systems. |
| `sensor.oil_tank_level_percent` | Estimated level as % of capacity. |
| `sensor.oil_tank_days_remaining` | Days until empty, forecast on normal temperatures for the season. |
| `sensor.oil_tank_order_by` | Last day to order, keeping delivery time and the safety buffer. |
| `number.oil_tank_tank_level_needle` | Slider in liters (10 L steps). Shows the estimate; setting it records a reading. |
| `binary_sensor.oil_tank_order_recommended` | On when you should order. Attribute `reason` explains why; `urgent` is true when oil is running out. |

## Logging a delivery

Use the fill-up form in the panel, or the `oil_tank.log_fill` action:

```yaml
action: oil_tank.log_fill
data:
  liters: 900
  price: 20100        # total paid, DKK
  date: "2026-10-07"  # optional, defaults to today
  level_after_liters: 1150  # optional: gauge reading after the delivery
```

With `level_after_liters` the delivery also counts as a needle reading. Without it, the estimate is raised by the delivered liters (capped at capacity). Duplicates (same date and liters) and future dates are rejected.

## Fill history CSV

The panel imports and exports a simple CSV, one delivery per row:

```
date,liters,price
12.01.26,950,20580
26.08.26,870,19400
```

`price` is the total paid for the delivery in DKK. Dates like `12.01.26`, `12.01.2026` and `2026-01-12` all work, as do `;`-separated files and Danish number formats. Importing the same file twice adds nothing. The history is used for the table, the chart and price-per-liter statistics; it never changes the level estimate.

**Privacy:** your fill history is your household's real purchase data. Do not commit it to this public repository (`docs/fills.csv` is git-ignored for that reason).

## Order notification

`binary_sensor.oil_tank_order_recommended` turns on when it is a good moment to order (good price and room in the tank) or when it is urgent. Its `reason` attribute explains why. Send yourself a notification with a normal automation; this example reminds at most once every 3 days while the sensor stays on. Replace `notify.notify` with your own notify action (for example `notify.mobile_app_your_phone`).

```yaml
alias: Oil tank - order reminder
mode: single
triggers:
  - trigger: state
    entity_id: binary_sensor.oil_tank_order_recommended
    to: "on"
  # Daily re-check so the reminder repeats while the sensor stays on.
  - trigger: time
    at: "09:00:00"
conditions:
  - condition: state
    entity_id: binary_sensor.oil_tank_order_recommended
    state: "on"
  # Cool-down: last_triggered only updates when the actions ran.
  - condition: template
    value_template: >
      {{ this.attributes.last_triggered is none
         or now() - this.attributes.last_triggered > timedelta(days=3) }}
actions:
  - action: notify.notify
    data:
      title: >
        {{ 'Order oil now' if state_attr('binary_sensor.oil_tank_order_recommended', 'urgent')
           else 'Good time to order oil' }}
      message: "{{ state_attr('binary_sensor.oil_tank_order_recommended', 'reason') }}"
```

## Security note

The panel is visible to all users, and its websocket commands (set the level, log, delete, import and export deliveries) are open to any logged-in Home Assistant user. It is meant as a shared household panel.

## Development

- `custom_components/oil_tank/` - the integration. `feed.py`, `prices.py`, `csv_io.py`, `model.py` and `decision.py` are pure logic with no Home Assistant imports.
- `tests/` - unit tests for the pure logic. Run them without installing anything locally:

  ```sh
  docker run --rm -v "$PWD":/src -w /src python:3.13-alpine \
    sh -c "pip install -q pytest && python -m pytest -q -p no:cacheprovider"
  ```

- Iterate against a test Home Assistant by mounting `custom_components/oil_tank` into its `/config/custom_components/oil_tank` and restarting the container.
- Releases: bump `version` in `manifest.json`, tag `vX.Y.Z`, publish a GitHub release. HACS offers the new version as an update.
