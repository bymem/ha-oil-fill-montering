"""Persisted state (spec section 6): one Home Assistant Store document.

Saved immediately after a user action, otherwise debounced to at most once
per 60 seconds (degree-day ticks change the document every 10 minutes).
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.data"
SAVE_DELAY_SECONDS = 60


def _empty_document() -> dict[str, Any]:
    """Defaults for a fresh install. `baseline` stays None until the first reading."""
    return {
        "fills": [],
        "baseline": None,
        "dd": 0.0,
        "scale": 1.0,
        "last_ts": None,
        "last_temp": None,
        "last_temp_ts": None,
        "last_calibration": None,
    }


class OilTankStore:
    """Thin wrapper that owns the document and its save policy."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.data: dict[str, Any] = _empty_document()

    async def async_load(self) -> None:
        """Load from disk; missing keys get their defaults."""
        stored = await self._store.async_load()
        self.data = {**_empty_document(), **(stored or {})}

    async def async_save_now(self) -> None:
        """Save right away (after user actions and on unload)."""
        await self._store.async_save(self.data)

    def schedule_save(self) -> None:
        """Debounced save for background changes."""
        self._store.async_delay_save(lambda: self.data, SAVE_DELAY_SECONDS)
