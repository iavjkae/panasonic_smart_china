import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from .api import PanasonicApiClient
from .const import (
    CONF_CATEGORY,
    CONF_CONTROLLER_MODEL,
    CONF_DEVICE_ID,
    CONF_DEVICES,
    CONF_ENABLED,
    CONF_PROFILE_ID,
    CONF_SSID,
    CONF_USR_ID,
    DOMAIN,
)
from .coordinator import PanasonicDeviceCoordinator
from .profiles import find_profile_for_device_config, supported_platforms

_LOGGER = logging.getLogger(__name__)

PLATFORMS = list(supported_platforms())


def _async_create_account_device(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """Create the account service device and return its registry id."""
    account_id = entry.unique_id or entry.data.get(CONF_USR_ID)
    if not account_id:
        _LOGGER.warning("No account id available; account device was not created")
        return None

    account_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, str(account_id))},
        name=entry.title,
        manufacturer="Panasonic",
        model="Smart China",
        entry_type=dr.DeviceEntryType.SERVICE,
    )
    return account_device.id


async def async_setup(hass: HomeAssistant, config: dict):
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    hass.data.setdefault(DOMAIN, {})

    # Register the account before forwarding platforms so every appliance can
    # reference an existing parent by its device-registry id.
    account_device_id = _async_create_account_device(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = {
        "client": PanasonicApiClient(hass, entry.data.get(CONF_SSID)),
        "account_device_id": account_device_id,
        "coordinators": {},
    }

    runtime = hass.data[DOMAIN][entry.entry_id]
    try:
        for device_id, config in entry.data.get(CONF_DEVICES, {}).items():
            if not config.get(CONF_ENABLED, True):
                continue
            profile = find_profile_for_device_config(
                profile_id=config.get(CONF_PROFILE_ID),
                controller_model=config.get(CONF_CONTROLLER_MODEL),
                category_id=config.get(CONF_CATEGORY),
            )
            if not profile or not profile.build_control_payload:
                continue
            coordinator = PanasonicDeviceCoordinator(
                hass,
                entry,
                runtime["client"],
                profile,
                {**entry.data, **config, CONF_DEVICE_ID: device_id},
                account_device_id,
            )
            runtime["coordinators"][device_id] = coordinator
            try:
                await coordinator.async_config_entry_first_refresh()
            except ConfigEntryNotReady as err:
                # A transient failure of one appliance must not prevent the
                # other devices in this account from loading. Its coordinator
                # remains unavailable and retries through normal polling.
                _LOGGER.warning("Initial status unavailable for %s: %s", device_id, err)

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except (Exception, asyncio.CancelledError):
        for coordinator in runtime["coordinators"].values():
            await coordinator.async_shutdown()
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        for coordinator in runtime.get("coordinators", {}).values():
            await coordinator.async_shutdown()
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok
