"""Shared device model definitions for Panasonic Smart China."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

PLATFORM_CLIMATE = "climate"

ENTITY_KIND_DUCTED_AC = "ducted_ac"
ENTITY_KIND_BATHROOM_HEATER = "bathroom_heater"

PROTOCOL_AC_STATUS = "ac_status"
PROTOCOL_BATHROOM_HEATER = "bathroom_heater"

TOKEN_STRATEGY_DEVICE_ID_SHA512 = "device_id_sha512"


def status_int(value: Any) -> int | None:
    """Accept integral JSON numbers and integer strings, never truncate codes."""
    # Booleans and fractional numbers must not accidentally enable hardware or
    # select a valid protocol mode. Integral floats retain JSON compatibility.
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        result = int(value)
    except (ValueError, OverflowError):
        return None
    if isinstance(value, float) and value != result:
        return None
    return result


@dataclass(frozen=True)
class PanasonicSelectCapability:
    """A choice supported by a model, independently of its HA presentation."""

    key: str
    field: str
    options: dict[str, int]
    modes: frozenset[int] = frozenset()
    mode_options: dict[int, tuple[str, ...]] = field(default_factory=dict)
    read_mapping: dict[int, int] = field(default_factory=dict)
    enabled_default: bool = True

    def options_for_mode(self, mode: int | None) -> list[str]:
        if self.modes and mode not in self.modes:
            return []
        return list(self.mode_options.get(mode, tuple(self.options)))

    def current_option(self, status: dict[str, Any], mode: int | None) -> str | None:
        """Decode a supported option, including model-specific read mappings."""
        value = status_int(status.get(self.field))
        value = self.read_mapping.get(value, value)
        return next(
            (key for key in self.options_for_mode(mode) if self.options[key] == value),
            None,
        )


@dataclass(frozen=True)
class PanasonicSwitchCapability:
    """A boolean control, optionally conditional on a device capability flag."""

    key: str
    field: str
    required_flag: str | None = None

    def is_supported(self, status: dict[str, Any]) -> bool:
        """Honor an optional hardware capability flag."""
        return not self.required_flag or status_int(status.get(self.required_flag)) == 1


@dataclass(frozen=True)
class PanasonicSensorCapability:
    """A read-only value derived from the shared status."""

    key: str
    value: Callable[[dict[str, Any]], Any]
    unit: str | None = None
    diagnostic: bool = False


@dataclass(frozen=True)
class PanasonicEndpoint:
    """Description of a Panasonic cloud control endpoint."""

    path: str
    request_id: int
    require_results: bool
    required_result_keys: frozenset[str] = frozenset()
    allow_non_json_response: bool = False
    validate_response_id: bool = False


@dataclass(frozen=True)
class PanasonicProfile:
    """Capability and protocol description for a supported device family."""

    profile_id: str
    controller_model: str
    name: str
    category_ids: frozenset[str]
    ha_platforms: tuple[str, ...]
    entity_kind: str
    protocol: str
    status_endpoint: PanasonicEndpoint
    set_endpoint: PanasonicEndpoint
    model_ids: frozenset[str] = frozenset()
    token_strategy: str = TOKEN_STRATEGY_DEVICE_ID_SHA512
    temp_scale: int = 1
    default_hvac_mode: Any | None = None
    hvac_mapping: dict[Any, int] = field(default_factory=dict)
    fan_mapping: dict[str, int] = field(default_factory=dict)
    fan_payload_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    safe_status_keys: frozenset[str] = frozenset()
    cookie_required: bool = False
    referer_template: str | None = None
    extra_control_headers: dict[str, str] = field(default_factory=dict)
    select_capabilities: tuple[PanasonicSelectCapability, ...] = ()
    swing_capability: PanasonicSelectCapability | None = None
    switch_capabilities: tuple[PanasonicSwitchCapability, ...] = ()
    sensor_capabilities: tuple[PanasonicSensorCapability, ...] = ()
    offline_field: str | None = None
    control_blockers: dict[str, frozenset[int]] = field(default_factory=dict)
    build_control_payload: (
        Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None
    ) = None
    mode_field: str = "runningMode"

    @property
    def active_modes(self) -> frozenset[int]:
        """Protocol modes that represent a running appliance."""
        return frozenset(
            value for mode, value in self.hvac_mapping.items() if mode != "off"
        )

    def matches_category(self, category_id: str | None) -> bool:
        """Return whether this profile supports a Panasonic category id."""
        return bool(category_id and category_id in self.category_ids)

    def matches_device(
        self,
        category_id: str | None,
        model_values: set[str] | frozenset[str] | None = None,
    ) -> bool:
        """Return whether this profile supports a concrete cloud device."""
        if not self.matches_category(category_id):
            return False
        if not self.model_ids:
            return True
        normalized_models = {
            value.strip().upper()
            for value in (model_values or set())
            if value and value.strip()
        }
        supported_models = {value.upper() for value in self.model_ids}
        return bool(normalized_models & supported_models)
