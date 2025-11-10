"""Support for Qingping CGSx sensors."""
from __future__ import annotations

import json
import logging
from datetime import timedelta
import time
import asyncio

from homeassistant.components import mqtt
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, CONF_MAC, CONF_MODEL, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.entity import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DOMAIN, MQTT_TOPIC_PREFIX,
    SENSOR_BATTERY, SENSOR_CO2, SENSOR_HUMIDITY, SENSOR_PM10, SENSOR_PM25, SENSOR_TEMPERATURE, SENSOR_TVOC, SENSOR_ETVOC,
    PERCENTAGE, PPM, PPB, CONCENTRATION, CONF_TVOC_UNIT, CONF_ETVOC_UNIT, SENSOR_NOISE, DB,
    CONF_TEMPERATURE_OFFSET, CONF_HUMIDITY_OFFSET, CONF_UPDATE_INTERVAL,
    ATTR_TYPE, ATTR_UP_ITVL, ATTR_DURATION,
    DEFAULT_TYPE, DEFAULT_DURATION
)

_LOGGER = logging.getLogger(__name__)

OFFLINE_TIMEOUT = 300  # 5 minutes in seconds
MQTT_PUBLISH_RETRY_LIMIT = 3
MQTT_PUBLISH_RETRY_DELAY = 5  # seconds
SETTING_CHANGE_DELAY = 5  # seconds delay before publishing setting changes

# Store pending setting publishes to debounce rapid changes
_pending_setting_publishes = {}

async def ensure_mqtt_connected(hass):
    """Ensure MQTT is connected before publishing."""
    for _ in range(5):  # Try up to 5 times
        if mqtt.is_connected(hass):
            return True
        await asyncio.sleep(1)
    return False

async def publish_setting_change(hass: HomeAssistant, mac: str, setting_key: str, value: any) -> None:
    """Publish a single setting change to the device with debounce."""
    # Cancel any pending publish for this setting
    publish_key = f"{mac}_{setting_key}"
    if publish_key in _pending_setting_publishes:
        _pending_setting_publishes[publish_key].cancel()
    
    async def _delayed_publish():
        """Publish after delay."""
        try:
            await asyncio.sleep(SETTING_CHANGE_DELAY)
            
            if not await ensure_mqtt_connected(hass):
                _LOGGER.error("MQTT is not connected, cannot publish setting change")
                return
            
            payload = {
                "type": "17",
                "setting": {
                    setting_key: value
                }
            }
            
            topic = f"{MQTT_TOPIC_PREFIX}/{mac}/down"
            await mqtt.async_publish(hass, topic, json.dumps(payload))
            _LOGGER.info("Published setting change to %s: %s = %s", mac, setting_key, value)
            
        except Exception as err:
            _LOGGER.error("Failed to publish setting change: %s", err)
        finally:
            # Clean up the pending publish
            if publish_key in _pending_setting_publishes:
                del _pending_setting_publishes[publish_key]
    
    # Schedule the delayed publish
    task = asyncio.create_task(_delayed_publish())
    _pending_setting_publishes[publish_key] = task

