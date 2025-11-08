"""Support for Qingping CGSx offset number inputs."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, CONF_MAC, CONF_MODEL, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory

from .const import (
    DOMAIN, CONF_TEMPERATURE_OFFSET, CONF_HUMIDITY_OFFSET, DEFAULT_OFFSET, 
    CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL,
    CONF_CO2_OFFSET, CONF_PM25_OFFSET, CONF_PM10_OFFSET, 
    CONF_NOISE_OFFSET, CONF_TVOC_OFFSET, CONF_TVOC_INDEX_OFFSET,
    CONF_POWER_OFF_TIME, CONF_DISPLAY_OFF_TIME, CONF_NIGHT_MODE_START_TIME, CONF_NIGHT_MODE_END_TIME,
    CONF_AUTO_SLIDING_TIME, CONF_SCREENSAVER_TYPE,
    DEFAULT_SENSOR_OFFSET
)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Qingping CGSx number inputs from a config entry."""
    mac = config_entry.data[CONF_MAC]
    name = config_entry.data[CONF_NAME]
    model = config_entry.data[CONF_MODEL]
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    native_temp_unit = hass.config.units.temperature_unit

    device_info = {
        "identifiers": {(DOMAIN, mac)},
        "name": name,
        "manufacturer": "Qingping",
        "model": model,
    }

    entities = [
        QingpingCGSxOffsetNumber(coordinator, config_entry, mac, name, "Temp Offset", CONF_TEMPERATURE_OFFSET, device_info, native_temp_unit),
        QingpingCGSxOffsetNumber(coordinator, config_entry, mac, name, "Humidity Offset", CONF_HUMIDITY_OFFSET, device_info, "%"),
        QingpingCGSxUpdateIntervalNumber(coordinator, config_entry, mac, name, device_info),
        QingpingCGSxSensorOffsetNumber(coordinator, config_entry, mac, name, "CO2 Offset", CONF_CO2_OFFSET, device_info, "ppm"),
        QingpingCGSxSensorOffsetNumber(coordinator, config_entry, mac, name, "PM2.5 Offset", CONF_PM25_OFFSET, device_info, "µg/m³"),
        QingpingCGSxSensorOffsetNumber(coordinator, config_entry, mac, name, "PM10 Offset", CONF_PM10_OFFSET, device_info, "µg/m³"),
    ]

    # Add model-specific entities
    if model == "CGS1":
        entities.append(
            QingpingCGSxSensorOffsetNumber(coordinator, config_entry, mac, name, "TVOC Offset", CONF_TVOC_OFFSET, device_info, "ppb")
        )
    elif model == "CGS2":
        entities.extend([
            QingpingCGSxSensorOffsetNumber(coordinator, config_entry, mac, name, "Noise Offset", CONF_NOISE_OFFSET, device_info, "dB"),
            QingpingCGSxSensorOffsetNumber(coordinator, config_entry, mac, name, "TVOC Index Offset", CONF_TVOC_INDEX_OFFSET, device_info, "index"),
        ])
    elif model == "CGDN1":
        entities.extend([
            QingpingCGSxTimeNumber(coordinator, config_entry, mac, name, "Power Off Time", CONF_POWER_OFF_TIME, device_info, 0, 60, 1, 30, "minutes"),
            QingpingCGSxTimeNumber(coordinator, config_entry, mac, name, "Display Off Time", CONF_DISPLAY_OFF_TIME, device_info, 0, 300, 1, 30, "seconds"),
            QingpingCGSxTimeNumber(coordinator, config_entry, mac, name, "Auto Sliding Time", CONF_AUTO_SLIDING_TIME, device_info, 0, 180, 5, 30, "seconds"),
            QingpingCGSxScreensaverTypeNumber(coordinator, config_entry, mac, name, device_info),
        ])

    async_add_entities(entities)

class QingpingCGSxOffsetNumber(CoordinatorEntity, NumberEntity):
    """Representation of a Qingping CGSx offset number input."""

    def __init__(self, coordinator, config_entry, mac, name, offset_name, offset_key, device_info, unit_of_measurement):
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._mac = mac
        self._offset_key = offset_key
        self._attr_name = f"{name} {offset_name}"
        self._attr_unique_id = f"{mac}_{offset_key}"
        self._attr_device_info = device_info
        self._attr_native_min_value = -10
        self._attr_native_max_value = 10
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = unit_of_measurement
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_mode = NumberMode.BOX  # Use number box instead of slider

    @property
    def native_value(self) -> float:
        """Return the current value."""
        return self.coordinator.data.get(self._offset_key, DEFAULT_OFFSET)

    @property
    def mode(self) -> NumberMode:
        """Return the mode of the number entity."""
        return NumberMode.BOX

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        self.coordinator.data[self._offset_key] = value
        self.async_write_ha_state()
        
        # Update config entry
        new_data = dict(self._config_entry.data)
        new_data[self._offset_key] = value
        self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)
        
        await self.coordinator.async_request_refresh()
        
        # Publish setting change to device
        from .sensor import publish_setting_change
        if self._offset_key == CONF_TEMPERATURE_OFFSET:
            if self._attr_native_unit_of_measurement == UnitOfTemperature.FAHRENHEIT:
                    # Convert to Fahrenheit
                    temp_fahrenheit = ((32+value) - 32) * 5/9

                    value = round(float(temp_fahrenheit), 0)
            device_value = int(value * 100)
        else:  # CONF_HUMIDITY_OFFSET
            device_value = int(value * 10)
        await publish_setting_change(self.hass, self._mac, self._offset_key, device_value)

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        self._handle_coordinator_update()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self._offset_key not in self.coordinator.data:
            self.coordinator.data[self._offset_key] = self._config_entry.data.get(self._offset_key, DEFAULT_OFFSET)
        self.async_write_ha_state()

