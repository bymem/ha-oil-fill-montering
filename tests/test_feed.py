"""Tests for the price feed parser (spec 12.1, feed)."""

from datetime import date

import pytest
from conftest import FIXTURES
from feed import FeedError, parse_feed


def test_parses_real_feed_sorted():
    prices = parse_feed((FIXTURES / "feed_2026-10-07.json").read_text())
    assert len(prices) == 731
    assert prices[0] == (date(2024, 10, 7), 16437.25)
    assert prices[-1] == (date(2026, 10, 7), 22321.0)
    assert [day for day, _ in prices] == sorted(day for day, _ in prices)


def test_sorts_unsorted_input():
    text = '{"prices":{"price":[{"@_date":"02.01.2026","value":2},{"@_date":"01.01.2026","value":1}]}}'
    assert parse_feed(text) == [(date(2026, 1, 1), 1.0), (date(2026, 1, 2), 2.0)]


def test_skips_bad_rows():
    text = (
        '{"prices":{"price":['
        '{"@_date":"01.01.2026","value":1000},'
        '{"@_date":"bad","value":1000},'
        '{"@_date":"02.01.2026","value":"x"},'
        '{"@_date":"03.01.2026"},'
        '{"@_date":"04.01.2026","value":-5}'
        "]}}"
    )
    assert parse_feed(text) == [(date(2026, 1, 1), 1000.0)]


def test_accepts_single_row_object_and_bom():
    text = '﻿{"prices":{"price":{"@_date":"01.01.2026","value":1000}}}'
    assert parse_feed(text) == [(date(2026, 1, 1), 1000.0)]


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "{}",
        '{"prices":{"price":[]}}',
        '{"prices":{"price":[{"@_date":"bad","value":1}]}}',
        "<prices><price/></prices>",
    ],
)
def test_rejects_unusable_feeds(text):
    with pytest.raises(FeedError):
        parse_feed(text)
