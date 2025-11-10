"""Constants for the Qingping CGSx integration."""

DOMAIN = "qingping_cgs1"
CONF_MAC = "mac"
CONF_NAME = "name"
CONF_MODEL = "model"

# Sensor types
SENSOR_BATTERY = "battery"
SENSOR_CO2 = "co2"
SENSOR_HUMIDITY = "humidity"
SENSOR_PM10 = "pm10"
SENSOR_PM25 = "pm25"
SENSOR_TEMPERATURE = "temperature"
SENSOR_TVOC = "tvoc"
SENSOR_ETVOC = "tvoc_index"
SENSOR_NOISE = "noise"

# Unit of measurement
PERCENTAGE = "%"
PPM = "ppm"
CONCENTRATION = "µg/m³"
PPB = "ppb"
DB = "dB"
CONF_TVOC_UNIT = "tvoc_unit"
CONF_ETVOC_UNIT = "etvoc_unit"

# Offsets
CONF_TEMPERATURE_OFFSET = "temperature_offset"
CONF_HUMIDITY_OFFSET = "humidity_offset"
CONF_UPDATE_INTERVAL = "update_interval"

# Default values for offsets and update interval
DEFAULT_OFFSET = 0
DEFAULT_UPDATE_INTERVAL = 15

# MQTT topics
MQTT_TOPIC_PREFIX = "qingping"

# Configuration message
ATTR_TYPE = "type"
ATTR_UP_ITVL = "up_itvl"
ATTR_DURATION = "duration"

DEFAULT_TYPE = "12"
DEFAULT_DURATION = "86400"

QP_MODELS = ["CGS1", "CGS2", "CGDN1"]
DEFAULT_MODEL = "CGS1"

# Device-specific settings
CONF_CO2_ASC = "co2_asc"
CONF_CO2_OFFSET = "co2_offset"
CONF_PM25_OFFSET = "pm25_offset"
CONF_PM10_OFFSET = "pm10_offset"
CONF_NOISE_OFFSET = "noise_offset"
CONF_TVOC_OFFSET = "tvoc_zoom"
CONF_TVOC_INDEX_OFFSET = "tvoc_index_zoom"

# Default values for device settings
DEFAULT_SENSOR_OFFSET = 0

# CGDN1 specific settings
CONF_POWER_OFF_TIME = "power_off_time"
CONF_DISPLAY_OFF_TIME = "display_off_time"
CONF_NIGHT_MODE_START_TIME = "night_mode_start_time"
CONF_NIGHT_MODE_END_TIME = "night_mode_end_time"
CONF_AUTO_SLIDING_TIME = "auto_slideing_time"
CONF_SCREENSAVER_TYPE = "screensaver_type"
CONF_TIMEZONE = "timezone"