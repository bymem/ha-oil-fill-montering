"""Consumption model: burn rates, degree-days, level estimate, forecast and
self-calibration (spec section 5).

Pure logic: imports nothing from Home Assistant so it can be unit tested alone.

Daily burn = scale * (base_l_per_day + l_per_dd * degree_days_that_day), where
degree_days = max(0, base_temp - outdoor_temp). The two rates are derived from
one number the owner can sanity-check: the typical yearly consumption.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

# Normal Danish monthly mean temperatures (deg C), January first.
NORMAL_TEMPS_C = (1.8, 1.7, 3.9, 8.0, 12.3, 15.7, 18.0, 17.7, 14.0, 9.6, 5.6, 2.7)
# February averaged over leap years so the year sums to 365.25 days.
DAYS_IN_MONTH = (31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)

DEFAULT_ANNUAL_L = 1790
DEFAULT_BASE_SHARE = 0.2
DEFAULT_BASE_TEMP_C = 17.0

MAX_FORECAST_DAYS = 730

# Degree-day accumulation (spec 5.1).
TEMP_TRUST_DAYS = 6 / 24  # a temperature older than 6 hours is not trusted
GAP_FALLBACK_DAYS = 2  # longer gaps (Home Assistant down) use normal temperatures

# Yearly consumption from logged deliveries (spec 5.0).
HISTORY_YEARS = 5
MIN_HISTORY_DAYS = 365
MIN_HISTORY_FILLS = 3

# Self-calibration (spec 5.4).
CALIBRATION_MIN_DAYS = 14
CALIBRATION_MIN_PREDICTED_L = 20
CALIBRATION_DAMPING = 0.3
RATIO_LIMITS = (0.5, 2.0)
SCALE_LIMITS = (0.5, 2.0)


@dataclass(frozen=True)
class Rates:
    """Burn rates at scale 1.0."""

    base_l_per_day: float
    l_per_dd: float
    base_temp: float


def degree_days(temp: float, base_temp: float) -> float:
    """Heating degree-days for one day at `temp`."""
    return max(0.0, base_temp - temp)


def normal_dd_per_day(month: int, base_temp: float) -> float:
    """Degree-days of an average day in `month` (1-12)."""
    return degree_days(NORMAL_TEMPS_C[month - 1], base_temp)


def annual_normal_dd(base_temp: float) -> float:
    """Degree-days of a normal year."""
    return sum(
        normal_dd_per_day(month, base_temp) * DAYS_IN_MONTH[month - 1]
        for month in range(1, 13)
    )


def make_rates(
    annual_l: float = DEFAULT_ANNUAL_L,
    base_share: float = DEFAULT_BASE_SHARE,
    base_temp: float = DEFAULT_BASE_TEMP_C,
) -> Rates:
    """Split yearly consumption into a fixed daily base and a per-degree-day part."""
    return Rates(
        base_l_per_day=annual_l * base_share / 365,
        l_per_dd=annual_l * (1 - base_share) / annual_normal_dd(base_temp),
        base_temp=base_temp,
    )


@dataclass(frozen=True)
class HistoryConsumption:
    """Yearly consumption measured from deliveries."""

    annual_l: float
    fills_used: int
    since: date


def annual_from_fills(fills: list[tuple[date, float]]) -> HistoryConsumption | None:
    """Liters per year from `(date, liters)` deliveries, or None with too little history.

    Over a long enough span, what was bought is what was burned. All
    deliveries except the latest one were burned between the first and the
    latest delivery date (the latest is still in the tank). Only the last
    HISTORY_YEARS before the latest delivery count, so old habits fade out.
    """
    if not fills:
        return None
    ordered = sorted(fills)
    latest = ordered[-1][0]
    cutoff = latest - timedelta(days=round(HISTORY_YEARS * 365.25))
    recent = [(day, liters) for day, liters in ordered if day >= cutoff]
    span_days = (latest - recent[0][0]).days
    if len(recent) < MIN_HISTORY_FILLS or span_days < MIN_HISTORY_DAYS:
        return None
    burned = sum(liters for _, liters in recent[:-1])
    return HistoryConsumption(
        annual_l=burned / (span_days / 365.25),
        fills_used=len(recent),
        since=recent[0][0],
    )


def normal_dd_between(start: date, end: date, base_temp: float) -> float:
    """Degree-days from `start` up to (not including) `end` on normal temperatures."""
    total = 0.0
    day = start
    while day < end:
        total += normal_dd_per_day(day.month, base_temp)
        day += timedelta(days=1)
    return total


def daily_burn(rates: Rates, scale: float, temp: float | None, month: int) -> float:
    """Liters per day at `temp`, or at the month's normal temperature when unknown."""
    dd = normal_dd_per_day(month, rates.base_temp) if temp is None else degree_days(temp, rates.base_temp)
    return scale * (rates.base_l_per_day + rates.l_per_dd * dd)


