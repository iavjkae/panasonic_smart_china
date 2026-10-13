"""Optional boolean controls declared by profiles."""

from homeassistant.components.switch import SwitchEntity

from .entity import PanasonicCoordinatorEntity, coordinators
from .models import status_int


async def async_setup_entry(hass, entry, async_add_entities):
    for coordinator in coordinators(hass, entry):
        if not coordinator.profile.switch_capabilities:
            continue
        created = set()

        def discover(coordinator=coordinator, created=created):
            entities = []
            for capability in coordinator.profile.switch_capabilities:
                if capability.key in created:
                    continue
                if not capability.is_supported(coordinator.data or {}):
                    continue
                created.add(capability.key)
                entities.append(PanasonicSwitchEntity(coordinator, capability))
            if entities:
                async_add_entities(entities)

        discover()
        # Discover flags after a failed first read too, without requiring reload.
        entry.async_on_unload(coordinator.async_add_listener(discover))


class PanasonicSwitchEntity(PanasonicCoordinatorEntity, SwitchEntity):
    def __init__(self, coordinator, capability):
        super().__init__(coordinator)
        self.capability = capability
        self.set_capability_identity(capability)

    @property
    def available(self):
        return super().available and self.capability.is_supported(
            self.coordinator.data or {}
        )

    @property
    def is_on(self):
        value = status_int((self.coordinator.data or {}).get(self.capability.field))
        return value == 1 if value in (0, 1) else None

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_control({self.capability.field: 1})

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_control({self.capability.field: 0})