async def _update_settings_from_device(hass: HomeAssistant, config_entry: ConfigEntry, settings: dict, model: str) -> None:
    """Update Home Assistant entities when settings are changed on the device."""
    _LOGGER.info("Starting _update_settings_from_device with settings: %s", settings)
    
    from .const import (
        CONF_TEMPERATURE_OFFSET, CONF_HUMIDITY_OFFSET,
        CONF_CO2_OFFSET, CONF_PM25_OFFSET, CONF_PM10_OFFSET,
        CONF_NOISE_OFFSET, CONF_TVOC_OFFSET, CONF_TVOC_INDEX_OFFSET,
        CONF_POWER_OFF_TIME, CONF_DISPLAY_OFF_TIME, CONF_NIGHT_MODE_START_TIME,
        CONF_NIGHT_MODE_END_TIME, CONF_AUTO_SLIDING_TIME, CONF_SCREENSAVER_TYPE,
        CONF_CO2_ASC
    )
    
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    updated = False
    
    # Map device settings to HA entity keys and conversion functions
    setting_mappings = {
        # Temperature offset: device sends value * 100, we need to divide by 100
        "temperature_offset": (CONF_TEMPERATURE_OFFSET, lambda x: round(x / 100, 1)),
        # Humidity offset: device sends value * 10, we need to divide by 10
        "humidity_offset": (CONF_HUMIDITY_OFFSET, lambda x: round(x / 10, 1)),
        # Other offsets: direct integer values
        "co2_offset": (CONF_CO2_OFFSET, int),
        "pm25_offset": (CONF_PM25_OFFSET, int),
        "pm10_offset": (CONF_PM10_OFFSET, int),
        "noise_offset": (CONF_NOISE_OFFSET, int),
        "tvoc_zoom": (CONF_TVOC_OFFSET, lambda x: round(x / 10, 1)),
        "tvoc_index_offset": (CONF_TVOC_INDEX_OFFSET, int),
        # CGDN1 specific settings
        "power_off_time": (CONF_POWER_OFF_TIME, int),
        "display_off_time": (CONF_DISPLAY_OFF_TIME, int),
        "night_mode_start_time": (CONF_NIGHT_MODE_START_TIME, int),
        "night_mode_end_time": (CONF_NIGHT_MODE_END_TIME, int),
        "auto_slideing_time": (CONF_AUTO_SLIDING_TIME, int),
        "screensaver_type": (CONF_SCREENSAVER_TYPE, int),
        "co2_asc": (CONF_CO2_ASC, int),
    }
    
    for device_key, value in settings.items():
        _LOGGER.info("Processing setting: %s = %s", device_key, value)
        if device_key in setting_mappings:
            ha_key, converter = setting_mappings[device_key]
            try:
                converted_value = converter(value)
                _LOGGER.info("Converted %s: %s -> %s", device_key, value, converted_value)
                
                # Update coordinator data
                if coordinator.data.get(ha_key) != converted_value:
                    coordinator.data[ha_key] = converted_value
                    updated = True
                    _LOGGER.info("Updated %s from device: %s", ha_key, converted_value)
                    
                    # Update config entry
                    new_data = dict(config_entry.data)
                    new_data[ha_key] = converted_value
                    hass.config_entries.async_update_entry(config_entry, data=new_data)
                else:
                    _LOGGER.info("Setting %s already has value %s, no update needed", ha_key, converted_value)
                    
            except (ValueError, TypeError) as err:
                _LOGGER.error("Failed to convert setting %s with value %s: %s", device_key, value, err)
        else:
            _LOGGER.warning("Unknown setting key from device: %s", device_key)
    
    # Refresh coordinator to update all entities
    if updated:
        _LOGGER.info("Settings updated, refreshing coordinator")
        await coordinator.async_request_refresh()
    else:
        _LOGGER.info("No settings were updated")

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Qingping CGSx sensor based on a config entry."""
    mac = config_entry.data[CONF_MAC]
    name = config_entry.data[CONF_NAME]
    model = config_entry.data[CONF_MODEL]
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    native_temp_unit = hass.config.units.temperature_unit

    async def async_update_data():
        """Fetch data from API endpoint."""
        # This is a placeholder. In a real scenario, you might
        # fetch data from an API or process local data here.
        return {}

    device_info = {
        "identifiers": {(DOMAIN, mac)},
        "name": name,
        "manufacturer": "Qingping",
        "model": model,
    }

    status_sensor = QingpingCGSxStatusSensor(coordinator, config_entry, mac, name, device_info)
    firmware_sensor = QingpingCGSxFirmwareSensor(coordinator, config_entry, mac, name, device_info)
    type_sensor = QingpingCGSxTypeSensor(coordinator, config_entry, mac, name, device_info)
    mac_sensor = QingpingCGSxMACSensor(coordinator, config_entry, mac, name, device_info)
    battery_state = QingpingCGSxBatteryStateSensor(coordinator, config_entry, mac, name, device_info)

    sensors = [
        status_sensor,
        firmware_sensor,
        type_sensor,
        mac_sensor,
        battery_state,
        QingpingCGSxSensor(coordinator, config_entry, mac, name, SENSOR_BATTERY, "Battery", PERCENTAGE, SensorDeviceClass.BATTERY, SensorStateClass.MEASUREMENT, device_info),
        QingpingCGSxSensor(coordinator, config_entry, mac, name, SENSOR_CO2, "CO2", PPM, SensorDeviceClass.CO2, SensorStateClass.MEASUREMENT, device_info),
        QingpingCGSxSensor(coordinator, config_entry, mac, name, SENSOR_HUMIDITY, "Humidity", PERCENTAGE, SensorDeviceClass.HUMIDITY, SensorStateClass.MEASUREMENT, device_info),
        QingpingCGSxSensor(coordinator, config_entry, mac, name, SENSOR_PM10, "PM10", CONCENTRATION, SensorDeviceClass.PM10, SensorStateClass.MEASUREMENT, device_info),
        QingpingCGSxSensor(coordinator, config_entry, mac, name, SENSOR_PM25, "PM25", CONCENTRATION, SensorDeviceClass.PM25, SensorStateClass.MEASUREMENT, device_info),
        QingpingCGSxSensor(coordinator, config_entry, mac, name, SENSOR_TEMPERATURE, "Temperature", native_temp_unit, SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, device_info),

    ]

    if model == "CGS1":
        sensors.append(QingpingCGSxSensor(coordinator, config_entry, mac, name, SENSOR_TVOC, "TVOC", PPB, SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS, SensorStateClass.MEASUREMENT, device_info))
    elif model == "CGS2":
        sensors.append(QingpingCGSxSensor(coordinator, config_entry, mac, name, SENSOR_ETVOC, "eTVOC", None, SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS, SensorStateClass.MEASUREMENT, device_info))
        sensors.append(QingpingCGSxSensor(coordinator, config_entry, mac, name, SENSOR_NOISE, "Noise", DB, SensorDeviceClass.SOUND_PRESSURE, SensorStateClass.MEASUREMENT, device_info))
    # CGDN1 has the same sensors as CGS1 (no TVOC, no Noise)

    async_add_entities(sensors)

    # Store sensors in hass.data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(config_entry.entry_id, {})
    hass.data[DOMAIN][config_entry.entry_id]["sensors"] = sensors

    @callback
    def message_received(message):
        """Handle new MQTT messages."""
        try:
            payload = json.loads(message.payload)
            
            if not isinstance(payload, dict):
                _LOGGER.error("Payload is not a dictionary")
                return

            # Check message type first - type 28 (settings) messages don't include MAC
            message_type = payload.get("type")
            
            # For messages with MAC, verify it matches
            received_mac = payload.get("mac", "").replace(":", "").upper()
            expected_mac = mac.replace(":", "").upper()
            
            # Skip MAC check for messages without MAC (type 28, 13, 10, 17, etc.)
            # We're subscribed to this device's specific topic, so we know it's for us
            if received_mac and received_mac != expected_mac:
                _LOGGER.debug("Received message for a different device. Expected: %s, Got: %s", expected_mac, received_mac)
                return
            
            _LOGGER.debug("Processing MQTT message type %s for device %s", message_type, mac)
            
            # Update timestamp first - any message from device means it's online
            # Always use current system time, not device's timestamp which may be unreliable
            current_timestamp = int(time.time())
            if status_sensor.hass:
                status_sensor.update_timestamp(current_timestamp)

            firmware_version = payload.get("version")
            if firmware_version is not None:
                if firmware_sensor.hass:
                    firmware_sensor.update_version(firmware_version)

            device_type = payload.get("type")
            if device_type is not None:
                if type_sensor.hass:
                    type_sensor.update_type(device_type)

            mac_address = payload.get("mac")
            if mac_address is not None:
                if mac_sensor.hass:
                    mac_sensor.update_mac(mac_address)

            # Handle type 28 messages (device settings update) - Check BEFORE sensorData
            if message_type == 28 or message_type == "28":
                _LOGGER.info("Type 28 settings update received for device %s", mac)
                settings = payload.get("setting", {})
                if settings:
                    hass.async_create_task(_update_settings_from_device(hass, config_entry, settings, model))
                else:
                    _LOGGER.warning("Type 28 message has no settings dict")
                return  # Don't process as sensor data

            sensor_data = payload.get("sensorData")
            if not isinstance(sensor_data, list) or not sensor_data:
                _LOGGER.debug("No valid sensorData in payload, possibly a config response or device just powered on")
                # Device is online, just waiting for sensor data
                return
            if len(sensor_data) == 1:
                #ignore type 17 sensor data                
                for data in sensor_data:
                    battery_charging = None
                    battery_status = None
                    if SENSOR_BATTERY in data:
                        battery_data = data[SENSOR_BATTERY]
                        if isinstance(battery_data, dict):
                            battery_status = battery_data.get("status")
                            if battery_status is not None:
                                battery_charging = (battery_status == 1)  # Explicitly True or False
                    
                    # Update battery state sensor first if we have status
                    if battery_status is not None and battery_state.hass:
                        battery_state.update_battery_state(battery_status)
                    
                    for sensor in sensors[5:]:  # Skip status, firmware, mac, type, and battery_state sensors
                        if not sensor.hass:
                            continue
                        if sensor._sensor_type in data:
                            sensor_data = data[sensor._sensor_type]
                            if isinstance(sensor_data, dict):
                                value = sensor_data.get("value")
                                status = sensor_data.get("status")
                                # Check if PM sensor is disabled (value=99999)
                                if sensor._sensor_type in [SENSOR_PM10, SENSOR_PM25] and value == 99999:
                                    sensor.set_unavailable()
                                elif value is not None:
                                    sensor.update_from_latest_data(value)
                                    if sensor._sensor_type == SENSOR_BATTERY and battery_charging is not None:
                                        sensor.update_battery_charging(battery_charging)
                            else:
                                # Handle non-dict values (backward compatibility)
                                value = sensor_data
                                if value is not None:
                                    sensor.update_from_latest_data(value)
                                    if sensor._sensor_type == SENSOR_BATTERY and battery_charging is not None:
                                        sensor.update_battery_charging(battery_charging)
            else:
                _LOGGER.info("sensorData is type 17")
                return

        except json.JSONDecodeError:
            _LOGGER.error("Invalid JSON in MQTT message: %s", message.payload)
        except Exception as e:
            _LOGGER.error("Error processing MQTT message: %s", str(e))

    await mqtt.async_subscribe(
        hass, f"{MQTT_TOPIC_PREFIX}/{mac}/up", message_received, 1
    )
    _LOGGER.info("Subscribed to MQTT topic: %s/%s/up", MQTT_TOPIC_PREFIX, mac)

    # Set up timer for periodic publishing
    async def publish_config_wrapper(*args):
        if await ensure_mqtt_connected(hass):
            # Don't force status to online - let actual device messages determine status
            await sensors[5].publish_config()
        else:
            _LOGGER.error("Failed to connect to MQTT for periodic config publish")

    hass.data[DOMAIN][config_entry.entry_id]["remove_timer"] = async_track_time_interval(
        hass, publish_config_wrapper, timedelta(seconds=int(DEFAULT_DURATION))
    )

    # Publish config immediately upon setup with a delay to ensure entities are ready
    async def delayed_publish():
        await asyncio.sleep(2)  # Wait 2 seconds for entities to be fully added
        if await ensure_mqtt_connected(hass):
            await publish_config_wrapper()
        else:
            _LOGGER.error("Failed to connect to MQTT for initial config publish")
    
    asyncio.create_task(delayed_publish())

class QingpingCGSxStatusSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Qingping CGSx status sensor."""

    def __init__(self, coordinator, config_entry, mac, name, device_info):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._mac = mac
        self._attr_name = f"{name} Status"
        self._attr_unique_id = f"{mac}_status"
        self._attr_device_info = device_info
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_native_value = "offline"
        self._last_timestamp = 0
        self._last_status = "online"

    @callback
    def update_timestamp(self, timestamp):
        """Update the last received timestamp."""
        old_timestamp = self._last_timestamp
        self._last_timestamp = int(timestamp)
        old_status = self._attr_native_value
        if old_timestamp == 0 or old_status == "offline":
            _LOGGER.info("Device %s came online (timestamp: %s)", self._mac, timestamp)
        self._update_status()
        # Log if status changed unexpectedly
        if old_status == "online" and self._attr_native_value == "offline":
            _LOGGER.error("Device %s immediately went offline after timestamp update! old_ts=%s, new_ts=%s, current_time=%s", 
                         self._mac, old_timestamp, self._last_timestamp, int(time.time()))

    @callback
    def _update_status(self):
        """Update the status based on the last timestamp."""
        if not self.hass:
            return
            
        current_time = int(time.time())
        time_since_last_msg = current_time - self._last_timestamp
        new_status = "online" if time_since_last_msg <= OFFLINE_TIMEOUT else "offline"
        if self._attr_native_value != new_status:
            old_status = self._attr_native_value
            self._attr_native_value = new_status
            self.async_write_ha_state()
            _LOGGER.info("Device %s status changed from %s to %s (time since last message: %s seconds)", 
                        self._mac, old_status, new_status, time_since_last_msg)
            
            # Update other sensors' availability
            sensors = self.hass.data[DOMAIN][self._config_entry.entry_id].get("sensors", [])
            for sensor in sensors:
                if isinstance(sensor, QingpingCGSxSensor) and sensor.hass:
                    sensor.async_write_ha_state()
            
            # Call publish_config when status changes from offline to online
            if self._last_status == "offline" and new_status == "online":
                _LOGGER.info("Device %s recovered from offline, publishing config", self._mac)
                asyncio.create_task(self._publish_config_on_status_change())
            
            self._last_status = new_status

    async def _publish_config_on_status_change(self):
        """Publish config when status changes from offline to online."""
        if not self.hass:
            return
        # Add a small delay to let the device fully come online
        await asyncio.sleep(2)
        sensors = self.hass.data[DOMAIN][self._config_entry.entry_id].get("sensors", [])
        for sensor in sensors:
            if isinstance(sensor, QingpingCGSxSensor):
                await sensor.publish_config()
                break  # We only need to call it once                

    async def async_added_to_hass(self):
        """Set up a timer to regularly update the status."""
        await super().async_added_to_hass()

        # Immediately check if we should be online based on recent activity
        self._update_status()

        async def update_status(*_):
            self._update_status()

        self.async_on_remove(async_track_time_interval(
            self.hass, update_status, timedelta(seconds=60)
        ))

class QingpingCGSxFirmwareSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Qingping CGSx firmware sensor."""

    def __init__(self, coordinator, config_entry, mac, name, device_info):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._mac = mac
        self._attr_name = f"{name} Firmware"
        self._attr_unique_id = f"{mac}_firmware"
        self._attr_device_info = device_info
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_native_value = None

    @callback
    def update_version(self, version):
        """Update the firmware version."""
        self._attr_native_value = version
        self.async_write_ha_state()

class QingpingCGSxMACSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Qingping CGSx mac sensor."""

    def __init__(self, coordinator, config_entry, mac, name, device_info):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._mac = mac
        self._attr_name = f"{name} MAC Address"
        self._attr_unique_id = f"{mac}_mac"
        self._attr_device_info = device_info
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_native_value = None

    @callback
    def update_mac(self, mac):
        """Update the mac address."""
        self._attr_native_value = mac
        self.async_write_ha_state()

class QingpingCGSxBatteryStateSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Qingping CGSx battery state sensor."""

    def __init__(self, coordinator, config_entry, mac, name, device_info):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._mac = mac
        self._attr_name = f"{name} Battery State"
        self._attr_unique_id = f"{mac}_battery_state"
        self._attr_device_info = device_info
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_native_value = "Discharging"

    @callback
    def update_battery_state(self, status):
        """Update the battery state."""
        if status == 1:
            self._attr_native_value = "Charging"
        elif status == 2:
            self._attr_native_value = "Fully Charged"
        elif status == 0:
            self._attr_native_value = "Discharging"
        else:
            self._attr_native_value = "Unknown"
        self.async_write_ha_state()

class QingpingCGSxTypeSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Qingping CGSx type sensor."""

    def __init__(self, coordinator, config_entry, mac, name, device_info):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._mac = mac
        self._attr_name = f"{name} Report Type"
        self._attr_unique_id = f"{mac}_report_type"
        self._attr_device_info = device_info
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_native_value = None
        self._attr_force_update = False
        self._attr_entity_registry_enabled_default = False

    @callback
    def update_type(self, device_type):
        """Update the device type."""
        self._attr_native_value = device_type
        self.async_write_ha_state()

class QingpingCGSxSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Qingping CGSx sensor."""

    def __init__(self, coordinator, config_entry, mac, name, sensor_type, cln_name, unit, device_class, state_class, device_info):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._mac = mac
        self._sensor_type = sensor_type
        self._attr_name = f"{name} {cln_name}"
        self._attr_unique_id = f"{mac}_{sensor_type}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_device_info = device_info
        self._battery_charging = False
        self._is_unavailable = False

    @callback
    def update_from_latest_data(self, value):
        """Update the sensor with the latest data."""
        try:
            if self._sensor_type == SENSOR_TEMPERATURE:
                offset = self.coordinator.data.get(CONF_TEMPERATURE_OFFSET, 0)
                temp_celsius = float(value)
                if self._attr_native_unit_of_measurement == UnitOfTemperature.FAHRENHEIT:
                    # Convert to Fahrenheit
                    temp_fahrenheit = (temp_celsius * 9/5) + 32
                    self._attr_native_value = round(float(temp_fahrenheit), 1)
                else:
                    self._attr_native_value = round(float(temp_celsius), 1)
            elif self._sensor_type == SENSOR_HUMIDITY:
                offset = self.coordinator.data.get(CONF_HUMIDITY_OFFSET, 0)
                self._attr_native_value = round(float(value), 1)
            elif self._sensor_type == SENSOR_ETVOC:
                etvoc_unit = self.coordinator.data.get(CONF_ETVOC_UNIT, "index")
                etvoc_value = int(value)
                if etvoc_unit == "ppb":
                    # Convert VOC index to ppb (this is an approximate conversion)
                    etvoc_value = (etvoc_value * 5) + 35
                elif etvoc_unit == "mg/m³":
                    # Convert VOC index to mg/m³ (this is an approximate conversion)
                    etvoc_value = (etvoc_value * 0.023) + 0.124
                self._attr_native_value = round(etvoc_value, 3)
                self._attr_native_unit_of_measurement = etvoc_unit
            elif self._sensor_type == SENSOR_TVOC:
                tvoc_unit = self.coordinator.data.get(CONF_TVOC_UNIT, "ppb")
                tvoc_value = int(value)
                if tvoc_unit == "ppm":
                    tvoc_value /= 1000
                elif tvoc_unit == "mg/m³":
                    tvoc_value /= 218.77
                    # tvoc_value /= 1000 
                    # tvoc_value *= 0.0409 
                    # tvoc_value *= 111.1  # Approximate conversion factor
                self._attr_native_value = round(tvoc_value, 3)
                self._attr_native_unit_of_measurement = tvoc_unit
            else:
                self._attr_native_value = int(value)
            self._is_unavailable = False
            self.async_write_ha_state()
        except ValueError:
            _LOGGER.error("Invalid value received for %s: %s", self._sensor_type, value)

    @callback
    def update_battery_charging(self, is_charging):
        """Update the battery charging state."""
        if self._sensor_type == SENSOR_BATTERY:
            self._battery_charging = is_charging
            self.async_write_ha_state()

    @callback
    def set_unavailable(self):
        """Set sensor as unavailable."""
        self._is_unavailable = True
        self._attr_native_value = None
        self.async_write_ha_state()

    @property
    def icon(self):
        """Return the icon of the sensor."""
        if self._sensor_type == SENSOR_BATTERY:
            if self._battery_charging:
                return "mdi:battery-charging"
            elif self._attr_native_value is not None:
                battery_level = int(self._attr_native_value)
                if battery_level <= 10:
                    return "mdi:battery-10"
                elif battery_level <= 20:
                    return "mdi:battery-20"
                elif battery_level <= 30:
                    return "mdi:battery-30"
                elif battery_level <= 40:
                    return "mdi:battery-40"
                elif battery_level <= 50:
                    return "mdi:battery-50"
                elif battery_level <= 60:
                    return "mdi:battery-60"
                elif battery_level <= 70:
                    return "mdi:battery-70"
                elif battery_level <= 80:
                    return "mdi:battery-80"
                elif battery_level <= 90:
                    return "mdi:battery-90"
                else:
                    return "mdi:battery"
        return super().icon

    async def publish_config(self):
        """Publish configuration message to MQTT."""
        update_interval = self.coordinator.data.get(CONF_UPDATE_INTERVAL, 15)
        payload = {
            ATTR_TYPE: DEFAULT_TYPE,
            ATTR_UP_ITVL: f"{int(update_interval)}",
            ATTR_DURATION: DEFAULT_DURATION
        }
        topic = f"{MQTT_TOPIC_PREFIX}/{self._mac}/down"

        for attempt in range(MQTT_PUBLISH_RETRY_LIMIT):
            if not await ensure_mqtt_connected(self.hass):
                _LOGGER.error("MQTT is not connected after multiple attempts")
                return

            try:
                await mqtt.async_publish(self.hass, topic, json.dumps(payload))
                _LOGGER.info(f"Published config to {topic}: {payload}")
                return
            except HomeAssistantError as err:
                _LOGGER.warning(f"Failed to publish config (attempt {attempt + 1}): {err}")
                if attempt < MQTT_PUBLISH_RETRY_LIMIT - 1:
                    await asyncio.sleep(MQTT_PUBLISH_RETRY_DELAY)
                else:
                    _LOGGER.error(f"Failed to publish config after {MQTT_PUBLISH_RETRY_LIMIT} attempts")

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        if not self.hass:
            return False
        sensors = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id, {}).get("sensors", [])
        status_sensor = next((sensor for sensor in sensors if isinstance(sensor, QingpingCGSxStatusSensor)), None)
        is_online = status_sensor.native_value == "online" if status_sensor else False
        
        # For PM sensors, also check if they are disabled
        if self._sensor_type in [SENSOR_PM10, SENSOR_PM25]:
            return is_online and not self._is_unavailable
        
        return is_online

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()

    async def async_will_remove_from_hass(self) -> None:
        """Clean up the timer when entity is removed."""
        if self.hass and self._config_entry.entry_id in self.hass.data.get(DOMAIN, {}):
            remove_timer = self.hass.data[DOMAIN][self._config_entry.entry_id].get("remove_timer")
            if remove_timer:
                remove_timer()
        await super().async_will_remove_from_hass()