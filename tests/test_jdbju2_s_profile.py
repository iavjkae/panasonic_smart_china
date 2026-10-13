"""Protocol expectations derived independently from native client behavior.

Keep expected wire codes literal so an incorrect profile change cannot also
change the test expectation through an imported constant.
"""

import pytest

from custom_components.panasonic_smart_china.profiles import find_profiles_for_device
from custom_components.panasonic_smart_china.profiles.bathroom_heater_0820_fv_jdbju2_s import (
    BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE,
    RUN_DURATION_CAPABILITY,
    build_payload,
    remaining_minutes,
)


@pytest.mark.parametrize("model", ["JDBJU2-S", "FV-JDBJU2-S", "jdbju2-s"])
def test_model_whitelist(model):
    """Guard model discovery against spelling differences; expect both supported
    names and lowercase input to select only this profile.
    """
    assert (
        BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE.profile_id
        in find_profiles_for_device("0820", {model})
    )


@pytest.mark.parametrize(
    "category,model",
    [("0901", "JDBJU2-S"), ("0820", "TB30U2-W"), ("0820", "FV-UNKNOWN")],
)
def test_no_automatic_family_support(category, model):
    """Prevent shared categories/pages from implying support; expect wrong
    categories and unlisted models to have no match.
    """
    assert not find_profiles_for_device(category, {model})


def test_existing_profiles_still_match():
    """Protect existing discovery after profile registration; expect AC and RB20
    aliases to retain their original profile.
    """
    assert list(find_profiles_for_device("0820", {"FV-RB20VL1"})) == [
        "bathroom_heater_0820_fv_rb20vl1"
    ]
    assert list(find_profiles_for_device("0820", {"Aircle-05-02"})) == [
        "bathroom_heater_0820_fv_rb20vl1"
    ]
    assert list(find_profiles_for_device("0900", {"6838"})) == ["ducted_ac_0900"]


def test_no_lighting_or_audio_capabilities():
    """Enforce the confirmed hardware scope; expect no lighting/audio capabilities,
    their fields at 255, and no RB20 DIY fields.
    """
    assert all(
        "light" not in cap.key and "speaker" not in cap.key
        for cap in BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE.select_capabilities
        + BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE.switch_capabilities
    )
    params = build_payload({"runningMode": 0}, {})
    assert params["lightSet"] == params["speakerSet"] == 255
    assert not any(key.startswith("DIY") for key in params)


@pytest.mark.parametrize(
    "mode,prefix", [(7, "remWarm"), (4, "remCoolDry"), (5, "remHotDry")]
)
def test_mode_switch_restores_target_memory(mode, prefix):
    """Prevent source-mode settings leaking into a new mode; expect target memory,
    normalized direction, and untouched fields omitted or skipped.
    """
    result = build_payload(
        {"runningMode": mode},
        {
            "runningMode": 3,
            f"{prefix}TimeSet": 12,
            f"{prefix}WindDirec": 3,
            f"{prefix}WindKind": 2,
            "lightSet": 1,
            "unknownField": 123,
        },
    )
    assert result["runningMode"] == mode
    assert result["windDirectionSet"] == 0
    assert result["windKindSet"] == 2
    assert result["timeSet"] == 12
    assert result["lightSet"] == 255
    assert "unknownField" not in result


def test_ventilation_restores_fan_not_direction():
    """Keep ventilation-specific restore separate from heating; expect fan and
    duration memory but skip direction and distribution.
    """
    params = build_payload(
        {"runningMode": 3}, {"remVentilationTimeSet": 35, "remVentilationWindVoSet": 0}
    )
    assert params["windVoSet"] == 0
    assert params["timeSet"] == 35
    assert params["windDirectionSet"] == params["windKindSet"] == 255


