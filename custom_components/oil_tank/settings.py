"""Effective settings for the config entry (spec section 8).

Setup values live in `entry.data`, everything changed later in
`entry.options`; options win. Missing keys fall back to the defaults, so
entries created by older versions keep working without a migration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_ANNUAL_CONSUMPTION_L,
    CONF_BASE_LOAD_SHARE,
    CONF_BASE_TEMP_C,
    CONF_BUFFER_DAYS,
    CONF_CALIBRATION_ENABLED,
    CONF_CAPACITY_L,
    CONF_FEED_URL,
    CONF_GAUGE_OFFSET_L,
    CONF_GAUGE_SCALE_MAX,
    CONF_LEAD_DAYS,
    CONF_LOOKBACK_DAYS,
    CONF_MIN_ORDER_L,
    CONF_STOCK_UP_DAYS,
    CONF_STOCK_UP_PERCENT,
    CONF_TEMPERATURE_ENTITY,
    CONF_WINDOW_DAYS,
    DEFAULTS,
)


@dataclass(frozen=True)
class Settings:
    """All tunable values in one place."""

    capacity_l: float
    temperature_entity: str
    feed_url: str
    annual_consumption_l: float
    base_load_share: float
    base_temp_c: float
    lead_days: int
    buffer_days: int
    min_order_l: float
    window_days: int
    lookback_days: int
    calibration_enabled: bool
    gauge_offset_l: float
    gauge_scale_max: float
    stock_up_percent: float
    stock_up_days: int

    @classmethod
    def from_entry(cls, entry: ConfigEntry) -> Settings:
        values: dict[str, Any] = {**DEFAULTS, **entry.data, **entry.options}
        capacity = float(values[CONF_CAPACITY_L])
        return cls(
            capacity_l=capacity,
            temperature_entity=values[CONF_TEMPERATURE_ENTITY],
            feed_url=values[CONF_FEED_URL],
            annual_consumption_l=float(values[CONF_ANNUAL_CONSUMPTION_L]),
            base_load_share=float(values[CONF_BASE_LOAD_SHARE]),
            base_temp_c=float(values[CONF_BASE_TEMP_C]),
            # Number selectors return floats; day counts are whole days.
            lead_days=int(values[CONF_LEAD_DAYS]),
            buffer_days=int(values[CONF_BUFFER_DAYS]),
            min_order_l=float(values[CONF_MIN_ORDER_L]),
            window_days=int(values[CONF_WINDOW_DAYS]),
            lookback_days=int(values[CONF_LOOKBACK_DAYS]),
            calibration_enabled=bool(values[CONF_CALIBRATION_ENABLED]),
            gauge_offset_l=float(values[CONF_GAUGE_OFFSET_L]),
            gauge_scale_max=float(values[CONF_GAUGE_SCALE_MAX] or capacity),
            stock_up_percent=float(values[CONF_STOCK_UP_PERCENT]),
            stock_up_days=int(values[CONF_STOCK_UP_DAYS]),
        )
