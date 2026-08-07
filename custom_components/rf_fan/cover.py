"""Cover platform for rf_fan - an optimistic RF cover (blinds, awnings, etc.)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import CoverEntity, CoverEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .command import async_send_stored
from .const import (
    CLEAN_REPEAT,
    CMD_CLOSE,
    CMD_OPEN,
    CMD_STOP,
    CONF_COMMANDS,
    CONF_DIRECT,
    CONF_FREQUENCY,
    CONF_HAS_STOP,
    CONF_NAME,
    CONF_SUB_ENTITIES,
    CONF_TRANSMITTER,
    DOMAIN,
    ENTITY_TYPE_COVER,
)


def _cover_key(prefix: str, cmd: str) -> str:
    return f"{prefix}_{cmd}" if prefix else cmd


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add cover entities from the config entry."""
    data = entry.data
    entities: list[CoverEntity] = []

    # Primary entity (legacy / first setup)
    primary_type = data.get("entity_type", "fan")
    if primary_type == ENTITY_TYPE_COVER:
        entities.append(RfCover(entry, name=data[CONF_NAME], key_prefix=""))

    # Sub-entities added via Configure
    for sub in data.get(CONF_SUB_ENTITIES, []):
        if sub.get("entity_type") == ENTITY_TYPE_COVER:
            entities.append(
                RfCover(entry, name=sub["name"], key_prefix=sub["key_prefix"])
            )

    if entities:
        async_add_entities(entities)


class RfCover(CoverEntity, RestoreEntity):
    """An RF cover (blind/awning) with optimistic open/close/stop state.

    RF is one-way, so we track what we last sent and restore it across restarts.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_assumed_state = True

    def __init__(
        self, entry: ConfigEntry, name: str, key_prefix: str
    ) -> None:
        self._commands: dict[str, Any] = entry.data[CONF_COMMANDS]
        self._transmitter: str = entry.data[CONF_TRANSMITTER]
        self._frequency: int = entry.data[CONF_FREQUENCY]
        self._direct: bool = entry.data.get(CONF_DIRECT, False)
        self._has_stop: bool = entry.data.get(CONF_HAS_STOP, False)
        self._key_prefix = key_prefix
        self._attr_name = name
        uid_suffix = f"cover_{key_prefix}" if key_prefix else "cover"
        self._attr_unique_id = f"{entry.entry_id}_{uid_suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data[CONF_NAME],
            manufacturer="RF Device (Broadlink Learning)",
        )
        features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE
        if self._has_stop:
            features |= CoverEntityFeature.STOP
        self._attr_supported_features = features
        self._attr_is_closed: bool | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            if last.state == "closed":
                self._attr_is_closed = True
            elif last.state == "open":
                self._attr_is_closed = False

    def _k(self, cmd: str) -> str:
        return _cover_key(self._key_prefix, cmd)

    async def _send(self, cmd: str) -> None:
        key = self._k(cmd)
        command = self._commands.get(key)
        if not command:
            return
        await async_send_stored(
            self.hass,
            self._transmitter,
            command,
            self._frequency,
            clean=self._direct,
            repeat=CLEAN_REPEAT if self._direct else 0,
        )

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self._send(CMD_OPEN)
        self._attr_is_closed = False
        self.async_write_ha_state()

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self._send(CMD_CLOSE)
        self._attr_is_closed = True
        self.async_write_ha_state()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self._send(CMD_STOP)
        self.async_write_ha_state()