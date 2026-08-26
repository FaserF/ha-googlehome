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

A modern, fast, and reliable Home Assistant custom integration offering **Hybrid Local & Google Home Cloud HomeGraph control** for all Google Home, Nest Audio, Nest Mini, Nest Hub, Nest Cams, and smart home devices.

---

## 🧭 Quick Links

| | | | |
| :--- | :--- | :--- | :--- |
| [✨ Features](#-features) | [📦 Installation](#-installation) | [⚙️ Configuration](#️-configuration) | [🛠️ Options](#️-options-flow) |
| [⚡ Events](#-automation-events) | [🧱 Services](#-services) | [💖 Credits](#-credits--acknowledgements) | [📄 License](#-license) |

---

## ✨ Features

- **🌐 Full Google Home Ecosystem Support (Local & Cloud HomeGraph)**:
  - **Google Home & Nest Speakers**: Live Media & Speech Volume Slider (0-100% with live sync), Alarm Volume Slider, Timers, Alarms, Next Alarm/Timer timestamps, Do Not Disturb, Night Mode, Reboot, Wi-Fi & Bluetooth MAC diagnostics.
  - **Lights & Dimmers**: On/Off, Brightness, Color control for all Google Home synced lights (`light`).
  - **Switches & Smart Plugs**: Control power and inspect real-time state (`switch`).
  - **Robot Vacuum Cleaners**: Start, stop, dock, and status tracking for connected vacuums (`vacuum`).
  - **Thermostats & Climate**: Nest Thermostats and AC units with temperature control and HVAC modes (`climate`).
  - **Smart Locks**: Lock/unlock Google Home and Nest x Yale locks (`lock`).
  - **Covers, Blinds & Garage Doors**: Open, close, and set position (0-100%) (`cover`).
  - **Cameras & Video Doorbells**: Live streams for Nest Cam, Nest Doorbell, and partner cameras (`camera`).
  - **Automations & Household Routines**: Trigger and execute any Google Home script, automation, or routine directly from Home Assistant (`scene`).
  - **Security Systems**: Arm home, arm away, disarm Nest Secure and security alarms (`alarm_control_panel`).
  - **Sensors & Doorbells**: Motion, occupancy, contact, and doorbell press binary sensors (`binary_sensor`).
- **🔄 Intelligent Home Assistant Loop Prevention & Mapping**:
  - Automatically identifies devices that originated from Home Assistant (e.g., via Nabu Casa / Cloud Sync).
  - Configurable toggle: **"Ignore devices synced from Home Assistant"** (default: `True`) to prevent duplicate entities and infinite automation loops.
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
  - Integrated Options Flow to dynamically customize operation modes and polling intervals (10s to 600s).
- **Alarm & Timer Management**:
  - **Next Alarm Sensor**: Native timestamp sensor (`datetime | None`) with full alarm list, repeat days, and status in state attributes.
  - **Next Timer Sensor**: Native timestamp sensor with duration, remaining time, and state details.
  - **Native Bus Events**: Automatically fires `google_home_timer_finished` and `google_home_alarm_triggered` on the Home Assistant event bus for easy automations.
  - Dedicated entity services to delete alarms, delete timers, and set alarm volume via automations or dashboard buttons.
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

1. In Home Assistant, go to **Settings** -> **Devices & Services** (or click on the discovered Google Home card).
2. Select your preferred authentication method:

### Option 1: Token Authentication (Recommended - 100% Reliable)
1. Open **[accounts.google.com/EmbeddedSetup](https://accounts.google.com/EmbeddedSetup)** in your browser and log in with your Google account.
2. *Note*: The final page will remain on a loading/blank screen (this is normal and indicates the token was created!).
3. Press **F12** (Developer Tools) -> **Application** (or Storage) -> **Cookies** (`https://accounts.google.com`).
4. Copy the value of the **`oauth_token`** cookie (starts with `oauth2_4/...`).
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

You can customize the polling interval at any time:
1. Navigate to **Settings** -> **Devices & Services** -> **Google Home**.
2. Click **Configure** on the integration card.
3. Adjust the **Update Interval** (default: 60 seconds).

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
