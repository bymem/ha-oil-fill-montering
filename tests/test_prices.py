"""Tests for price statistics (spec 12.1, prices)."""

from datetime import date, timedelta

import pytest
from conftest import FIXTURES
from oil_tank.feed import parse_feed
from oil_tank.prices import price_stats

TODAY = date(2026, 10, 7)


def _series(values, end=TODAY):
    """Daily prices ending on `end`, oldest first."""
    start = end - timedelta(days=len(values) - 1)
    return [(start + timedelta(days=i), float(v)) for i, v in enumerate(values)]


def test_empty_list_returns_none():
    assert price_stats([], TODAY) is None


def test_real_data_case():
    prices = parse_feed((FIXTURES / "feed_2026-10-07.json").read_text())
    stats = price_stats(prices, TODAY, 30)
    assert stats.price == 22321
    assert stats.average == pytest.approx(22811)
    assert stats.percent_vs_average == pytest.approx(-2.148, abs=0.01)
    # 22,121 earlier in the window was lower, so today is not the lowest.
    assert stats.low == 22121
    assert stats.lowest_in_window is False
    assert stats.age_days == 0


def test_window_only_uses_lookback_days():
    stats = price_stats(_series([1, 100, 100, 100]), TODAY, 3)
    assert stats.low == 100
    assert stats.average == 100


def test_lowest_in_window_with_tolerance():
    # 0.25% above the earlier low still counts as lowest.
    assert price_stats(_series([1000, 1100, 1002.5]), TODAY).lowest_in_window is True
    assert price_stats(_series([1000, 1100, 1003]), TODAY).lowest_in_window is False


def test_single_price_is_not_lowest():
    assert price_stats(_series([1000]), TODAY).lowest_in_window is False


def test_age_days():
    stats = price_stats(_series([1000], end=TODAY - timedelta(days=4)), TODAY)
    assert stats.age_days == 4
