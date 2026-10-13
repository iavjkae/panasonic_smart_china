"""Exercise real HA entities/coordinator with a fake Panasonic cloud."""

import asyncio
from dataclasses import replace
from types import MappingProxyType
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.climate.const import HVACMode
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError

from custom_components.panasonic_smart_china import (
    async_setup_entry,
    async_unload_entry,
)
from custom_components.panasonic_smart_china.api import (
    PanasonicApiAuthError,
    PanasonicApiResponseError,
)
from custom_components.panasonic_smart_china.climate import (
    PanasonicBathroomHeaterEntity,
    PanasonicProfileClimateEntity,
)
from custom_components.panasonic_smart_china.const import DOMAIN
from custom_components.panasonic_smart_china.profiles.bathroom_heater_0820_fv_jdbju2_s import (
    AIR_DISTRIBUTION_CAPABILITY,
    BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE,
    RUN_DURATION_CAPABILITY,
)
from custom_components.panasonic_smart_china.profiles.bathroom_heater_0820_fv_rb20vl1 import (
    BATHROOM_HEATER_0820_FV_RB20VL1_PROFILE,
)
from custom_components.panasonic_smart_china.select import PanasonicSelectEntity
from custom_components.panasonic_smart_china.select import (
    async_setup_entry as setup_select,
)
from custom_components.panasonic_smart_china.switch import (
    async_setup_entry as setup_switch,
)


@pytest.mark.asyncio
async def test_accepted_mode_updates_without_readback(device_context):
    """Accepted OFF must publish immediately, preserve status and exclude skips."""
    _, _, client, coordinator, _ = device_context
    entity = PanasonicProfileClimateEntity(coordinator)
    client.get_device_status.reset_mock()
    original_status = client.get_device_status.return_value.copy()
    await entity.async_turn_off()
    client.get_device_status.assert_awaited_once()
    assert client.set_device_status.call_args.args[-1]["runningMode"] == 0
    assert entity.hvac_mode == HVACMode.OFF
    assert coordinator.data == {**original_status, "runningMode": 0}


@pytest.mark.asyncio
async def test_periodic_poll_reconciles_accepted_mode(device_context):
    """Successful control updates locally; normal polling later uses actual status."""
    _, _, client, coordinator, _ = device_context
    await coordinator.async_control({"runningMode": 3})
    assert coordinator.mode == 3
    assert client.set_device_status.call_args.args[-1]["runningMode"] == 3
    await coordinator.async_refresh()
    assert coordinator.mode == 7


@pytest.mark.asyncio
async def test_turn_on_preserves_app_mode_and_running_timer(device_context):
    """Prevent HA turn_on undoing a recent App change; expect the running mode and
    countdown to remain untouched with no write.
    """
    _, _, client, coordinator, _ = device_context
    entity = PanasonicProfileClimateEntity(coordinator)
    # The App changed mode since HA's last poll. turn_on must not change it
    # back to heat or restore remembered settings over the current countdown.
    client.get_device_status.return_value = {
        "runningMode": 5,
        "timeSet": 16,
        "timeMinuteLeft": 23,
    }
    await entity.async_turn_on()
    client.set_device_status.assert_not_called()
    assert entity.hvac_mode == HVACMode.DRY
    assert coordinator.data["timeMinuteLeft"] == 23


@pytest.mark.asyncio
async def test_queued_turn_on_uses_latest_remembered_mode(device_context):
    """Prevent mode restoration from being decided before the lock; expect queued
    turn_on to use the latest remembered active mode.
    """
    _, _, client, coordinator, _ = device_context
    entity = PanasonicProfileClimateEntity(coordinator)
    client.get_device_status.return_value = {"runningMode": 0}
    async with coordinator._command_lock:
        task = asyncio.create_task(entity.async_turn_on())
        await asyncio.sleep(0)
        # An earlier queued command establishes a new last active mode.
        coordinator.last_active_mode = 5
    await task
    assert client.set_device_status.call_args.args[-1]["runningMode"] == 5
    assert entity.hvac_mode == HVACMode.DRY


