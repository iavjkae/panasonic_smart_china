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


@pytest.fixture
def cloud_http():
    """Provide HTTP responses for API contract tests without network traffic."""
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
async def test_smallbath_endpoints_and_headers(device_context, cloud_http):
    """Match native request routing and session requirements; expect SmallBath
    paths, top-level credentials, nested controls and SmartApp/Cookie headers.
    """
    hass, _, _, _, _ = device_context
    client = PanasonicApiClient(hass, "session")
    response, session = cloud_http
    response.json.return_value = {"id": 100, "results": {"runningMode": 7}}
    assert await client.get_device_status(
        BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE, "usr", "device", "token"
    ) == {"runningMode": 7}
    assert session.post.call_args.args[0].endswith("/App/ADevGetStatusInfoSmallBath")
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
    assert session.post.call_args.args[0].endswith("/App/ADevSetStatusInfoSmallBath")
    assert session.post.call_args.kwargs["json"]["params"] == {"runningMode": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [{"id": 100, "results": {}}, {"id": 100, "results": []}],
)
async def test_invalid_status_is_not_accepted(device_context, cloud_http, result):
    """Missing mode or non-object results must fail before becoming device state."""
    hass, _, _, _, _ = device_context
    client = PanasonicApiClient(hass, "session")
    response, _ = cloud_http
    response.json.return_value = result
    with pytest.raises(PanasonicApiResponseError):
        await client.get_device_status(
            BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE, "usr", "device", "token"
        )


@pytest.mark.parametrize(
    "data,error",
    [
        ({"errorCode": None, "error": {"code": 4102}}, PanasonicApiAuthError),
        ({"errorCode": 0, "error": {"code": 4102}}, PanasonicApiAuthError),
        ({"errorCode": 0, "error": {"code": 400}}, PanasonicApiResponseError),
        ({"errorCode": 400, "error": {"code": 4102}}, PanasonicApiAuthError),
        ({"errorCode": 4102, "error": {"code": 400}}, PanasonicApiAuthError),
        ({"errorCode": []}, PanasonicApiResponseError),
        ({"error": {"code": {}}}, PanasonicApiResponseError),
        ({"errorCode": 0, "error": {"code": 0}}, None),
        ({"errorCode": None, "error": {"code": "0000"}}, None),
    ],
)
def test_business_errors(data, error):
    """Honor both error fields, prioritize auth and reject malformed codes."""
    client = PanasonicApiClient(None)
    if error:
        with pytest.raises(error):
            client._raise_for_business_error(data)
    else:
        client._raise_for_business_error(data)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["status", "control"])
async def test_business_errors_reach_both_endpoints(
    device_context, cloud_http, operation
):
    """Read and write endpoints must both apply the shared business-error parser."""
    hass, _, _, _, _ = device_context
    response, _ = cloud_http
    response.json.return_value = {"errorCode": 0, "error": {"code": 4102}}
    client = PanasonicApiClient(hass, "session")
    with pytest.raises(PanasonicApiAuthError):
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
    "operation,bad_id",
    [
        ("status", None),
        ("control", 999),
        ("status", "invalid"),
        ("control", 52.5),
        ("status", True),
    ],
)
async def test_smallbath_rejects_missing_or_mismatched_response_id(
    device_context, cloud_http, operation, bad_id
):
    """Reject missing, mismatched and malformed IDs across both native endpoints."""
    hass, _, _, _, _ = device_context
    response, _ = cloud_http
    response.json.return_value = {"id": bad_id, "results": {"runningMode": 7}}
    client = PanasonicApiClient(hass, "session")
    with pytest.raises(PanasonicApiResponseError, match="Response id"):
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
    device_context, cloud_http, operation, response_id
):
    """Preserve native numeric-string ID compatibility; expect matching string IDs
    to pass for reads and writes.
    """
    hass, _, _, _, _ = device_context
    client = PanasonicApiClient(hass, "session")
    response, _ = cloud_http
    response.json.return_value = {"id": response_id, "results": {"runningMode": 7}}
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
    device_context, cloud_http, profile_id
):
    """Prevent new native validation breaking legacy endpoints; expect existing
    profiles to keep accepting valid ID-less responses.
    """
    hass, _, _, _, _ = device_context
    profile = SUPPORTED_PROFILES[profile_id]
    client = PanasonicApiClient(hass, "session")
    response, _ = cloud_http
    state = dict.fromkeys(profile.status_endpoint.required_result_keys, 0)
    response.json.return_value = {"results": state}
    assert await client.get_device_status(profile, "usr", "device", "token") == state
    response.json.return_value = {"results": {}}
    assert await client.set_device_status(profile, "usr", "device", "token", {}) == {
        "results": {}
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("family_id", ["family", 123])
async def test_authenticate_valid_account_chain(device_context, cloud_http, family_id):
    """A valid token/login/list chain must retain native IDs and use the session."""
    hass, _, _, _, _ = device_context
    response, session = cloud_http
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
@pytest.mark.parametrize("results", [[], {}, {"token": 123}])
async def test_malformed_token_response(device_context, cloud_http, results):
    """Invalid challenges must raise API response errors before login is sent."""
    hass, _, _, _, _ = device_context
    response, session = cloud_http
    response.json.return_value = {"results": results}
    with pytest.raises(PanasonicApiResponseError):
        await PanasonicApiClient(hass).authenticate("user", "password")
    assert session.post.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,invalid",
    [
        ("usrId", None),
        ("ssId", ""),
        ("familyId", True),
        ("realFamilyId", []),
    ],
)
async def test_malformed_login_fields(device_context, cloud_http, field, invalid):
    """Missing/invalid credentials must fail within the API before listing devices."""
    hass, _, _, _, _ = device_context
    response, session = cloud_http
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
async def test_malformed_login_results(device_context, cloud_http):
    """Non-object login results must produce response errors instead of KeyError."""
    hass, _, _, _, _ = device_context
    response, _ = cloud_http
    response.json.side_effect = [
        {"results": {"token": "challenge"}},
        {"results": []},
    ]
    with pytest.raises(PanasonicApiResponseError):
        await PanasonicApiClient(hass).authenticate("user", "password")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "results",
    [
        [],
        {"devList": None},
        {"devList": [None]},
        {"devList": [{"deviceId": [], "params": {}}]},
        {"devList": [{"deviceId": "device", "params": []}]},
    ],
)
async def test_malformed_device_list(device_context, cloud_http, results):
    """Malformed lists/records must produce API errors, never partial inventories."""
    hass, _, _, _, _ = device_context
    response, _ = cloud_http
    response.json.return_value = {"results": results}
    with pytest.raises(PanasonicApiResponseError):
        await PanasonicApiClient(hass).get_devices("usr", 1, 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("results", [{}, {"devList": []}])
async def test_empty_device_list_is_valid(device_context, cloud_http, results):
    """Absent or empty devList must remain a valid account with no bound devices."""
    hass, _, _, _, _ = device_context
    response, _ = cloud_http
    response.json.return_value = {"results": results}
    assert await PanasonicApiClient(hass).get_devices("usr", 1, 2) == {}
