# Oil Tank for Home Assistant

Estimates the oil left in a tank without a working gauge, follows the supplier's daily price, and recommends when to order.

Status: early skeleton. See `docs/SPEC-2.md`.

## Install (HACS)

1. HACS → ⋮ → Custom repositories → add this repository URL, type **Integration**.
2. Download **Oil Tank**, then restart Home Assistant.
3. Settings → Devices & services → Add integration → **Oil Tank**.

## Privacy

Fill history is imported through the panel. Do not commit your own `fills.csv` to this public repository.
