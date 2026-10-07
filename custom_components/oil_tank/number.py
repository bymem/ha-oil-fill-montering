"""The gauge "needle": shows the estimate, and setting it records a reading."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .data import OilTankConfigEntry
from .entity import TankEntity
from .tank import TankError, TankManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OilTankConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the needle entity."""
    async_add_entities([NeedleNumber(entry.runtime_data.tank, entry.entry_id)])


class NeedleNumber(TankEntity, NumberEntity):
    """0-100% slider. State = current estimate; a write = a needle reading."""

    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:gauge"

    def __init__(self, tank: TankManager, entry_id: str) -> None:
        super().__init__(tank, entry_id, "tank_level_needle")

    @property
    def native_value(self) -> float | None:
        percent = self.tank.snapshot.level_percent
        return None if percent is None else round(percent)

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self.tank.async_set_level_percent(value)
        except TankError as err:
            raise ServiceValidationError(str(err)) from err
