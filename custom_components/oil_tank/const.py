"""Constants for the Oil Tank integration."""

from datetime import timedelta

DOMAIN = "oil_tank"

# Config entry keys (see spec section 8).
CONF_CAPACITY_L = "capacity_l"
CONF_TEMPERATURE_ENTITY = "temperature_entity"
CONF_FEED_URL = "feed_url"

DEFAULT_CAPACITY_L = 1200
DEFAULT_FEED_URL = "https://www.fyringsolie.dk/api/yx-xml/pg000015BULK.xml"
DEFAULT_LOOKBACK_DAYS = 30

# Recommendation settings (spec sections 7 and 8); configurable from M5.
DEFAULT_LEAD_DAYS = 5
DEFAULT_BUFFER_DAYS = 14
DEFAULT_MIN_ORDER_L = 500
DEFAULT_WINDOW_DAYS = 45

# Price feed polling (spec 3.1): prices change once a day.
FEED_POLL_INTERVAL = timedelta(hours=3)
FEED_RETRY_INTERVAL = timedelta(minutes=30)
FEED_TIMEOUT_SECONDS = 30

# Sidebar panel (see spec section 9.5).
PANEL_URL_PATH = "oil-tank"
PANEL_WEBCOMPONENT = "oil-tank-panel"
PANEL_STATIC_URL = f"/{DOMAIN}/oil-tank-panel.js"
PANEL_TITLE = "Oil tank"
PANEL_ICON = "mdi:barrel"
