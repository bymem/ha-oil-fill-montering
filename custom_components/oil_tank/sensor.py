"""Sensors for Oil Tank: price (from the feed) and the level estimate."""

from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfTime, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .coordinator import OilTankCoordinator
from .data import OilTankConfigEntry
from .entity import TankEntity, device_info
from .tank import TankManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OilTankConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the sensors for this config entry."""
    tank = entry.runtime_data.tank
    async_add_entities(
        [
            OilTankPriceSensor(entry.runtime_data.coordinator, entry.entry_id),
            LevelSensor(tank, entry.entry_id),
            LevelPercentSensor(tank, entry.entry_id),
            DaysRemainingSensor(tank, entry.entry_id),
            OrderBySensor(tank, entry.entry_id),
        ]
    )


class OilTankPriceSensor(CoordinatorEntity[OilTankCoordinator], SensorEntity):
    """Newest list price in DKK per liter, with window stats as attributes."""

    _attr_has_entity_name = True
    _attr_translation_key = "price"
    _attr_native_unit_of_measurement = "DKK/L"
    _attr_suggested_display_precision = 2
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:cash"

    def __init__(self, coordinator: OilTankCoordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_price"
        self._attr_device_info = device_info(entry_id)

    @property
    def available(self) -> bool:
        """Stay available on a failed fetch as long as earlier prices exist."""
        return self.coordinator.data is not None

    @property
    def native_value(self) -> float | None:
        """Feed prices are per 1000 L; the sensor shows per liter."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.stats.price / 1000

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Window stats from spec 9.2; per-liter values rounded to 4 decimals."""
        if self.coordinator.data is None:
            return None
        stats = self.coordinator.data.stats
        return {
            "price_per_1000_l": stats.price,
            "price_date": stats.price_date.isoformat(),
            "lookback_days": stats.lookback_days,
            "average_per_l": round(stats.average / 1000, 4),
            "low_per_l": round(stats.low / 1000, 4),
            "high_per_l": round(stats.high / 1000, 4),
            "percent_vs_average": round(stats.percent_vs_average, 2),
            "lowest_in_window": stats.lowest_in_window,
            # From today, not the last fetch, so a dead feed shows its age.
            "age_days": (dt_util.now().date() - stats.price_date).days,
        }


class LevelSensor(TankEntity, SensorEntity):
    """Estimated liters left; unknown until the first needle reading."""

    _attr_device_class = SensorDeviceClass.VOLUME_STORAGE
    _attr_native_unit_of_measurement = UnitOfVolume.LITERS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:barrel"

    def __init__(self, tank: TankManager, entry_id: str) -> None:
        super().__init__(tank, entry_id, "level")

    @property
    def native_value(self) -> float | None:
        return self.tank.snapshot.level_l

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Learned burn-rate factor and the last needle correction."""
        return {
            "burn_rate_scale": round(self.tank.data["scale"], 3),
            "last_calibration": self.tank.data["last_calibration"],
        }


class LevelPercentSensor(TankEntity, SensorEntity):
    """Estimated level as percent of capacity."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:gauge"

    def __init__(self, tank: TankManager, entry_id: str) -> None:
        super().__init__(tank, entry_id, "level_percent")

    @property
    def native_value(self) -> float | None:
        return self.tank.snapshot.level_percent


class DaysRemainingSensor(TankEntity, SensorEntity):
    """Days until empty, forecast on normal temperatures."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, tank: TankManager, entry_id: str) -> None:
        super().__init__(tank, entry_id, "days_remaining")

    @property
    def native_value(self) -> float | None:
        return self.tank.snapshot.days_remaining


class OrderBySensor(TankEntity, SensorEntity):
    """Last day to order, keeping delivery time and a safety buffer."""

    _attr_device_class = SensorDeviceClass.DATE
    _attr_icon = "mdi:truck-delivery"

    def __init__(self, tank: TankManager, entry_id: str) -> None:
        super().__init__(tank, entry_id, "order_by")

    @property
    def native_value(self) -> date | None:
        return self.tank.snapshot.order_by
