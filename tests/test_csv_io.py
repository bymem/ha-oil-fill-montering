"""Tests for the fill history CSV module (spec 12.1, CSV)."""

from datetime import date

from conftest import FIXTURES
from csv_io import Fill, export_csv, merge, parse_csv, parse_date, parse_number


def test_sample_file():
    result = parse_csv((FIXTURES / "fills_sample.csv").read_text())
    assert result.errors == []
    assert len(result.fills) == 22
    fills = sorted(result.fills, key=lambda fill: fill.date)
    assert fills[0] == Fill(date(2016, 1, 12), 950, 6650)
    assert fills[-1] == Fill(date(2026, 8, 26), 870, 19400)
    assert sum(fill.liters for fill in fills) == 20660
    assert sum(fill.price for fill in fills) == 242200


def test_two_digit_year_is_2000s():
    assert parse_date("28.08.15") == date(2015, 8, 28)


def test_date_formats():
    for text in ("2026-01-08", "08.01.2026", "08-01-2026", "08/01/2026", "08.01.26"):
        assert parse_date(text) == date(2026, 1, 8), text
    assert parse_date("31.02.2026") is None
    assert parse_date("hello") is None


def test_number_formats():
    assert parse_number("12490") == 12490
    assert parse_number("12.490") == 12490
    assert parse_number("12 490,50") == 12490.5
    assert parse_number("1,234.56") == 1234.56
    assert parse_number("6.566,00") == 6566
    assert parse_number("12490 kr") == 12490
    assert parse_number("12490 DKK") == 12490
    assert parse_number("800 L") == 800
    assert parse_number("12,5") == 12.5
    assert parse_number("abc") is None


def test_danish_semicolon_file_with_aliases_and_bom():
    text = "﻿Dato;Liter;Pris\n08.01.2026;1.000;22.500,00\n"
    result = parse_csv(text)
    assert result.errors == []
    assert result.fills == [Fill(date(2026, 1, 8), 1000, 22500)]


def test_headerless_file():
    result = parse_csv("08.01.26,800,14000\n")
    assert result.fills == [Fill(date(2026, 1, 8), 800, 14000)]


def test_bad_rows_reported_good_rows_kept():
    text = "date,liters,price\nbad,800,100\n08.01.26,0,100\n08.01.26,800,-1\n09.01.26,800,100\n"
    result = parse_csv(text)
    assert result.fills == [Fill(date(2026, 1, 9), 800, 100)]
    assert [error.split(":")[0] for error in result.errors] == ["Row 2", "Row 3", "Row 4"]


def test_empty_file():
    result = parse_csv("")
    assert result.fills == []
    assert result.errors


def test_missing_column():
    result = parse_csv("date,liters\n08.01.26,800\n")
    assert result.fills == []
    assert "price" in result.errors[0]


def test_merge_idempotent_and_sorted():
    fills = parse_csv((FIXTURES / "fills_sample.csv").read_text()).fills
    merged, added, skipped = merge([], list(reversed(fills)))
    assert added == 22 and skipped == 0
    assert [fill.date for fill in merged] == sorted(fill.date for fill in merged)
    again, added, skipped = merge(merged, fills)
    assert again == merged
    assert added == 0 and skipped == 22


def test_export_then_import_round_trips():
    fills = [Fill(date(2026, 1, 8), 800.5, 14000.25), Fill(date(2025, 6, 1), 900, 15000)]
    text = export_csv(fills)
    assert text.splitlines()[0] == "date,liters,price"
    assert text.splitlines()[1] == "2025-06-01,900,15000"
    assert sorted(parse_csv(text).fills, key=lambda f: f.date) == sorted(fills, key=lambda f: f.date)
