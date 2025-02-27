"""Define config schema."""
# pylint: disable=dangerous-default-value
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
import voluptuous as vol

from ..const import (
    CONF_AREA,
    CONF_COUNTRY,
    CONF_CURRENCY_IN_CENT,
    CONF_DECIMALS,
    CONF_PRICETYPE,
    CONF_TEMPLATE,
    CONF_VAT,
    UNIT_TO_MULTIPLIER,
)
from .regionhandler import RegionHandler

_LOGGER = logging.getLogger(__name__)


def list_to_str(data: list[Any]) -> str:
    """Convert an int list to a string."""
    return " ".join([str(i) for i in data])


def energidataservice_config_option_info_schema(options: ConfigEntry = {}) -> dict:
    """Return a schema for info configuration options."""
    _LOGGER.debug(options.get(CONF_AREA))
    info_options = {
        CONF_NAME: options.get(CONF_NAME),
        CONF_COUNTRY: (
            options.get(CONF_COUNTRY)
            or RegionHandler.country_from_region(options.get(CONF_AREA))
        )
        or RegionHandler.country_from_region(
            RegionHandler.description_to_region(options.get(CONF_AREA))
        )
        or None,
        CONF_AREA: options.get(CONF_AREA) or None,
        CONF_CURRENCY_IN_CENT: options.get(CONF_CURRENCY_IN_CENT) or False,
        CONF_DECIMALS: options.get(CONF_DECIMALS) or 3,
        CONF_PRICETYPE: options.get(CONF_PRICETYPE) or "kWh",
        CONF_TEMPLATE: options.get(CONF_TEMPLATE) or "",
        CONF_VAT: options.get(CONF_VAT) or True,
    }

    schema = {
        vol.Required(CONF_AREA, default=info_options.get(CONF_AREA)): vol.In(
            RegionHandler.get_regions(info_options.get(CONF_COUNTRY), True)
        ),
        vol.Required(CONF_VAT, default=info_options.get(CONF_VAT)): bool,
        vol.Required(
            CONF_CURRENCY_IN_CENT,
            default=info_options.get(CONF_CURRENCY_IN_CENT) or False,
        ): bool,
        vol.Optional(
            CONF_DECIMALS, default=info_options.get(CONF_DECIMALS)
        ): vol.Coerce(int),
        vol.Optional(CONF_PRICETYPE, default=info_options.get(CONF_PRICETYPE)): vol.In(
            list(UNIT_TO_MULTIPLIER.keys())
        ),
        vol.Optional(CONF_TEMPLATE, default=info_options.get(CONF_TEMPLATE)): str,
    }

    _LOGGER.debug("Schema: %s", schema)
    return schema


def energidataservice_config_option_initial_schema(options: ConfigEntry = {}) -> dict:
    """Return a shcema for initial configuration options."""
    if not options:
        options = {
            CONF_NAME: "Energi Data Service",
            CONF_COUNTRY: None,
        }

    schema = {
        vol.Optional(CONF_NAME, default=options.get(CONF_NAME)): str,
        vol.Required(CONF_COUNTRY, default=options.get(CONF_COUNTRY)): vol.In(
            RegionHandler.get_countries(True)
        ),
    }

    _LOGGER.debug("Schema: %s", schema)
    return schema
