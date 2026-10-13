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
        "sensor_id": "sensor.bathroom",
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
    for key in ("token", "enabled", "sensor_id"):
        assert saved[key] == original[key]
    reload.assert_awaited_once_with("test")
