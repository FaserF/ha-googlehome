"""Constants for Google Home integration."""

from __future__ import annotations

from typing import Final

NAME: Final = "Google Home"
DOMAIN: Final = "google_home"
DOMAIN_DATA: Final = f"{DOMAIN}_data"
MANUFACTURER: Final = "Google"

ATTRIBUTION: Final = "Data provided by Google Home local API"
CONF_UPDATE_INTERVAL: Final = "update_interval"
DEFAULT_UPDATE_INTERVAL: Final = 60
DEFAULT_TIMEOUT: Final = 10

CONF_ANDROID_ID: Final = "android_id"
CONF_MASTER_TOKEN: Final = "master_token"
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"
CONF_AUTH_METHOD: Final = "auth_method"

AUTH_METHOD_TOKEN: Final = "token"
AUTH_METHOD_APP_PASSWORD: Final = "app_password"
AUTH_METHOD_ADDON: Final = "addon"
AUTH_METHOD_PASSWORD: Final = "password"
AUTH_METHOD_CREDENTIALS: Final = "credentials"

CONF_ADDON_HOST: Final = "addon_host"
CONF_ADDON_PORT: Final = "addon_port"
CONF_ADDON_ACTION: Final = "addon_action"
DEFAULT_ADDON_HOST: Final = "605cee21_googlehome"
DEFAULT_ADDON_PORT: Final = 8195

ADDON_CONTAINER_HOSTS: Final = [
    "605cee21_googlehome",
    "605cee21-googlehome",
    "edfe50eb_googlehome",
    "edfe50eb-googlehome",
    "local-googlehome",
    "local_googlehome",
    "127.0.0.1",
]

CONF_OPERATION_MODE: Final = "operation_mode"
MODE_HYBRID: Final = "hybrid"
MODE_LOCAL: Final = "local"
MODE_CLOUD: Final = "cloud"

CONF_IGNORE_HA_SYNCED_DEVICES: Final = "ignore_ha_synced_devices"
DEFAULT_IGNORE_HA_SYNCED_DEVICES: Final = True

DATA_CLIENT: Final = "client"
DATA_COORDINATOR: Final = "coordinator"
DATA_CLOUD_CLIENT: Final = "cloud_client"
DATA_CLOUD_COORDINATOR: Final = "cloud_coordinator"

ALARM_AND_TIMER_ID_LENGTH: Final = 42
MAX_PASSWORD_LENGTH: Final = 100

GOOGLE_HOME_ALARM_DEFAULT_VALUE: Final = 0.0

ICON_TOKEN: Final = "mdi:form-textbox-password"
ICON_ALARMS: Final = "mdi:alarm-multiple"
ICON_TIMERS: Final = "mdi:timer-sand"
ICON_DO_NOT_DISTURB: Final = "mdi:minus-circle"
ICON_ALARM_VOLUME_LOW: Final = "mdi:volume-low"
ICON_ALARM_VOLUME_MID: Final = "mdi:volume-medium"
ICON_ALARM_VOLUME_HIGH: Final = "mdi:volume-high"
ICON_ALARM_VOLUME_OFF: Final = "mdi:volume-off"
ICON_NIGHT_MODE: Final = "mdi:weather-night"
ICON_WIFI: Final = "mdi:wifi"
ICON_BLUETOOTH: Final = "mdi:bluetooth"
ICON_REBOOT: Final = "mdi:restart"
ICON_REFRESH: Final = "mdi:refresh"

EVENT_TIMER_FINISHED: Final = "google_home_timer_finished"
EVENT_ALARM_TRIGGERED: Final = "google_home_alarm_triggered"

PLATFORMS: Final = [
    "sensor",
    "binary_sensor",
    "switch",
    "number",
    "button",
    "light",
    "camera",
    "vacuum",
    "climate",
    "lock",
    "cover",
    "alarm_control_panel",
    "scene",
]

SERVICE_REBOOT: Final = "reboot_device"
SERVICE_DELETE_ALARM: Final = "delete_alarm"
SERVICE_DELETE_TIMER: Final = "delete_timer"
SERVICE_REFRESH: Final = "refresh_devices"
SERVICE_SET_ALARM_VOLUME: Final = "set_alarm_volume"

SERVICE_ATTR_ALARM_ID: Final = "alarm_id"
SERVICE_ATTR_TIMER_ID: Final = "timer_id"
SERVICE_ATTR_SKIP_REFRESH: Final = "skip_refresh"
SERVICE_ATTR_VOLUME: Final = "volume"

PORT: Final = 8443
API_ENDPOINT_ALARMS: Final = "setup/assistant/alarms"
API_ENDPOINT_ALARM_VOLUME: Final = "setup/assistant/alarms/volume"
API_ENDPOINT_CURRENT_VOLUME: Final = "setup/assistant/volume"
API_ENDPOINT_ALARM_DELETE: Final = "setup/assistant/alarms/delete"
API_ENDPOINT_DO_NOT_DISTURB: Final = "setup/assistant/notifications"
API_ENDPOINT_NIGHT_MODE: Final = "setup/assistant/alarms/volume"
API_ENDPOINT_NIGHT_MODE_SETTINGS: Final = "setup/night_mode_params"
API_ENDPOINT_DEVICE_INFO: Final = "setup/eureka_info?params=version,name,build_info,device_info,net,wifi,wlan,bluetooth,setup,settings,opt_in,audio"
API_ENDPOINT_BLUETOOTH_STATUS: Final = "setup/bluetooth/status"
API_ENDPOINT_REBOOT: Final = "setup/reboot"

HEADER_CAST_LOCAL_AUTH: Final = "cast-local-authorization-token"
HEADER_CONTENT_TYPE: Final = "content-type"

JSON_ALARM: Final = "alarm"
JSON_TIMER: Final = "timer"
JSON_ALARM_VOLUME: Final = "volume"
JSON_NOTIFICATIONS_ENABLED: Final = "notifications_enabled"
JSON_NIGHT_MODE_ENABLED: Final = "enabled"

DATETIME_STR_FORMAT: Final = "%Y-%m-%d %H:%M:%S"
DEFAULT_TIMESTAMP_NONE: Final = "2000-01-01T00:00:00+00:00"
