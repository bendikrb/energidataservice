"""Support for number helper in Energidataservice."""
from __future__ import annotations
import logging

from homeassistant.components.number import (
    NumberEntityDescription,
    NumberMode,
    NumberEntity,
)
from homeassistant.components.number.const import ATTR_VALUE
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, CONF_STATE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory, Entity
from homeassistant.helpers.script import Script
from homeassistant.util import slugify as util_slugify
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from . import async_setup_entry_platform
from .const import (
    ATTR_HOUR,
    CONF_AREA,
    CONF_PERIOD_LENGTH,
    CONF_SET_VALUE,
    DOMAIN,
)

from .device import DeviceState, State
from .entity import EnergidataserviceEntity
from .utils.regionhandler import RegionHandler

_LOGGER = logging.getLogger(__name__)

entitydesc = NumberEntityDescription(
    key=CONF_PERIOD_LENGTH,
    name="Lookup period",
    icon="mdi:clock",
)


async def async_setup_entry(hass, config_entry: ConfigEntry, async_add_entities):
    """Setup sensor platform from a config entry."""
    config = config_entry

    def _constructor(device_state: DeviceState) -> list[Entity]:
        area = config.options.get(CONF_AREA) or config.data.get(CONF_AREA)
        region = RegionHandler(area)

        return [
            EnergidataserviceNumber(config, hass, region),
        ]

    # _setup(hass, config, async_add_devices)
    # return True
    async_setup_entry_platform(hass, config_entry, async_add_entities, _constructor)



def _setup(hass, config: ConfigEntry, add_devices):
    """Setup the platform."""
    area = config.options.get(CONF_AREA) or config.data.get(CONF_AREA)
    region = RegionHandler(area)

    entity = EnergidataserviceNumber(config, hass, region)

    add_devices([entity])


class EnergidataserviceNumber(
    CoordinatorEntity[DataUpdateCoordinator[CONF_STATE]], NumberEntity
):
    """Represent Energidataservice number entity."""

    _attr_max_value: float = 59
    _attr_min_value: float = 0
    _attr_step: float = 1
    _attr_entity_category = EntityCategory.CONFIG
    _attr_unit_of_measurement = (ATTR_HOUR,)
    _attr_mode: NumberMode = NumberMode.SLIDER

    def __init__(
        self, config: ConfigEntry, hass: HomeAssistant, region: RegionHandler
    ) -> None:
        """Initialize instance."""
        super().__init__(
            config.data.get(CONF_NAME), region.description, "period_length"
        )
        # self.entity_description = entitydesc
        self._config = config
        self.region = region
        self._entry_id = config.entry_id
        self._name = config.data.get(CONF_NAME)
        self._area = region.description
        self._api = hass.data[DOMAIN][config.entry_id]

        self._attr_unique_id = util_slugify(
            f"{self._name}_{self._entry_id}_period_length"
        )

    @property
    def value(self) -> float | None:
        """Return the entity value to represent the entity state."""
        # Unknown or unsupported data type
        if self._value is None:
            return None

        return self._value

    async def async_set_value(self, value: float) -> None:
        """Set new value."""
        self._api.p_length = value
        self.async_write_ha_state()

    #     await self._command_set_value.async_run(
    #         {ATTR_VALUE: value}, context=self._context
    #     )
