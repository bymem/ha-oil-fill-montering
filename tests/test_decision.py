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
