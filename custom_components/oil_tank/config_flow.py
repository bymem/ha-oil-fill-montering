"""Config and options flows for Oil Tank.

Setup asks for tank capacity, outdoor temperature sensor and price feed URL,
and checks that the feed is reachable and parseable before creating the
entry. The options screen holds those plus all tuning values (spec section 8);
saving it reloads the integration. Single instance is enforced by
`single_config_entry` in manifest.json.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_ANNUAL_CONSUMPTION_L,
    CONF_BASE_LOAD_SHARE,
    CONF_BASE_TEMP_C,
    CONF_BUFFER_DAYS,
    CONF_CALIBRATION_ENABLED,
    CONF_CAPACITY_L,
    CONF_FEED_URL,
    CONF_LEAD_DAYS,
    CONF_LOOKBACK_DAYS,
    CONF_MIN_ORDER_L,
    CONF_TEMPERATURE_ENTITY,
    CONF_WINDOW_DAYS,
    DEFAULT_CAPACITY_L,
    DEFAULT_FEED_URL,
    DEFAULTS,
    DOMAIN,
)
from .coordinator import async_fetch_prices
from .feed import FeedError

_LOGGER = logging.getLogger(__name__)


def _number(
    minimum: float, maximum: float, step: float, unit: str | None = None
) -> selector.NumberSelector:
    """Number box with limits (spec section 8 ranges)."""
    config = selector.NumberSelectorConfig(
        min=minimum, max=maximum, step=step, mode=selector.NumberSelectorMode.BOX
    )
    # The selector rejects unit_of_measurement=None, so only set it when given.
    if unit:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)


TEMPERATURE_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="sensor", device_class=SensorDeviceClass.TEMPERATURE)
)
URL_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CAPACITY_L, default=DEFAULT_CAPACITY_L): _number(100, 20000, 1, "L"),
        vol.Required(CONF_TEMPERATURE_ENTITY): TEMPERATURE_SELECTOR,
        vol.Required(CONF_FEED_URL, default=DEFAULT_FEED_URL): URL_SELECTOR,
    }
)

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CAPACITY_L): _number(100, 20000, 1, "L"),
        vol.Required(CONF_TEMPERATURE_ENTITY): TEMPERATURE_SELECTOR,
        vol.Required(CONF_FEED_URL): URL_SELECTOR,
        vol.Required(CONF_ANNUAL_CONSUMPTION_L): _number(100, 20000, 10, "L"),
        vol.Required(CONF_BASE_LOAD_SHARE): _number(0, 0.9, 0.05),
        vol.Required(CONF_BASE_TEMP_C): _number(10, 25, 0.5, "°C"),
        vol.Required(CONF_LEAD_DAYS): _number(1, 30, 1, "days"),
        vol.Required(CONF_BUFFER_DAYS): _number(0, 60, 1, "days"),
        vol.Required(CONF_MIN_ORDER_L): _number(0, 5000, 50, "L"),
        vol.Required(CONF_WINDOW_DAYS): _number(1, 180, 1, "days"),
        vol.Required(CONF_LOOKBACK_DAYS): _number(7, 365, 1, "days"),
        vol.Required(CONF_CALIBRATION_ENABLED): selector.BooleanSelector(),
    }
)


async def _validate_feed(hass: HomeAssistant, url: str) -> str | None:
    """Return an error key, or None when the feed is usable."""
    try:
        await async_fetch_prices(hass, url)
    except (aiohttp.ClientError, TimeoutError):
        return "cannot_connect"
    except FeedError as err:
        _LOGGER.debug("Feed validation failed: %s", err)
        return "invalid_feed"
    return None


class OilTankConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the setup screen."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OilTankOptionsFlow:
        return OilTankOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the form, validate the feed, then create the entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if error := await _validate_feed(self.hass, user_input[CONF_FEED_URL]):
                errors["base"] = error
            else:
                return self.async_create_entry(title="Oil tank", data=user_input)

        return self.async_show_form(
            step_id="user",
            # Refill the form with what was typed when validation failed.
            data_schema=self.add_suggested_values_to_schema(STEP_USER_SCHEMA, user_input),
            errors=errors,
        )


class OilTankOptionsFlow(OptionsFlowWithReload):
    """All settings in one screen; saving reloads the integration."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = {**DEFAULTS, **self.config_entry.data, **self.config_entry.options}

        if user_input is not None:
            # Only re-check the feed when its URL actually changed.
            if user_input[CONF_FEED_URL] != current[CONF_FEED_URL]:
                if error := await _validate_feed(self.hass, user_input[CONF_FEED_URL]):
                    errors["base"] = error
            if not errors:
                return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, user_input or current
            ),
            errors=errors,
        )
