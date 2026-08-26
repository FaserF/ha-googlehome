# Google Home (for Home Assistant)

[![GitHub Release](https://img.shields.io/github/release/FaserF/ha-googlehome.svg?style=flat-square)](https://github.com/FaserF/ha-googlehome/releases)
[![Downloads (Current release)](https://img.shields.io/github/downloads/FaserF/ha-googlehome/latest/google_home.zip?label=Downloads%20(Current%20release)&style=flat-square)](https://github.com/FaserF/ha-googlehome/releases)
[![License](https://img.shields.io/github/license/FaserF/ha-googlehome.svg?style=flat-square)](LICENSE)
[![hacs](https://img.shields.io/badge/HACS-custom-orange.svg?style=flat-square)](https://hacs.xyz)
[![Add to Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=google_home)
[![CI Orchestrator](https://github.com/FaserF/ha-googlehome/actions/workflows/ci-orchestrator.yml/badge.svg)](https://github.com/FaserF/ha-googlehome/actions/workflows/ci-orchestrator.yml)

<p align="center">
  <img src="custom_components/google_home/brand/logo.png" alt="Google Home Logo" height="100">
</p>

A modern, fast, and feature-complete Home Assistant integration offering **Hybrid Local & Google Cloud HomeGraph control** for all Google Home & Nest speakers, smart home devices, household routines, and multi-home structures.

---

## 🧭 Quick Links

| | | | |
| :--- | :--- | :--- | :--- |
| [✨ Features](#-features) | [🔄 Operation Modes Comparison](#-operation-modes-comparison) | [📦 Installation](#-installation) | [⚙️ Configuration](#️-configuration) |
| [🛠️ Options Flow](#️-options-flow) | [⚡ Events](#-automation-events) | [🧱 Services](#-services) | [📄 License](#-license) |

---

## 🔄 Operation Modes Comparison

Choose the best mode during setup or change it anytime in the Options Flow:

| Feature / Device Type | 🏠 **Local Only** (`local`) | ☁️ **Cloud Only** (`cloud`) | ⚡ **Hybrid (Recommended)** (`hybrid`) |
|---|:---:|:---:|:---:|
| **Internet Dependency** | ❌ None (local network) | 🌐 Internet required | 🌐 Internet for cloud sync, local fallback |
| **Speaker Alarms & Timers** | ✅ Yes (zero latency) | ❌ No | ✅ Yes (zero latency via local API) |
| **Next Alarm / Timer Timestamps** | ✅ Yes | ❌ No | ✅ Yes |
| **Speaker Volume & Alarm Volume** | ✅ Yes | ❌ No | ✅ Yes |
| **Do Not Disturb & Night Mode** | ✅ Yes | ❌ No | ✅ Yes |
| **Reboot Speaker & Diagnostics** | ✅ Yes (IP, Wi-Fi RSSI, Bluetooth) | ❌ No | ✅ Yes |
| **Lights & Dimmers** (Hue, Tuya, etc.) | ❌ No | ✅ Yes (On/Off, Brightness, Color) | ✅ Yes |
| **Fans & Air Purifiers** | ❌ No | ✅ Yes (On/Off, Speed %) | ✅ Yes |
| **Media Players & Smart TVs** | ❌ No | ✅ Yes (State, Play/Pause, Volume) | ✅ Yes |
| **Thermostats & AC (`climate`)** | ❌ No | ✅ Yes (Temp setpoints, HVAC modes) | ✅ Yes |
| **Smart Plugs & Switches** | ❌ No | ✅ Yes | ✅ Yes |
| **Robot Vacuums & Mowers** | ❌ No | ✅ Yes (Start, Stop, Dock) | ✅ Yes |
| **Smart Locks** | ❌ No | ✅ Yes (Lock/Unlock) | ✅ Yes |
| **Covers, Blinds & Garage Doors** | ❌ No | ✅ Yes (Open, Close, Position %) | ✅ Yes |
| **Cameras & Video Doorbells** | ❌ No | ✅ Yes | ✅ Yes |
| **Security Systems & Alarm Panels** | ❌ No | ✅ Yes (Arm Home/Away, Disarm) | ✅ Yes |
| **Sensors** (Motion, Presence, Doorbell) | ❌ No | ✅ Yes | ✅ Yes |
| **Google Routines & Scenes (`scene`)** | ❌ No | ✅ Yes (Trigger any routine/scene) | ✅ Yes |
| **Multi-Home Structure Filtering** | ❌ No | ✅ Yes | ✅ Yes |
| **HA-Loop Prevention Filter** | ❌ No | ✅ Yes | ✅ Yes |

---

## ✨ Features

- **👥 Multi-Account Support**:
  - Add **multiple distinct Google Accounts** simultaneously to your Home Assistant instance.
  - Automatic deduplication prevents accidental duplicate setups of the same account.

- **🏡 Dynamic Multi-Home (Structure) Discovery & Filtering**:
  - Automatically discovers all homes (structures) linked to your Google Account (e.g. *Main Home*, *Parents' House*, *Holiday Home*).
  - Dynamically displays human-readable home names while internally binding to stable UUIDs (renaming a home in the Google Home app will never break your Home Assistant setup).
  - Multi-select filter allows you to synchronize only specific homes into Home Assistant.

- **🌐 Full Google Home Ecosystem Support (Local & Cloud HomeGraph)**:
  - **Google Home & Nest Speakers**: Live Media & Speech Volume Slider (0-100% with live local sync), Alarm Volume Slider, Timers, Alarms, Next Alarm/Timer timestamps, Do Not Disturb, Night Mode, Reboot, Wi-Fi RSSI, Bluetooth MAC diagnostics, and call pickup status.
  - **Smart Clocks & Nightlights**: Specialized Lenovo Smart Clock and smart clock nightlight support (`light.wohnzimmer_uhr` with On/Off & Brightness), display brightness diagnostics, and alarm synchronization.
  - **Lights & Dimmers**: On/Off, Brightness, Color temperature, and RGB color control (`light`).
  - **Fans & Air Purifiers**: Power, oscillation, and percentage speed controls (`fan`).
  - **Media Players & Smart TVs**: Real-time state tracking, volume control, mute, play/pause, input selection, app listing, and transport control (`media_player`).
  - **Switches & Smart Plugs**: Control power and inspect real-time state (`switch`).
  - **Robot Vacuum Cleaners**: Start, stop, dock, zone cleaning metadata, and status tracking for connected vacuums (`vacuum`).
  - **Thermostats & Climate**: Nest Thermostats and AC units with temperature setpoints, humidity, and HVAC modes (`climate`).
  - **Smart Locks**: Lock/unlock Google Home and Nest x Yale locks (`lock`).
  - **Covers, Blinds & Garage Doors**: Open, close, and set position (0-100%) (`cover`).
  - **Cameras & Video Doorbells**: Live streams for Nest Cam, Nest Doorbell, and partner cameras (`camera`).
  - **Automations & Household Routines**: Trigger and execute any Google Home script, automation, or routine directly from Home Assistant (`scene`).
  - **Security Systems**: Arm home, arm away, disarm Nest Secure and security alarms (`alarm_control_panel`).
  - **Sensors & Doorbells**: Motion, occupancy, contact, presence, sound, and doorbell press binary sensors (`binary_sensor`).

  - **Household Presence & Attendance Tracker**: Real-time Home & Away tracking (`device_tracker`) leveraging live Google HomeGraph `AreaPresenceStateTrait` and `AreaAttendanceStateTrait` (tracking whether *all household members* or individual members are present).
  - **Nest Aware Sound & Smoke/CO Alarm Sensing**: Acoustic smoke alarm, carbon monoxide, and glass break detection binary sensors for Nest speakers (`binary_sensor.xxx_rauch_co_alarmton`, disabled by default).
  - **Nest Aware Familiar Face Library**: Sensor exposing recognized familiar face names and counts per household (`sensor.xxx_bekannte_gesichter`, disabled by default).
  - **Gemini Activity Briefs**: Daily AI-generated activity summaries from Google Home Gemini AI (`sensor.xxx_home_briefs`, disabled by default).


- **🔄 Intelligent Home Assistant Loop Prevention & Dynamic Cleanup**:
  - Automatically identifies devices that originated from Home Assistant (e.g., via Nabu Casa / Cloud Sync).
  - Configurable toggle: **"Ignore devices synced from Home Assistant"** (default: `True`) to prevent duplicate entities and infinite automation loops.
  - **Dynamic Entity & Device Registry Purge**: When deselecting a home or switching third-party representation modes, stale or orphaned entities and devices are automatically and cleanly removed from Home Assistant's entity registry without leaving ghost entities.

- **🏛️ Google Home Cloud Architecture, Capabilities & Third-Party Control**:
  - **Universal Capability & Attribute Extraction**: The integration dynamically inspects all Google HomeGraph key-value pairs (`message20` and `message30`), uncovering hidden capabilities across all your devices:
    - *Smart TVs*: Available streaming apps (`availableApplications`), HDMI inputs (`availableInputs`), supported media types, and toggle states.
    - *Robot Vacuums*: Configured cleaning zones (`availableZones`) and pause capabilities (`pausable`).
    - *Speakers & Clocks*: Call capabilities (`communicationCallCapabilities`), ducking state (`RemoteDucking`), and active audio streams.
  - **HomeGraph Discovery & State Inspection**: The integration leverages the Google Foyer / HomeGraph gRPC endpoint (`GetHomeGraph`) to synchronize all devices, structures/homes, rooms, hardware models, and traits into Home Assistant.
  - **Third-Party & Device Status Architecture**: Google's Cloud Foyer API serves as a secure read-and-aggregation layer for consumer accounts.
    - In **`readonly_sensors` mode (Default & Recommended)**, cloud devices and specialized speaker/clock traits are represented as clean, descriptive status sensors (`sensor.xxx_status`) with real-world dynamic states:
      - **Lights**: Shows brightness percentage when active (e.g. `on (75%)`), `on`, or `off`.
      - **Switches & Plugs**: `on` or `off`.
      - **Covers & Blinds**: `open (50%)`, `open`, or `closed`.
      - **Locks**: `locked`, `unlocked`, or `jammed`.
      - **Robot Vacuums & Mowers**: `cleaning`, `docked`, `docking`, `paused`, `stopped`.
      - **Thermostats**: Mode and setpoint (e.g. `heat (21.5°C)`).
      - **Speakers & Media Players**: `playing`, `paused`, or `off`.
    - **Rich State Attributes**: Every status sensor exposes attributes including `brightness`, `open_percent`, `is_locked`, `device_ip`, `wifi_network` (SSID), `wifi_signal_level` (RSSI), `mac_address`, `bluetooth_mac`, `hardware_model`, `firmware_version`, `room`, and raw `state_data`.
  - **Best Practice**: For bi-directional hardware switching of third-party devices, use their native Home Assistant integrations (e.g. Xiaomi Miio, Tuya, Hue). Local Google Cast speakers are controlled directly and with zero latency via their local HTTPS/REST API!




- **⚡ Direct Local Speaker Communication**:
  - Direct local HTTPS/REST polling and control for speakers within your local network (no cloud delay for alarms/timers).
  - Automatic token management and background recovery when local authorization tokens expire.
  - Zeroconf local IP resolution with intelligent caching & dynamic discovery.
  - Concurrently polled endpoints to minimize latency and eliminate timeout freezes.

- **Native User-Friendly Configuration**:
  - Clear multi-step Config Flow:
    - **Token Authentication (Recommended)**: 100% reliable 30-second setup using a browser token from Google setup page, automatically exchanged for a permanent Master Token.
    - **[Google Home Token Hub Add-on](https://github.com/FaserF/hassio-addons/tree/master/googlehome)**: Automatic setup via Add-on (auto-detected, edge & stable).
    - **App Password Authentication**: Automatic token extraction via Google App Password.

- **Alarm & Timer Management**:
  - **Next Alarm Sensor**: Native timestamp sensor (`datetime | None`) with full alarm list, repeat days, and status in state attributes.
  - **Next Timer Sensor**: Native timestamp sensor with duration, remaining time, and state details.
  - **Delete Buttons**: Convenient **Delete All Alarms** and **Delete All Timers** buttons (`button.xxx_alle_wecker_loschen` & `button.xxx_alle_timer_loschen`, disabled by default) to purge all active alarms and timers with one click.
  - **Native Bus Events**: Automatically fires `google_home_timer_finished` and `google_home_alarm_triggered` on the Home Assistant event bus for easy automations.
  - Dedicated entity services to delete alarms, delete timers, broadcast local announcements, and set alarm volume via automations or dashboard buttons.


- **Diagnostics & Network Info**:
  - **Device IP Sensor**: Diagnostic sensor exposing speaker IP, hardware model, availability, and tokens.
  - **Wi-Fi Network Sensor**: Shows connected Wi-Fi SSID with signal strength (RSSI in dBm) and IP in attributes.
  - **Bluetooth Sensor**: Diagnostic sensor exposing the speaker local Bluetooth MAC address.
  - Full English, German, and Greek (`de`, `en`, `el`) native translations.

---

## 📦 Installation

### Via HACS (Recommended)
1. Open **HACS** in your Home Assistant instance.
2. Click on the 3 dots in the top right corner and select **Custom repositories**.
3. Add the repository URL: `https://github.com/FaserF/ha-googlehome` with category **Integration**.
4. Search for **Google Home**, click **Download**, and restart Home Assistant.

### Manual Installation
1. Download `google_home.zip` from the [Latest Release](https://github.com/FaserF/ha-googlehome/releases).
2. Unpack and copy the `custom_components/google_home` folder to your Home Assistant `custom_components` directory.
3. Restart Home Assistant.

---

## ⚙️ Configuration

1. In Home Assistant, go to **Settings** -> **Devices & Services** -> **Add Integration** -> **Google Home**.
2. Select your preferred authentication method:

### Option 1: Token Authentication (Recommended - 100% Reliable)
1. Open **[accounts.google.com/EmbeddedSetup](https://accounts.google.com/EmbeddedSetup)** in your browser and log in with your Google account.
2. *Note*: The final page will remain on a loading/blank screen (this is normal and indicates the token was created!).
3. Press **F12** (Developer Tools) -> **Application** (or Storage) -> **Cookies** (`https://accounts.google.com`).
4. Copy the value of the **`oauth_token`** cookie (starts with `oauth2_4/...` or `1//...`).
5. Enter your **Google Email Address**, paste the token into the **Token** field, and click **Submit**.
6. ✨ **Done!** The integration automatically exchanges this token for a permanent Master Token (`aas_et/...`) in the background.

*(If you already have a permanent Master Token starting with `aas_et/...`, you can also paste it directly into the Token field).*

### Option 2: Google Home Token Hub Add-on (Automated Setup)
1. Install and start the **[Google Home Token Hub Add-on](https://github.com/FaserF/hassio-addons/tree/master/googlehome)** from the [FaserF Add-on Repository](https://github.com/FaserF/hassio-addons).
2. The Home Assistant integration will auto-discover the running add-on and prompt you to log in directly via the HA dialog.
3. Once the token is acquired, the integration offers you the option to automatically stop or uninstall the add-on to conserve system resources.

### Option 3: App Password
1. Create a 16-character App Password at **[myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)**.
2. Enter your Google Email Address and App Password.
3. The integration will attempt to generate your Master Token automatically.

---

## 🛠️ Options Flow

You can customize your integration settings at any time without reinstalling:
1. Navigate to **Settings** -> **Devices & Services** -> **Google Home**.
2. Click **Configure** on the integration card.
3. Available options:
   - **Operation Mode**: Switch between *Hybrid (Local & Cloud)*, *Local Only*, or *Cloud Only*.
   - **Third-Party Devices Representation**:
     - **Read-Only Status Entities & Attributes (Default & Recommended)**: Third-party partner devices (Xiaomi/Tuya/Hue/Smart Life) are represented as clean diagnostic status sensors with live state and attributes, clearly communicating read-only nature without broken control switches.
     - **Control Entities**: Third-party devices are mapped as native HA control domains (`fan`, `light`, `switch`, `cover`, `vacuum`, `climate`) reflecting live state from Google Cloud (with outbound partner execution restricted by Google Foyer API).
   - **Google Homes to synchronize**: Select or deselect individual homes/structures.
   - **Ignore devices synced from Home Assistant**: Toggle loop prevention on/off.
   - **Local Speaker Polling Interval**: Adjust local LAN speaker polling frequency (min: 60s, default: 60s / 1 min).
   - **Cloud HomeGraph Polling Interval**: Adjust cloud HomeGraph synchronization frequency (min: 60s, default: 300s / 5 min).
   - **Master Token**: View or update your Master Token if you refreshed credentials.


---

## ⚡ Automation Events

The integration fires native events on the Home Assistant Event Bus that you can use directly in your automations:

- **`google_home_timer_finished`**: Fired when a timer finishes on a speaker.
  ```yaml
  trigger:
    - platform: event
      event_type: google_home_timer_finished
      event_data:
        device_name: "Kitchen Speaker"
  ```
- **`google_home_alarm_triggered`**: Fired when an alarm goes off.
  ```yaml
  trigger:
    - platform: event
      event_type: google_home_alarm_triggered
  ```

---

## 🧱 Services

| Service | Description | Parameters |
|---|---|---|
| `google_home.delete_alarm` | Deletes a specific alarm from a Google Home device | `alarm_id`, `skip_refresh` |
| `google_home.delete_timer` | Deletes a specific timer from a Google Home device | `timer_id`, `skip_refresh` |
| `google_home.set_alarm_volume` | Sets the alarm and timer volume (0-100%) | `volume` |
| `google_home.broadcast` | Broadcasts an announcement locally to a Google Home speaker | `message` |
| `google_home.reboot_device` | Reboots the Google Home speaker | `entity_id` |
| `google_home.refresh_devices` | Triggers an immediate coordinator refresh | - |


---

## ❤️ Support & Sponsoring

If you appreciate this integration and want to support ongoing maintenance:
- [GitHub Sponsors](https://github.com/sponsors/FaserF)
- [PayPal](https://paypal.me/FaserF)

---

## 💖 Credits & Acknowledgements

A huge thank you to **[@leikoilja](https://github.com/leikoilja)** and the contributors of the original [ha-google-home](https://github.com/leikoilja/ha-google-home) repository. 

The original concept, reverse engineering, and foundational ideas were pioneered by their great work. This integration was completely rewritten from the ground up to modernize the architecture, resolve authentication/token expiry issues, eliminate timeouts, and provide a fully native configuration experience inside Home Assistant.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

