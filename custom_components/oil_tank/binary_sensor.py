"""Order recommendation binary sensor (spec FR-6).

On when it is a good moment (or urgent) to order. Notifications are left to
a normal Home Assistant automation triggered by this entity (see README).
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .data import OilTankConfigEntry, OilTankData
from .decision import Decision
from .entity import TankEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OilTankConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the recommendation entity."""
    async_add_entities([OrderRecommendedSensor(entry.runtime_data, entry.entry_id)])


class OrderRecommendedSensor(TankEntity, BinarySensorEntity):
    """Follows both the tank estimate and the price feed."""

    _attr_icon = "mdi:truck-delivery"

    def __init__(self, runtime: OilTankData, entry_id: str) -> None:
        super().__init__(runtime.tank, entry_id, "order_recommended")
        self.runtime = runtime
        self.coordinator = runtime.coordinator
        self._decision: Decision | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Also re-evaluate when new prices arrive.
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))

    @callback
    def async_write_ha_state(self) -> None:
        """Decide once per state write; is_on and attributes read the result."""
        self._decision = self.runtime.recommendation()
        super().async_write_ha_state()

    @property
    def is_on(self) -> bool | None:
        return self._decision.order if self._decision else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Attributes from spec 9.2, usable in notification templates."""
        if self._decision is None:
            return None
        snapshot = self.tank.snapshot
        stats = self.coordinator.data.stats if self.coordinator.data else None
        return {
            "reason": self._decision.reason,
            "urgent": self._decision.urgent,
            "order_by": self._decision.order_by.isoformat() if self._decision.order_by else None,
            "days_remaining": _rounded(snapshot.days_remaining, 1),
            "level_liters": _rounded(snapshot.level_l, 0),
            "level_percent": _rounded(snapshot.level_percent, 0),
            "price_per_l": round(stats.price / 1000, 2) if stats else None,
            "percent_vs_average": round(stats.percent_vs_average, 2) if stats else None,
        }


def _rounded(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)
