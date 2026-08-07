"""Button platform for rf_fan - one entity per learned custom button."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .command import async_send_stored
from .const import (
    CLEAN_REPEAT,
    CONF_COMMANDS,
    CONF_CUSTOMS,
    CONF_DIRECT,
    CONF_FREQUENCY,
    CONF_NAME,
    CONF_SUB_ENTITIES,
    CONF_TRANSMITTER,
    DOMAIN,
    ENTITY_TYPE_BUTTON,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a button entity for each learned custom button."""
    data = entry.data
    commands = data[CONF_COMMANDS]
    entities: list[ButtonEntity] = []

    # Custom buttons from the main entity wizard
    for custom in data.get(CONF_CUSTOMS, []):
        if custom["key"] in commands:
            entities.append(RfButton(entry, name=custom["name"], key=custom["key"]))

    # Sub-entities of type button (each is treated as a group of buttons via its customs)
    for sub in data.get(CONF_SUB_ENTITIES, []):
        if sub.get("entity_type") == ENTITY_TYPE_BUTTON:
            # A "button" sub-entity is just an extra button — its key is its key_prefix
            key = sub["key_prefix"]
            if key in commands:
                entities.append(RfButton(entry, name=sub["name"], key=key))

    if entities:
        async_add_entities(entities)


class RfButton(ButtonEntity):
    """A custom learned button - presses send the captured code once."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, name: str, key: str) -> None:
        """Initialise from a custom button definition."""
        self._command = entry.data[CONF_COMMANDS][key]
        self._transmitter = entry.data[CONF_TRANSMITTER]
        self._frequency = entry.data[CONF_FREQUENCY]
        self._direct = entry.data.get(CONF_DIRECT, False)
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data[CONF_NAME],
            manufacturer="RF Device (Broadlink Learning)",
        )

    async def async_press(self) -> None:
        """Send the learned code."""
        await async_send_stored(
            self.hass,
            self._transmitter,
            self._command,
            self._frequency,
            clean=self._direct,
            repeat=CLEAN_REPEAT if self._direct else 0,
        )
