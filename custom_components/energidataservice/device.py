"""Device data library."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator


@dataclass
class DeviceState:
    """Store state of a device."""

    coordinator: DataUpdateCoordinator[State]
    device_info: DeviceInfo


@dataclass(frozen=True)
class State:
    """Data received from characteristics."""

    period_length: int = 0
    period_deadline: datetime = None
