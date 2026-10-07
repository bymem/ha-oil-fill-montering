"""Config flow for Oil Tank.

Asks for tank capacity, outdoor temperature sensor and price feed URL, and
checks that the feed is reachable and parseable before creating the entry.
Single instance is enforced by `single_config_entry` in manifest.json.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_CAPACITY_L,
    CONF_FEED_URL,
    CONF_TEMPERATURE_ENTITY,
    DEFAULT_CAPACITY_L,
    DEFAULT_FEED_URL,
    DOMAIN,
)
from .coordinator import async_fetch_prices
from .feed import FeedError

_LOGGER = logging.getLogger(__name__)


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
        vol.Required(CONF_FEED_URL, default=DEFAULT_FEED_URL): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
        ),
    }
)


class OilTankConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the setup screen."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form, validate the feed, then create the entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await async_fetch_prices(self.hass, user_input[CONF_FEED_URL])
            except (aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            except FeedError as err:
                _LOGGER.debug("Feed validation failed: %s", err)
                errors["base"] = "invalid_feed"
            else:
                return self.async_create_entry(title="Oil tank", data=user_input)

        return self.async_show_form(
            step_id="user",
            # Refill the form with what was typed when validation failed.
            data_schema=self.add_suggested_values_to_schema(STEP_USER_SCHEMA, user_input),
            errors=errors,
        )
