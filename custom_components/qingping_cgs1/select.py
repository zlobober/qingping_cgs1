"""Support for Qingping CGSx select entities."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, CONF_MAC, CONF_MODEL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN, CONF_TVOC_UNIT, CONF_ETVOC_UNIT, CONF_SCREENSAVER_TYPE

TVOC_UNIT_OPTIONS = ["ppb", "ppm", "mg/m³"]
ETVOC_UNIT_OPTIONS = ["index", "ppb", "mg/m³"]

# Mapping between display names and values for screensaver types
SCREENSAVER_OPTIONS = {
    "All sensors": 0,
    "Current sensor": 1,
    "Clock and all sensors": 2,
    "Clock and current sensor": 3,
}

# Reverse mapping for looking up names from values
SCREENSAVER_VALUES = {v: k for k, v in SCREENSAVER_OPTIONS.items()}

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Qingping CGSx select entities from a config entry."""
    mac = config_entry.data[CONF_MAC]
    name = config_entry.data[CONF_NAME]
    model = config_entry.data[CONF_MODEL]
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]

    device_info = {
        "identifiers": {(DOMAIN, mac)},
        "name": name,
        "manufacturer": "Qingping",
        "model": model,
    }

    entities = []

    if model == "CGS1":
        entities.append(
            QingpingCGSxTVOCUnitSelect(coordinator, config_entry, mac, name, device_info, CONF_TVOC_UNIT, TVOC_UNIT_OPTIONS)
        )
    elif model == "CGS2":
        entities.append(
            QingpingCGSxTVOCUnitSelect(coordinator, config_entry, mac, name, device_info, CONF_ETVOC_UNIT, ETVOC_UNIT_OPTIONS)
        )
    elif model == "CGDN1":
        entities.append(
            QingpingCGSxScreensaverTypeSelect(coordinator, config_entry, mac, name, device_info)
        )

    if entities:
        async_add_entities(entities)

class QingpingCGSxTVOCUnitSelect(CoordinatorEntity, SelectEntity):
    """Representation of a Qingping CGSx TVOC unit select entity."""

    def __init__(self, coordinator, config_entry, mac, name, device_info, conf_unit, unit_options):
        """Initialize the select entity."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._mac = mac
        self._conf_unit = conf_unit
        self._unit_options = unit_options
        self._attr_name = f"{name} {'eTVOC' if conf_unit == CONF_ETVOC_UNIT else 'TVOC'} Unit"
        self._attr_unique_id = f"{mac}_{conf_unit}"
        self._attr_device_info = device_info
        self._attr_options = unit_options
        self._attr_entity_category = EntityCategory.CONFIG

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        return self.coordinator.data.get(self._conf_unit, self._unit_options[0])

    async def async_select_option(self, option: str) -> None:
        """Update the current selected option."""
        self.coordinator.data[self._conf_unit] = option
        self.async_write_ha_state()

        # Update config entry
        new_data = dict(self._config_entry.data)
        new_data[self._conf_unit] = option
        self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)

        await self.coordinator.async_request_refresh()

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        self._handle_coordinator_update()

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if CONF_TVOC_UNIT not in self.coordinator.data:
            self.coordinator.data[self._conf_unit] = self._config_entry.data.get(self._conf_unit, self._unit_options[0])
        self.async_write_ha_state()

class QingpingCGSxScreensaverTypeSelect(CoordinatorEntity, SelectEntity):
    """Representation of a Qingping CGSx screensaver type select input."""

    def __init__(self, coordinator, config_entry, mac, name, device_info):
        """Initialize the select entity."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._mac = mac
        self._attr_name = f"{name} Screensaver Type"
        self._attr_unique_id = f"{mac}_screensaver_type"
        self._attr_device_info = device_info
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_options = list(SCREENSAVER_OPTIONS.keys())

    @property
    def current_option(self) -> str:
        """Return the current option."""
        value = self.coordinator.data.get(CONF_SCREENSAVER_TYPE, 1)
        return SCREENSAVER_VALUES.get(value, "Current sensor")

    async def async_select_option(self, option: str) -> None:
        """Update the current option."""
        value = SCREENSAVER_OPTIONS.get(option)
        if value is None:
            return
        
        self.coordinator.data[CONF_SCREENSAVER_TYPE] = value
        self.async_write_ha_state()
        
        # Update config entry
        new_data = dict(self._config_entry.data)
        new_data[CONF_SCREENSAVER_TYPE] = value
        self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)
        
        await self.coordinator.async_request_refresh()
        
        # Publish setting change to device
        from .sensor import publish_setting_change
        await publish_setting_change(self.hass, self._mac, CONF_SCREENSAVER_TYPE, int(value))

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        self._handle_coordinator_update()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if CONF_SCREENSAVER_TYPE not in self.coordinator.data:
            self.coordinator.data[CONF_SCREENSAVER_TYPE] = self._config_entry.data.get(CONF_SCREENSAVER_TYPE, 1)
        self.async_write_ha_state()