"""Services: `oil_tank.log_fill` (spec 9.3).

Registered when the config entry loads and removed when it unloads.
"""

from __future__ import annotations

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .tank import TankError, TankManager

SERVICE_LOG_FILL = "log_fill"

LOG_FILL_SCHEMA = vol.Schema(
    {
        vol.Required("liters"): vol.Coerce(float),
        vol.Required("price"): vol.Coerce(float),
        vol.Optional("date"): cv.date,
        # Upper bound (tank capacity) is checked by the tank manager.
        vol.Optional("level_after_liters"): vol.All(vol.Coerce(float), vol.Range(min=0)),
    }
)


def async_register_services(hass: HomeAssistant, tank: TankManager) -> None:
    """Register the services for the loaded entry."""

    async def log_fill(call: ServiceCall) -> None:
        try:
            await tank.async_log_fill(
                liters=call.data["liters"],
                price=call.data["price"],
                fill_date=call.data.get("date"),
                level_after_liters=call.data.get("level_after_liters"),
            )
        except TankError as err:
            raise ServiceValidationError(str(err)) from err

    hass.services.async_register(DOMAIN, SERVICE_LOG_FILL, log_fill, schema=LOG_FILL_SCHEMA)


def async_remove_services(hass: HomeAssistant) -> None:
    """Remove the services on unload."""
    hass.services.async_remove(DOMAIN, SERVICE_LOG_FILL)
