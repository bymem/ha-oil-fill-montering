"""Tank state: degree-day counter, level estimate, readings and fills.

Glue between Home Assistant (temperature sensor, timers, storage) and the
pure model in model.py. Entities subscribe with `async_add_listener` and read
`snapshot`, which is recomputed after every change.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, UnitOfTemperature
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

from . import csv_io, model
from .const import DEFAULT_BUFFER_DAYS, DEFAULT_LEAD_DAYS
from .storage import OilTankStore

TICK_INTERVAL = timedelta(minutes=10)

SECONDS_PER_DAY = 86400


class TankError(ValueError):
    """A user action was rejected; the message is shown to the user."""


@dataclass(frozen=True)
class TankSnapshot:
    """Derived values for the entities. Level fields are None before the first reading."""

    level_l: float | None
    level_percent: float | None
    days_remaining: float | None
    order_by: date | None


class TankManager:
    """Owns the stored document and keeps the estimate up to date."""

    def __init__(
        self,
        hass: HomeAssistant,
        store: OilTankStore,
        capacity_l: float,
        temperature_entity: str,
    ) -> None:
        self.hass = hass
        self.store = store
        self.capacity_l = capacity_l
        self.temperature_entity = temperature_entity
        self.rates = model.make_rates()
        self.snapshot = TankSnapshot(None, None, None, None)
        self._listeners: list[Callable[[], None]] = []
        self._unsubscribers: list[Callable[[], None]] = []

    @property
    def data(self) -> dict[str, Any]:
        return self.store.data

    async def async_start(self) -> None:
        """Load state, catch up on time spent offline, then start listening."""
        await self.store.async_load()
        # Catches up on any downtime; long gaps fall back to normal degree-days.
        self._advance(dt_util.utcnow())
        self._read_temperature(self.hass.states.get(self.temperature_entity))
        self._recompute()
        self.store.schedule_save()

        self._unsubscribers = [
            async_track_state_change_event(
                self.hass, [self.temperature_entity], self._on_temperature_change
            ),
            async_track_time_interval(self.hass, self._on_tick, TICK_INTERVAL),
        ]

    async def async_stop(self) -> None:
        """Stop listening and save."""
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers = []
        await self.store.async_save_now()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Call `listener` after every change; returns the unsubscribe function."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    # --- Background updates -------------------------------------------------

    @callback
    def _on_temperature_change(self, event: Event[EventStateChangedData]) -> None:
        self._advance(dt_util.utcnow())
        self._read_temperature(event.data["new_state"])
        self._changed()

    @callback
    def _on_tick(self, now: datetime) -> None:
        # Re-read the sensor too: a steady temperature fires no change events,
        # but it is still a fresh reading.
        self._advance(now)
        self._read_temperature(self.hass.states.get(self.temperature_entity))
        self._changed()

    def _advance(self, now: datetime) -> None:
        """Add degree-days since the last step, using the previous temperature."""
        data = self.data
        if data["last_ts"] is not None:
            last_ts = datetime.fromisoformat(data["last_ts"])
            elapsed_days = (now - last_ts).total_seconds() / SECONDS_PER_DAY
            temp_age_days = (
                (last_ts - datetime.fromisoformat(data["last_temp_ts"])).total_seconds()
                / SECONDS_PER_DAY
                if data["last_temp_ts"]
                else 0.0
            )
            data["dd"] += model.accumulate_dd(
                elapsed_days=elapsed_days,
                prev_temp=data["last_temp"],
                prev_temp_age_days=temp_age_days,
                month=dt_util.as_local(now).month,
                base_temp=self.rates.base_temp,
            )
        data["last_ts"] = now.isoformat()

    def _read_temperature(self, state: State | None) -> None:
        """Store the sensor value in Celsius; unavailable states keep the old one."""
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        try:
            value = float(state.state)
        except ValueError:
            return
        if state.attributes.get("unit_of_measurement") == UnitOfTemperature.FAHRENHEIT:
            value = TemperatureConverter.convert(
                value, UnitOfTemperature.FAHRENHEIT, UnitOfTemperature.CELSIUS
            )
        self.data["last_temp"] = value
        self.data["last_temp_ts"] = dt_util.utcnow().isoformat()

    @callback
    def _changed(self) -> None:
        self._recompute()
        self.store.schedule_save()

    # --- Estimate -----------------------------------------------------------

    def estimate_l(self) -> float | None:
        """Current level: baseline minus modelled burn since then."""
        baseline = self.data["baseline"]
        if baseline is None:
            return None
        return model.clamp(
            baseline["liters"] - self._burn_since_baseline(), 0.0, self.capacity_l
        )

    def _burn_since_baseline(self) -> float:
        baseline = self.data["baseline"]
        days = (
            dt_util.utcnow() - datetime.fromisoformat(baseline["ts"])
        ).total_seconds() / SECONDS_PER_DAY
        return model.burn_since(
            self.rates, self.data["scale"], days, self.data["dd"] - baseline["dd"]
        )

    def _recompute(self) -> None:
        """Rebuild the snapshot and notify entities."""
        level = self.estimate_l()
        if level is None:
            self.snapshot = TankSnapshot(None, None, None, None)
        else:
            today = dt_util.now().date()
            remaining = model.days_left(level, today, self.rates, self.data["scale"])
            self.snapshot = TankSnapshot(
                level_l=level,
                level_percent=level / self.capacity_l * 100,
                days_remaining=remaining,
                order_by=model.order_by_date(
                    remaining, today, DEFAULT_LEAD_DAYS, DEFAULT_BUFFER_DAYS
                ),
            )
        for listener in list(self._listeners):
            listener()

    # --- User actions -------------------------------------------------------

    async def async_set_level_liters(self, liters: float) -> None:
        """Record a needle reading."""
        if not 0 <= liters <= self.capacity_l:
            raise TankError(f"Level must be between 0 and {self.capacity_l:g} L")
        self._record_reading(liters, delivered_l=0.0)
        await self._saved()

    async def async_log_fill(
        self,
        liters: float,
        price: float,
        fill_date: date | None = None,
        level_after_liters: float | None = None,
    ) -> None:
        """Record a delivery and update the estimate (spec FR-4)."""
        today = dt_util.now().date()
        fill_date = fill_date or today
        if liters <= 0:
            raise TankError("Liters must be above 0")
        if price < 0:
            raise TankError("Price cannot be negative")
        if fill_date > today:
            raise TankError("Date cannot be in the future")
        if level_after_liters is not None and not 0 <= level_after_liters <= self.capacity_l:
            raise TankError(
                f"Level after delivery must be between 0 and {self.capacity_l:g} L"
            )
        key = (fill_date.isoformat(), round(liters, 1))
        if any((fill["date"], round(fill["liters"], 1)) == key for fill in self.data["fills"]):
            raise TankError(f"A delivery of {liters:g} L on {fill_date} already exists")

        self.data["fills"].append(
            {
                "id": secrets.token_hex(4),
                "date": fill_date.isoformat(),
                "liters": float(liters),
                "price": float(price),
            }
        )

        baseline = self.data["baseline"]
        # A delivery dated before the last reading is already part of that reading.
        after_reading = baseline is None or fill_date >= dt_util.as_local(
            datetime.fromisoformat(baseline["ts"])
        ).date()

        if after_reading and level_after_liters is not None:
            # The level after delivery is a calibration point.
            self._record_reading(level_after_liters, delivered_l=liters)
        elif after_reading and baseline is not None:
            # No reading given: re-base on the estimate plus the delivery.
            self._set_baseline(min(self.capacity_l, (self.estimate_l() or 0) + liters))
        # Otherwise (no reading yet, or older than the reading): history only.

        await self._saved()

    def _record_reading(self, reading_l: float, delivered_l: float) -> None:
        """Store a reading as the new baseline, learning from the old one first."""
        baseline = self.data["baseline"]
        if baseline is not None:
            interval_days = (
                dt_util.utcnow() - datetime.fromisoformat(baseline["ts"])
            ).total_seconds() / SECONDS_PER_DAY
            predicted = self._burn_since_baseline()
            actual = baseline["liters"] + delivered_l - reading_l
            self.data["scale"] = model.calibrate(
                self.data["scale"], predicted, actual, interval_days
            )
            self.data["last_calibration"] = {
                "ts": dt_util.utcnow().isoformat(),
                "estimated_l": round(self.estimate_l() + delivered_l, 1),
                "reading_l": round(reading_l, 1),
            }
        self._set_baseline(reading_l)

    def _set_baseline(self, liters: float) -> None:
        self.data["baseline"] = {
            "ts": dt_util.utcnow().isoformat(),
            "liters": model.clamp(liters, 0.0, self.capacity_l),
            "dd": self.data["dd"],
        }

    async def async_delete_fill(self, fill_id: str) -> None:
        """Remove a delivery from the history. The level estimate is not changed."""
        fills = self.data["fills"]
        remaining = [fill for fill in fills if fill["id"] != fill_id]
        if len(remaining) == len(fills):
            raise TankError("That delivery no longer exists")
        self.data["fills"] = remaining
        await self._saved()

    async def async_import_csv(self, text: str) -> dict[str, Any]:
        """Merge a fill history file into the history (spec FR-5).

        History only: imported rows never change the level estimate.
        """
        result = csv_io.parse_csv(text)
        existing = {
            self._fill_from_dict(fill).key: fill["id"] for fill in self.data["fills"]
        }
        merged, added, skipped = csv_io.merge(
            [self._fill_from_dict(fill) for fill in self.data["fills"]], result.fills
        )
        self.data["fills"] = [
            {
                "id": existing.get(fill.key) or secrets.token_hex(4),
                "date": fill.date.isoformat(),
                "liters": float(fill.liters),
                "price": float(fill.price),
            }
            for fill in merged
        ]
        if added:
            await self._saved()
        return {"added": added, "skipped": skipped, "errors": result.errors}

    def export_csv(self) -> str:
        """The history in the canonical three-column format."""
        return csv_io.export_csv([self._fill_from_dict(fill) for fill in self.data["fills"]])

    def fills_newest_first(self) -> list[dict[str, Any]]:
        return sorted(self.data["fills"], key=lambda fill: fill["date"], reverse=True)

    @staticmethod
    def _fill_from_dict(fill: dict[str, Any]) -> csv_io.Fill:
        return csv_io.Fill(date.fromisoformat(fill["date"]), fill["liters"], fill["price"])

    async def _saved(self) -> None:
        """After a user action: recompute, notify, save immediately."""
        self._recompute()
        await self.store.async_save_now()