@pytest.mark.parametrize(
    "mode,prefix",
    [(7, "remWarm"), (3, "remVentilation"), (4, "remCoolDry"), (5, "remHotDry")],
)
def test_mode_switch_preserves_explicit_timer_skip(mode, prefix):
    """Prevent an explicit native skip from becoming a new timer; expect
    timeSet=255 in every supported target mode.
    """
    params = build_payload({"runningMode": mode}, {f"{prefix}TimeSet": 255})
    assert params["timeSet"] == 255


@pytest.mark.parametrize(
    "mode,prefix",
    [(7, "remWarm"), (3, "remVentilation"), (4, "remCoolDry"), (5, "remHotDry")],
)
def test_missing_timer_memory_uses_default(mode, prefix):
    """Handle absent memory without inventing a zero duration; expect the native
    15-minute fallback for each active mode.
    """
    assert build_payload({"runningMode": mode}, {})["timeSet"] == 3


@pytest.mark.parametrize("mode,invalid", [(7, 35), (7, 22), (5, 35), (3, 999)])
def test_invalid_memory_gets_safe_default(mode, invalid):
    """Reject unsupported timer memory during mode restore; expect the 15-minute
    fallback instead of sending the invalid code.
    """
    prefix = {7: "remWarm", 5: "remHotDry", 3: "remVentilation"}[mode]
    assert (
        build_payload({"runningMode": mode}, {f"{prefix}TimeSet": invalid})["timeSet"]
        == 3
    )


@pytest.mark.parametrize(
    "mode,allowed",
    [
        (7, [3, 6, 12, 16]),
        (5, [3, 6, 12, 16, 22]),
        (3, [3, 6, 12, 16, 22, 35]),
        (4, [3, 6, 12, 16, 22, 35]),
    ],
)
def test_duration_choices(mode, allowed):
    """Enforce mode-specific timer limits from the native dialog; expect exactly
    the independent wire-code list for each mode.
    """
    assert [
        RUN_DURATION_CAPABILITY.options[key]
        for key in RUN_DURATION_CAPABILITY.options_for_mode(mode)
    ] == allowed


def test_single_control_skips_unrelated_settings():
    """Prevent a distribution edit from resetting other settings; expect current
    mode plus the requested value and skip codes elsewhere.
    """
    params = build_payload({"windKindSet": 2}, {"runningMode": 7, "timeSet": 16})
    assert params["runningMode"] == 7
    assert params["windKindSet"] == 2
    assert params["timeSet"] == params["windDirectionSet"] == 255


@pytest.mark.parametrize(
    "changes,state",
    [
        ({"windDirectionSet": 6}, {"runningMode": 3}),
        ({"timeSet": 35}, {"runningMode": 7}),
        ({"windVoSet": 1}, {"runningMode": 7}),
        ({"lightSet": 1}, {"runningMode": 7}),
        ({"runningMode": 37}, {}),
        ({"odorSensorSet": 1}, {}),
        ({"timeSet": 3}, {"runningMode": 255}),
    ],
)
def test_reject_unsupported_controls(changes, state):
    """Prevent invalid modes, fields and hardware controls reaching the cloud;
    expect payload validation to raise ValueError.
    """
    with pytest.raises(ValueError):
        build_payload(changes, state)


def test_odor_sensor_requires_hardware_flag():
    """Avoid inferring hardware from a shared App page; expect odor control only
    with its flag and no accompanying mode change.
    """
    params = build_payload({"odorSensorSet": 0}, {"gasCheckHas": 1, "runningMode": 0})
    assert params["odorSensorSet"] == 0
    assert params["runningMode"] == 255


@pytest.mark.parametrize(
    "state,expected",
    [
        ({"timeSet": 12, "timeHourLeft": "1", "timeMinuteLeft": "20"}, 80),
        ({"timeSet": 35, "timeHourLeft": 7, "timeMinuteLeft": 0}, None),
        ({}, None),
        ({"timeHourLeft": 0, "timeMinuteLeft": 80}, None),
    ],
)
def test_remaining_time(state, expected):
    """Avoid fabricated countdowns from continuous or malformed status; expect
    valid time in minutes and unknown for unusable values.
    """
    assert remaining_minutes(state) == expected
