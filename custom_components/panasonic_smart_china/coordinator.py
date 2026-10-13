"""Shared polling and serialized control for multi-entity device profiles."""

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import PanasonicApiAuthError, PanasonicApiClient, PanasonicApiError
from .const import (
    CONF_DEVICE_ID,
    CONF_DEVICE_MODEL,
    CONF_DEVICE_NAME,
    CONF_TOKEN,
    CONF_USR_ID,
)
from .models import PanasonicProfile, PanasonicSelectCapability, status_int

_LOGGER = logging.getLogger(__name__)


class PanasonicDeviceCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """One state source and command lock for one appliance."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: PanasonicApiClient,
        profile: PanasonicProfile,
        config: dict[str, Any],
        account_device_id: str | None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"Panasonic {config[CONF_DEVICE_ID]}",
            config_entry=entry,
            update_interval=timedelta(seconds=15),
        )
        self.client = client
        self.entry = entry
        self.profile = profile
        self.device_id = config[CONF_DEVICE_ID]
        self.device_name = config.get(CONF_DEVICE_NAME, self.device_id)
        self.model = config.get(CONF_DEVICE_MODEL) or profile.controller_model
        self.usr_id = config[CONF_USR_ID]
        self.token = config[CONF_TOKEN]
        self.account_device_id = account_device_id
        self._command_lock = asyncio.Lock()
        self.last_active_mode = profile.hvac_mapping[profile.default_hvac_mode]

    @property
    def online(self) -> bool:
        if (
            self._shutdown_requested
            or not self.last_update_success
            or self.data is None
        ):
            return False
        field = self.profile.offline_field
        return not field or status_int(self.data.get(field)) != 1

    @property
    def mode(self) -> int | None:
        return status_int((self.data or {}).get(self.profile.mode_field))

    def capability_available(self, capability: PanasonicSelectCapability) -> bool:
        return self.online and bool(capability.options_for_mode(self.mode))

    async def _read_status(self) -> dict[str, Any]:
        try:
            status = await self.client.get_device_status(
                self.profile,
                self.usr_id,
                self.device_id,
                self.token,
            )
        except PanasonicApiAuthError as err:
            raise ConfigEntryAuthFailed("Panasonic session expired") from err
        except PanasonicApiError as err:
            raise UpdateFailed(str(err)) from err
        mode = status_int(status.get(self.profile.mode_field))
        if mode in self.profile.active_modes:
            self.last_active_mode = mode
        return status

    async def _async_update_data(self) -> dict[str, Any]:
        async with self._command_lock:
            self._ensure_poll_active()
            try:
                status = await self._read_status()
            except (UpdateFailed, ConfigEntryAuthFailed):
                self._ensure_poll_active()
                raise
            self._ensure_poll_active()
            return status

    def _ensure_poll_active(self) -> None:
        if self._shutdown_requested:
            # HA handles a cancelled poll without publishing data or starting
            # reauth. Its initial shutdown check precedes our lock/network
            # waits, so we must check again when those waits finish.
            raise asyncio.CancelledError

    def _ensure_control_active(self) -> None:
        if self._shutdown_requested:
            raise HomeAssistantError("The Panasonic device has been unloaded")

    def _mark_control_error(self, err: Exception) -> None:
        # An obsolete coordinator must not update entities or start reauth
        # after a reload while an old cloud request is still finishing.
        self._ensure_control_active()
        self.async_set_update_error(err)
        if isinstance(err, ConfigEntryAuthFailed):
            self.entry.async_start_reauth(self.hass)

    async def _async_prepare_control(self) -> dict[str, Any]:
        """Read fresh parameters without publishing old cloud state before a write."""
        self._ensure_control_active()
        try:
            status = await self._read_status()
        except (UpdateFailed, ConfigEntryAuthFailed) as err:
            self._mark_control_error(err)
            if isinstance(err, ConfigEntryAuthFailed):
                raise
            raise HomeAssistantError(f"Cannot read device status: {err}") from err
        self._ensure_control_active()
        offline_field = self.profile.offline_field
        if offline_field and status_int(status.get(offline_field)) == 1:
            self.async_set_updated_data(status)
            raise HomeAssistantError("The Panasonic device is offline")
        if any(
            status_int(status.get(key)) in values
            for key, values in self.profile.control_blockers.items()
        ):
            self.async_set_updated_data(status)
            raise HomeAssistantError("The device is temporarily blocking control")
        return status

    async def _async_send_control(
        self,
        changes: dict[str, Any],
        status: dict[str, Any],
    ) -> None:
        """Publish accepted controls under the caller's lock, as legacy entities do."""
        try:
            control_payload = self.profile.build_control_payload(changes, status)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        try:
            await self.client.set_device_status(
                self.profile,
                self.usr_id,
                self.device_id,
                self.token,
                control_payload,
            )
        except PanasonicApiAuthError as err:
            auth_error = ConfigEntryAuthFailed("Panasonic session expired")
            self._mark_control_error(auth_error)
            raise auth_error from err
        except PanasonicApiError as err:
            raise HomeAssistantError(f"Panasonic control failed: {err}") from err
        self._ensure_control_active()
        # Match the existing heater: acceptance updates controls immediately;
        # normal polling later reconciles device execution. Skip values mean
        # "leave unchanged", so they must never replace real status fields.
        updated_status = {
            **status,
            **{
                key: value
                for key, value in control_payload.items()
                if value != self.profile.control_skip_value
            },
        }
        mode = status_int(updated_status.get(self.profile.mode_field))
        if mode in self.profile.active_modes:
            self.last_active_mode = mode
        self.async_set_updated_data(updated_status)

    async def async_control(self, changes: dict[str, Any]) -> None:
        """Serialize reading, validation, writing and the accepted-state update."""
        async with self._command_lock:
            status = await self._async_prepare_control()
            await self._async_send_control(changes, status)

    async def async_set_mode(self, mode: int) -> None:
        """Avoid restoring mode memory over a running countdown on repeated calls."""
        if mode not in self.profile.hvac_mapping.values():
            raise HomeAssistantError(f"Unsupported device mode: {mode}")
        async with self._command_lock:
            status = await self._async_prepare_control()
            # Compare fresh state under the lock: App actions and queued HA
            # controls can both change the mode since the last periodic poll.
            if status_int(status.get(self.profile.mode_field)) == mode:
                self.async_set_updated_data(status)
                return
            await self._async_send_control({self.profile.mode_field: mode}, status)

    async def async_turn_on(self) -> None:
        """Restore the latest active mode without restarting a running device."""
        async with self._command_lock:
            status = await self._async_prepare_control()
            if (
                status_int(status.get(self.profile.mode_field))
                in self.profile.active_modes
            ):
                self.async_set_updated_data(status)
                return
            await self._async_send_control(
                {self.profile.mode_field: self.last_active_mode},
                status,
            )

    async def async_select(
        self, capability: PanasonicSelectCapability, option: str
    ) -> None:
        if option not in capability.options:
            raise HomeAssistantError(f"Unsupported option: {option}")
        if capability.field == self.profile.mode_field:
            await self.async_set_mode(capability.options[option])
            return
        # The profile validates modes/options again using fresh state inside the lock.
        await self.async_control({capability.field: capability.options[option]})
