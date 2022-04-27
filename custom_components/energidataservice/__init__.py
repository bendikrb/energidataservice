"""Adds support for Energi Data Service spot prices."""
from datetime import datetime, timedelta
from functools import partial
import logging
from random import randint

import aiohttp
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_time_change
from homeassistant.loader import async_get_integration
from pytz import timezone
import voluptuous as vol

from .api import Energidataservice
from .const import AREA_MAP, CONF_AREA, DOMAIN, STARTUP, UPDATE_EDS

RANDOM_MINUTE = randint(0, 10)
RANDOM_SECOND = randint(0, 59)

RETRY_MINUTES = 10
MAX_RETRY_MINUTES = 120

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the component."""

    hass.data.setdefault(DOMAIN, {})

    if DOMAIN not in config:
        return True

    for conf in config[DOMAIN]:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_IMPORT},
                data=conf,
            )
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Energi Data Service from a config entry."""
    _LOGGER.debug("Entry data: %s", entry.data)
    _LOGGER.debug("Entry options: %s", entry.options)
    result = await _setup(hass, entry)

    hass.async_create_task(
        hass.config_entries.async_forward_entry_setup(entry, "sensor")
    )

    return result


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_forward_entry_unload(entry, "sensor")

    if unload_ok:
        for unsub in hass.data[DOMAIN][entry.entry_id].listeners:
            unsub()
        hass.data[DOMAIN].pop(entry.entry_id)

        return True

    return False


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


async def _setup(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Setup the integration using a config entry."""
    integration = await async_get_integration(hass, DOMAIN)
    _LOGGER.info(STARTUP, integration.version)

    api = EDSConnector(
        hass,
        AREA_MAP[(entry.options.get(CONF_AREA) or entry.data.get(CONF_AREA))],
        entry.entry_id,
    )
    hass.data[DOMAIN][entry.entry_id] = api

    async def new_day(n):  # type: ignore pylint: disable=unused-argument, invalid-name
        """Handle data on new day."""
        _LOGGER.debug("New day function called")
        api.today = api.tomorrow
        api.tomorrow = None
        api._tomorrow_valid = False  # pylint: disable=protected-access
        api.tomorrow_calculated = False
        async_dispatcher_send(hass, UPDATE_EDS)

    async def new_hour(n):  # type: ignore pylint: disable=unused-argument, invalid-name
        """Callback to tell the sensors to update on a new hour."""
        _LOGGER.debug("New hour, updating state")
        async_dispatcher_send(hass, UPDATE_EDS)

    async def get_new_data(n):  # type: ignore pylint: disable=unused-argument, invalid-name
        """Fetch new data for tomorrows prices at 13:00ish CET."""
        _LOGGER.debug("Getting latest dataset")
        await api.update()
        async_dispatcher_send(hass, UPDATE_EDS)

    # Handle dataset updates
    update_tomorrow = async_track_time_change(
        hass,
        get_new_data,
        hour=13,
        minute=RANDOM_MINUTE,
        second=RANDOM_SECOND,
    )

    update_new_day = async_track_time_change(
        hass,
        new_day,
        hour=0,
        minute=0,
        second=0,
    )

    update_new_hour = async_track_time_change(hass, new_hour, minute=0, second=0)

    api.listeners.append(update_tomorrow)
    api.listeners.append(update_new_hour)
    api.listeners.append(update_new_day)

    return True


class EDSConnector:
    """An object to store Energi Data Service data."""

    def __init__(self, hass, area, entry_id):
        """Initialize Energi Data Service Connector."""
        self._hass = hass
        self._last_tick = None
        self._tomorrow_valid = False
        self._entry_id = entry_id

        self.today = None
        self.tomorrow = None
        self.today_calculated = False
        self.tomorrow_calculated = False
        self.listeners = []

        self._next_retry_delay = RETRY_MINUTES
        self._retry_count = 0

        client = async_get_clientsession(hass)
        self._eds = Energidataservice(area, client, hass.config.time_zone)
        _LOGGER.debug("Initializing Energi Data Service for area %s", area)

    async def update(self, dt=None):  # type: ignore pylint: disable=unused-argument,invalid-name
        """Fetch latest prices from Energi Data Service API"""
        eds = self._eds

        try:
            await eds.get_spotprices()
            self.today = eds.today
            self.tomorrow = eds.tomorrow

            self.today_calculated = False
            self.tomorrow_calculated = False

            if not self.tomorrow:
                self._tomorrow_valid = False
                self.tomorrow = None

                midnight = datetime.strptime("23:59:59", "%H:%M:%S")
                refresh = datetime.strptime(self.next_data_refresh, "%H:%M:%S")
                local_tz = timezone(self._hass.config.time_zone)
                now = datetime.now().astimezone(local_tz)
                _LOGGER.debug(
                    "Now: %s:%s:%s",
                    f"{now.hour:02d}",
                    f"{now.minute:02d}",
                    f"{now.second:02d}",
                )
                _LOGGER.debug(
                    "Refresh: %s:%s:%s",
                    f"{refresh.hour:02d}",
                    f"{refresh.minute:02d}",
                    f"{refresh.second:02d}",
                )
                if (
                    f"{midnight.hour}:{midnight.minute}:{midnight.second}"
                    > f"{now.hour:02d}:{now.minute:02d}:{now.second:02d}"
                    and f"{refresh.hour:02d}:{refresh.minute:02d}:{refresh.second:02d}"
                    < f"{now.hour:02d}:{now.minute:02d}:{now.second:02d}"
                ):
                    retry_update(self)
                else:
                    _LOGGER.debug(
                        "Not forcing refresh, as we are past midnight and haven't reached next update time"  # pylint: disable=line-too-long
                    )
            else:
                self._retry_count = 0
                self._tomorrow_valid = True
        except aiohttp.client_exceptions.ServerDisconnectedError:
            _LOGGER.warning("Server disconnected.")
            retry_update(self)

    @property
    def tomorrow_valid(self):
        """Is tomorrows prices valid?"""
        return self._tomorrow_valid

    @property
    def next_data_refresh(self):
        """When is next data update?"""
        return f"13:{RANDOM_MINUTE:02d}:{RANDOM_SECOND:02d}"

    @property
    def entry_id(self):
        """Return entry_id."""
        return self._entry_id


def retry_update(self):
    """Retry update on error."""
    self._retry_count += 1
    self._next_retry_delay = RETRY_MINUTES * self._retry_count
    if self._next_retry_delay > MAX_RETRY_MINUTES:
        self._next_retry_delay = MAX_RETRY_MINUTES

    _LOGGER.warning(
        "Couldn't get data from Energi Data Service, retrying in %s minutes.",
        self._next_retry_delay,
    )

    local_tz = timezone(self._hass.config.time_zone)
    now = (datetime.now() + timedelta(minutes=self._next_retry_delay)).astimezone(
        local_tz
    )
    _LOGGER.debug(
        "Next retry: %s:%s:%s",
        f"{now.hour:02d}",
        f"{now.minute:02d}",
        f"{now.second:02d}",
    )
    async_call_later(
        self._hass,
        timedelta(minutes=self._next_retry_delay),
        partial(self.update),
    )
