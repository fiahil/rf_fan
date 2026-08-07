"""RF Device with Learning.

A learn-and-replay Home Assistant integration for RF devices: capture your
remote's codes with a Broadlink RM Pro / RM4 Pro through a guided wizard, then
transmit them via Home Assistant's native ``radio_frequency`` platform.
Fans, covers (blinds/awnings), lights and buttons are all set up from the UI.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_CUSTOMS, CONF_SUB_ENTITIES, ENTITY_TYPE_BUTTON

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.FAN, Platform.COVER, Platform.LIGHT, Platform.BUTTON]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entries from older versions.

    v1 → v2: CONF_CUSTOMS (list of {key, name} button dicts) is converted into
    CONF_SUB_ENTITIES entries of entity_type=button so the new button.py
    platform can pick them up without any data loss.
    """
    if entry.version == 1:
        _LOGGER.info(
            "rf_fan: migrating config entry '%s' from version 1 to 2", entry.title
        )
        data = dict(entry.data)

        # Convert each legacy custom button into a sub-entity record.
        legacy_customs = data.pop(CONF_CUSTOMS, [])
        sub_entities = list(data.get(CONF_SUB_ENTITIES, []))

        for custom in legacy_customs:
            # Only migrate if the key actually has a learned code stored.
            if custom.get("key") in data.get("commands", {}):
                sub_entities.append({
                    "entity_type": ENTITY_TYPE_BUTTON,
                    "name": custom["name"],
                    # For buttons the key_prefix IS the command key itself.
                    "key_prefix": custom["key"],
                })

        data[CONF_SUB_ENTITIES] = sub_entities

        hass.config_entries.async_update_entry(entry, data=data, version=2)
        _LOGGER.info(
            "rf_fan: migration complete — %d custom button(s) converted to sub-entities",
            len(legacy_customs),
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change (e.g. after re-learning)."""
    await hass.config_entries.async_reload(entry.entry_id)
