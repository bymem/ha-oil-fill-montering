"""Parsers for the supplier's prices (spec section 3.1).

Pure logic: imports nothing from Home Assistant so it can be unit tested alone.

Supplier: Billigolie.dk (a WooCommerce shop). Two sources:

* The daily price: the public WooCommerce Store API for one product, e.g.
  `/wp-json/wc/store/v1/products/4775`. It has no date and no history, only
  today's price per liter in minor units:
      {"prices": {"price": "1736", "currency_minor_unit": 2, ...}, ...}
* The one-time history import: the market page's chart script holds the
  weekly price per 1000 litres (Alm. oil) as JavaScript:
      var startDate = new Date(2025,9,20);   (month is 0-based)
      var bo_vores = [11700,10900,...];

All prices returned here are DKK per 1000 litres.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta


class FeedError(Exception):
    """The response could not be turned into at least one price."""


def parse_feed(text: str, today: date) -> list[tuple[date, float]]:
    """Return `[(today, price_per_1000_l)]` from a Store API product response.

    The API has no date, so the price is stamped with `today`.
    Raises FeedError when the body is not a product with a usable price.
    """
    try:
        data = json.loads(text.lstrip("﻿").strip())
    except ValueError as err:
        raise FeedError("Feed is not valid JSON") from err

    prices = data.get("prices") if isinstance(data, dict) else None
    if not isinstance(prices, dict):
        raise FeedError("Feed has no prices object")

    try:
        per_liter = int(prices["price"]) / 10 ** int(prices["currency_minor_unit"])
    except (KeyError, TypeError, ValueError) as err:
        raise FeedError("Feed has no usable price") from err
    if per_liter <= 0:
        raise FeedError("Feed price is not positive")

    return [(today, round(per_liter * 1000, 2))]


_START_RE = re.compile(r"var\s+startDate\s*=\s*new\s+Date\(\s*(\d{4})\s*,\s*(\d{1,2})\s*,\s*(\d{1,2})\s*\)")
_VALUES_RE = re.compile(r"var\s+bo_vores\s*=\s*\[([^\]]*)\]")


def parse_history_page(html: str, today: date) -> list[tuple[date, float]]:
    """Return daily `(date, price_per_1000_l)` rows from the market page chart.

    The chart has one price per week. Each week's price is repeated for its
    7 days, so the history stays one row per day (the trend compares the last
    14 rows). The newest week runs on until yesterday; today's price comes
    from the feed. Rows are sorted oldest first.
    Raises FeedError when the chart script is missing or holds no prices.
    """
    start_match = _START_RE.search(html)
    values_match = _VALUES_RE.search(html)
    if not start_match or not values_match:
        raise FeedError("History page has no price chart data")

    year, month, day = (int(part) for part in start_match.groups())
    try:
        # JavaScript months are 0-based.
        start = date(year, month + 1, day)
        weekly = [float(value) for value in values_match.group(1).split(",") if value.strip()]
    except ValueError as err:
        raise FeedError("History page chart data is malformed") from err
    if not weekly:
        raise FeedError("History page chart has no prices")

    rows: list[tuple[date, float]] = []
    for week, value in enumerate(weekly):
        week_start = start + timedelta(weeks=week)
        # The newest week runs on until yesterday; no row ever reaches today.
        week_end = today if week == len(weekly) - 1 else min(week_start + timedelta(days=7), today)
        current = week_start
        while current < week_end:
            rows.append((current, value))
            current += timedelta(days=1)
    return rows
