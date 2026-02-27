"""Config flow for the Colmi R09 Smart Ring integration.

Supports:
  1. Automatic Bluetooth discovery (triggered by the ``bluetooth`` manifest entry)
  2. Manual entry of the ring's MAC address
  3. Options flow to change the polling interval after initial setup
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Minimum / maximum polling interval in minutes
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 60


class ColmiR09ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise the flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, str] = {}  # address -> name

    # ------------------------------------------------------------------
    # Bluetooth auto-discovery (triggered by manifest bluetooth entry)
    # ------------------------------------------------------------------

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle a device discovered via Bluetooth."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm the Bluetooth-discovered device."""
        assert self._discovery_info is not None

        if user_input is not None:
            return self.async_create_entry(
                title=self._discovery_info.name,
                data={
                    CONF_ADDRESS: self._discovery_info.address,
                    CONF_NAME: self._discovery_info.name,
                },
            )

        # Show an empty confirmation form (no _set_confirm_only() needed)
        placeholders = {"name": self._discovery_info.name}
        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=vol.Schema({}),
            description_placeholders=placeholders,
        )

    # ------------------------------------------------------------------
    # Manual entry flow (user goes to Add Integration -> Colmi R09)
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step shown when user manually adds integration.

        First, scan for nearby R09 devices. If found, show a picker.
        If none found, fall back to manual MAC entry.
        """
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper()
            dev_name = self._discovered_devices.get(address, f"Colmi R09 ({address})")

            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=dev_name,
                data={
                    CONF_ADDRESS: address,
                    CONF_NAME: dev_name,
                },
            )

        # Gather any already-discovered R09 service info from HA BT cache
        current_addresses = self._async_current_ids()
        for service_info in async_discovered_service_info(self.hass, connectable=True):
            if service_info.address in current_addresses:
                continue
            # Guard against devices with no name
            if service_info.name and "R09" in service_info.name.upper():
                self._discovered_devices[service_info.address] = service_info.name

        if self._discovered_devices:
            # Build select options: "R09_0803 (30:38:47:31:08:03)"
            options = {
                addr: f"{dev_name} ({addr})"
                for addr, dev_name in self._discovered_devices.items()
            }
            schema = vol.Schema(
                {vol.Required(CONF_ADDRESS): vol.In(options)}
            )
        else:
            # No devices found -- allow manual address entry
            schema = vol.Schema(
                {vol.Required(CONF_ADDRESS): str}
            )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors={},
        )

    # ------------------------------------------------------------------
    # Options flow (change polling interval after setup)
    # ------------------------------------------------------------------

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "ColmiR09OptionsFlow":
        """Return the options flow handler."""
        return ColmiR09OptionsFlow(config_entry)


class ColmiR09OptionsFlow(config_entries.OptionsFlow):
    """Handle the options flow for changing the polling interval."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialise."""
        # Store the entry; HA also exposes it via self.config_entry in newer versions
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show the options form."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=current_interval,
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    )
                }
            ),
        )
