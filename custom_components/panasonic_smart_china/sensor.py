"""Read-only state from the same device poll as the controls."""

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory

from .entity import PanasonicCoordinatorEntity, coordinators


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [
            PanasonicSensorEntity(coordinator, capability)
            for coordinator in coordinators(hass, entry)
            for capability in coordinator.profile.sensor_capabilities
        ]
    )


class PanasonicSensorEntity(PanasonicCoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, capability):
        super().__init__(coordinator)
        self.capability = capability
        self.set_capability_identity(capability)
        self._attr_native_unit_of_measurement = capability.unit
        if capability.unit == "min":
            self._attr_device_class = SensorDeviceClass.DURATION
        if capability.diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        return self.capability.value(self.coordinator.data or {})
