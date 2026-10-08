"""Runtime objects stored on the config entry."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.util import dt as dt_util

from .coordinator import OilTankCoordinator
from .decision import Decision, decide
from .settings import Settings
from .tank import TankManager


@dataclass
class OilTankData:
    """Everything the platforms and services need for the one config entry."""

    settings: Settings
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
            stock_up_stats=prices.stock_up_stats if prices else None,
            stock_up_percent=self.settings.stock_up_percent,
            lead_days=self.settings.lead_days,
            buffer_days=self.settings.buffer_days,
            min_order_l=self.settings.min_order_l,
            window_days=self.settings.window_days,
        )


type OilTankConfigEntry = ConfigEntry[OilTankData]
