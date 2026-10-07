"""Oil Tank integration.

Price feed coordinator, level tracking (tank manager), sensors, the needle
number entity, the order recommendation, the log_fill service, and the
sidebar panel with its websocket API.
"""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import panel_custom
from homeassistant.components.frontend import async_remove_panel
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_CAPACITY_L,
    CONF_TEMPERATURE_ENTITY,
    DOMAIN,
    PANEL_ICON,
    PANEL_STATIC_URL,
    PANEL_TITLE,
    PANEL_URL_PATH,
    PANEL_WEBCOMPONENT,
)
from .coordinator import OilTankCoordinator
from .data import OilTankConfigEntry, OilTankData
from .services import async_register_services, async_remove_services
from .storage import OilTankStore
from .tank import TankManager
from .websocket_api import async_register_commands

PLATFORMS = [Platform.BINARY_SENSOR, Platform.NUMBER, Platform.SENSOR]

PANEL_JS_PATH = Path(__file__).parent / "frontend" / "oil-tank-panel.js"

# hass.data flag: static paths and websocket commands cannot be unregistered,
# so register them only once per Home Assistant run (reloads would raise).
_REGISTERED_ONCE = f"{DOMAIN}_registered_once"


async def async_setup_entry(hass: HomeAssistant, entry: OilTankConfigEntry) -> bool:
    """Set up Oil Tank from a config entry."""
    coordinator = OilTankCoordinator(hass, entry)
    # Plain refresh, not first_refresh: a dead feed must not block setup.
    await coordinator.async_refresh()

    tank = TankManager(
        hass,
        OilTankStore(hass),
        capacity_l=float(entry.data[CONF_CAPACITY_L]),
        temperature_entity=entry.data[CONF_TEMPERATURE_ENTITY],
    )
    await tank.async_start()
    entry.runtime_data = OilTankData(coordinator=coordinator, tank=tank)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_register_services(hass, tank)
    await _async_register_panel(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OilTankConfigEntry) -> bool:
    """Unload a config entry: save state, remove services and the sidebar entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.tank.async_stop()
        async_remove_services(hass)
        async_remove_panel(hass, PANEL_URL_PATH)
    return unloaded


async def _async_register_panel(hass: HomeAssistant) -> None:
    """Serve the panel JS file, register its websocket commands, add the sidebar entry."""
    if not hass.data.get(_REGISTERED_ONCE):
        # cache_headers=False so a browser refresh picks up JS changes in dev.
        await hass.http.async_register_static_paths(
            [StaticPathConfig(PANEL_STATIC_URL, str(PANEL_JS_PATH), cache_headers=False)]
        )
        async_register_commands(hass)
        hass.data[_REGISTERED_ONCE] = True

    await panel_custom.async_register_panel(
        hass,
        webcomponent_name=PANEL_WEBCOMPONENT,
        frontend_url_path=PANEL_URL_PATH,
        module_url=PANEL_STATIC_URL,
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        require_admin=False,
    )
