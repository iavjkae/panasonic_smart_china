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


@pytest.fixture
def account_http():
    """Supply real API methods with queued JSON replies and no network traffic."""
    response = AsyncMock()
    response.status = 200
    session = MagicMock()
    session.post = AsyncMock(return_value=response)
    with patch(
        "custom_components.panasonic_smart_china.api.async_get_clientsession",
        return_value=session,
    ):
        yield response, session


@pytest.mark.asyncio
@pytest.mark.parametrize("family_id", ["family", 123])
async def test_authenticate_valid_account_chain(
    device_context, account_http, family_id
):
    """A valid token/login/list chain must retain native IDs and use the session."""
    hass, _, _, _, _ = device_context
    response, session = account_http
    response.json.side_effect = [
        {"results": {"token": "challenge"}},
        {
            "results": {
                "usrId": "usr",
                "ssId": "session",
                "familyId": family_id,
                "realFamilyId": family_id,
            }
        },
        {
            "results": {
                "devList": [{"deviceId": "device", "params": {"deviceName": "bath"}}]
            }
        },
    ]
    client = PanasonicApiClient(hass)
    result = await client.authenticate("user", "password")
    assert result.usr_id == "usr"
    assert result.ssid == client.ssid == "session"
    assert result.family_id == result.real_family_id == family_id
    assert result.devices == {"device": {"deviceName": "bath"}}
    requests = session.post.call_args_list
    assert [call.args[0].rsplit("/", 1)[-1] for call in requests] == [
        "UsrGetToken",
        "UsrLogin",
        "UsrGetBindDevInfo",
    ]
    assert requests[-1].kwargs["headers"]["Cookie"] == "SSID=session"
    assert requests[-1].kwargs["json"]["params"]["familyId"] == family_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "results", [None, [], "bad", {}, {"token": []}, {"token": 123}, {"token": ""}]
)
async def test_malformed_token_response(device_context, account_http, results):
    """Invalid challenges must raise API response errors before login is sent."""
    hass, _, _, _, _ = device_context
    response, session = account_http
    response.json.return_value = {"results": results}
    with pytest.raises(PanasonicApiResponseError):
        await PanasonicApiClient(hass).authenticate("user", "password")
    assert session.post.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["usrId", "ssId", "familyId", "realFamilyId"])
@pytest.mark.parametrize("invalid", [None, [], True, ""])
async def test_malformed_login_fields(device_context, account_http, field, invalid):
    """Missing/invalid credentials must fail within the API before listing devices."""
    hass, _, _, _, _ = device_context
    response, session = account_http
    fields = {"usrId": "usr", "ssId": "session", "familyId": 1, "realFamilyId": 2}
    if invalid is None:
        fields.pop(field)
    else:
        fields[field] = invalid
    response.json.side_effect = [
        {"results": {"token": "challenge"}},
        {"results": fields},
    ]
    client = PanasonicApiClient(hass)
    with pytest.raises(PanasonicApiResponseError, match=field):
        await client.authenticate("user", "password")
    assert client.ssid is None
    assert session.post.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("results", [None, [], "bad"])
async def test_malformed_login_results(device_context, account_http, results):
    """Non-object login results must produce response errors instead of KeyError."""
    hass, _, _, _, _ = device_context
    response, _ = account_http
    response.json.side_effect = [
        {"results": {"token": "challenge"}},
        {"results": results},
    ]
    with pytest.raises(PanasonicApiResponseError):
        await PanasonicApiClient(hass).authenticate("user", "password")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "results",
    [
        None,
        [],
        "bad",
        {"devList": None},
        {"devList": {}},
        {"devList": [None]},
        {"devList": [{"deviceId": [], "params": {}}]},
        {"devList": [{"deviceId": "device", "params": []}]},
        {"devList": [{"deviceId": "device"}]},
        {"devList": [{"params": {}}]},
    ],
)
async def test_malformed_device_list(device_context, account_http, results):
    """Malformed lists/records must produce API errors, never partial inventories."""
    hass, _, _, _, _ = device_context
    response, _ = account_http
    response.json.return_value = {"results": results}
    with pytest.raises(PanasonicApiResponseError):
        await PanasonicApiClient(hass).get_devices("usr", 1, 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("results", [{}, {"devList": []}])
async def test_empty_device_list_is_valid(device_context, account_http, results):
    """Absent or empty devList must remain a valid account with no bound devices."""
    hass, _, _, _, _ = device_context
    response, _ = account_http
    response.json.return_value = {"results": results}
    assert await PanasonicApiClient(hass).get_devices("usr", 1, 2) == {}
