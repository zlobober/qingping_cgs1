"""Support for Qingping CGSx button entities."""
from __future__ import annotations

import json
import logging

from homeassistant.components import mqtt
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, CONF_MAC, CONF_MODEL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, MQTT_TOPIC_PREFIX

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Qingping CGSx button entities from a config entry."""
    mac = config_entry.data[CONF_MAC]
    name = config_entry.data[CONF_NAME]
    model = config_entry.data[CONF_MODEL]

    device_info = {
        "identifiers": {(DOMAIN, mac)},
        "name": name,
        "manufacturer": "Qingping",
        "model": model,
    }

    buttons = []

    # CGDN1-specific buttons
    if model == "CGDN1":
        buttons.append(
            QingpingCGSxManualCalibrationButton(config_entry, mac, name, device_info)
        )

    if buttons:
        async_add_entities(buttons)


class QingpingCGSxManualCalibrationButton(ButtonEntity):
    """Button to trigger manual CO2 calibration."""

    def __init__(self, config_entry, mac, name, device_info):
        """Initialize the button."""
        self._config_entry = config_entry
        self._mac = mac
        self._attr_name = f"{name} Manual Calibration"
        self._attr_unique_id = f"{mac}_manual_calibration"
        self._attr_device_info = device_info
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_icon = "mdi:tune-vertical"

    async def async_press(self) -> None:
        """Handle the button press."""
        try:
            payload = {"type": "29"}
            topic = f"{MQTT_TOPIC_PREFIX}/{self._mac}/down"
            
            _LOGGER.info("Triggering manual calibration for %s", self._mac)
            await mqtt.async_publish(self.hass, topic, json.dumps(payload))
            
        except Exception as err:
            _LOGGER.error("Failed to trigger manual calibration: %s", err)
            raise HomeAssistantError(f"Failed to trigger calibration: {err}")