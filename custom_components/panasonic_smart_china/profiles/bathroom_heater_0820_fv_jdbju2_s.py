"""SmallBath protocol for FV-JDBJU2-S, based on the native Android client.

Lighting and speaker controls belong to the shared App page, not this model.
The adaptation is pending hardware validation. No other SmallBath model is
enabled merely because it shares this endpoint.
"""

from homeassistant.components.climate.const import HVACMode

from ..models import (
    ENTITY_KIND_BATHROOM_HEATER,
    PanasonicEndpoint,
    PanasonicProfile,
    PanasonicSelectCapability,
    PanasonicSensorCapability,
    PanasonicSwitchCapability,
    status_int,
)

MODE_OFF = 0
MODE_VENTILATION = 3
MODE_COOL_DRY = 4
MODE_HOT_DRY = 5
MODE_HEAT = 7
CONTROL_SKIP_VALUE = 255
DEFAULT_DURATION_CODE = 3
CONTINUOUS_DURATION_CODE = 35

ACTIVE_MODES = frozenset({MODE_VENTILATION, MODE_COOL_DRY, MODE_HOT_DRY, MODE_HEAT})
DIRECTION_SUPPORTED_MODES = frozenset({MODE_COOL_DRY, MODE_HOT_DRY, MODE_HEAT})
OPERATING_MODE_CAPABILITY = PanasonicSelectCapability(
    key="operating_mode",
    field="runningMode",
    # HA's fixed HVAC labels describe air conditioners. Provide the appliance's
    # actual modes without changing existing climate service identifiers.
    options={
        "off": MODE_OFF,
        "heat": MODE_HEAT,
        "ventilation": MODE_VENTILATION,
        "cool_dry": MODE_COOL_DRY,
        "hot_dry": MODE_HOT_DRY,
    },
)
WIND_DIRECTION_CAPABILITY = PanasonicSelectCapability(
    key="wind_direction",
    field="windDirectionSet",
    options={"fixed": 0, "auto": 6},
    modes=DIRECTION_SUPPORTED_MODES,
    # SmallBathHeatPowerStateActivity converts remembered direction 3 to fixed
    # (0); preserve that normalization so restore and display agree.
    read_mapping={3: 0},
)
AIR_DISTRIBUTION_CAPABILITY = PanasonicSelectCapability(
    key="wind_kind",
    field="windKindSet",
    # Follow SmallBathHeatSetParamsDialog because its selection and write paths
    # agree on concentrated=2. Main-page labels disagree; verify on hardware.
    options={"concentrated": 2, "diffused": 1},
    modes=DIRECTION_SUPPORTED_MODES,
)
RUN_DURATION_CODES = {
    "15_minutes": DEFAULT_DURATION_CODE,
    "30_minutes": 6,
    "1_hour": 12,
    "3_hours": 16,
    "6_hours": 22,
    "continuous": CONTINUOUS_DURATION_CODE,
}
RUN_DURATION_CAPABILITY = PanasonicSelectCapability(
    key="duration",
    field="timeSet",
    options=RUN_DURATION_CODES,
    modes=ACTIVE_MODES,
    # HiddenBathheatSetTimeDialog limits heat to 3h and hot drying to 6h;
    # enumerate those options explicitly so dict ordering cannot widen them.
    mode_options={
        MODE_HEAT: ("15_minutes", "30_minutes", "1_hour", "3_hours"),
        MODE_HOT_DRY: ("15_minutes", "30_minutes", "1_hour", "3_hours", "6_hours"),
        MODE_VENTILATION: tuple(RUN_DURATION_CODES),
        MODE_COOL_DRY: tuple(RUN_DURATION_CODES),
    },
)
VENTILATION_FAN_STRENGTH_CAPABILITY = PanasonicSelectCapability(
    key="fan_strength",
    field="windVoSet",
    options={"weak": 0, "strong": 1},
    modes=frozenset({MODE_VENTILATION}),
    # The native SmallBath page hides fan strength. Keep it opt-in because a
    # shared protocol field does not prove this model supports the control.
    enabled_default=False,
)

