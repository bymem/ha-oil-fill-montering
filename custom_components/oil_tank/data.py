"""Runtime objects stored on the config entry."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry

from .coordinator import OilTankCoordinator
from .tank import TankManager


@dataclass
class OilTankData:
    """Everything the platforms and services need for the one config entry."""

    coordinator: OilTankCoordinator
    tank: TankManager


type OilTankConfigEntry = ConfigEntry[OilTankData]
