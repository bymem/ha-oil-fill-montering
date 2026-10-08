"""Order recommendation (spec section 7).

Pure logic: imports nothing from Home Assistant so it can be unit tested alone.

The checks run in a fixed order and the first match wins. The urgent case
ignores price entirely; it is the safety net.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .model import order_by_date
from .prices import PriceStats

STALE_PRICE_DAYS = 3
# Stock-up tier defaults (spec section 7): unusually cheap vs a long window.
DEFAULT_STOCK_UP_PERCENT = 7.0
GOOD_PERCENT_BELOW_AVERAGE = -3.0
CLOSE_TO_ORDER_BY_DAYS = 7


@dataclass(frozen=True)
class Decision:
    """Whether to order now, and a human-readable reason."""

    order: bool
    urgent: bool
    reason: str
    order_by: date | None


def decide(
    *,
    level_l: float | None,
    days_remaining: float | None,
    capacity_l: float,
    today: date,
    stats: PriceStats | None,
    lead_days: int,
    buffer_days: int,
    min_order_l: float,
    window_days: int,
    stock_up_stats: PriceStats | None = None,
    stock_up_percent: float = DEFAULT_STOCK_UP_PERCENT,
) -> Decision:
    """Combine level, forecast and price into one recommendation.

    Two tiers: "stock up" when the price is unusually cheap against a long
    window (`stock_up_stats`) and the tank has room, at any time; otherwise
    the normal price rules, only inside the order window.
    """
    if level_l is None or days_remaining is None:
        return Decision(False, False, "Set the tank level (needle) to start tracking.", None)

    slack = days_remaining - lead_days - buffer_days
    order_by = order_by_date(days_remaining, today, lead_days, buffer_days)
    by = f"Order by {_format_date(order_by)}."
    room = capacity_l - level_l

    if slack <= 0:
        return Decision(
            True,
            True,
            f"Order now: about {days_remaining:.0f} days of oil left "
            f"and delivery takes ~{lead_days} days.",
            order_by,
        )

    if room < min_order_l:
        return Decision(
            False,
            False,
            f"Tank has room for only {room:.0f} L (minimum order {min_order_l:.0f} L). {by}",
            order_by,
        )

    # Tier A: unusually cheap and the tank can take it, whatever the order-by date.
    if (
        stock_up_stats is not None
        and (today - stock_up_stats.price_date).days <= STALE_PRICE_DAYS
        and stock_up_stats.percent_vs_average <= -stock_up_percent
    ):
        return Decision(
            True,
            False,
            f"Unusually cheap: {stock_up_stats.price / 1000:.2f} kr/L is "
            f"{-stock_up_stats.percent_vs_average:.1f}% below the "
            f"{stock_up_stats.lookback_days}-day average, and the tank has room for "
            f"{room:.0f} L. {by}",
            order_by,
        )

    # Tier B: the normal price rules, only close to the order-by date.
    if slack > window_days:
        return Decision(
            False,
            False,
            f"No need yet: order by {_format_date(order_by)} "
            f"(about {days_remaining:.0f} days of oil left).",
            order_by,
        )

    # Age from today, not from the last fetch: a dead feed must go stale.
    if stats is None or (today - stats.price_date).days > STALE_PRICE_DAYS:
        return Decision(False, False, f"No fresh price data. {by}", order_by)

    price_per_l = stats.price / 1000
    window = stats.lookback_days
    good = None
    if stats.lowest_in_window:
        good = f"the cheapest in {window} days"
    elif stats.percent_vs_average <= GOOD_PERCENT_BELOW_AVERAGE:
        good = f"{-stats.percent_vs_average:.1f}% below the {window}-day average"
    elif slack <= CLOSE_TO_ORDER_BY_DAYS and stats.percent_vs_average <= 0:
        good = "below the recent average and the order-by date is close"

    if good:
        return Decision(
            True, False, f"Good time to order: {price_per_l:.2f} kr/L is {good}. {by}", order_by
        )

    return Decision(
        False,
        False,
        f"Waiting for a better price ({price_per_l:.2f} kr/L, "
        f"{stats.percent_vs_average:+.1f}% vs average). {by}",
        order_by,
    )


def _format_date(day: date) -> str:
    """`17 Oct` style, independent of the system locale."""
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    return f"{day.day} {months[day.month - 1]}"
