"""Verify the actual cloud request boundary without sending network requests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.panasonic_smart_china.api import (
    PanasonicApiAuthError,
    PanasonicApiClient,
    PanasonicApiResponseError,
)
from custom_components.panasonic_smart_china.profiles import SUPPORTED_PROFILES
from custom_components.panasonic_smart_china.profiles.bathroom_heater_0820_fv_jdbju2_s import (
    BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE,
)


@pytest.mark.asyncio
async def test_smallbath_endpoints_and_headers(device_context):
    """Match native request routing and session requirements; expect SmallBath
    paths, top-level credentials, nested controls and SmartApp/Cookie headers.
    """
    hass, _, _, _, _ = device_context
    client = PanasonicApiClient(hass, "session")
    response = AsyncMock()
    response.status = 200
    response.json.return_value = {"id": 100, "results": {"runningMode": 7}}
    session = MagicMock()
    session.post = AsyncMock(return_value=response)
    with patch(
        "custom_components.panasonic_smart_china.api.async_get_clientsession",
        return_value=session,
    ):
        assert await client.get_device_status(
            BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE, "usr", "device", "token"
        ) == {"runningMode": 7}
        assert session.post.call_args.args[0].endswith(
            "/App/ADevGetStatusInfoSmallBath"
        )
        request_kwargs = session.post.call_args.kwargs
        assert request_kwargs["json"] == {
            "id": 100,
            "usrId": "usr",
            "deviceId": "device",
            "token": "token",
        }
        assert request_kwargs["headers"]["User-Agent"] == "SmartApp"
        assert request_kwargs["headers"]["Cookie"] == "SSID=session"
        response.json.return_value = {"id": 52}
        await client.set_device_status(
            BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE,
            "usr",
            "device",
            "token",
            {"runningMode": 0},
        )
        assert session.post.call_args.args[0].endswith(
            "/App/ADevSetStatusInfoSmallBath"
        )
        assert session.post.call_args.kwargs["json"]["params"] == {"runningMode": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result,error",
    [
        ({"id": 100, "results": {}}, PanasonicApiResponseError),
        ({"errorCode": 4102}, PanasonicApiAuthError),
        ({"errorCode": 400}, PanasonicApiResponseError),
        ({"id": 100, "results": []}, PanasonicApiResponseError),
    ],
)
async def test_invalid_status_is_not_accepted(device_context, result, error):
    """Prevent malformed or failed status responses becoming device state; expect
    the appropriate response/auth exception.
    """
    hass, _, _, _, _ = device_context
    client = PanasonicApiClient(hass, "session")
    response = AsyncMock()
    response.status = 200
    response.json.return_value = result
    session = MagicMock()
    session.post = AsyncMock(return_value=response)
    with (
        patch(
            "custom_components.panasonic_smart_china.api.async_get_clientsession",
            return_value=session,
        ),
        pytest.raises(error),
    ):
        await client.get_device_status(
            BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE, "usr", "device", "token"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["status", "control"])
@pytest.mark.parametrize(
    "response_data",
    [
        {"errorCode": []},
        {"errorCode": {}},
        {"error": {"code": []}},
        {"error": {"code": {}}},
    ],
)
async def test_structured_error_code_returns_api_error(
    device_context, operation, response_data
):
    """Keep malformed business errors inside the API boundary; expect a response
    error for reads and writes instead of an uncaught TypeError or success.
    """
    hass, _, _, _, _ = device_context
    client = PanasonicApiClient(hass, "session")
    response = AsyncMock()
    response.status = 200
    response.json.return_value = response_data
    session = MagicMock()
    session.post = AsyncMock(return_value=response)
    with (
        patch(
            "custom_components.panasonic_smart_china.api.async_get_clientsession",
            return_value=session,
        ),
        pytest.raises(PanasonicApiResponseError, match="error code"),
    ):
        if operation == "status":
            await client.get_device_status(
                BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE, "usr", "device", "token"
            )
        else:
            await client.set_device_status(
                BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE,
                "usr",
                "device",
                "token",
                {"runningMode": 0},
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["status", "control"])
@pytest.mark.parametrize("bad_id", [None, 999, "invalid", 52.5, True])
async def test_smallbath_rejects_missing_or_mismatched_response_id(
    device_context, operation, bad_id
):
    """Prevent unrelated JSON being accepted as a native reply; expect missing,
    malformed and mismatched IDs to fail for reads and writes.
    """
    hass, _, _, _, _ = device_context
    client = PanasonicApiClient(hass, "session")
    response = AsyncMock()
    response.status = 200
    response.json.return_value = {"results": {"runningMode": 7}}
    if bad_id is not None:
        response.json.return_value["id"] = bad_id
    session = MagicMock()
    session.post = AsyncMock(return_value=response)
    with (
        patch(
            "custom_components.panasonic_smart_china.api.async_get_clientsession",
            return_value=session,
        ),
        pytest.raises(PanasonicApiResponseError, match="Response id"),
    ):
        if operation == "status":
            await client.get_device_status(
                BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE, "usr", "device", "token"
            )
        else:
            await client.set_device_status(
                BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE,
                "usr",
                "device",
                "token",
                {"runningMode": 0},
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,response_id", [("status", "100"), ("control", "52")]
)
async def test_smallbath_accepts_numeric_string_response_id(
    device_context, operation, response_id
):
    """Preserve native numeric-string ID compatibility; expect matching string IDs
    to pass for reads and writes.
    """
    hass, _, _, _, _ = device_context
    client = PanasonicApiClient(hass, "session")
    response = AsyncMock()
    response.status = 200
    response.json.return_value = {"id": response_id, "results": {"runningMode": 7}}
    session = MagicMock()
    session.post = AsyncMock(return_value=response)
    with patch(
        "custom_components.panasonic_smart_china.api.async_get_clientsession",
        return_value=session,
    ):
        if operation == "status":
            assert await client.get_device_status(
                BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE, "usr", "device", "token"
            ) == {"runningMode": 7}
        else:
            assert (
                await client.set_device_status(
                    BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE,
                    "usr",
                    "device",
                    "token",
                    {"runningMode": 0},
                )
                == response.json.return_value
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "profile_id", ["ducted_ac_0900", "bathroom_heater_0820_fv_rb20vl1"]
)
async def test_existing_profiles_keep_accepting_responses_without_id(
    device_context, profile_id
):
    """Prevent new native validation breaking legacy endpoints; expect existing
    profiles to keep accepting valid ID-less responses.
    """
    hass, _, _, _, _ = device_context
    profile = SUPPORTED_PROFILES[profile_id]
    client = PanasonicApiClient(hass, "session")
    response = AsyncMock()
    response.status = 200
    state = dict.fromkeys(profile.status_endpoint.required_result_keys, 0)
    response.json.return_value = {"results": state}
    session = MagicMock()
    session.post = AsyncMock(return_value=response)
    with patch(
        "custom_components.panasonic_smart_china.api.async_get_clientsession",
        return_value=session,
    ):
        assert (
            await client.get_device_status(profile, "usr", "device", "token") == state
        )
        response.json.return_value = {"results": {}}
        assert await client.set_device_status(
            profile, "usr", "device", "token", {}
        ) == {"results": {}}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["status", "control"])
@pytest.mark.parametrize(
    "top,nested,error",
    [
        (None, 4102, PanasonicApiAuthError),
        (0, 4102, PanasonicApiAuthError),
        ("0000", 400, PanasonicApiResponseError),
        (400, 4102, PanasonicApiAuthError),
        (4102, 400, PanasonicApiAuthError),
        (0, [], PanasonicApiResponseError),
        (0, 0, None),
        (None, "0000", None),
    ],
)
async def test_both_business_error_representations(
    device_context, operation, top, nested, error
):
    """Both error fields must be honored; auth takes priority and success passes."""
    hass, _, _, _, _ = device_context
    client = PanasonicApiClient(hass, "session")
    response = AsyncMock()
    response.status = 200
    response.json.return_value = {
        "id": 100 if operation == "status" else 52,
        "results": {"runningMode": 7},
        "errorCode": top,
        "error": {"code": nested},
    }
    session = MagicMock()
    session.post = AsyncMock(return_value=response)
    with patch(
        "custom_components.panasonic_smart_china.api.async_get_clientsession",
        return_value=session,
    ):
        if operation == "status":
            call = client.get_device_status(
                BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE, "usr", "device", "token"
            )
        else:
            call = client.set_device_status(
                BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE,
                "usr",
                "device",
                "token",
                {"runningMode": 0},
            )
        if error:
            with pytest.raises(error):
                await call
        else:
            await call
