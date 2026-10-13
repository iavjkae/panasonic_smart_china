"""Shared device metadata for profile-driven coordinator entities."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class PanasonicCoordinatorEntity(CoordinatorEntity):
    """Bind all controls and sensors to the same Panasonic appliance."""

    _attr_has_entity_name = True

    @property
    def available(self):
        return self.coordinator.online

    @property
    def device_info(self):
        coordinator = self.coordinator
        info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_id)},
            name=coordinator.device_name,
            manufacturer="Panasonic",
            model=coordinator.model,
        )
        if coordinator.account_device_id:
            info["via_device_id"] = coordinator.account_device_id
        return info

    def set_capability_identity(self, capability):
        self._attr_unique_id = (
            f"panasonic_smart_china_{self.coordinator.device_id}_{capability.key}"
        )
        self._attr_translation_key = capability.key


def coordinators(hass, entry):
    return hass.data[DOMAIN][entry.entry_id].get("coordinators", {}).values()