@pytest.mark.asyncio
async def test_options_follow_mode_and_unknown_values(device_context):
    """Prevent stale or invalid options being displayed as valid; expect
    options/availability to follow mode and unknown codes to stay unknown.
    """
    _, _, _, coordinator, _ = device_context
    duration_entity = PanasonicSelectEntity(coordinator, RUN_DURATION_CAPABILITY)
    air_distribution_entity = PanasonicSelectEntity(
        coordinator, AIR_DISTRIBUTION_CAPABILITY
    )
    assert "continuous" not in duration_entity.options
    assert air_distribution_entity.current_option == "diffused"
    coordinator.async_set_updated_data({"runningMode": 3, "timeSet": 35})
    assert duration_entity.current_option == "continuous"
    assert not air_distribution_entity.available
    coordinator.async_set_updated_data({"runningMode": 7, "windKindSet": 255})
    assert air_distribution_entity.current_option is None
    coordinator.async_set_updated_data({"runningMode": 255})
    assert PanasonicProfileClimateEntity(coordinator).hvac_mode is None
    assert not duration_entity.available


@pytest.mark.asyncio
async def test_shared_controls_use_profile_mode_field(device_context):
    """Prevent SmallBath field names leaking into shared code; expect climate
    commands, state and turn_on to use the alternate profile field.
    """
    _, _, client, coordinator, _ = device_context

    def build_payload(changes, status):
        assert "operation" in status
        return changes.copy()

    coordinator.profile = replace(
        BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE,
        mode_field="operation",
        build_control_payload=build_payload,
    )
    entity = PanasonicProfileClimateEntity(coordinator)
    client.get_device_status.return_value = {"operation": 0}
    await entity.async_set_hvac_mode(HVACMode.DRY)
    assert client.set_device_status.call_args.args[-1] == {"operation": 5}
    assert entity.hvac_mode == HVACMode.DRY
    client.get_device_status.return_value = {"operation": 0}
    await entity.async_turn_on()
    assert client.set_device_status.call_args.args[-1] == {"operation": 5}


@pytest.mark.asyncio
async def test_profile_without_swing_rejects_swing_service(device_context):
    """Protect models without direction control; expect unknown swing state and a
    clear service error without a cloud write.
    """
    _, _, client, coordinator, _ = device_context
    coordinator.profile = replace(
        BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE, swing_capability=None
    )
    entity = PanasonicProfileClimateEntity(coordinator)
    assert entity.swing_mode is None
    with pytest.raises(HomeAssistantError, match="does not support swing"):
        await entity.async_set_swing_mode("auto")
    client.set_device_status.assert_not_called()


@pytest.mark.asyncio
async def test_server_mode_revalidated_before_select(device_context):
    """Prevent a stale UI option acting after an App mode change; expect fresh-
    state validation to reject it before sending.
    """
    _, _, client, coordinator, _ = device_context
    client.get_device_status.return_value = {"runningMode": 3}
    with pytest.raises(HomeAssistantError):
        await coordinator.async_select(AIR_DISTRIBUTION_CAPABILITY, "concentrated")
    client.set_device_status.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state",
    [
        {"runningMode": 7, "offline": 1},
        {"runningMode": 7, "otaStatus": 1},
        {"runningMode": 7, "filterDisp": 16},
    ],
)
async def test_block_offline_or_maintenance_commands(device_context, state):
    """Protect offline or maintenance devices from control; expect a service error
    and no write, with offline entities unavailable.
    """
    _, _, client, coordinator, _ = device_context
    client.get_device_status.return_value = state
    with pytest.raises(HomeAssistantError):
        await coordinator.async_control({"runningMode": 0})
    client.set_device_status.assert_not_called()
    if state.get("offline"):
        assert not coordinator.online


@pytest.mark.asyncio
async def test_failed_write_does_not_change_mode(device_context):
    """Prevent a rejected command from fabricating success; expect a service error
    and preservation of the actual pre-write mode.
    """
    _, _, client, coordinator, _ = device_context
    client.set_device_status.side_effect = PanasonicApiResponseError("rejected")
    with pytest.raises(HomeAssistantError):
        await coordinator.async_control({"runningMode": 3})
    assert coordinator.mode == 7


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["read", "write"])
async def test_auth_failure_triggers_reauth(device_context, stage):
    """Protect authentication handling at all transaction stages; expect
    unavailable state, an auth error and one reauth request.
    """
    _, _, client, coordinator, reauth = device_context
    err = PanasonicApiAuthError("expired")
    if stage == "write":
        client.set_device_status.side_effect = err
    else:
        client.get_device_status.side_effect = err
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator.async_control({"runningMode": 0})
    assert not coordinator.online
    reauth.assert_called_once()


@pytest.mark.asyncio
async def test_poll_failure_after_accepted_control_marks_unavailable(device_context):
    """A later poll failure must not turn accepted control into a service failure."""
    _, _, client, coordinator, _ = device_context
    client.get_device_status.side_effect = [
        {"runningMode": 7},
        PanasonicApiResponseError("timeout"),
    ]
    await coordinator.async_control({"runningMode": 0})
    assert coordinator.mode == 0
    assert coordinator.online
    await coordinator.async_refresh()
    assert not coordinator.online
    assert coordinator.mode == 0