CONTROL_PAYLOAD_FIELDS = (
    "runningMode",
    "windVoSet",
    "warmTempset",
    "windDirectionSet",
    "windKindSet",
    "timeSet",
    "lightSet",
    "speakerSet",
    "odorSensorSet",
    *(f"reserved{i}" for i in range(3, 11)),
)
MODE_MEMORY_PREFIXES = {
    MODE_HEAT: "remWarm",
    MODE_VENTILATION: "remVentilation",
    MODE_COOL_DRY: "remCoolDry",
    MODE_HOT_DRY: "remHotDry",
}
ODOR_SENSOR_CAPABILITY = PanasonicSwitchCapability(
    key="odor_sensor",
    field="odorSensorSet",
    required_flag="gasCheckHas",
)


def remaining_minutes(status):
    """Return unknown for continuous/missing time instead of inventing a countdown."""
    hours = status_int(status.get("timeHourLeft"))
    minutes = status_int(status.get("timeMinuteLeft"))
    if (
        status_int(status.get("timeSet")) == CONTINUOUS_DURATION_CODE
        or hours is None
        or minutes is None
    ):
        return None
    if not 0 <= hours <= 6 or not 0 <= minutes < 60:
        return None
    return hours * 60 + minutes


def _restore_mode_params(mode, status):
    """Match native mode switching so target settings survive App/HA transitions."""
    control_payload = {}
    prefix = MODE_MEMORY_PREFIXES[mode]
    valid_duration_codes = {
        RUN_DURATION_CAPABILITY.options[key]
        for key in RUN_DURATION_CAPABILITY.options_for_mode(mode)
    }
    remembered_duration_code = status_int(status.get(f"{prefix}TimeSet"))
    # SmallBathHeatPowerStateActivity.a(mode, time) preserves 255. Falling back
    # to 15 minutes here would reset a timer the native client leaves unchanged.
    control_payload["timeSet"] = (
        remembered_duration_code
        if remembered_duration_code in valid_duration_codes | {CONTROL_SKIP_VALUE}
        else DEFAULT_DURATION_CODE
    )
    if mode in DIRECTION_SUPPORTED_MODES:
        direction = status_int(status.get(f"{prefix}WindDirec"))
        direction = WIND_DIRECTION_CAPABILITY.read_mapping.get(direction, direction)
        air_distribution = status_int(status.get(f"{prefix}WindKind"))
        if direction in WIND_DIRECTION_CAPABILITY.options.values():
            control_payload[WIND_DIRECTION_CAPABILITY.field] = direction
        if air_distribution in AIR_DISTRIBUTION_CAPABILITY.options.values():
            control_payload[AIR_DISTRIBUTION_CAPABILITY.field] = air_distribution
    else:
        fan_strength = status_int(status.get("remVentilationWindVoSet"))
        if fan_strength in VENTILATION_FAN_STRENGTH_CAPABILITY.options.values():
            control_payload[VENTILATION_FAN_STRENGTH_CAPABILITY.field] = fan_strength
    return control_payload


