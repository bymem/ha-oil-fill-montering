"""Tests for the consumption model (spec 12.1, model)."""

from datetime import date, timedelta

import pytest
from oil_tank.model import (
    DAYS_IN_MONTH,
    accumulate_dd,
    annual_from_fills,
    annual_normal_dd,
    burn_since,
    calibrate,
    clamp,
    daily_burn,
    days_left,
    make_rates,
    normal_dd_between,
    normal_dd_per_day,
    order_by_date,
)

TODAY = date(2026, 10, 7)
RATES = make_rates()


def test_default_rates_match_spec():
    assert annual_normal_dd(17) == pytest.approx(2869, abs=1)
    assert RATES.base_l_per_day == pytest.approx(0.98, abs=0.01)
    assert RATES.l_per_dd == pytest.approx(0.499, abs=0.001)


def test_rates_reproduce_yearly_consumption():
    year = sum(
        burn_since(RATES, 1.0, DAYS_IN_MONTH[m - 1], normal_dd_per_day(m, 17) * DAYS_IN_MONTH[m - 1])
        for m in range(1, 13)
    )
    assert year == pytest.approx(1790, rel=0.01)


@pytest.mark.parametrize(
    ("level", "expected"),
    [(150, 30.0), (300, 52.5), (450, 71.4), (600, 89.7), (800, 113.0), (1000, 136.2)],
)
def test_days_left_vectors(level, expected):
    assert days_left(level, TODAY, RATES, 1.0) == pytest.approx(expected, abs=0.05)


def test_days_left_empty_and_cap():
    assert days_left(0, TODAY, RATES, 1.0) == 0
    assert days_left(1_000_000, TODAY, RATES, 1.0) == 730


def test_forecast_shorter_in_autumn_than_summer():
    autumn = days_left(500, date(2026, 10, 1), RATES, 1.0)
    summer = days_left(500, date(2026, 5, 1), RATES, 1.0)
    assert autumn < summer


def test_clamp_level():
    assert clamp(-5, 0, 1200) == 0
    assert clamp(1500, 0, 1200) == 1200


def test_one_day_at_7c_is_10_dd():
    added = accumulate_dd(elapsed_days=1, prev_temp=7, prev_temp_age_days=0, month=10, base_temp=17)
    assert added == pytest.approx(10)


def test_warm_day_adds_nothing():
    assert accumulate_dd(elapsed_days=1, prev_temp=20, prev_temp_age_days=0, month=7, base_temp=17) == 0


@pytest.mark.parametrize(
    ("elapsed", "temp", "age"),
    [(3, 7, 0), (0.1, None, 0), (0.1, 7, 0.5)],
    ids=["long gap", "no temperature", "stale temperature"],
)
def test_fallback_to_normal_dd(elapsed, temp, age):
    added = accumulate_dd(elapsed_days=elapsed, prev_temp=temp, prev_temp_age_days=age, month=1, base_temp=17)
    assert added == pytest.approx(normal_dd_per_day(1, 17) * elapsed)


def test_order_by_date():
    # 30 days left - 5 lead - 14 buffer = 11 days of slack.
    assert order_by_date(30.0, TODAY, 5, 14) == TODAY + timedelta(days=11)
    assert order_by_date(10.0, TODAY, 5, 14) == TODAY


def test_calibration_ignores_short_intervals_and_tiny_predictions():
    assert calibrate(1.0, predicted=100, actual=200, interval_days=13) == 1.0
    assert calibrate(1.0, predicted=19, actual=40, interval_days=30) == 1.0


def test_calibration_is_damped():
    # Burned 20% more than predicted -> scale moves 30% of the way.
    assert calibrate(1.0, predicted=100, actual=120, interval_days=30) == pytest.approx(1.06)


def test_calibration_is_capped():
    # Ratio capped at 2.0, then scale capped at 2.0.
    assert calibrate(1.0, predicted=100, actual=1000, interval_days=30) == pytest.approx(1.3)
    assert calibrate(1.9, predicted=100, actual=1000, interval_days=30) == 2.0
    # Negative actual is treated as 0, ratio capped at 0.5.
    assert calibrate(1.0, predicted=100, actual=-50, interval_days=30) == pytest.approx(0.85)
    assert calibrate(0.55, predicted=100, actual=0, interval_days=30) == 0.5


def test_annual_from_fills_excludes_latest_delivery():
    fills = [(date(2024, 1, 1), 1000), (date(2024, 7, 1), 800), (date(2025, 1, 1), 900)]
    history = annual_from_fills(fills)
    # 1,800 L burned over 366 days (2024 is a leap year).
    assert history.annual_l == pytest.approx(1800 / (366 / 365.25))
    assert history.fills_used == 3
    assert history.since == date(2024, 1, 1)


def test_annual_from_fills_needs_enough_history():
    assert annual_from_fills([]) is None
    # Two fills only.
    assert annual_from_fills([(date(2024, 1, 1), 1000), (date(2025, 6, 1), 800)]) is None
    # Three fills, but less than a year apart.
    assert annual_from_fills([(date(2025, 1, 1), 1), (date(2025, 3, 1), 1), (date(2025, 9, 1), 1)]) is None


def test_annual_from_fills_uses_last_five_years():
    old = [(date(2010, 1, 1), 5000)]
    recent = [(date(2022, 1, 1), 1000), (date(2023, 1, 1), 1000), (date(2024, 1, 1), 1000)]
    assert annual_from_fills(old + recent) == annual_from_fills(recent)


def test_annual_from_sample_history():
    from conftest import FIXTURES
    from oil_tank.csv_io import parse_csv

    fills = parse_csv((FIXTURES / "fills_sample.csv").read_text()).fills
    history = annual_from_fills([(f.date, f.liters) for f in fills])
    # Last 5 years before 2026-08-26: 2021-08-26 onwards.
    assert history.since == date(2022, 1, 11)
    assert history.fills_used == 10
    assert 1700 < history.annual_l < 2000


def test_normal_dd_between():
    assert normal_dd_between(date(2026, 1, 1), date(2026, 1, 1), 17) == 0
    assert normal_dd_between(date(2026, 1, 1), date(2026, 1, 11), 17) == pytest.approx(10 * (17 - 1.8))


def test_daily_burn_uses_temperature_or_normal():
    assert daily_burn(RATES, 1.0, 7, 10) == pytest.approx(RATES.base_l_per_day + RATES.l_per_dd * 10)
    assert daily_burn(RATES, 1.0, None, 7) == pytest.approx(RATES.base_l_per_day + RATES.l_per_dd * 0)  # July is above 17 C
