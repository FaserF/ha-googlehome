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
| [✨ Features](#-features) | [🔄 Operation Modes Comparison](#-operation-modes-comparison) | [📦 Installation](#-installation) | [🔄 Migration from leikoilja](#-migration-from-leikoilja-ha-google-home) |
| [⚙️ Configuration](#️-configuration) | [🛠️ Options Flow](#️-options-flow) | [⚡ Events](#-automation-events) | [🧱 Services](#-services) |

---

## 🔄 Operation Modes Comparison

Choose the best mode during setup or change it anytime in the Options Flow:

| Feature / Device Type | 🏠 **Local Only** (`local`) | ☁️ **Cloud Only** (`cloud`) | ⚡ **Hybrid (Recommended)** (`hybrid`) |
|---|:---:|:---:|:---:|
| **Internet Dependency** | ❌ None (local network) | 🌐 Internet required | 🌐 Internet for cloud sync, local fallback |
| **Speaker Alarms & Timers** | ✅ Yes (zero latency) | ❌ No | ✅ Yes (zero latency via local API) |
| **Next Alarm / Timer Timestamps** | ✅ Yes | ❌ No | ✅ Yes |
| **Speaker Volume & Alarm Volume** | ✅ Yes (Local & Restored) | ❌ No | ✅ Yes (Local & Restored) |
| **Do Not Disturb & Night Mode** | ✅ Yes | ❌ No | ✅ Yes |
| **Smart Clock Nightlight (`light` & Brightness)** | ❌ No | 🗣️ Via [Assistant SDK](https://www.home-assistant.io/integrations/google_assistant_sdk/) | 🗣️ Via [Assistant SDK](https://www.home-assistant.io/integrations/google_assistant_sdk/) |
| **Reboot Speaker & Diagnostics** | ✅ Yes (IP, Wi-Fi RSSI, Bluetooth) | ❌ No | ✅ Yes |

| **Cloud Device Live Telemetry & Status Sensors** | ❌ No | ✅ Yes (State, Brightness, Fan Speed %, Covers, etc.) | ✅ Yes |
| **Cloud Device Control (Lights, Switches, Fans, etc.)** | ❌ No | 🗣️ Via [Assistant SDK](https://www.home-assistant.io/integrations/google_assistant_sdk/) | 🗣️ Via [Assistant SDK](https://www.home-assistant.io/integrations/google_assistant_sdk/) |
| **Google Routines & Scenes (`scene`)** | ❌ No | ✅ Yes (Trigger any routine/scene) | ✅ Yes |
| **Household Presence & Attendance Tracker** | ❌ No | ✅ Yes | ✅ Yes |
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
  - **HomeGraph Discovery & Third-Party Architecture (3 Modes in Options Flow)**:
    - **`readonly_sensors` (Default & Recommended)**: Cloud devices and specialized speaker/clock traits are represented as clean, descriptive status sensors (`sensor.xxx_status`) with real-world dynamic states (e.g. `on (75%)`, `cleaning`, `docked`). No duplicate control entities are created.
    - **`control_entities`**: Exposes controllable entities (`light`, `fan`, `switch`, `cover`, `vacuum`, `climate`) reflecting live telemetry via Google HomeGraph without dispatching outbound voice commands.
    - **`assistant_sdk_control`**: Dynamically available if the official [Google Assistant SDK](https://www.home-assistant.io/integrations/google_assistant_sdk/) integration is installed. Universal text commands are automatically dispatched (e.g. `"Turn on night light on Wohnzimmer Uhr"`, `"Set fan speed on Bedroom Fan to 50%"`, `"Turn off Living Room Light"`) while maintaining real-time telemetry from Google HomeGraph!





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

## 🔄 Migration from [leikoilja/ha-google-home](https://github.com/leikoilja/ha-google-home)

Already running the original community integration by [@leikoilja](https://github.com/leikoilja)? **Migration is fully automatic — no manual steps required.**

### How it works

Both integrations use the same `google_home` domain. When you replace the files and restart Home Assistant, the new integration detects your existing config entry by its legacy schema (VERSION 1, no `auth_method` key) and automatically migrates it:

| What is migrated | Notes |
|---|---|
| **Google Account Email** (`username`) | Carried over 1:1 |
| **Master Token** (`aas_et/...`) | Carried over 1:1 |
| **App Password / Password** | Carried over if no master token was present |
| **Android ID** | Carried over 1:1 |
| **Polling interval** (`update_interval`) | Mapped to `local_update_interval`; enforced min 60s |
| **Operation mode** | Defaulted to **Local Only** (safe, identical to original behavior) |
| **Entity IDs & device registry** | All existing entities keep their IDs — no automations break |

### Migration steps

1. **Remove** the old integration files (or let HACS replace them):
   - Via **HACS**: Add `https://github.com/FaserF/ha-googlehome` as a Custom Repository → Download → overwrite.
   - Manually: copy the new `custom_components/google_home/` folder, replacing the old one.
2. **Restart** Home Assistant.
3. ✅ Done — the migration runs silently on startup. Check **Settings → System → Logs** for a `"Successfully auto-migrated leikoilja entry"` confirmation line.

> **Tip:** After migration the integration starts in **Local Only** mode (identical to leikoilja). To unlock cloud device support (lights, fans, thermostats, cameras, locks, vacuums, routines, etc.), go to **Settings → Devices & Services → Google Home → Configure** and switch the Operation Mode to **Hybrid (Local & Cloud)**.

---

<details>
<summary><strong>📊 Comparison with leikoilja/ha-google-home</strong> <em>(as of 2026-08-27)</em></summary>

Both integrations share the same `google_home` domain and the same underlying library ([glocaltokens](https://github.com/leikoilja/glocaltokens)) to obtain local auth tokens.

### 🏗️ Architecture & Setup

| Feature | **This integration** | [leikoilja/ha-google-home](https://github.com/leikoilja/ha-google-home) |
|---|---|---|
| **Operation modes** | ✅ Three modes: `local`, `cloud`, `hybrid` (configurable in Options Flow) | ❌ Local-only |
| **Authentication methods** | ✅ Browser token (recommended), Add-on (auto-detected) | ✅ Username + password (glocaltokens) |
| **Multi-account support** | ✅ Multiple distinct Google accounts per HA instance | ❌ One account per entry |
| **Multi-home (structure) filtering** | ✅ Selectively sync specific homes; stable UUID binding | ❌ No concept of homes/structures |
| **Zeroconf discovery** | ✅ `_googlecast._tcp.local.` + `_googlezone._tcp.local.` | ✅ `_googlecast._tcp.local.` |
| **HA-loop prevention** | ✅ Filters out devices synced from HA (configurable) | ❌ Not present |
| **Dynamic entity/device cleanup** | ✅ Stale entities auto-removed when homes are deselected | ❌ Not present |
| **Update intervals** | ✅ Separate local (60s default) and cloud (300s default) | ⚠️ Single interval (default 180s, configurable) |
| **Maintenance status** | ✅ Actively maintained (2025–2026) | ⚠️ Unmaintained since ~2023 |

### 🔌 Platforms & Entity Types

| Platform | **This integration** | **leikoilja** |
|---|---|---|
| `sensor` | ✅ Alarms, Timers, Device Info, Wi-Fi SSID/RSSI, Bluetooth MAC, Familiar Faces, Gemini Briefs, cloud status sensors | ✅ Alarms, Timers, Device Info (IP) |
| `switch` | ✅ Do Not Disturb + cloud smart plug/switch control | ✅ Do Not Disturb only |
| `number` | ✅ Media Volume + Alarm Volume | ✅ Alarm Volume only |
| `button` | ✅ Reboot, Delete All Alarms, Delete All Timers | ❌ Not present |
| `binary_sensor` | ✅ Motion, occupancy, contact, presence, doorbell, smoke/CO (Nest Aware) | ❌ Not present |
| `light` | ✅ Lights, dimmers, RGB, color temp, Smart Clock nightlight | ❌ Not present |
| `fan` | ✅ Power, oscillation, speed % (fans & air purifiers) | ❌ Not present |
| `media_player` | ✅ Real-time state, volume, mute, play/pause, inputs, app listing | ❌ Not present |
| `climate` | ✅ Nest Thermostat/AC (setpoint, humidity, HVAC mode) | ❌ Not present |
| `lock` | ✅ Google Home / Nest x Yale locks | ❌ Not present |
| `cover` | ✅ Blinds, garage doors (open/close/position) | ❌ Not present |
| `camera` | ✅ Live streams for Nest Cam / Doorbell | ❌ Not present |
| `vacuum` | ✅ Start/stop/dock, zone metadata | ❌ Not present |
| `alarm_control_panel` | ✅ Nest Secure (arm home/away/disarm) | ❌ Not present |
| `scene` | ✅ Trigger Google Home routines & automations | ❌ Not present |
| `device_tracker` | ✅ Household presence (HomeGraph AreaPresenceState) | ❌ Not present |

### 📡 Data Sources

| | **This integration** | **leikoilja** |
|---|---|---|
| **Local speaker API** | ✅ Alarms, timers, volume, DND, night mode, reboot, Wi-Fi, Bluetooth | ✅ Same local endpoints |
| **Google HomeGraph (Cloud)** | ✅ Full device graph, traits, telemetry for all smart home device types | ❌ Not present |
| **Third-party entity modes** | ✅ `readonly_sensors` / `control_entities` / `assistant_sdk_control` | ❌ Not applicable |
| **Google Assistant SDK integration** | ✅ Optional – auto-detects installed SDK and dispatches voice commands | ❌ Not present |

### ⚡ Events & Services

| | **This integration** | **leikoilja** |
|---|---|---|
| **HA event bus events** | ✅ `google_home_timer_finished`, `google_home_alarm_triggered` | ❌ Not present |
| **Services** | `reboot_device`, `delete_alarm`, `delete_timer`, `refresh_devices`, `set_alarm_volume`, `broadcast` | `reboot_device`, `delete_alarm`, `delete_timer`, `refresh_devices` |
| **`broadcast` service** | ✅ Local TTS announcement via speaker | ❌ Not present |
| **`set_alarm_volume` service** | ✅ Yes | ❌ Not present |

### 🌍 Maintenance & Quality

| | **This integration** | **leikoilja** |
|---|---|---|
| **HACS status** | ⚠️ Custom repository | ✅ Official HACS default |
| **Diagnostics support** | ✅ Yes | ❌ Not present |
| **Translations** | ✅ English, German (`de`), Greek (`el`) | ✅ English + community translations |
| **Type hints / mypy + ruff CI** | ✅ Full | ✅ Basic |

</details>

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

---

## 🛠️ Options Flow

You can customize your integration settings at any time without reinstalling:
1. Navigate to **Settings** -> **Devices & Services** -> **Google Home**.
2. Click **Configure** on the integration card.
3. Available options:
   - **Operation Mode**: Switch between *Hybrid (Local & Cloud)*, *Local Only*, or *Cloud Only*.
   - **Third-Party Devices Representation**:
     - **Read-Only Status Entities & Attributes**: Third-party partner devices (Xiaomi/Tuya/Hue/Smart Life) are represented as clean diagnostic status sensors (`sensor.xxx_status`) with live state, brightness, fan speed, and attributes without duplicate control entities. (Default when Google Assistant SDK is not configured).
     - **Control Entities with Google Assistant SDK Execution**: Third-party devices are mapped as native HA control domains (`fan`, `light`, `switch`, `cover`, `vacuum`, `climate`) that automatically dispatch voice commands through the official [Google Assistant SDK](https://www.home-assistant.io/integrations/google_assistant_sdk/) while synchronizing live state from Google Cloud. (Automatically preselected when Assistant SDK is installed!).
     - **Control Entities without Execution**: Exposes native control entities tracking live HomeGraph state without sending outbound voice commands.

   - **Google Homes to synchronize**: Select or deselect individual homes/structures.
   - **Ignore devices synced from Home Assistant**: Toggle loop prevention on/off.
   - **Local Speaker Polling Interval**: Adjust local LAN speaker polling frequency (min: 60s, default: 120s / 2 min).
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

