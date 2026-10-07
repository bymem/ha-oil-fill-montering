"""Parser for the supplier's daily price feed (spec section 3.1).

Pure logic: imports nothing from Home Assistant so it can be unit tested alone.

The feed URL ends in `.xml` but the body is JSON:
    {"prices":{"price":[{"@_date":"07.10.2024","value":16437.25}, ...]}}
`value` is the list price in DKK per 1000 litres, one row per calendar day.
"""

from __future__ import annotations

import json
from datetime import date, datetime


class FeedError(Exception):
    """The feed body could not be turned into at least one price."""


def parse_feed(text: str) -> list[tuple[date, float]]:
    """Return `(date, price_per_1000_l)` pairs sorted oldest first.

    Bad rows are skipped. Raises FeedError when nothing usable is left,
    so the caller can keep its previous prices.
    """
    text = text.lstrip("﻿").strip()
    if text.startswith("<"):
        # Real XML is not supported in v1; do not guess at its shape.
        raise FeedError("Unexpected format: feed returned XML, expected JSON")

    try:
        data = json.loads(text)
    except ValueError as err:
        raise FeedError("Feed is not valid JSON") from err

    rows = data.get("prices", {}).get("price") if isinstance(data, dict) else None
    if isinstance(rows, dict):
        # XML-to-JSON converters emit a single object instead of a one-item list.
        rows = [rows]
    if not isinstance(rows, list):
        raise FeedError("Feed has no prices.price list")

    # Keyed by date so a duplicated day keeps only its last value.
    by_date: dict[date, float] = {}
    for row in rows:
        try:
            day = datetime.strptime(str(row["@_date"]).strip(), "%d.%m.%Y").date()
            value = float(row["value"])
        except (KeyError, TypeError, ValueError):
            continue
        if value > 0:
            by_date[day] = value

    if not by_date:
        raise FeedError("Feed contains no usable price rows")

    return sorted(by_date.items())
