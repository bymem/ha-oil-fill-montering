"""Shared base for entities that follow the tank estimate."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .tank import TankManager


def device_info(entry_id: str) -> DeviceInfo:
    """The single "Oil tank" device all entities belong to."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        name="Oil tank",
        entry_type=DeviceEntryType.SERVICE,
    )


class TankEntity(Entity):
    """Pushes a state update whenever the tank manager recomputes."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, tank: TankManager, entry_id: str, key: str) -> None:
        self.tank = tank
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_device_info = device_info(entry_id)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.tank.async_add_listener(self.async_write_ha_state))