def build_payload(changes, status):
    """Restore target-mode memory, otherwise only set the requested controls.

    No status dictionary is echoed into a command. Reserved fields and controls
    absent from this model remain at the native client's skip value (255).
    """
    allowed_control_fields = {
        "runningMode",
        WIND_DIRECTION_CAPABILITY.field,
        AIR_DISTRIBUTION_CAPABILITY.field,
        RUN_DURATION_CAPABILITY.field,
        VENTILATION_FAN_STRENGTH_CAPABILITY.field,
        ODOR_SENSOR_CAPABILITY.field,
    }
    if not changes or changes.keys() - allowed_control_fields:
        raise ValueError("Unsupported SmallBath control fields")
    control_payload = dict.fromkeys(CONTROL_PAYLOAD_FIELDS, CONTROL_SKIP_VALUE)
    if "runningMode" in changes:
        mode = status_int(changes["runningMode"])
        if mode not in ACTIVE_MODES | {MODE_OFF}:
            raise ValueError("Unsupported SmallBath mode")
        control_payload["runningMode"] = mode
        if mode != MODE_OFF:
            control_payload.update(_restore_mode_params(mode, status))
    else:
        mode = status_int(status.get("runningMode"))

    for capability in (
        WIND_DIRECTION_CAPABILITY,
        AIR_DISTRIBUTION_CAPABILITY,
        RUN_DURATION_CAPABILITY,
        VENTILATION_FAN_STRENGTH_CAPABILITY,
    ):
        if capability.field not in changes:
            continue
        value = status_int(changes[capability.field])
        choices = capability.options_for_mode(mode)
        if value not in {capability.options[key] for key in choices}:
            raise ValueError(f"{capability.key} is not valid in the current mode")
        control_payload[capability.field] = value
        # Mirror the native parameter/time request: include the freshly read
        # mode while leaving unrelated controls at 255, to avoid resetting them.
        control_payload["runningMode"] = mode

    if ODOR_SENSOR_CAPABILITY.field in changes:
        value = status_int(changes[ODOR_SENSOR_CAPABILITY.field])
        if not ODOR_SENSOR_CAPABILITY.is_supported(status) or value not in (0, 1):
            raise ValueError("Odor sensor is not supported by this device")
        control_payload[ODOR_SENSOR_CAPABILITY.field] = value
    return control_payload


BATHROOM_HEATER_0820_FV_JDBJU2_S_PROFILE = PanasonicProfile(
    profile_id="bathroom_heater_0820_fv_jdbju2_s",
    controller_model="FV-JDBJU2-S",
    name="松下浴霸 (FV-JDBJU2-S)",
    category_ids=frozenset({"0820"}),
    model_ids=frozenset({"FV-JDBJU2-S", "JDBJU2-S"}),
    ha_platforms=("climate", "select", "switch", "sensor"),
    entity_kind=ENTITY_KIND_BATHROOM_HEATER,
    protocol="small_bath",
    # NetRequestMgr rejects missing/mismatched response IDs even for writes
    # without results. Enable this per endpoint to preserve legacy API behavior.
    status_endpoint=PanasonicEndpoint(
        path="ADevGetStatusInfoSmallBath",
        request_id=100,
        require_results=True,
        required_result_keys=frozenset({"runningMode"}),
        validate_response_id=True,
    ),
    set_endpoint=PanasonicEndpoint(
        path="ADevSetStatusInfoSmallBath",
        request_id=52,
        require_results=False,
        validate_response_id=True,
    ),
    default_hvac_mode=HVACMode.FAN_ONLY,
    hvac_mapping={
        HVACMode.OFF: MODE_OFF,
        HVACMode.HEAT: MODE_HEAT,
        HVACMode.FAN_ONLY: MODE_VENTILATION,
        HVACMode.COOL: MODE_COOL_DRY,
        HVACMode.DRY: MODE_HOT_DRY,
    },
    cookie_required=True,
    extra_control_headers={
        "User-Agent": "SmartApp",
        "Referer": "https://app.psmartcloud.com/",
    },
    control_skip_value=CONTROL_SKIP_VALUE,
    select_capabilities=(
        OPERATING_MODE_CAPABILITY,
        AIR_DISTRIBUTION_CAPABILITY,
        RUN_DURATION_CAPABILITY,
        VENTILATION_FAN_STRENGTH_CAPABILITY,
    ),
    swing_capability=WIND_DIRECTION_CAPABILITY,
    switch_capabilities=(ODOR_SENSOR_CAPABILITY,),
    sensor_capabilities=(
        PanasonicSensorCapability("remaining_time", remaining_minutes, unit="min"),
        PanasonicSensorCapability(
            "alarm", lambda state: status_int(state.get("alarmStatus")), diagnostic=True
        ),
        PanasonicSensorCapability(
            "filter", lambda state: status_int(state.get("filterDisp")), diagnostic=True
        ),
        PanasonicSensorCapability(
            "ota_status",
            lambda state: status_int(state.get("otaStatus")),
            diagnostic=True,
        ),
    ),
    offline_field="offline",
    build_control_payload=build_payload,
    control_blockers={"otaStatus": frozenset({1}), "filterDisp": frozenset({16})},
)
