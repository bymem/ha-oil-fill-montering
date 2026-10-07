"""Price statistics over a comparison window (spec FR-1).

Pure logic: imports nothing from Home Assistant so it can be unit tested alone.
All prices are DKK per 1000 litres, as delivered by the feed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

# "Lowest of the window" allows today to be this much above the earlier low.
LOWEST_TOLERANCE = 0.0025


@dataclass(frozen=True)
class PriceStats:
    """Newest price compared with the window that ends on its date."""

    price_date: date
    price: float
    average: float
    low: float
    high: float
    percent_vs_average: float
    lowest_in_window: bool
    age_days: int
    lookback_days: int


def price_stats(
    prices: list[tuple[date, float]], today: date, lookback_days: int = 30
) -> PriceStats | None:
    """Compute stats for the newest price, or None when there are no prices.

    The window is the `lookback_days` calendar days ending on the newest
    price date, newest day included. `prices` must be sorted oldest first.
    """
    if not prices:
        return None

    newest_date, newest_price = prices[-1]
    window_start = newest_date - timedelta(days=lookback_days - 1)
    window = [value for day, value in prices if day >= window_start]
    earlier = window[:-1]

    average = sum(window) / len(window)

    # With no earlier days there is nothing to be cheapest against.
    lowest_in_window = bool(earlier) and newest_price <= min(earlier) * (
        1 + LOWEST_TOLERANCE
    )

    return PriceStats(
        price_date=newest_date,
        price=newest_price,
        average=average,
        low=min(window),
        high=max(window),
        percent_vs_average=(newest_price - average) / average * 100,
        lowest_in_window=lowest_in_window,
        age_days=(today - newest_date).days,
        lookback_days=lookback_days,
    )
