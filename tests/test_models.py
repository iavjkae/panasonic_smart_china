"""Validate cloud code normalization independently of entity presentation."""

import pytest

from custom_components.panasonic_smart_china.models import status_int
from custom_components.panasonic_smart_china.profiles.bathroom_heater_0820_fv_jdbju2_s import (
    AIR_DISTRIBUTION_CAPABILITY,
    ODOR_SENSOR_CAPABILITY,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        (7, 7),
        ("7", 7),
        (7.0, 7),
        (7.9, None),
        (True, None),
        (float("inf"), None),
        (float("nan"), None),
        (None, None),
        ([], None),
        ({}, None),
        ("7.9", None),
    ],
)
def test_status_integer_codes(value, expected):
    """Accept integer encodings; malformed numbers must never become valid codes."""
    assert status_int(value) == expected


def test_fractional_capabilities_are_not_enabled():
    """Fractional hardware/option codes must yield unsupported/unknown state."""
    assert not ODOR_SENSOR_CAPABILITY.is_supported({"gasCheckHas": 1.9})
    assert AIR_DISTRIBUTION_CAPABILITY.current_option({"windKindSet": 1.9}, 7) is None
