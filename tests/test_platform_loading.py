"""Load the actual HA platforms, registry and services against a fake cloud."""

import asyncio
import importlib
import json
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

import pytest
from homeassistant import loader
from homeassistant.config_entries import ConfigEntries
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.panasonic_smart_china.api import PanasonicApiResponseError
from custom_components.panasonic_smart_china.const import DOMAIN
from custom_components.panasonic_smart_china.profiles.bathroom_heater_0820_fv_jdbju2_s import (
    BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_failure", [False, True])
async def test_real_platforms_and_services(device_context, initial_failure):
    """Verify actual HA integration rather than isolated methods; expect existing-
    device continuity, late hardware discovery, service updates and complete
    unload.
    """
    hass, entry, client, coordinator, _ = device_context
    assert hass.loop is asyncio.get_running_loop()
    loader.async_setup(hass)
    root = Path(__file__).resolve().parents[1] / "custom_components" / DOMAIN
    # Pre-import platforms in the test runner, just as existing imports in the
    # other tests; exercise HA registration/services rather than import threads.
    for module in ("config_flow", "climate", "select", "switch", "sensor"):
        importlib.import_module(f"custom_components.{DOMAIN}.{module}")
    integration = loader.Integration(
        hass,
        f"custom_components.{DOMAIN}",
        root,
        json.loads((root / "manifest.json").read_text()),
        top_level_files={item.name for item in root.iterdir()},
    )
    hass.data[loader.DATA_CUSTOM_COMPONENTS] = {DOMAIN: integration}
    hass.config_entries = ConfigEntries(hass, {})

    # Disk/import work is small and local in this test. Use completed futures
    # so executor thread lifecycle does not dominate platform/service testing.
    def inline_executor(target, *args):
        future = hass.loop.create_future()
        try:
            future.set_result(target(*args))
        except Exception as err:
            future.set_exception(err)
        return future

    hass.async_add_executor_job = inline_executor
    hass.async_add_import_executor_job = inline_executor
    await asyncio.wait_for(hass.config_entries.async_initialize(), 10)
    object.__setattr__(
        entry,
        "data",
        MappingProxyType(
            {
                "usrId": "test",
                "SSID": "test",
                "devices": {
                    coordinator.device_id: {
                        "token": "test",
                        "profile_id": BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE.profile_id,
                        "deviceName": "浴霸",
                    },
                    "112233445566_0820_Aircle-05-02": {
                        "token": "test",
                        "profile_id": "bathroom_heater_0820_fv_rb20vl1",
                        "deviceName": "现有浴霸",
                    },
                },
            }
        ),
    )
    new_status = client.get_device_status.return_value.copy()

    async def read_status(profile, *args):
        if profile.profile_id == BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE.profile_id:
            if initial_failure:
                raise PanasonicApiResponseError("Device timeout")
            return new_status.copy()
        return {"runningMode": 37}

    client.get_device_status.side_effect = read_status
    hass.config_entries._entries[entry.entry_id] = entry
    await ar.async_load(hass)
    dr.async_setup(hass)
    await dr.async_load(hass)
    await er.async_load(hass)
    with patch(
        "custom_components.panasonic_smart_china.PanasonicApiClient",
        return_value=client,
    ):
        assert await asyncio.wait_for(
            hass.config_entries.async_setup(entry.entry_id), 15
        )
        await asyncio.wait_for(hass.async_block_till_done(), 10)
        registry = er.async_get(hass)
        entries = er.async_entries_for_config_entry(registry, entry.entry_id)
        assert (
            len(entries) == 9
        )  # 8 new-profile entities plus the existing bath climate.
        new_entries = [
            item for item in entries if coordinator.device_id in item.unique_id
        ]
        assert len(new_entries) == 8
        assert len({item.device_id for item in new_entries}) == 1
        old_climate = next(item for item in entries if "Aircle-05-02" in item.unique_id)
        assert hass.states.get(old_climate.entity_id).state == "heat"
        climate = next(item for item in new_entries if item.domain == "climate")
        duration = next(item for item in entries if item.translation_key == "duration")
        if initial_failure:
            assert hass.states.get(climate.entity_id).state == "unavailable"
            # Recover on the same coordinator without rebuilding account entities.
            client.get_device_status.side_effect = None
            client.get_device_status.return_value = new_status
            runtime = hass.data[DOMAIN][entry.entry_id]["coordinators"][
                coordinator.device_id
            ]
            await runtime.async_refresh()
        assert hass.states.get(climate.entity_id).state == "heat"
        assert hass.states.get(duration.entity_id).state == "1_hour"
        # Exercise late capability discovery through the real HA platform and
        # registries, including after a failed initial device read.
        runtime = hass.data[DOMAIN][entry.entry_id]["coordinators"][
            coordinator.device_id
        ]
        client.get_device_status.side_effect = None
        client.get_device_status.return_value = {
            **new_status,
            "gasCheckHas": 1,
            "odorSensorSet": 0,
        }
        await runtime.async_refresh()
        await hass.async_block_till_done()
        entries = er.async_entries_for_config_entry(registry, entry.entry_id)
        switches = [item for item in entries if item.translation_key == "odor_sensor"]
        assert len(switches) == 1
        assert switches[0].device_id == climate.device_id
        assert hass.states.get(switches[0].entity_id).state == "off"
        await runtime.async_refresh()
        await hass.async_block_till_done()
        assert (
            len(
                [
                    item
                    for item in er.async_entries_for_config_entry(
                        registry, entry.entry_id
                    )
                    if item.translation_key == "odor_sensor"
                ]
            )
            == 1
        )
        client.get_device_status.side_effect = [{"runningMode": 7}, {"runningMode": 0}]
        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": climate.entity_id, "hvac_mode": "off"},
            blocking=True,
        )
        assert hass.states.get(climate.entity_id).state == "off"
        assert hass.states.get(duration.entity_id).state == "unavailable"
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.entry_id not in hass.data[DOMAIN]
        assert not runtime._listeners
