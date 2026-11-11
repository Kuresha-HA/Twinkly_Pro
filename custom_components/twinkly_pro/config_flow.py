"""Config flow for Twinkly Pro integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import zeroconf
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_CLOUD_EMAIL,
    CONF_CLOUD_PASSWORD,
    CONF_DEVICE_NAME,
    CONF_ENABLE_PANEL,
    CONF_HOST,
    CONF_HW_ID,
    CONF_LED_PROFILE,
    CONF_MAC,
    CONF_NUM_LEDS,
    CONF_PRODUCT_CODE,
    DOMAIN,
)
from .twinkly_client import GestaltInfo, TwinklyClient, TwinklyError

_LOGGER = logging.getLogger(__name__)


class TwinklyProConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Twinkly Pro."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_host: str | None = None
        self._discovered_gestalt: GestaltInfo | None = None

    async def _async_probe_device(self, host: str) -> GestaltInfo:
        """Connect to a Twinkly device and fetch its Gestalt hardware info."""
        session = async_get_clientsession(self.hass)
        client = TwinklyClient(host=host, session=session)
        gestalt = await client.get_gestalt(force_refresh=True)
        await client.authenticate()
        return gestalt

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step where the user enters the device IP or hostname."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = str(user_input[CONF_HOST]).strip()
            try:
                gestalt = await self._async_probe_device(host)
            except TwinklyError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error probing Twinkly at %s", host)
                errors["base"] = "unknown"
            else:
                unique_id = gestalt.mac or gestalt.uuid or host
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})

                title = f"{gestalt.device_name} ({gestalt.number_of_led} LED)"
                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_HOST: host,
                        CONF_MAC: gestalt.mac,
                        CONF_DEVICE_NAME: gestalt.device_name,
                        CONF_PRODUCT_CODE: gestalt.product_code,
                        CONF_HW_ID: gestalt.hw_id,
                        CONF_LED_PROFILE: gestalt.led_profile,
                        CONF_NUM_LEDS: gestalt.number_of_led,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_zeroconf(
        self, discovery_info: zeroconf.ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle Zeroconf auto-discovery of _xled._tcp.local. devices."""
        host = discovery_info.host
        if not host:
            return self.async_abort(reason="cannot_connect")

        try:
            gestalt = await self._async_probe_device(host)
        except Exception:
            return self.async_abort(reason="cannot_connect")

        unique_id = gestalt.mac or gestalt.uuid or host
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        self._discovered_host = host
        self._discovered_gestalt = gestalt
        self.context["title_placeholders"] = {
            "name": f"{gestalt.device_name} ({host})"
        }
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm adding a Zeroconf-discovered Twinkly device."""
        if not self._discovered_host or not self._discovered_gestalt:
            return self.async_abort(reason="cannot_connect")

        gestalt = self._discovered_gestalt
        host = self._discovered_host

        if user_input is not None:
            title = f"{gestalt.device_name} ({gestalt.number_of_led} LED)"
            return self.async_create_entry(
                title=title,
                data={
                    CONF_HOST: host,
                    CONF_MAC: gestalt.mac,
                    CONF_DEVICE_NAME: gestalt.device_name,
                    CONF_PRODUCT_CODE: gestalt.product_code,
                    CONF_HW_ID: gestalt.hw_id,
                    CONF_LED_PROFILE: gestalt.led_profile,
                    CONF_NUM_LEDS: gestalt.number_of_led,
                },
            )

        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders={
                "name": gestalt.device_name,
                "host": host,
                "model": gestalt.product_code,
                "leds": str(gestalt.number_of_led),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> TwinklyProOptionsFlowHandler:
        """Get the options flow for this handler."""
        return TwinklyProOptionsFlowHandler(config_entry)


class TwinklyProOptionsFlowHandler(OptionsFlow):
    """Handle options for Twinkly Pro (Cloud credentials & Twinkly Studio panel)."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the Twinkly Pro options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self._config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_ENABLE_PANEL,
                    default=options.get(CONF_ENABLE_PANEL, True),
                ): bool,
                vol.Optional(
                    CONF_CLOUD_EMAIL,
                    default=options.get(CONF_CLOUD_EMAIL, ""),
                ): str,
                vol.Optional(
                    CONF_CLOUD_PASSWORD,
                    default=options.get(CONF_CLOUD_PASSWORD, ""),
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