@pytest.mark.asyncio
async def test_serialized_commands_and_polling(device_context):
    """Prevent polling and writes interleaving into lost updates; expect serialized
    cloud access and both independent changes preserved.
    """
    _, _, client, coordinator, _ = device_context
    state = {"runningMode": 7, "windKindSet": 1, "windDirectionSet": 6}
    sent_payloads = []
    write_in_progress = False

    async def read(*args):
        assert not write_in_progress
        await asyncio.sleep(0)
        return state.copy()

    async def write(*args):
        nonlocal write_in_progress
        assert not write_in_progress
        write_in_progress = True
        await asyncio.sleep(0)
        params = args[-1]
        sent_payloads.append(params.copy())
        state.update({key: value for key, value in params.items() if value != 255})
        write_in_progress = False
        return {}

    client.get_device_status.side_effect = read
    client.set_device_status.side_effect = write
    await asyncio.gather(
        coordinator.async_control({"windKindSet": 2}),
        coordinator.async_control({"windDirectionSet": 0}),
        coordinator.async_refresh(),
    )
    assert len(sent_payloads) == 2
    assert coordinator.data["windKindSet"] == 2
    assert coordinator.data["windDirectionSet"] == 0


@pytest.mark.asyncio
async def test_queued_command_is_rejected_after_shutdown(device_context):
    """Prevent old queued services operating after unload; expect an unloaded error
    with no further status reads or writes.
    """
    _, _, client, coordinator, _ = device_context
    status_reads_before = client.get_device_status.call_count
    async with coordinator._command_lock:
        task = asyncio.create_task(coordinator.async_control({"runningMode": 3}))
        await asyncio.sleep(0)
        await coordinator.async_shutdown()
    with pytest.raises(HomeAssistantError, match="unloaded"):
        await task
    assert client.get_device_status.call_count == status_reads_before
    client.set_device_status.assert_not_called()


@pytest.mark.asyncio
async def test_shutdown_during_control_read_prevents_write(device_context):
    """Close the unload race during pre-command reads; expect no write or state
    publication when the old request completes.
    """
    _, _, client, coordinator, _ = device_context
    request_started, complete_request = asyncio.Event(), asyncio.Event()
    original_state = coordinator.data.copy()

    async def read(*args):
        request_started.set()
        await complete_request.wait()
        return {"runningMode": 5}

    client.get_device_status.side_effect = read
    task = asyncio.create_task(coordinator.async_control({"runningMode": 3}))
    await request_started.wait()
    await coordinator.async_shutdown()
    complete_request.set()
    with pytest.raises(HomeAssistantError, match="unloaded"):
        await task
    client.set_device_status.assert_not_called()
    assert coordinator.data == original_state


@pytest.mark.asyncio
async def test_profile_driven_creation_and_shared_updates(device_context):
    """Prevent capability inference and duplicated device polling; expect declared
    entities only, one late switch and one read shared by listeners.
    """
    hass, entry, client, coordinator, _ = device_context
    hass.data[DOMAIN] = {
        entry.entry_id: {"coordinators": {coordinator.device_id: coordinator}}
    }
    entities = []
    await setup_select(hass, entry, entities.extend)
    assert {entity.capability.key for entity in entities} == {
        "operating_mode",
        "wind_kind",
        "duration",
        "fan_strength",
    }
    assert not next(
        e for e in entities if e.capability.key == "fan_strength"
    ).entity_registry_enabled_default
    switches = []
    await setup_switch(hass, entry, switches.extend)
    assert not switches  # Never infer hardware capability from shared App fields.
    coordinator.async_set_updated_data({"runningMode": 7, "gasCheckHas": 1})
    assert len(switches) == 1
    coordinator.async_set_updated_data({"runningMode": 7, "gasCheckHas": 1})
    assert len(switches) == 1  # Late discovery must not duplicate an entity.
    assert switches[0].device_info == entities[0].device_info
    coordinator.profile = replace(
        BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE, select_capabilities=()
    )
    undeclared_entities = []
    await setup_select(hass, entry, undeclared_entities.extend)
    assert not undeclared_entities
    # All listeners share a single data update, not separate cloud queries.
    listener_updates = []
    remove_listeners = [
        coordinator.async_add_listener(lambda: listener_updates.append(True))
        for _ in range(3)
    ]
    status_reads_before = client.get_device_status.call_count
    await coordinator.async_refresh()
    assert client.get_device_status.call_count == status_reads_before + 1
    assert len(listener_updates) == 3
    for remove in remove_listeners:
        remove()


