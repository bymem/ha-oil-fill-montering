"""Config flow for Oil Tank.

Asks for the two confirmed settings: tank capacity and outdoor temperature
sensor. Single instance is enforced by `single_config_entry` in manifest.json.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_CAPACITY_L,
    CONF_TEMPERATURE_ENTITY,
    DEFAULT_CAPACITY_L,
    DOMAIN,
)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CAPACITY_L, default=DEFAULT_CAPACITY_L): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=100,
                max=20000,
                step=1,
                unit_of_measurement="L",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Required(CONF_TEMPERATURE_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain="sensor",
                device_class=SensorDeviceClass.TEMPERATURE,
            )
        ),
    }
)


class OilTankConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the setup screen."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form, then create the entry."""
        if user_input is not None:
            return self.async_create_entry(title="Oil tank", data=user_input)

        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA)
