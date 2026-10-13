"""Choice entities created exclusively from profile capability declarations."""

from homeassistant.components.select import SelectEntity

from .entity import PanasonicCoordinatorEntity, coordinators


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [
            PanasonicSelectEntity(coordinator, capability)
            for coordinator in coordinators(hass, entry)
            for capability in coordinator.profile.select_capabilities
        ]
    )


class PanasonicSelectEntity(PanasonicCoordinatorEntity, SelectEntity):
    def __init__(self, coordinator, capability):
        super().__init__(coordinator)
        self.capability = capability
        self.set_capability_identity(capability)
        self._attr_entity_registry_enabled_default = capability.enabled_default

    @property
    def available(self):
        return self.coordinator.capability_available(self.capability)

    @property
    def options(self):
        return self.capability.options_for_mode(self.coordinator.mode)

    @property
    def current_option(self):
        return self.capability.current_option(
            self.coordinator.data or {}, self.coordinator.mode
        )

    async def async_select_option(self, option):
        await self.coordinator.async_select(self.capability, option)
