"""Price feed coordinator.

Polls the feed every 3 hours, or after 30 minutes when the last fetch failed.
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
    CONF_FEED_URL,
    DEFAULT_FEED_URL,
    DEFAULT_LOOKBACK_DAYS,
    DOMAIN,
    FEED_POLL_INTERVAL,
    FEED_RETRY_INTERVAL,
    FEED_TIMEOUT_SECONDS,
)
from .feed import FeedError, parse_feed
from .prices import PriceStats, price_stats

_LOGGER = logging.getLogger(__name__)

type OilTankConfigEntry = ConfigEntry[OilTankCoordinator]


@dataclass(frozen=True)
class PriceData:
    """Full price history (oldest first) plus stats for the newest price."""

    prices: list[tuple[date, float]]
    stats: PriceStats


async def async_fetch_prices(hass: HomeAssistant, url: str) -> list[tuple[date, float]]:
    """Download and parse the feed.

    Raises aiohttp.ClientError or TimeoutError when the feed is unreachable,
    and FeedError when it cannot be parsed.
    """
    session = async_get_clientsession(hass)
    async with session.get(
        url, timeout=aiohttp.ClientTimeout(total=FEED_TIMEOUT_SECONDS)
    ) as response:
        response.raise_for_status()
        # Read as text: the server labels the JSON body as XML.
        text = await response.text()
    return parse_feed(text)


class OilTankCoordinator(DataUpdateCoordinator[PriceData]):
    """Fetches the price feed and computes price stats."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=FEED_POLL_INTERVAL,
        )
        # Entries created before the feed URL was configurable fall back to the default.
        self.feed_url: str = entry.data.get(CONF_FEED_URL, DEFAULT_FEED_URL)

    async def _async_update_data(self) -> PriceData:
        """Fetch prices; switch to the short retry interval on failure."""
        try:
            prices = await async_fetch_prices(self.hass, self.feed_url)
        except (aiohttp.ClientError, TimeoutError, FeedError) as err:
            self.update_interval = FEED_RETRY_INTERVAL
            raise UpdateFailed(f"Price feed failed: {err}") from err

        self.update_interval = FEED_POLL_INTERVAL
        stats = price_stats(prices, dt_util.now().date(), DEFAULT_LOOKBACK_DAYS)
        # parse_feed never returns an empty list, so stats is always set here.
        assert stats is not None
        return PriceData(prices=prices, stats=stats)
