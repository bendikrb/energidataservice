"""Base class for Energi Data Service entity."""
from homeassistant.helpers.entity import Entity

from .const import AREA_MAP, AREA_TO_TEXT, DOMAIN


class EnergidataserviceEntity(Entity):
    """Base implementation for Energi Data Service."""

    def __init__(self, name: str, area: str, type: str) -> None:
        """Initialize Energi Data Service."""
        super().__init__()
        self._name = name
        self._area = area
        self._type = type

    @property
    def device_info(self):
        """Return the device_info of the device."""
        area_name = AREA_MAP[self._area] or self._area
        area_text = (
            AREA_TO_TEXT[self._area] if self._area in AREA_TO_TEXT else self._area
        )
        return {
            "identifiers": {(DOMAIN, self._area, self._type)},
            "name": self._name,
            "manufacturer": None,
            "model": f"Spot prices {area_text} ({area_name})",
        }

    @property
    def should_poll(self):
        """Do not poll."""
        return True
