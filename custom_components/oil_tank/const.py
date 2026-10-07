"""Constants for the Oil Tank integration."""

DOMAIN = "oil_tank"

# Config entry keys (see spec section 8).
CONF_CAPACITY_L = "capacity_l"
CONF_TEMPERATURE_ENTITY = "temperature_entity"

DEFAULT_CAPACITY_L = 1200

# Sidebar panel (see spec section 9.5).
PANEL_URL_PATH = "oil-tank"
PANEL_WEBCOMPONENT = "oil-tank-panel"
PANEL_STATIC_URL = f"/{DOMAIN}/oil-tank-panel.js"
PANEL_TITLE = "Oil tank"
PANEL_ICON = "mdi:barrel"
