"""Support for Energi Data Service sensor."""
from __future__ import annotations

from collections import namedtuple
from datetime import datetime, timedelta
import logging

from homeassistant.components import sensor
from homeassistant.components.sensor import SensorStateClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, DEVICE_CLASS_MONETARY
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, Entity, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.template import Template, attach
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.util import dt as dt_utils, slugify as util_slugify
import pytz
from jinja2 import pass_context

from . import async_setup_entry_platform
from .const import (
    AREA_MAP,
    CENT_MULTIPLIER,
    CONF_AREA,
    CONF_CURRENCY_IN_CENT,
    CONF_DECIMALS,
    CONF_PRICETYPE,
    CONF_TEMPLATE,
    CONF_VAT,
    DEFAULT_TEMPLATE,
    DOMAIN,
    UNIT_TO_MULTIPLIER,
    UPDATE_EDS,
)
from .device import DeviceState, State
from .entity import EnergidataserviceEntity
from .utils.regionhandler import RegionHandler

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor platform from a config entry."""

    def _constructor(device_state: DeviceState) -> list[Entity]:
        """Setup the platform."""
        config = config_entry
        area = config.options.get(CONF_AREA) or config.data.get(CONF_AREA)
        region = RegionHandler(area)
        _LOGGER.debug("Timezone set in ha %s", hass.config.time_zone)
        _LOGGER.debug("Currency set in ha %s", hass.config.currency)
        _LOGGER.debug("Country: %s", region.country)
        _LOGGER.debug("Region: %s", region.name)
        _LOGGER.debug("Region description: %s", region.description)
        _LOGGER.debug("Region currency %s", region.currency.name)
        _LOGGER.debug(
            "Show in cent: %s", config.options.get(CONF_CURRENCY_IN_CENT) or False
        )
        _LOGGER.debug("Domain %s", DOMAIN)

        if region.currency.name != hass.config.currency:
            _LOGGER.warning(
                "Official currency for %s is %s but Home Assistant reports %s from config and will show prices in %s",  # pylint: disable=line-too-long
                region.country,
                region.currency.name,
                hass.config.currency,
                hass.config.currency,
            )
            region.set_region(area, hass.config.currency)

        return [EnergidataserviceSensor(device_state.coordinator, config, hass, region)]

    async_setup_entry_platform(hass, config_entry, async_add_entities, _constructor)


def mean(data: list) -> float:
    """Calculate mean value of list."""
    val = 0
    num = 0

    for i in data:
        val += i.price
        num += 1

    return val / num


# def _setup(hass, config: ConfigEntry, add_devices):
#     """Setup the platform."""
#     area = config.options.get(CONF_AREA) or config.data.get(CONF_AREA)
#     region = RegionHandler(area)
#     _LOGGER.debug("Timezone set in ha %s", hass.config.time_zone)
#     _LOGGER.debug("Currency set in ha %s", hass.config.currency)
#     _LOGGER.debug("Country: %s", region.country)
#     _LOGGER.debug("Region: %s", region.name)
#     _LOGGER.debug("Region description: %s", region.description)
#     _LOGGER.debug("Region currency %s", region.currency.name)
#     _LOGGER.debug(
#         "Show in cent: %s", config.options.get(CONF_CURRENCY_IN_CENT) or False
#     )
#     _LOGGER.debug("Domain %s", DOMAIN)

#     if region.currency.name != hass.config.currency:
#         _LOGGER.warning(
#             "Official currency for %s is %s but Home Assistant reports %s from config and will show prices in %s",  # pylint: disable=line-too-long
#             region.country,
#             region.currency.name,
#             hass.config.currency,
#             hass.config.currency,
#         )
#         region.set_region(area, hass.config.currency)

#     sens = EnergidataserviceSensor(config, hass, region)

#     add_devices(hass, config, add_devices, sens)
#     # add_devices([sens])


@callback
def _async_migrate_unique_id(hass: HomeAssistant, entity: str, new_id: str) -> None:
    """Change unique_ids to allow multiple instances."""
    _LOGGER.debug("Testing for unique_id")
    entity_registry = er.async_get(hass)
    curentity = entity_registry.async_get(entity)
    if not curentity is None:
        _LOGGER.debug("- Device_id: %s", curentity.device_id)
        if not new_id is None:
            device_registry = dr.async_get(hass)
            curdevice = device_registry.async_get(curentity.device_id)
            identifiers = curdevice.identifiers
            for identifier in identifiers:
                _LOGGER.debug(" - Identifier found: %s", identifier)
            _LOGGER.debug(" - Adding new device identifier")
            device_registry = dr.async_get(hass)
            curdevice = device_registry.async_get(curentity.device_id)
            identifiers = curdevice.identifiers
            tup_dict = dict(identifiers)  # {'hi': 'bye', 'one': 'two'}
            tup_dict[DOMAIN] = new_id
            identifiers = tuple(tup_dict.items())  # (('one', 'two'),)
            for identifier in identifiers:
                _LOGGER.debug(" - Identifier after edit: %s", identifier)
            device_registry.async_update_device(
                curentity.device_id, new_identifiers=identifiers
            )
            if curentity.unique_id in [
                "energidataservice_West of the great belt",
                "energidataservice_East of the great belt",
            ]:
                _LOGGER.debug(" - Adding extra entity identifier")
                entity_registry.async_update_entity(entity, new_unique_id=new_id)
        else:
            _LOGGER.debug(" - New id not set, skipping")
    else:
        _LOGGER.debug("- Check didn't find anything")


# class EnergidataserviceSensor(EnergidataserviceEntity):
class EnergidataserviceSensor(
    CoordinatorEntity[DataUpdateCoordinator[State]], SensorEntity
):
    """Representation of Energi Data Service data."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[State],
        config: ConfigEntry,
        hass: HomeAssistant,
        region: RegionHandler,
    ) -> None:
        """Initialize Energidataservice sensor."""
        self._config = config
        self.region = region
        self._entry_id = config.entry_id
        self._cent = config.options.get(CONF_CURRENCY_IN_CENT) or False
        self._area = (
            region.description
        )  # config.options.get(CONF_AREA) or config.data.get(CONF_AREA)
        self._currency = hass.config.currency
        self._price_type = config.options.get(CONF_PRICETYPE) or config.data.get(
            CONF_PRICETYPE
        )
        self._decimals = config.options.get(CONF_DECIMALS) or config.data.get(
            CONF_DECIMALS
        )
        self._api = hass.data[DOMAIN][config.entry_id]
        self._cost_template = config.options.get(CONF_TEMPLATE) or config.data.get(
            CONF_TEMPLATE
        )
        self._hass = hass
        self._name = config.data.get(CONF_NAME)
        self._friendly_name = config.options.get(CONF_NAME) or config.data.get(
            CONF_NAME
        )
        if config.options.get(CONF_VAT) is True:
            self._vat = 0.25
        else:
            self._vat = 0
        # super().__init__(self._name, region.description, "price_sensor")
        # super().__init__(coordinator)

        self._entity_id = sensor.ENTITY_ID_FORMAT.format(
            util_slugify(f"{self._name} {self._area}")
        )
        self._unique_id = util_slugify(f"{self._name}_{self._entry_id}")
        _async_migrate_unique_id(hass, self._entity_id, self._unique_id)

        _LOGGER.debug("Sensor unique id: %s", self._unique_id)

        # Holds current price
        self._state = None

        # Holds the raw data
        self._today_raw = None
        self._tomorrow_raw = None

        # Holds statistical prices for today
        self._today_min = None
        self._today_max = None

        # Holds statistical prices for tomorrow
        self._tomorrow_min = None
        self._tomorrow_max = None

        # Holds mean values for today and tomorrow
        self._today_mean = None
        self._tomorrow_mean = None

        # Holds cheapest period
        self._cheap = None

        # Holds most expensive period
        self._expensive = None

        # Check incase the sensor was setup using config flow.
        # This blow up if the template isnt valid.
        if not isinstance(self._cost_template, Template):
            if self._cost_template in (None, ""):
                self._cost_template = DEFAULT_TEMPLATE
            self._cost_template = cv.template(self._cost_template)
        # check for yaml setup.
        else:
            if self._cost_template.template in ("", None):
                self._cost_template = cv.template(DEFAULT_TEMPLATE)

        attach(self._hass, self._cost_template)

    def _get_cheap_and_expensive_period(self, before, length: int) -> list:
        """Get the cheapest period of the given length in hours."""
        data = self.raw_today
        if self.tomorrow_valid:
            data += self.raw_tomorrow

        local_tz = pytz.timezone(self._hass.config.time_zone)
        now = datetime.now().astimezone(local_tz)
        before = local_tz.localize(
            datetime.strptime(
                f"{now.month}/{now.day}/{now.year} {before}", "%d/%m/%Y %H:%M:%S"
            ).replace(tzinfo=None)
        )
        if now.hour > before.hour:
            before += timedelta(days=1)

        index_start = now.hour
        index_end = (
            data.index(
                max(
                    (n for n in data if n["hour"].hour == before.hour),
                    key=lambda k: k["hour"],
                )
            )
            - length
        )

        if index_end < index_start:
            index_end = len(data) - length
        if index_end < index_start:
            index_end = len(data)

        res = []
        for index in range(index_start, index_end):
            start = data[index]["hour"]
            end = data[index + length]["hour"]
            current_total = 0
            for i in range(index, index + length):
                current_total += data[i]["price"]
            Result = namedtuple("Result", "start end total")
            res.append(Result(start, end, round(current_total, self._decimals)))

        res_min = min(res, key=lambda k: k.total)
        res_max = max(res, key=lambda k: k.total)

        return [res_min, res_max]

    async def validate_data(self) -> None:
        """Validate sensor data."""
        _LOGGER.debug("Validating sensor %s", self.name)

        if not self._api.today:
            _LOGGER.debug("No sensor data found - calling update")
            await self._api.update()
            # self._api.today =
            await self._hass.async_add_executor_job(self._format_list, self._api.today)

        if self.tomorrow_valid:
            if not self._api.tomorrow_calculated:
                # self._api.tomorrow =
                await self._hass.async_add_executor_job(
                    self._format_list, self._api.tomorrow, True
                )
            self._tomorrow_raw = self._add_raw(self._api.tomorrow)
        else:
            self._api.tomorrow = None
            self._tomorrow_raw = None
            self._api.tomorrow_calculated = False

        if not self._api.today_calculated:
            await self._hass.async_add_executor_job(self._format_list, self._api.today)

        # Updates price for this hour.
        self._get_current_price()

        # Update attributes
        self._today_raw = self._add_raw(self._api.today)

        self._today_min = self._get_specific("min", self._api.today)
        self._today_max = self._get_specific("max", self._api.today)
        self._tomorrow_min = self._get_specific("min", self._api.tomorrow)
        self._tomorrow_max = self._get_specific("max", self._api.tomorrow)
        self._today_mean = round(
            self._get_specific("mean", self._api.today), self._decimals
        )

        if self.tomorrow_valid:
            self._tomorrow_mean = round(
                self._get_specific("mean", self._api.tomorrow), self._decimals
            )
        else:
            self._tomorrow_mean = None

        cheap_expensive = self._get_cheap_and_expensive_period("6:45:00", 4)
        self._cheap = cheap_expensive[0]
        self._expensive = cheap_expensive[1]

        self.async_write_ha_state()

    def _get_current_price(self) -> None:
        """Get price for current hour"""
        # now = dt_utils.now()
        current_state_time = datetime.fromisoformat(
            dt_utils.now()
            .replace(microsecond=0)
            .replace(second=0)
            .replace(minute=0)
            .isoformat()
        )
        _LOGGER.debug(self._api.today)
        if self._api.today:
            for dataset in self._api.today:
                if dataset.hour == current_state_time:
                    self._state = dataset.price
                    _LOGGER.debug("Current price updated to %f", self._state)
                    break
        else:
            _LOGGER.debug("No data found, can't update _state")

    async def async_added_to_hass(self):
        """Connect to dispatcher listening for entity data notifications."""
        await super().async_added_to_hass()
        _LOGGER.debug("Added sensor '%s'", self._entity_id)
        await self.validate_data()
        async_dispatcher_connect(self._hass, UPDATE_EDS, self.validate_data)

    @property
    def unique_id(self):
        """Return the unique id."""
        return self._unique_id

    @property
    def icon(self) -> str:
        return "mdi:flash"

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._friendly_name

    @property
    def should_poll(self):
        """No need to poll. Coordinator notifies entity of updates."""
        return False

    @property
    def state(self):
        """Return sensor state."""
        return self._state

    @property
    def unit(self) -> str:
        """Return currency unit."""
        return self._price_type

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return {
            "current_price": self.state,
            "unit": self.unit,
            "currency": self._currency,
            "area": self._area,
            "area_code": AREA_MAP[self._area],
            "tomorrow_valid": self.tomorrow_valid,
            "next_data_update": self._api.next_data_refresh,
            "today": self.today,
            "tomorrow": self.tomorrow,
            "raw_today": self.raw_today,
            "raw_tomorrow": self.raw_tomorrow,
            "today_min": self.today_min,
            "today_max": self.today_max,
            "today_mean": self.today_mean,
            "tomorrow_min": self.tomorrow_min,
            "tomorrow_max": self.tomorrow_max,
            "tomorrow_mean": self.tomorrow_mean,
            "cheapest": self._cheap,
            "most_expensive": self._expensive,
        }

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return (
            f"{self.region.currency.cent}/{self._price_type}"
            if self._cent
            else f"{self.region.currency.name}/{self._price_type}"
        )

    @property
    def device_class(self):
        """Return the class of this sensor."""
        return DEVICE_CLASS_MONETARY

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.unique_id)},
            "name": self.name,
            "model": f"Area code: {AREA_MAP[self._area]}",
            "manufacturer": "Energi Data Service",
        }

    @property
    def today(self) -> list:
        """Get todays prices
        Returns:
            list: sorted list where today[0] is the price of hour 00.00 - 01.00
        """

        return [i.price for i in self._api.today if i]

    @property
    def tomorrow(self) -> list:
        """Get tomorrows prices
        Returns:
            list: sorted where tomorrow[0] is the price of hour 00.00 - 01.00 etc.
        """
        if self._api.tomorrow_valid:
            return [i.price for i in self._api.tomorrow if i]
        else:
            return None

    @staticmethod
    def _add_raw(data) -> list:
        lst = []
        for i in data:
            ret = {
                "hour": i.hour,
                "price": i.price,
            }
            lst.append(ret)

        return lst

    @property
    def raw_today(self):
        """Return the raw array with todays prices."""
        return self._today_raw

    @property
    def raw_tomorrow(self):
        """Return the raw array with tomorrows prices."""
        return self._tomorrow_raw

    @property
    def tomorrow_valid(self):
        """Return state of tomorrow_valid."""
        return self._api.tomorrow_valid

    @property
    def today_min(self):
        """Return lowpoint for today."""
        return self._today_min

    @property
    def today_max(self):
        """Return highpoint for today."""
        return self._today_max

    @property
    def tomorrow_min(self):
        """Return lowpoint for tomorrow."""
        return self._tomorrow_min

    @property
    def tomorrow_max(self):
        """Return highpoint for tomorrow."""
        return self._tomorrow_max

    @property
    def today_mean(self):
        """Return mean value for today."""
        return self._today_mean

    @property
    def tomorrow_mean(self):
        """Return mean value for tomorrow."""
        return self._tomorrow_mean

    @property
    def state_class(self) -> SensorStateClass.MEASUREMENT:
        """Return the state class of this entity."""
        return SensorStateClass.MEASUREMENT

    def _calculate(self, value=None, fake_dt=None) -> float:
        """Do price calculations"""
        if value is None:
            value = self._state

        # Convert currency from EUR
        if self._currency != "EUR":
            value = self.region.currency.convert(value, self._currency)

        # Used to inject the current hour.
        # so template can be simplified using now
        if fake_dt is not None:

            def faker():
                def inner(*args, **kwargs):  # type: ignore pylint: disable=unused-argument
                    return fake_dt

                return pass_context(inner)

            template_value = self._cost_template.async_render(now=faker())
        else:
            template_value = self._cost_template.async_render()

        # The api returns prices in MWh
        if self._price_type in ("MWh", "mWh"):
            price = template_value / 1000 + value * float(1 + self._vat)
        else:
            price = template_value + value / UNIT_TO_MULTIPLIER[self._price_type] * (
                float(1 + self._vat)
            )

        if self._cent:
            price = price * CENT_MULTIPLIER

        return round(price, self._decimals)

    def _format_list(self, data, tomorrow=False) -> None:
        """Format data as list with prices localized."""
        formatted_pricelist = []

        _start = datetime.now().timestamp()
        for i in data:
            Interval = namedtuple("Interval", "price hour")
            price = self._calculate(i.price, fake_dt=dt_utils.as_local(i.hour))
            formatted_pricelist.append(Interval(price, i.hour))

        _stop = datetime.now().timestamp()
        _ttf = round(_stop - _start, 2)

        if tomorrow:
            _calc_for = "TOMORROW"
            self._api.tomorrow_calculated = True
            self._api.tomorrow = formatted_pricelist
        else:
            _calc_for = "TODAY"
            self._api.today_calculated = True
            self._api.today = formatted_pricelist

        _LOGGER.debug("Calculation for %s took %s seconds", _calc_for, _ttf)

    @staticmethod
    def _get_specific(datatype: str, data: list):
        """Get specific values - ie. min, max, mean values"""

        if datatype in ["MIN", "Min", "min"]:
            if data:
                res = min(data, key=lambda k: k.price)
                ret = {
                    "hour": res.hour,
                    "price": res.price,
                }

                return ret
            else:
                return None
        elif datatype in ["MAX", "Max", "max"]:
            if data:
                res = max(data, key=lambda k: k.price)
                ret = {
                    "hour": res.hour,
                    "price": res.price,
                }

                return ret
            else:
                return None
        elif datatype in ["MEAN", "Mean", "mean"]:
            if data:
                return mean(data)
            else:
                return None
        else:
            return None