@pytest.mark.asyncio
async def test_setup_first_refresh_once_and_unload(device_context):
    """Protect account setup and resource cleanup; expect one initial device read,
    closed coordinators and removed runtime on unload.
    """
    hass, entry, client, coordinator, _ = device_context
    hass.data[DOMAIN] = {}
    data = {
        "usrId": "test",
        "SSID": "test",
        "devices": {
            coordinator.device_id: {
                "token": "test",
                "profile_id": BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE.profile_id,
            },
        },
    }
    object.__setattr__(entry, "data", MappingProxyType(data))
    object.__setattr__(entry, "state", ConfigEntryState.SETUP_IN_PROGRESS)
    fake_entries = AsyncMock()
    fake_entries.async_unload_platforms.return_value = True
    with (
        patch.object(hass, "config_entries", fake_entries),
        patch(
            "custom_components.panasonic_smart_china._async_create_account_device",
            return_value=None,
        ),
        patch(
            "custom_components.panasonic_smart_china.PanasonicApiClient",
            return_value=client,
        ),
    ):
        before = client.get_device_status.call_count
        await async_setup_entry(hass, entry)
        assert client.get_device_status.call_count == before + 1
        loaded_coordinator = hass.data[DOMAIN][entry.entry_id]["coordinators"][
            coordinator.device_id
        ]
        await async_unload_entry(hass, entry)
        assert entry.entry_id not in hass.data[DOMAIN]
        assert loaded_coordinator._shutdown_requested


def test_existing_rb20vl1_payload_unchanged():
    """Protect the original bathroom-heater protocol; expect its mode, timer, DIY
    step and shutdown code to remain unchanged.
    """
    entity = PanasonicBathroomHeaterEntity.__new__(PanasonicBathroomHeaterEntity)
    params = entity._build_send_payload({"runningMode": 37}, {})
    assert params["runningMode"] == 37 and params["timeSet"] == 3
    assert params["DIYnextStepNo"] == 2
    assert entity._build_off_command() == {"runningMode": 32}
    assert BATHROOM_HEATER_0820_FV_RB20VL1_PROFILE.build_control_payload is None


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["first_read", "platform_setup"])
async def test_cancelled_setup_cleans_up_coordinators(device_context, stage):
    """Prevent resources surviving cancelled initialization; expect cancellation to
    propagate and all created device runtimes to close.
    """
    hass, entry, client, coordinator, _ = device_context
    hass.data[DOMAIN] = {}
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
                    },
                },
            }
        ),
    )
    object.__setattr__(entry, "state", ConfigEntryState.SETUP_IN_PROGRESS)
    fake_entries = AsyncMock()
    created_coordinators = []
    request_started = asyncio.Event()

    async def blocked(*args):
        request_started.set()
        await asyncio.Event().wait()

    def create_coordinator(*args):
        result = type(coordinator)(*args)
        created_coordinators.append(result)
        return result

    if stage == "first_read":
        client.get_device_status.side_effect = blocked
    else:
        fake_entries.async_forward_entry_setups.side_effect = blocked
    with (
        patch.object(hass, "config_entries", fake_entries),
        patch(
            "custom_components.panasonic_smart_china._async_create_account_device",
            return_value=None,
        ),
        patch(
            "custom_components.panasonic_smart_china.PanasonicApiClient",
            return_value=client,
        ),
        patch(
            "custom_components.panasonic_smart_china.PanasonicDeviceCoordinator",
            side_effect=create_coordinator,
        ),
    ):
        task = asyncio.create_task(async_setup_entry(hass, entry))
        await request_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert entry.entry_id not in hass.data[DOMAIN]
    assert created_coordinators and all(
        item._shutdown_requested for item in created_coordinators
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_failure", [False, True])
async def test_inflight_poll_is_ignored_after_shutdown(device_context, auth_failure):
    """Prevent old poll results affecting a reloaded entry; expect no state
    publication or reauth after shutdown, even on auth failure.
    """
    _, _, client, coordinator, _ = device_context
    request_started, complete_request = asyncio.Event(), asyncio.Event()
    original_state = coordinator.data.copy()

    async def read(*args):
        request_started.set()
        await complete_request.wait()
        if auth_failure:
            raise PanasonicApiAuthError("old session expired")
        return {"runningMode": 5}

    client.get_device_status.side_effect = read
    with patch.object(
        type(coordinator.entry), "async_start_reauth_if_available"
    ) as reauth:
        task = asyncio.create_task(coordinator.async_refresh())
        await request_started.wait()
        await coordinator.async_shutdown()
        complete_request.set()
        await task
        reauth.assert_not_called()
    assert coordinator.data == original_state
    assert not coordinator.online


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [0, 7])
async def test_repeated_mode_preserves_countdown(device_context, mode):
    """Repeated heat/off calls must publish fresh status without resetting memory."""
    _, _, client, coordinator, _ = device_context
    client.get_device_status.return_value = {
        "runningMode": mode,
        "timeMinuteLeft": 20,
        "remWarmTimeSet": 12,
    }
    await coordinator.async_set_mode(mode)
    client.set_device_status.assert_not_called()
    assert coordinator.data["timeMinuteLeft"] == 20


