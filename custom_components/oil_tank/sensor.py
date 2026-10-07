"""Sensors for Oil Tank. M1: today's oil price."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OilTankConfigEntry, OilTankCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OilTankConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the sensors for this config entry."""
    async_add_entities([OilTankPriceSensor(entry.runtime_data, entry.entry_id)])


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
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Oil tank",
            entry_type=DeviceEntryType.SERVICE,
        )

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
            "age_days": stats.age_days,
        }
