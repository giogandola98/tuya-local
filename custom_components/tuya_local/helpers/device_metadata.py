"""Validate user-provided network identity and device registry relationships."""

import re

from homeassistant.helpers import device_registry as dr

from ..const import CONF_MAC_ADDRESS, CONF_VIA_DEVICE_ID, DOMAIN
from .config import get_device_id


def validate_metadata(hass, config, user_input):
    """Normalize metadata and reject invalid MACs or cyclic parent links."""
    errors = {}
    registry = dr.async_get(hass)
    current = registry.async_get_device(identifiers={(DOMAIN, get_device_id(config))})
    raw = user_input.get(CONF_MAC_ADDRESS, "").strip()
    compact = re.sub(r"[:.\-]", "", raw)
    if raw and not re.fullmatch(r"[0-9a-fA-F]{12}", compact):
        errors[CONF_MAC_ADDRESS] = "invalid_mac"
    else:
        user_input[CONF_MAC_ADDRESS] = dr.format_mac(compact) if raw else ""

    selected = user_input.get(CONF_VIA_DEVICE_ID, "")
    user_input[CONF_VIA_DEVICE_ID] = selected or ""
    if selected:
        parent = registry.async_get(selected)
        seen = {current.id} if current else set()
        while parent is not None:
            if parent.id in seen:
                errors[CONF_VIA_DEVICE_ID] = "invalid_via_device"
                break
            seen.add(parent.id)
            if not parent.via_device_id:
                break
            parent = registry.async_get(parent.via_device_id)
        if parent is None:
            errors[CONF_VIA_DEVICE_ID] = "invalid_via_device"
    return errors


def update_metadata(hass, config, user_input):
    """Replace previously configured metadata on an existing registry device."""
    registry = dr.async_get(hass)
    current = registry.async_get_device(identifiers={(DOMAIN, get_device_id(config))})
    if current is None:
        return
    connections = set(current.connections)
    if old_mac := config.get(CONF_MAC_ADDRESS):
        connections.discard((dr.CONNECTION_NETWORK_MAC, dr.format_mac(old_mac)))
    if mac := user_input.get(CONF_MAC_ADDRESS):
        connections.add((dr.CONNECTION_NETWORK_MAC, mac))
    registry.async_update_device(
        current.id,
        new_connections=connections,
        via_device_id=user_input.get(CONF_VIA_DEVICE_ID) or None,
    )
