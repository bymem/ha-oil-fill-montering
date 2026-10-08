"""Tests for the order recommendation (spec 12.1, decision): one per branch."""

from datetime import date, timedelta

import pytest
from conftest import FIXTURES
from oil_tank.decision import decide
from oil_tank.feed import parse_feed
from oil_tank.model import days_left, make_rates
from oil_tank.prices import PriceStats, price_stats

TODAY = date(2026, 10, 7)
SETTINGS = {"lead_days": 5, "buffer_days": 14, "min_order_l": 500, "window_days": 45}


def _stats(percent=0.0, lowest=False, age=0):
    """Hand-made price stats around 20 kr/L."""
    average = 20000
    return PriceStats(
        price_date=TODAY - timedelta(days=age),
        price=average * (1 + percent / 100),
        average=average,
        low=19000,
        high=21000,
        percent_vs_average=percent,
        lowest_in_window=lowest,
        age_days=age,
        lookback_days=30,
    )


def _decide(level, days, stats=None):
    return decide(
        level_l=level,
        days_remaining=days,
        capacity_l=1200,
        today=TODAY,
        stats=stats,
        **SETTINGS,
    )


def test_no_level():
    result = _decide(None, None, _stats())
    assert result.order is False
    assert result.order_by is None
    assert "Set the tank level" in result.reason


def test_urgent_ignores_price():
    result = _decide(100, 19, None)
    assert result.order is True and result.urgent is True
    assert result.reason.startswith("Order now")
    assert result.order_by == TODAY


def test_no_room_for_minimum_order():
    result = _decide(800, 60, _stats(percent=-10))
    assert result.order is False
    assert "room for only 400 L" in result.reason


def test_no_need_yet():
    result = _decide(400, 19 + 46, _stats(lowest=True))
    assert result.order is False
    assert result.reason.startswith("No need yet")


@pytest.mark.parametrize("stats", [None, _stats(lowest=True, age=4)], ids=["none", "stale"])
def test_no_fresh_price(stats):
    result = _decide(400, 40, stats)
    assert result.order is False
    assert result.reason.startswith("No fresh price data")


def test_good_price_lowest_in_window():
    result = _decide(400, 40, _stats(lowest=True))
    assert result.order is True and result.urgent is False
    assert "cheapest in 30 days" in result.reason


def test_good_price_below_average():
    result = _decide(400, 40, _stats(percent=-3))
    assert result.order is True
    assert "3.0% below the 30-day average" in result.reason


def test_good_price_close_to_order_by():
    # Slack 7 days, price just below average.
    result = _decide(400, 26, _stats(percent=-0.5))
    assert result.order is True
    assert "order-by date is close" in result.reason


def test_waiting_for_better_price():
    result = _decide(400, 40, _stats(percent=1.5))
    assert result.order is False
    assert result.reason.startswith("Waiting for a better price")
    assert "+1.5% vs average" in result.reason


@pytest.mark.parametrize(
    ("level", "start", "order_by"),
    [
        (150, "Waiting for a better price", date(2026, 10, 17)),
        (300, "Waiting for a better price", date(2026, 11, 9)),
        (450, "No need yet", date(2026, 11, 28)),
        (800, "Tank has room for only 400 L", date(2027, 1, 9)),
    ],
)
def test_worked_example_on_real_data(level, start, order_by):
    """Spec section 7 table: real prices on 2026-10-07, default model."""
    stats = price_stats(parse_feed((FIXTURES / "feed_2026-10-07.json").read_text()), TODAY, 30)
    days = days_left(level, TODAY, make_rates(), 1.0)
    result = _decide(level, days, stats)
    assert result.order is False
    assert result.reason.startswith(start)
    assert result.order_by == order_by


def _stock(percent, age=0):
    """90-day stats for the stock-up tier."""
    stats = _stats(percent=percent, age=age)
    return PriceStats(**{**stats.__dict__, "lookback_days": 90})


def test_stock_up_any_time_with_room():
    # Far from the order-by date (no need yet), but 7.5% below the 90-day average.
    result = decide(
        level_l=400, days_remaining=200, capacity_l=1200, today=TODAY, stats=_stats(),
        stock_up_stats=_stock(-7.5), stock_up_percent=7, **SETTINGS,
    )
    assert result.order is True and result.urgent is False
    assert result.reason.startswith("Unusually cheap")
    assert "7.5% below the 90-day average" in result.reason
    assert "room for 800 L" in result.reason


@pytest.mark.parametrize(
    ("level", "stock"),
    [(800, _stock(-10)), (400, _stock(-6.9)), (400, _stock(-10, age=4))],
    ids=["no room", "not cheap enough", "stale price"],
)
def test_stock_up_does_not_fire(level, stock):
    result = decide(
        level_l=level, days_remaining=200, capacity_l=1200, today=TODAY, stats=_stats(),
        stock_up_stats=stock, stock_up_percent=7, **SETTINGS,
    )
    assert result.order is False


def test_urgent_wins_over_stock_up():
    result = decide(
        level_l=100, days_remaining=10, capacity_l=1200, today=TODAY, stats=_stats(),
        stock_up_stats=_stock(-10), stock_up_percent=7, **SETTINGS,
    )
    assert result.urgent is True


def test_stock_up_catches_june_2026_dip():
    """Backtest case: 18 June 2026, 19.02 kr/L, more than 7% below the 90-day average."""
    prices = parse_feed((FIXTURES / "feed_2026-10-07.json").read_text())
    day = date(2026, 6, 18)
    upto = [p for p in prices if p[0] <= day]
    result = decide(
        level_l=600, days_remaining=150, capacity_l=1225, today=day,
        stats=price_stats(upto, day, 30), stock_up_stats=price_stats(upto, day, 90),
        stock_up_percent=7, **SETTINGS,
    )
    assert result.order is True
    assert result.reason.startswith("Unusually cheap: 19.02 kr/L")
