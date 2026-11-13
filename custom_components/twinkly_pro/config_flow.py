"""Config flow for Twinkly Pro integration (Cloud -> Auto-Discovery -> Optional Manual IP)."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import dhcp, zeroconf
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_ADD_MANUAL_IP,
    CONF_CLOUD_EMAIL,
    CONF_CLOUD_PASSWORD,
    CONF_COMPOSITION_NAME,
    CONF_DEVICE_NAME,
    CONF_ENABLE_PANEL,
    CONF_GROUP_UID,
    CONF_HOST,
    CONF_HW_ID,
    CONF_LED_PROFILE,
    CONF_MAC,
    CONF_NUM_LEDS,
    CONF_PRODUCT_CODE,
    CONF_SCENE_NAME,
    CONF_SELECTED_DEVICES,
    CONF_SKIP_CLOUD,
    CONF_SKIP_MANUAL,
    DOMAIN,
)
from .twinkly_client import (
    DiscoveredTwinklyDevice,
    GestaltInfo,
    TwinklyClient,
    TwinklyCloudClient,
    TwinklyError,
    async_probe_discovered_host,
)

_LOGGER = logging.getLogger(__name__)


class TwinklyProConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a multi-step config flow for Twinkly Pro."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow state."""
        self._cloud_email: str = ""
        self._cloud_password: str = ""
        self._cloud_authenticated: bool = False
        self._discovered_devices: dict[str, DiscoveredTwinklyDevice] = {}
        self._queued_devices: list[DiscoveredTwinklyDevice] = []
        self._scenes_summary: str = ""
        self._compositions_summary: str = ""

        # For single zeroconf/dhcp background discovery
        self._single_discovered: DiscoveredTwinklyDevice | None = None

    def _get_configured_ids_and_hosts(self) -> tuple[set[str], set[str]]:
        """Return sets of already-configured unique_ids and hosts."""
        configured_ids: set[str] = set()
        configured_hosts: set[str] = set()
        for entry in self._async_current_entries():
            if entry.unique_id:
                configured_ids.add(entry.unique_id.lower())
            if entry.data.get(CONF_MAC):
                configured_ids.add(str(entry.data[CONF_MAC]).lower())
            if entry.data.get(CONF_HOST):
                configured_hosts.add(str(entry.data[CONF_HOST]).lower())
        return configured_ids, configured_hosts

    def _build_entry_data(self, dev: DiscoveredTwinklyDevice) -> dict[str, Any]:
        """Build ConfigEntry data dict from a DiscoveredTwinklyDevice."""
        return {
            CONF_HOST: dev.host,
            CONF_MAC: dev.mac,
            CONF_DEVICE_NAME: dev.name,
            CONF_PRODUCT_CODE: dev.product_code,
            CONF_HW_ID: "",
            CONF_LED_PROFILE: dev.led_profile,
            CONF_NUM_LEDS: dev.number_of_led,
            CONF_SCENE_NAME: dev.scene_name,
            CONF_COMPOSITION_NAME: dev.composition_name,
            CONF_GROUP_UID: dev.group_uid,
            CONF_CLOUD_EMAIL: self._cloud_email,
            CONF_CLOUD_PASSWORD: self._cloud_password,
        }

    def _build_entry_title(self, dev: DiscoveredTwinklyDevice) -> str:
        """Build a descriptive ConfigEntry title including composition or LED count."""
        title = dev.name
        if dev.composition_name and dev.composition_name != dev.name:
            title = f"{dev.name} [{dev.composition_name}]"
        if dev.number_of_led:
            title = f"{title} ({dev.number_of_led} LED)"
        return title

    async def _async_finalize_selected_devices(
        self, devices: list[DiscoveredTwinklyDevice]
    ) -> ConfigFlowResult:
        """Create ConfigEntry for the first device and spawn background import flows for the rest."""
        if not devices:
            return self.async_abort(reason="no_devices_selected")

        primary = devices[0]
        remaining = devices[1:]

        for extra_dev in remaining:
            self.hass.async_create_task(
                self.hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={"source": "import_batch"},
                    data=self._build_entry_data(extra_dev),
                )
            )

        await self.async_set_unique_id(primary.unique_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: primary.host})

        return self.async_create_entry(
            title=self._build_entry_title(primary),
            data=self._build_entry_data(primary),
        )

    # -------------------------------------------------------------------------
    # STEP 1: Twinkly Cloud Login (Default initial step, skippable)
    # -------------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: Prompt for Twinkly Cloud credentials (with option to skip)."""
        if user_input is not None:
            skip_cloud = bool(user_input.get(CONF_SKIP_CLOUD, False))
            email = str(user_input.get(CONF_CLOUD_EMAIL, "")).strip()
            password = str(user_input.get(CONF_CLOUD_PASSWORD, "")).strip()

            if not skip_cloud and email and password:
                self._cloud_email = email
                self._cloud_password = password
            else:
                self._cloud_email = ""
                self._cloud_password = ""

            session = async_get_clientsession(self.hass)
            cloud_client = TwinklyCloudClient(session=session)
            account_res = await cloud_client.async_discover_account_and_lan(
                email=self._cloud_email,
                password=self._cloud_password,
            )
            self._cloud_authenticated = account_res.authenticated
            self._scenes_summary = (
                ", ".join(account_res.scenes) if account_res.scenes else "По умолчанию"
            )
            self._compositions_summary = (
                ", ".join(account_res.compositions.values())
                if account_res.compositions
                else "Нет активных групп"
            )

            configured_ids, configured_hosts = self._get_configured_ids_and_hosts()
            self._discovered_devices = {}
            for dev in account_res.devices:
                if (
                    dev.unique_id not in configured_ids
                    and dev.host.lower() not in configured_hosts
                ):
                    self._discovered_devices[dev.unique_id] = dev

            return await self.async_step_discovery_select()

        schema = vol.Schema(
            {
                vol.Optional(CONF_CLOUD_EMAIL, default=""): str,
                vol.Optional(CONF_CLOUD_PASSWORD, default=""): str,
                vol.Optional(CONF_SKIP_CLOUD, default=False): bool,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
        )

    # -------------------------------------------------------------------------
    # STEP 2: Select discovered devices, scenes & compositions
    # -------------------------------------------------------------------------

    async def async_step_discovery_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: Display devices, scenes, and compositions found via Cloud & LAN UDP 5555."""
        if not self._discovered_devices:
            # No unconfigured devices responded automatically -> move to optional Manual IP step
            return await self.async_step_manual()

        if user_input is not None:
            selected_keys: list[str] = user_input.get(CONF_SELECTED_DEVICES, [])
            add_manual: bool = bool(user_input.get(CONF_ADD_MANUAL_IP, False))

            self._queued_devices = [
                self._discovered_devices[k]
                for k in selected_keys
                if k in self._discovered_devices
            ]

            if add_manual or not self._queued_devices:
                return await self.async_step_manual()

            return await self._async_finalize_selected_devices(self._queued_devices)

        device_options = {
            uid: dev.display_label for uid, dev in self._discovered_devices.items()
        }
        default_selected = list(device_options.keys())

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SELECTED_DEVICES,
                    default=default_selected,
                ): cv.multi_select(device_options),
                vol.Optional(CONF_ADD_MANUAL_IP, default=False): bool,
            }
        )

        cloud_status = (
            f"Подключен ({self._cloud_email})"
            if self._cloud_email
            else "Пропущен (локальное сканирование)"
        )

        return self.async_show_form(
            step_id="discovery_select",
            data_schema=schema,
            description_placeholders={
                "count": str(len(device_options)),
                "cloud_status": cloud_status,
                "scenes": self._scenes_summary or "По умолчанию",
                "compositions": self._compositions_summary or "Отдельные устройства",
            },
        )

    # -------------------------------------------------------------------------
    # STEP 3: Manual IP Addition (Optional, skippable)
    # -------------------------------------------------------------------------

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 3: Optional manual addition by IP address (can be skipped)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            skip_manual = bool(user_input.get(CONF_SKIP_MANUAL, False))
            host = str(user_input.get(CONF_HOST, "")).strip()

            if skip_manual or not host:
                if self._queued_devices:
                    return await self._async_finalize_selected_devices(
                        self._queued_devices
                    )
                return self.async_abort(reason="manual_skipped")

            session = async_get_clientsession(self.hass)
            probed = await async_probe_discovered_host(host=host, session=session)
            if not probed:
                errors["base"] = "cannot_connect"
            else:
                self._queued_devices.append(probed)
                return await self._async_finalize_selected_devices(
                    self._queued_devices
                )

        schema = vol.Schema(
            {
                vol.Optional(CONF_HOST, default=""): str,
                vol.Optional(CONF_SKIP_MANUAL, default=False): bool,
            }
        )
        return self.async_show_form(
            step_id="manual",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "queued_count": str(len(self._queued_devices)),
            },
        )

    # -------------------------------------------------------------------------
    # Background batch import & Zeroconf / DHCP auto-discovery
    # -------------------------------------------------------------------------

    async def async_step_import_batch(
        self, import_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle automatic creation of additional selected devices from Step 2."""
        mac = str(import_data.get(CONF_MAC, "")).lower()
        host = str(import_data.get(CONF_HOST, ""))
        unique_id = mac or host
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        name = str(import_data.get(CONF_DEVICE_NAME, "Twinkly"))
        leds = int(import_data.get(CONF_NUM_LEDS, 0))
        comp = str(import_data.get(CONF_COMPOSITION_NAME, ""))
        title = f"{name} [{comp}]" if comp and comp != name else name
        if leds:
            title = f"{title} ({leds} LED)"

        return self.async_create_entry(title=title, data=import_data)

    async def _async_handle_network_discovery(
        self, host: str
    ) -> ConfigFlowResult:
        """Common handler for Zeroconf and DHCP network discovery."""
        if not host:
            return self.async_abort(reason="cannot_connect")

        session = async_get_clientsession(self.hass)
        probed = await async_probe_discovered_host(host=host, session=session)
        if not probed:
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(probed.unique_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        self._single_discovered = probed
        self.context["title_placeholders"] = {
            "name": f"{probed.name} ({probed.number_of_led} LED)"
        }
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf(
        self, discovery_info: zeroconf.ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle Zeroconf auto-discovery of _xled._tcp.local. devices."""
        return await self._async_handle_network_discovery(discovery_info.host)

    async def async_step_dhcp(
        self, discovery_info: dhcp.DhcpServiceInfo
    ) -> ConfigFlowResult:
        """Handle DHCP auto-discovery of Twinkly devices on the local network."""
        return await self._async_handle_network_discovery(discovery_info.ip)

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm adding a Zeroconf/DHCP-discovered Twinkly device in 1 click."""
        if not self._single_discovered:
            return self.async_abort(reason="cannot_connect")

        dev = self._single_discovered
        if user_input is not None:
            return self.async_create_entry(
                title=self._build_entry_title(dev),
                data=self._build_entry_data(dev),
            )

        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders={
                "name": dev.name,
                "host": dev.host,
                "model": dev.product_code or "Twinkly",
                "leds": str(dev.number_of_led),
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
        data = self._config_entry.data
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_ENABLE_PANEL,
                    default=options.get(CONF_ENABLE_PANEL, True),
                ): bool,
                vol.Optional(
                    CONF_CLOUD_EMAIL,
                    default=options.get(
                        CONF_CLOUD_EMAIL, data.get(CONF_CLOUD_EMAIL, "")
                    ),
                ): str,
                vol.Optional(
                    CONF_CLOUD_PASSWORD,
                    default=options.get(
                        CONF_CLOUD_PASSWORD, data.get(CONF_CLOUD_PASSWORD, "")
                    ),
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
