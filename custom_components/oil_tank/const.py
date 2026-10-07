"""Constants for the Oil Tank integration."""

from datetime import timedelta

DOMAIN = "oil_tank"

# Config entry keys (see spec section 8). The first three are asked at
# setup; all of them can be changed in the options screen.
CONF_CAPACITY_L = "capacity_l"
CONF_TEMPERATURE_ENTITY = "temperature_entity"
CONF_FEED_URL = "feed_url"
CONF_ANNUAL_CONSUMPTION_L = "annual_consumption_l"
CONF_BASE_LOAD_SHARE = "base_load_share"
CONF_BASE_TEMP_C = "base_temp_c"
CONF_LEAD_DAYS = "lead_days"
CONF_BUFFER_DAYS = "buffer_days"
CONF_MIN_ORDER_L = "min_order_l"
CONF_WINDOW_DAYS = "window_days"
CONF_LOOKBACK_DAYS = "lookback_days"
CONF_CALIBRATION_ENABLED = "calibration_enabled"
CONF_GAUGE_OFFSET_L = "gauge_offset_l"
CONF_GAUGE_SCALE_MAX = "gauge_scale_max"

DEFAULT_CAPACITY_L = 1200
DEFAULT_FEED_URL = "https://www.fyringsolie.dk/api/yx-xml/pg000015BULK.xml"

# Defaults for every setting except the temperature sensor (always chosen).
DEFAULTS = {
    CONF_CAPACITY_L: DEFAULT_CAPACITY_L,
    CONF_FEED_URL: DEFAULT_FEED_URL,
    CONF_ANNUAL_CONSUMPTION_L: 1790,
    CONF_BASE_LOAD_SHARE: 0.2,
    CONF_BASE_TEMP_C: 17.0,
    CONF_LEAD_DAYS: 5,
    CONF_BUFFER_DAYS: 14,
    CONF_MIN_ORDER_L: 500,
    CONF_WINDOW_DAYS: 45,
    CONF_LOOKBACK_DAYS: 30,
    CONF_CALIBRATION_ENABLED: True,
    # Panel dial: what the physical gauge shows when the tank is empty, and
    # the value printed at the end of its scale (None = tank capacity).
    CONF_GAUGE_OFFSET_L: 0,
    CONF_GAUGE_SCALE_MAX: None,
}

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
