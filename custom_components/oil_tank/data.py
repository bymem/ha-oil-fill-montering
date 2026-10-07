"""Runtime objects stored on the config entry."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_BUFFER_DAYS,
    DEFAULT_LEAD_DAYS,
    DEFAULT_MIN_ORDER_L,
    DEFAULT_WINDOW_DAYS,
)
from .coordinator import OilTankCoordinator
from .decision import Decision, decide
from .tank import TankManager


@dataclass
class OilTankData:
    """Everything the platforms and services need for the one config entry."""

    coordinator: OilTankCoordinator
    tank: TankManager

    def recommendation(self) -> Decision:
        """Current order advice; shared by the binary sensor and the panel."""
        snapshot = self.tank.snapshot
        prices = self.coordinator.data
        return decide(
            level_l=snapshot.level_l,
            days_remaining=snapshot.days_remaining,
            capacity_l=self.tank.capacity_l,
            today=dt_util.now().date(),
            stats=prices.stats if prices else None,
            lead_days=DEFAULT_LEAD_DAYS,
            buffer_days=DEFAULT_BUFFER_DAYS,
            min_order_l=DEFAULT_MIN_ORDER_L,
            window_days=DEFAULT_WINDOW_DAYS,
        )


type OilTankConfigEntry = ConfigEntry[OilTankData]