def accumulate_dd(
    *,
    elapsed_days: float,
    prev_temp: float | None,
    prev_temp_age_days: float,
    month: int,
    base_temp: float,
) -> float:
    """Degree-days to add for an interval of `elapsed_days`.

    Uses the previous temperature for the whole interval (step integral).
    Falls back to the month's normal degree-days when there is no trusted
    temperature (none, or older than 6 hours at the start of the interval)
    or when the interval itself is longer than 2 days.
    """
    if elapsed_days <= 0:
        return 0.0
    if (
        prev_temp is None
        or prev_temp_age_days > TEMP_TRUST_DAYS
        or elapsed_days > GAP_FALLBACK_DAYS
    ):
        return normal_dd_per_day(month, base_temp) * elapsed_days
    return degree_days(prev_temp, base_temp) * elapsed_days


def burn_since(rates: Rates, scale: float, days: float, dd_delta: float) -> float:
    """Liters burned over `days` with `dd_delta` degree-days."""
    return scale * (rates.base_l_per_day * days + rates.l_per_dd * dd_delta)


def clamp(value: float, low: float, high: float) -> float:
    """Limit `value` to [low, high]."""
    return max(low, min(high, value))


def days_left(level: float, today: date, rates: Rates, scale: float) -> float:
    """Fractional days until empty, walking forward on normal temperatures.

    Normal (not recent) temperatures on purpose: in autumn recent weather
    understates what winter will burn. Capped at MAX_FORECAST_DAYS.
    """
    remaining = level
    for day_index in range(MAX_FORECAST_DAYS):
        if remaining <= 0:
            return float(day_index)
        day = today + timedelta(days=day_index)
        burn = scale * (
            rates.base_l_per_day
            + rates.l_per_dd * normal_dd_per_day(day.month, rates.base_temp)
        )
        if remaining <= burn:
            return day_index + remaining / burn
        remaining -= burn
    return float(MAX_FORECAST_DAYS)


def order_by_date(
    days_remaining: float, today: date, lead_days: int, buffer_days: int
) -> date:
    """Last day to order so delivery arrives with the buffer still in the tank."""
    slack = days_remaining - lead_days - buffer_days
    return today + timedelta(days=math.floor(max(0.0, slack)))


@dataclass(frozen=True)
class Prediction:
    """What ordering `ordered_l` today would mean (spec FR-9)."""

    delivery_date: date
    level_before_l: float
    room_l: float
    ordered_l: float
    level_after_l: float
    days_left: float
    order_by: date
    window_start: date


def predict_order(
    *,
    level_l: float,
    ordered_l: float,
    today: date,
    capacity_l: float,
    rates: Rates,
    scale: float,
    lead_days: int,
    buffer_days: int,
    window_days: int,
) -> Prediction:
    """Order `ordered_l` today: level at delivery, then when to order again.

    The delivery arrives after `lead_days`; burn until then and afterwards
    is modelled on normal temperatures, like the days-left forecast. More
    than fits is capped at capacity (`room_l` says how much would fit).
    """
    delivery = today + timedelta(days=lead_days)
    burned = burn_since(rates, scale, lead_days, normal_dd_between(today, delivery, rates.base_temp))
    before = max(0.0, level_l - burned)
    after = min(capacity_l, before + ordered_l)
    left = days_left(after, delivery, rates, scale)
    next_order_by = order_by_date(left, delivery, lead_days, buffer_days)
    return Prediction(
        delivery_date=delivery,
        level_before_l=before,
        room_l=capacity_l - before,
        ordered_l=ordered_l,
        level_after_l=after,
        days_left=left,
        order_by=next_order_by,
        window_start=max(today, next_order_by - timedelta(days=window_days)),
    )


def calibrate(
    scale: float, predicted: float, actual: float, interval_days: float
) -> float:
    """Nudge the burn-rate scale towards what a reading showed.

    Damped and capped on purpose: readings are eyeballed off a gauge. Short
    intervals and tiny predictions carry too little signal and are ignored.
    """
    if interval_days < CALIBRATION_MIN_DAYS or predicted < CALIBRATION_MIN_PREDICTED_L:
        return scale
    ratio = clamp(max(actual, 0.0) / predicted, *RATIO_LIMITS)
    return clamp(scale * (1 + CALIBRATION_DAMPING * (ratio - 1)), *SCALE_LIMITS)