class QingpingCGSxUpdateIntervalNumber(CoordinatorEntity, NumberEntity):
    """Representation of a Qingping CGSx update interval number input."""

    def __init__(self, coordinator, config_entry, mac, name, device_info):
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._mac = mac
        self._attr_name = f"{name} Update Interval"
        self._attr_unique_id = f"{mac}_update_interval"
        self._attr_device_info = device_info
        self._attr_native_min_value = 5
        self._attr_native_max_value = 120
        self._attr_native_step = 5
        self._attr_native_unit_of_measurement = "seconds"
        self._attr_entity_category = EntityCategory.CONFIG

    @property
    def native_value(self) -> int:
        """Return the current value."""
        return self.coordinator.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)

    async def async_set_native_value(self, value: int) -> None:
        """Update the current value."""
        self.coordinator.data[CONF_UPDATE_INTERVAL] = value
        self.async_write_ha_state()

        # Update config entry
        new_data = dict(self._config_entry.data)
        new_data[CONF_UPDATE_INTERVAL] = value
        self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)
        
        await self.coordinator.async_request_refresh()

        # Publish new configuration (this uses type 12, not type 17)
        sensors = self.hass.data[DOMAIN][self._config_entry.entry_id].get("sensors", [])
        for sensor in sensors:
            if hasattr(sensor, 'publish_config'):
                await sensor.publish_config()
                break  # We only need to call it once

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        self._handle_coordinator_update()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if CONF_UPDATE_INTERVAL not in self.coordinator.data:
            self.coordinator.data[CONF_UPDATE_INTERVAL] = self._config_entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        self.async_write_ha_state()

class QingpingCGSxSensorOffsetNumber(CoordinatorEntity, NumberEntity):
    """Representation of a Qingping CGSx sensor offset number input."""

    def __init__(self, coordinator, config_entry, mac, name, offset_name, offset_key, device_info, unit_of_measurement):
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._mac = mac
        self._offset_key = offset_key
        self._attr_name = f"{name} {offset_name}"
        self._attr_unique_id = f"{mac}_{offset_key}"
        self._attr_device_info = device_info
        self._attr_native_min_value = -500
        self._attr_native_max_value = 500
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = unit_of_measurement
        self._attr_entity_category = EntityCategory.CONFIG

    @property
    def native_value(self) -> int:
        """Return the current value."""
        return self.coordinator.data.get(self._offset_key, DEFAULT_SENSOR_OFFSET)

    async def async_set_native_value(self, value: int) -> None:
        """Update the current value."""
        self.coordinator.data[self._offset_key] = value
        self.async_write_ha_state()
        
        # Update config entry
        new_data = dict(self._config_entry.data)
        new_data[self._offset_key] = value
        self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)
        
        await self.coordinator.async_request_refresh()
        
        # Publish setting change to device
        from .sensor import publish_setting_change
        await publish_setting_change(self.hass, self._mac, self._offset_key, int(value))

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        self._handle_coordinator_update()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self._offset_key not in self.coordinator.data:
            self.coordinator.data[self._offset_key] = self._config_entry.data.get(self._offset_key, DEFAULT_SENSOR_OFFSET)
        self.async_write_ha_state()

class QingpingCGSxTimeNumber(CoordinatorEntity, NumberEntity):
    """Representation of a Qingping CGSx time setting number input."""

    def __init__(self, coordinator, config_entry, mac, name, time_name, time_key, device_info, min_val, max_val, step, default_val, unit):
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._mac = mac
        self._time_key = time_key
        self._default_val = default_val
        self._attr_name = f"{name} {time_name}"
        self._attr_unique_id = f"{mac}_{time_key}"
        self._attr_device_info = device_info
        self._attr_native_min_value = min_val
        self._attr_native_max_value = max_val
        self._attr_native_step = step
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_native_unit_of_measurement = unit

    @property
    def native_value(self) -> int:
        """Return the current value."""
        return self.coordinator.data.get(self._time_key, self._default_val)

    async def async_set_native_value(self, value: int) -> None:
        """Update the current value."""
        self.coordinator.data[self._time_key] = value
        self.async_write_ha_state()
        
        # Update config entry
        new_data = dict(self._config_entry.data)
        new_data[self._time_key] = value
        self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)
        
        await self.coordinator.async_request_refresh()
        
        # Publish setting change to device
        from .sensor import publish_setting_change
        await publish_setting_change(self.hass, self._mac, self._time_key, int(value))

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        self._handle_coordinator_update()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self._time_key not in self.coordinator.data:
            self.coordinator.data[self._time_key] = self._config_entry.data.get(self._time_key, self._default_val)
        self.async_write_ha_state()

class QingpingCGSxScreensaverTypeNumber(CoordinatorEntity, NumberEntity):
    """Representation of a Qingping CGSx screensaver type number input."""

    def __init__(self, coordinator, config_entry, mac, name, device_info):
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._mac = mac
        self._attr_name = f"{name} Screensaver Type"
        self._attr_unique_id = f"{mac}_screensaver_type"
        self._attr_device_info = device_info
        self._attr_native_min_value = 0
        self._attr_native_max_value = 3
        self._attr_native_step = 1
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_mode = NumberMode.BOX  # Use number box instead of slider

    @property
    def native_value(self) -> int:
        """Return the current value."""
        return self.coordinator.data.get(CONF_SCREENSAVER_TYPE, 1)

    async def async_set_native_value(self, value: int) -> None:
        """Update the current value."""
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