@pytest.mark.asyncio
async def test_set_mode_uses_fresh_state(device_context):
    """A stale cached heat mode must not suppress heat after an App mode change."""
    _, _, client, coordinator, _ = device_context
    client.get_device_status.return_value = {"runningMode": 3}
    await coordinator.async_set_mode(7)
    assert client.set_device_status.call_args.args[-1]["runningMode"] == 7


@pytest.mark.asyncio
async def test_same_mode_combined_control_is_sent(device_context):
    """Explicit timer changes accompanying a mode must still reach the device."""
    _, _, client, coordinator, _ = device_context
    await coordinator.async_control({"runningMode": 7, "timeSet": 6})
    assert client.set_device_status.call_args.args[-1]["timeSet"] == 6


@pytest.mark.asyncio
async def test_operating_mode_select_preserves_running_countdown(device_context):
    """Selecting current appliance mode must not restore memory or resend a write."""
    from custom_components.panasonic_smart_china.profiles.bathroom_heater_0820_fv_jdbju2_s import (
        OPERATING_MODE_CAPABILITY,
    )

    _, _, client, coordinator, _ = device_context
    entity = PanasonicSelectEntity(coordinator, OPERATING_MODE_CAPABILITY)
    assert entity.options == ["off", "heat", "ventilation", "cool_dry", "hot_dry"]
    assert entity.current_option == "heat"
    await entity.async_select_option("heat")
    client.set_device_status.assert_not_called()
    assert coordinator.data["timeMinuteLeft"] == 40


@pytest.mark.asyncio
async def test_state_changes_only_after_control_is_accepted(device_context):
    """Do not publish pre-write cloud state or the target until the API succeeds."""
    _, _, client, coordinator, _ = device_context
    client.get_device_status.reset_mock()
    client.get_device_status.return_value = {"runningMode": 0}
    write_started, accept_write = asyncio.Event(), asyncio.Event()

    async def write(*_args):
        write_started.set()
        await accept_write.wait()
        return {}

    client.set_device_status.side_effect = write
    task = asyncio.create_task(coordinator.async_set_mode(5))
    await write_started.wait()
    try:
        assert coordinator.mode == 7
    finally:
        accept_write.set()
        await task
    assert coordinator.mode == 5
    assert coordinator.last_active_mode == 5
    client.get_device_status.assert_awaited_once()


@pytest.mark.asyncio
async def test_shutdown_during_write_prevents_local_publication(device_context):
    """A successful obsolete write must not publish state after device unload."""
    _, _, client, coordinator, _ = device_context
    original_status = coordinator.data.copy()
    write_started, complete_write = asyncio.Event(), asyncio.Event()

    async def write(*_args):
        write_started.set()
        await complete_write.wait()
        return {}

    client.set_device_status.side_effect = write
    task = asyncio.create_task(coordinator.async_set_mode(3))
    await write_started.wait()
    await coordinator.async_shutdown()
    complete_write.set()
    with pytest.raises(HomeAssistantError, match="unloaded"):
        await task
    assert coordinator.data == original_status


@pytest.mark.asyncio
async def test_accepted_select_updates_control_but_preserves_other_fields(
    device_context,
):
    """An accepted choice must immediately update its entity without merging skips."""
    _, _, client, coordinator, _ = device_context
    client.get_device_status.reset_mock()
    original = client.get_device_status.return_value.copy()
    entity = PanasonicSelectEntity(coordinator, AIR_DISTRIBUTION_CAPABILITY)
    await entity.async_select_option("concentrated")
    assert entity.current_option == "concentrated"
    assert coordinator.data == {**original, "windKindSet": 2}
    client.get_device_status.assert_awaited_once()
