"""Tests for the Billigolie price parsers (spec 12.1, feed)."""

from datetime import date, timedelta

import pytest
from conftest import FIXTURES
from oil_tank.feed import FeedError, parse_feed, parse_history_page
from oil_tank.prices import merge_prices

TODAY = date(2026, 10, 30)


def test_parses_real_product():
    text = (FIXTURES / "billigolie_product_4775.json").read_text()
    # 1736 ore per liter = 17,360 kr per 1000 L.
    assert parse_feed(text, TODAY) == [(TODAY, 17360.0)]


def test_accepts_bom_and_other_minor_unit():
    text = '﻿{"prices":{"price":"17","currency_minor_unit":0}}'
    assert parse_feed(text, TODAY) == [(TODAY, 17000.0)]


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "{}",
        "[]",
        '{"prices":{"currency_minor_unit":2}}',
        '{"prices":{"price":"abc","currency_minor_unit":2}}',
        '{"prices":{"price":"0","currency_minor_unit":2}}',
        "<html></html>",
    ],
)
def test_rejects_unusable_feeds(text):
    with pytest.raises(FeedError):
        parse_feed(text, TODAY)


def test_parses_real_history_page():
    rows = parse_history_page((FIXTURES / "billigolie_history_2026-10-30.html").read_text(), TODAY)
    # 2025-10-20 (JS month 9 = October) up to yesterday, one row per day.
    assert rows[0] == (date(2025, 10, 20), 11700.0)
    assert rows[6] == (date(2025, 10, 26), 11700.0)
    assert rows[7] == (date(2025, 10, 27), 10900.0)
    assert rows[-1] == (date(2026, 10, 29), 17260.0)
    assert len(rows) == (TODAY - date(2025, 10, 20)).days


def test_history_never_reaches_today():
    html = "var startDate = new Date(2026,9,27); var bo_vores = [1,2];"
    rows = parse_history_page(html, TODAY)
    # Second week would start 2026-11-03, after today: nothing of it is kept.
    assert rows == [(date(2026, 10, 27) + timedelta(days=i), 1.0) for i in range(3)]


@pytest.mark.parametrize(
    "html",
    [
        "<html></html>",
        "var bo_vores = [1,2];",
        "var startDate = new Date(2025,9,20); var bo_vores = [];",
        "var startDate = new Date(2025,9,20); var bo_vores = [1,x];",
        "var startDate = new Date(2025,12,40); var bo_vores = [1];",
    ],
)
def test_rejects_unusable_history_pages(html):
    with pytest.raises(FeedError):
        parse_history_page(html, TODAY)


def test_merge_overwrites_by_default_and_trims():
    old = date(2024, 10, 1)
    history = [(old, 1.0), (date(2026, 10, 29), 2.0), (TODAY, 3.0)]
    merged = merge_prices(history, [(TODAY, 4.0)], TODAY)
    assert merged == [(date(2026, 10, 29), 2.0), (TODAY, 4.0)]


def test_merge_without_overwrite_keeps_saved_dates():
    history = [(TODAY, 3.0)]
    merged = merge_prices(history, [(date(2026, 10, 29), 2.0), (TODAY, 9.0)], TODAY, overwrite=False)
    assert merged == [(date(2026, 10, 29), 2.0), (TODAY, 3.0)]
