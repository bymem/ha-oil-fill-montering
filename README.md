# Oil Tank for Home Assistant

Estimates the oil left in a tank without a working gauge, follows the supplier's daily price, and recommends when to order.

Status: in development. See `docs/SPEC-2.md`.

## Install (HACS)

1. HACS → ⋮ → Custom repositories → add this repository URL, type **Integration**.
2. Download **Oil Tank**, then restart Home Assistant.
3. Settings → Devices & services → Add integration → **Oil Tank**.

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

## Privacy

Fill history is imported through the panel. Do not commit your own `fills.csv` to this public repository.
