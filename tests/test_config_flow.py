"""Regression coverage for persisted account/device configuration."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.panasonic_smart_china.config_flow import PanasonicOptionsFlow


@pytest.mark.asyncio
async def test_existing_only_rescan_preserves_old_data_until_update():
    """Metadata-only rescans must change saved data and retain user settings."""
    device_id = "AABBCCDDEEFF_0820_JDBJU2-S"
    original = {
        "deviceName": "old",
        "device_model": "FV-JDBJU2-S",
        "category": "0820",
        "token": "custom-token",
        "enabled": False,
        "sensor_entity_id": "sensor.bathroom",
    }
    entry = SimpleNamespace(
        entry_id="test",
        data={
            "usrId": "usr",
            "SSID": "session",
            "familyId": "family",
            "realFamilyId": "family",
            "devices": {device_id: original},
        },
    )
    updates = []

    def update(config_entry, *, data):
        assert config_entry.data["devices"][device_id]["deviceName"] == "old"
        assert config_entry.data != data
        updates.append(data)
        return True

    reload = AsyncMock()
    flow = PanasonicOptionsFlow(entry)
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_update_entry=update,
            async_reload=reload,
        )
    )
    flow.async_create_entry = MagicMock(return_value={})
    client = MagicMock()
    client.get_devices = AsyncMock(
        return_value={
            device_id: {
                "deviceName": "new",
                "devType": "FV-JDBJU2-S",
            }
        }
    )
    with patch(
        "custom_components.panasonic_smart_china.config_flow.PanasonicApiClient",
        return_value=client,
    ):
        await flow.async_step_rescan()
    saved = updates[0]["devices"][device_id]
    assert saved["deviceName"] == "new"
    assert saved["profile_id"] == "bathroom_heater_0820_fv_jdbju2_s"
    for key in ("token", "enabled", "sensor_entity_id"):
        assert saved[key] == original[key]
    reload.assert_awaited_once_with("test")


@pytest.mark.asyncio
async def test_malformed_account_response_shows_cannot_connect(device_context):
    """Invalid cloud results must render a retryable login error in the HA flow."""
    from custom_components.panasonic_smart_china.api import PanasonicApiClient
    from custom_components.panasonic_smart_china.config_flow import PanasonicConfigFlow

    hass, _, _, _, _ = device_context
    client = PanasonicApiClient(hass)
    client._post = AsyncMock(return_value={"results": []})
    flow = PanasonicConfigFlow()
    flow.hass = hass
    with patch(
        "custom_components.panasonic_smart_china.config_flow.PanasonicApiClient",
        return_value=client,
    ):
        result = await flow.async_step_user(
            {"username": "user", "password": "password"}
        )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "device_id,metadata",
    [
        ("AABBCCDDEEFF_0820_JDBJU2-S", {"deviceName": "浴霸"}),
        (
            "AABBCCDDEEFF_0820_native-controller",
            {"deviceName": "浴霸", "devSubTypeId": "JDBJU2-S"},
        ),
    ],
)
async def test_jdbju2_s_account_discovery_reaches_device_selection(
    device_context, device_id, metadata
):
    """The reported 0820/JDBJU2-S device must reach selection and save its profile."""
    from custom_components.panasonic_smart_china.api import LoginResult
    from custom_components.panasonic_smart_china.config_flow import PanasonicConfigFlow

    hass, _, _, _, _ = device_context
    flow = PanasonicConfigFlow()
    flow.hass = hass
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    client = MagicMock()
    client.authenticate = AsyncMock(
        return_value=LoginResult("usr", "session", 1, 2, {device_id: metadata})
    )
    with patch(
        "custom_components.panasonic_smart_china.config_flow.PanasonicApiClient",
        return_value=client,
    ):
        result = await flow.async_step_user(
            {"username": "user", "password": "password"}
        )
    assert result["type"] == "form"
    assert result["step_id"] == "devices"
    assert flow._unsupported_device_summary() == "无"
    result = await flow.async_step_devices({"devices": [device_id]})
    assert result["type"] == "create_entry"
    device = result["data"]["devices"][device_id]
    assert device["profile_id"] == "bathroom_heater_0820_fv_jdbju2_s"
    assert device["controller_model"] == "FV-JDBJU2-S"
    assert device["entity_kind"] == "bathroom_heater"
    assert device["ha_platforms"] == ["climate", "select", "switch", "sensor"]
