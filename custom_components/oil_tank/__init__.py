"""Oil Tank integration.

M1: price feed coordinator, price sensor and a placeholder sidebar panel.
Level tracking, recommendation and the real panel come in later milestones.
"""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import panel_custom
from homeassistant.components.frontend import async_remove_panel
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    PANEL_ICON,
    PANEL_STATIC_URL,
    PANEL_TITLE,
    PANEL_URL_PATH,
    PANEL_WEBCOMPONENT,
)
from .coordinator import OilTankConfigEntry, OilTankCoordinator

PLATFORMS = [Platform.SENSOR]

PANEL_JS_PATH = Path(__file__).parent / "frontend" / "oil-tank-panel.js"

# hass.data flag: static paths cannot be unregistered, so register only once
# per Home Assistant run (integration reloads would otherwise raise).
_STATIC_REGISTERED = f"{DOMAIN}_static_registered"


async def async_setup_entry(hass: HomeAssistant, entry: OilTankConfigEntry) -> bool:
    """Set up Oil Tank from a config entry."""
    coordinator = OilTankCoordinator(hass, entry)
    # Plain refresh, not first_refresh: a dead feed must not block setup.
    await coordinator.async_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await _async_register_panel(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OilTankConfigEntry) -> bool:
    """Unload a config entry and remove the sidebar entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        async_remove_panel(hass, PANEL_URL_PATH)
    return unloaded


async def _async_register_panel(hass: HomeAssistant) -> None:
    """Serve the panel JS file and add the sidebar entry."""
    if not hass.data.get(_STATIC_REGISTERED):
        # cache_headers=False so a browser refresh picks up JS changes in dev.
        await hass.http.async_register_static_paths(
            [StaticPathConfig(PANEL_STATIC_URL, str(PANEL_JS_PATH), cache_headers=False)]
        )
        hass.data[_STATIC_REGISTERED] = True

    await panel_custom.async_register_panel(
        hass,
        webcomponent_name=PANEL_WEBCOMPONENT,
        frontend_url_path=PANEL_URL_PATH,
        module_url=PANEL_STATIC_URL,
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        require_admin=False,
    )
