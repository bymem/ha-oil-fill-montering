"""Fill history CSV import, merge and export (spec section 3.2).

Pure logic: imports nothing from Home Assistant so it can be unit tested alone.

The supported format is `date,liters,price` with one delivery per row. The
parser is tolerant of re-saved files (other delimiters, Danish number and
date formats, header aliases, no header) as a safety net only.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date

MAX_LITERS = 20_000
MAX_PRICE = 1_000_000

HEADER_ALIASES = {
    "date": {"date", "dato"},
    "liters": {"liters", "litres", "liter", "l", "amount"},
    "price": {"price", "pris", "total", "kr", "dkk"},
}

_ISO_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_DMY_DATE = re.compile(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})$")
_UNIT_SUFFIX = re.compile(r"(kr\.?|dkk|liters?|litres?|l)$")
_DOT_THOUSANDS = re.compile(r"^\d{1,3}(\.\d{3})+$")
_COMMA_THOUSANDS = re.compile(r"^\d{1,3}(,\d{3}){2,}$")


@dataclass(frozen=True)
class Fill:
    """One oil delivery. `price` is the total paid in DKK."""

    date: date
    liters: float
    price: float

    @property
    def key(self) -> tuple[date, float]:
        """Identity of a fill: same date and same liters (0.1 L precision)."""
        return (self.date, round(self.liters, 1))


@dataclass
class ParseResult:
    """Good rows plus one readable message per rejected row."""

    fills: list[Fill]
    errors: list[str]


def parse_date(text: str) -> date | None:
    """Parse the accepted date formats; two-digit years follow Python's %y pivot."""
    text = text.strip()
    try:
        if match := _ISO_DATE.match(text):
            year, month, day = (int(part) for part in match.groups())
            return date(year, month, day)
        if match := _DMY_DATE.match(text):
            day, month = int(match[1]), int(match[2])
            year = int(match[3])
            if len(match[3]) == 2:
                year += 2000 if year <= 68 else 1900
            return date(year, month, day)
    except ValueError:
        return None
    return None


def parse_number(text: str) -> float | None:
    """Parse `12490`, `12.490`, `12 490,50`, `1,234.56`, with optional kr/DKK/L."""
    text = text.strip().lower().replace(" ", "").replace(" ", "")
    text = _UNIT_SUFFIX.sub("", text)
    if not text:
        return None

    if "," in text and "." in text:
        # Both present: the last one is the decimal separator.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        # Danish decimal comma, unless it is clearly 1,234,567 grouping.
        text = text.replace(",", "") if _COMMA_THOUSANDS.match(text) else text.replace(",", ".")
    elif _DOT_THOUSANDS.match(text):
        # `12.490` is Danish thousands grouping, not 12.49.
        text = text.replace(".", "")

    try:
        return float(text)
    except ValueError:
        return None


def parse_csv(text: str) -> ParseResult:
    """Parse a fill history file. Bad rows are reported and skipped."""
    text = text.lstrip("﻿")
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return ParseResult([], ["File is empty"])

    delimiter = _detect_delimiter(lines[0])
    rows = list(csv.reader(lines, delimiter=delimiter))

    # Headerless files are accepted when the first cell is already a date.
    if parse_date(rows[0][0]) is not None:
        columns = {"date": 0, "liters": 1, "price": 2}
        data_rows = list(enumerate(rows, start=1))
    else:
        columns = _map_header(rows[0])
        missing = [name for name in HEADER_ALIASES if name not in columns]
        if missing:
            return ParseResult([], [f"Header is missing column(s): {', '.join(missing)}"])
        data_rows = list(enumerate(rows[1:], start=2))

    fills: list[Fill] = []
    errors: list[str] = []
    for row_number, row in data_rows:
        fill, error = _parse_row(row, columns)
        if error:
            errors.append(f"Row {row_number}: {error}")
        else:
            fills.append(fill)

    return ParseResult(fills, errors)


def merge(existing: list[Fill], incoming: list[Fill]) -> tuple[list[Fill], int, int]:
    """Merge without duplicates. Returns (merged sorted oldest first, added, skipped)."""
    seen = {fill.key for fill in existing}
    merged = list(existing)
    added = skipped = 0
    for fill in incoming:
        if fill.key in seen:
            skipped += 1
            continue
        seen.add(fill.key)
        merged.append(fill)
        added += 1
    merged.sort(key=lambda fill: fill.date)
    return merged, added, skipped


def export_csv(fills: list[Fill]) -> str:
    """Write the canonical format: ISO dates, dot decimals, oldest first."""
    lines = ["date,liters,price"]
    for fill in sorted(fills, key=lambda fill: fill.date):
        lines.append(f"{fill.date.isoformat()},{_format_number(fill.liters)},{_format_number(fill.price)}")
    return "\n".join(lines) + "\n"


def _detect_delimiter(first_line: str) -> str:
    """Pick tab, semicolon or comma from the first line."""
    if "\t" in first_line:
        return "\t"
    if ";" in first_line:
        return ";"
    return ","


def _map_header(header: list[str]) -> dict[str, int]:
    """Map known column names (case-insensitive aliases) to their index."""
    columns: dict[str, int] = {}
    for index, cell in enumerate(header):
        name = cell.strip().lower()
        for column, aliases in HEADER_ALIASES.items():
            if name in aliases and column not in columns:
                columns[column] = index
    return columns


def _parse_row(row: list[str], columns: dict[str, int]) -> tuple[Fill | None, str | None]:
    """Validate one row. Returns (fill, None) or (None, error message)."""
    if len(row) <= max(columns.values()):
        return None, "too few columns"

    day = parse_date(row[columns["date"]])
    liters = parse_number(row[columns["liters"]])
    price = parse_number(row[columns["price"]])

    if day is None:
        return None, f"invalid date '{row[columns['date']].strip()}'"
    if liters is None or not 0 < liters <= MAX_LITERS:
        return None, f"liters must be above 0 and at most {MAX_LITERS}"
    if price is None or not 0 <= price <= MAX_PRICE:
        return None, f"price must be between 0 and {MAX_PRICE}"
    return Fill(day, liters, price), None


def _format_number(value: float) -> str:
    """Integers without decimals, everything else with up to 2 decimals."""
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")
