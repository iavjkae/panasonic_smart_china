"""Tests use real HA classes and a fake cloud client; never contact appliances."""

from types import MappingProxyType
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.panasonic_smart_china.coordinator import (
    PanasonicDeviceCoordinator,
)
from custom_components.panasonic_smart_china.profiles.bathroom_heater_0820_fv_jdbju2_s import (
    BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE,
)


@pytest_asyncio.fixture
async def device_context(tmp_path):
    """Supply a heated device and mock cloud without hardware or network access.

    Tests start from known status; teardown closes polling and the HA instance
    so listeners and scheduled work cannot affect the next scenario.
    """
    dt_util.set_default_time_zone(dt_util.UTC)
    hass = HomeAssistant(str(tmp_path))
    entry = ConfigEntry(
        domain="panasonic_smart_china",
        version=2,
        minor_version=1,
        title="Test",
        source="user",
        data={},
        options={},
        unique_id="test",
        discovery_keys=MappingProxyType({}),
        subentries_data=[],
    )
    client = AsyncMock()
    client.get_device_status.return_value = {
        "runningMode": 7,
        "offline": 0,
        "timeSet": 12,
        "windDirectionSet": 6,
        "windKindSet": 1,
        "remWarmTimeSet": 12,
        "remWarmWindDirec": 6,
        "remWarmWindKind": 1,
        "timeHourLeft": 0,
        "timeMinuteLeft": 40,
    }
    coordinator = PanasonicDeviceCoordinator(
        hass,
        entry,
        client,
        BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE,
        {"deviceId": "AABBCCDDEEFF_0820_JDBJU2-S", "usrId": "test", "token": "test"},
        None,
    )
    with patch.object(ConfigEntry, "async_start_reauth") as reauth:
        await coordinator.async_refresh()
        yield hass, entry, client, coordinator, reauth
    await coordinator.async_shutdown()
    await hass.async_stop(force=True)
