"""Websocket commands used by the panel (spec 9.4).

Available to any logged-in user: this is a household panel. Payload field
names avoid `id`, which collides with the websocket message id (`fill_id`).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from . import model
from .const import DOMAIN
from .data import OilTankData
from .tank import TankError

MAX_IMPORT_BYTES = 1_000_000


@callback
def async_register_commands(hass: HomeAssistant) -> None:
    """Register all commands. Called once per Home Assistant run."""
    for command in (
        ws_get_state,
        ws_get_prices,
        ws_set_level,
        ws_log_fill,
        ws_delete_fill,
        ws_import_csv,
        ws_export_csv,
        ws_predict,
    ):
        websocket_api.async_register_command(hass, command)


def _runtime(hass: HomeAssistant) -> OilTankData | None:
    """The loaded config entry's runtime data (single instance)."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    return entries[0].runtime_data if entries else None


def _state(runtime: OilTankData) -> dict[str, Any]:
    """Everything the panel shows, except the price history."""
    tank = runtime.tank
    coordinator = runtime.coordinator
    snapshot = tank.snapshot
    decision = runtime.recommendation()

    price = None
    if coordinator.data is not None:
        stats = coordinator.data.stats
        price = {
            "price_per_l": stats.price / 1000,
            "price_date": stats.price_date.isoformat(),
            "average_per_l": stats.average / 1000,
            "low_per_l": stats.low / 1000,
            "high_per_l": stats.high / 1000,
            "percent_vs_average": stats.percent_vs_average,
            "lowest_in_window": stats.lowest_in_window,
            "lookback_days": stats.lookback_days,
            "stock_up_days": coordinator.data.stock_up_stats.lookback_days,
            "stock_up_average_per_l": coordinator.data.stock_up_stats.average / 1000,
            "percent_vs_stock_up_average": coordinator.data.stock_up_stats.percent_vs_average,
            "trend_percent": coordinator.data.trend_percent,
            "stock_up_percent": runtime.settings.stock_up_percent,
        }

    return {
        "capacity_l": tank.capacity_l,
        "gauge": {
            "offset_l": runtime.settings.gauge_offset_l,
            "scale_max": runtime.settings.gauge_scale_max,
        },
        "level_l": snapshot.level_l,
        "level_percent": snapshot.level_percent,
        "days_remaining": snapshot.days_remaining,
        "order_by": snapshot.order_by.isoformat() if snapshot.order_by else None,
        "recommendation": {
            "order": decision.order,
            "urgent": decision.urgent,
            "reason": decision.reason,
        },
        "price": price,
        "price_error": (
            None if coordinator.last_update_success else str(coordinator.last_exception)
        ),
        "prices_version": coordinator.prices_version,
        "daily_l": snapshot.daily_l,
        "yearly_l": tank.consumption.annual_l * tank.data["scale"],
        "consumption": {
            "source": tank.consumption.source,
            "fills_used": tank.consumption.fills_used,
            "since": tank.consumption.since.isoformat() if tank.consumption.since else None,
        },
        "needle_check_since": tank.data["needle_check_since"],
        "fills": tank.fills_newest_first(),
        "scale": tank.data["scale"],
        "last_calibration": tank.data["last_calibration"],
    }


def _not_loaded(connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    connection.send_error(msg["id"], "not_loaded", "Oil tank is not set up")


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/get_state"})
@callback
def ws_get_state(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    if (runtime := _runtime(hass)) is None:
        return _not_loaded(connection, msg)
    connection.send_result(msg["id"], _state(runtime))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/get_prices"})
@callback
def ws_get_prices(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    if (runtime := _runtime(hass)) is None:
        return _not_loaded(connection, msg)
    data = runtime.coordinator.data
    prices = [[day.isoformat(), value] for day, value in data.prices] if data else []
    connection.send_result(msg["id"], {"prices": prices})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_level",
        vol.Required("liters"): vol.Coerce(float),
    }
)
@websocket_api.async_response
async def ws_set_level(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    if (runtime := _runtime(hass)) is None:
        return _not_loaded(connection, msg)
    try:
        await runtime.tank.async_set_level_liters(msg["liters"])
    except TankError as err:
        return connection.send_error(msg["id"], "invalid", str(err))
    connection.send_result(msg["id"], _state(runtime))


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/log_fill",
        vol.Required("date"): str,
        vol.Required("liters"): vol.Coerce(float),
        vol.Required("price"): vol.Coerce(float),
        vol.Optional("level_after_liters"): vol.Any(None, vol.Coerce(float)),
    }
)
@websocket_api.async_response
async def ws_log_fill(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    if (runtime := _runtime(hass)) is None:
        return _not_loaded(connection, msg)
    try:
        fill_date = date.fromisoformat(msg["date"])
    except ValueError:
        return connection.send_error(msg["id"], "invalid", "Invalid date")
    try:
        await runtime.tank.async_log_fill(
            liters=msg["liters"],
            price=msg["price"],
            fill_date=fill_date,
            level_after_liters=msg.get("level_after_liters"),
        )
    except TankError as err:
        return connection.send_error(msg["id"], "invalid", str(err))
    connection.send_result(msg["id"], _state(runtime))


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/delete_fill",
        vol.Required("fill_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_fill(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    if (runtime := _runtime(hass)) is None:
        return _not_loaded(connection, msg)
    try:
        await runtime.tank.async_delete_fill(msg["fill_id"])
    except TankError as err:
        return connection.send_error(msg["id"], "invalid", str(err))
    connection.send_result(msg["id"], _state(runtime))


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/import_csv",
        vol.Required("text"): str,
    }
)
@websocket_api.async_response
async def ws_import_csv(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    if (runtime := _runtime(hass)) is None:
        return _not_loaded(connection, msg)
    if len(msg["text"].encode()) > MAX_IMPORT_BYTES:
        return connection.send_error(msg["id"], "invalid", "File is larger than 1 MB")
    result = await runtime.tank.async_import_csv(msg["text"])
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/predict",
        vol.Required("liters"): vol.All(vol.Coerce(float), vol.Range(min=0)),
    }
)
@callback
def ws_predict(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """If `liters` were ordered today: level after delivery and the next order-by date."""
    if (runtime := _runtime(hass)) is None:
        return _not_loaded(connection, msg)
    tank = runtime.tank
    level = tank.snapshot.level_l
    if level is None:
        return connection.send_error(msg["id"], "invalid", "Set the tank level first")
    settings = runtime.settings
    result = model.predict_order(
        level_l=level,
        ordered_l=msg["liters"],
        today=dt_util.now().date(),
        capacity_l=tank.capacity_l,
        rates=tank.rates,
        scale=tank.data["scale"],
        lead_days=settings.lead_days,
        buffer_days=settings.buffer_days,
        window_days=settings.window_days,
    )
    prices = runtime.coordinator.data
    connection.send_result(
        msg["id"],
        {
            "delivery_date": result.delivery_date.isoformat(),
            "level_before_l": result.level_before_l,
            "room_l": result.room_l,
            "ordered_l": result.ordered_l,
            "level_after_l": result.level_after_l,
            "days_left": result.days_left,
            "order_by": result.order_by.isoformat(),
            "window_start": result.window_start.isoformat(),
            "price_per_l": prices.stats.price / 1000 if prices else None,
        },
    )


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/export_csv"})
@callback
def ws_export_csv(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    if (runtime := _runtime(hass)) is None:
        return _not_loaded(connection, msg)
    connection.send_result(msg["id"], {"text": runtime.tank.export_csv()})
