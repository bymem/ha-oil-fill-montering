"""Price feed coordinator.

Polls the feed every 3 hours, or after 30 minutes when the last fetch failed.
The feed gives only today's price, so each fetch is merged into the saved
price history, and the stats are computed from that history. The first
successful fetch also imports about a year of weekly history (retried on
each poll until it works).
A failed fetch keeps the previous prices: entities keep showing them, and
the age attribute tells how old they are.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    FEED_POLL_INTERVAL,
    FEED_RETRY_INTERVAL,
    FEED_TIMEOUT_SECONDS,
    HISTORY_BASE_PRODUCT_URL,
    HISTORY_PAGE_URL,
)
from .feed import FeedError, parse_feed, parse_history_page
from .prices import PriceStats, merge_prices, price_stats, trend_percent
from .settings import Settings
from .storage import PriceHistoryStore

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PriceData:
    """Full price history (oldest first) plus stats for the newest price."""

    prices: list[tuple[date, float]]
    stats: PriceStats
    # Same newest price against the longer stock-up window.
    stock_up_stats: PriceStats
    # Percent change over the last 14 days vs the 14 before (information only).
    trend_percent: float | None


async def _async_fetch_text(hass: HomeAssistant, url: str) -> str:
    """Download a URL as text.

    Raises aiohttp.ClientError or TimeoutError when it is unreachable.
    """
    session = async_get_clientsession(hass)
    async with session.get(
        url, timeout=aiohttp.ClientTimeout(total=FEED_TIMEOUT_SECONDS)
    ) as response:
        response.raise_for_status()
        return await response.text()


async def async_fetch_prices(hass: HomeAssistant, url: str) -> list[tuple[date, float]]:
    """Download and parse the feed: one row with today's price.

    Raises aiohttp.ClientError or TimeoutError when the feed is unreachable,
    and FeedError when it cannot be parsed.
    """
    return parse_feed(await _async_fetch_text(hass, url), dt_util.now().date())


class OilTankCoordinator(DataUpdateCoordinator[PriceData]):
    """Fetches the price feed and computes price stats."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        settings: Settings,
        history: PriceHistoryStore,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=FEED_POLL_INTERVAL,
        )
        self.feed_url = settings.feed_url
        self.lookback_days = settings.lookback_days
        self.stock_up_days = settings.stock_up_days
        self.history = history
        # Bumped whenever the price history changes, so the panel only
        # downloads the full history when there is something new.
        self.prices_version = 0

    async def _async_update_data(self) -> PriceData:
        """Fetch today's price; switch to the short retry interval on failure."""
        try:
            rows = await async_fetch_prices(self.hass, self.feed_url)
        except (aiohttp.ClientError, TimeoutError, FeedError) as err:
            self.update_interval = FEED_RETRY_INTERVAL
            raise UpdateFailed(f"Price feed failed: {err}") from err

        self.update_interval = FEED_POLL_INTERVAL
        today = dt_util.now().date()
        prices = merge_prices(self.history.prices, rows, today)

        was_imported = self.history.imported
        if not was_imported:
            imported = await self._async_import_history(rows[-1][1], today)
            if imported is not None:
                # Never replace saved prices with the coarser weekly ones.
                prices = merge_prices(prices, imported, today, overwrite=False)
                self.history.imported = True

        if prices != self.history.prices or self.history.imported != was_imported:
            self.history.prices = prices
            await self.history.async_save()
        if self.data is None or self.data.prices != prices:
            self.prices_version += 1

        stats = price_stats(prices, today, self.lookback_days)
        stock_up_stats = price_stats(prices, today, self.stock_up_days)
        # parse_feed never returns an empty list, so stats are always set here.
        assert stats is not None and stock_up_stats is not None
        return PriceData(
            prices=prices,
            stats=stats,
            stock_up_stats=stock_up_stats,
            trend_percent=trend_percent(prices),
        )

    async def _async_import_history(
        self, today_price: float, today: date
    ) -> list[tuple[date, float]] | None:
        """Weekly history from the market page, shifted onto the configured product.

        The chart holds Alm. prices; today's difference between the configured
        product and Alm. is added to every row (0 when the product is Alm.).
        Returns None on failure, so the next poll tries again.
        """
        try:
            html = await _async_fetch_text(self.hass, HISTORY_PAGE_URL)
            history = parse_history_page(html, today)
            base_rows = await async_fetch_prices(self.hass, HISTORY_BASE_PRODUCT_URL)
        except (aiohttp.ClientError, TimeoutError, FeedError) as err:
            _LOGGER.warning("Price history import failed, retrying on the next poll: %s", err)
            return None

        shift = today_price - base_rows[-1][1]
        _LOGGER.info("Imported %d days of price history (shift %+.0f kr/1000 L)", len(history), shift)
        return [(day, value + shift) for day, value in history]
