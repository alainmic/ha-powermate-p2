# PowerMate P2 / Orvibo Allone Pro Motorized Shades for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Tests](https://github.com/alainmic/ha-powermate-p2/actions/workflows/tests.yml/badge.svg)](https://github.com/alainmic/ha-powermate-p2/actions/workflows/tests.yml)
[![Validate](https://github.com/alainmic/ha-powermate-p2/actions/workflows/validate.yml/badge.svg)](https://github.com/alainmic/ha-powermate-p2/actions/workflows/validate.yml)

Native Home Assistant custom integration for **PowerMate P2** (`com.smarthome.powermate`) and **Orvibo HomeMate / Allone Pro** RF motorized shades, roller blinds, and curtains (**A-OK Motor**, **Dooya**, and compatible 433 MHz RF tubular motors).

This integration eliminates the need to purchase an external RF bridge (such as a Bond Bridge) or use workarounds like Google Home / Alexa virtual switch relays.

---

## Features

- **Native `cover` Entities:** Exposes each motorized shade with full **Open**, **Stop**, and **Close** controls (`CoverEntityFeature.OPEN | CLOSE | STOP`).
- **Auto-Discovery:** Automatically discovers your **PowerMate P2 / Allone Pro** hub (`deviceType: 67`) and all paired RF shades/curtains (`deviceType: 34, 35, 39, 42`) from your account.
- **Persistent Encrypted Session & Push Updates:** Maintains a warm AES-128-ECB (`hd` binary frame) TCP session with periodic heartbeats (`cmd: 32`), automatic reconnect/retry on demand, and real-time `cmd: 42` status push updates when shades are controlled via the mobile app or built-in hub timers.
- **UI Config Flow & Reauthentication:** Set up entirely through the Home Assistant UI (**Settings → Devices & Services → Add Integration**), with built-in reauthentication and redacted diagnostics support.

---

## Supported Hardware

| Device / Brand | Orvibo `deviceType` | Home Assistant Platform | Supported Actions |
| :--- | :---: | :---: | :--- |
| **PowerMate P2 / Orvibo Allone Pro Hub** | `67` | Device Registry Hub | Gateway / Bridge |
| **A-OK / PowerMate RF Roller Shade** | `42` | `cover` (`shade`) | Open, Stop, Close |
| **Orvibo / Dooya RF Roller Shutter** | `35` | `cover` (`shade`) | Open, Stop, Close |
| **Orvibo / Dooya RF Curtain** | `34` | `cover` (`shade`) | Open, Stop, Close |
| **RF Window Opener** | `39` | `cover` (`shade`) | Open, Stop, Close |

> **Note:** Because 433 MHz RF tubular shade motors (`A-OK Motor`, `Dooya`) use one-way RF communication from the hub, exact percentage position feedback is not reported by the motor. Entities use `assumed_state: true` so that **Open**, **Stop**, and **Close** buttons remain available at all times even if a shade was moved using a physical handheld remote.

---

## Installation

### Option 1: HACS (Recommended)

1. Open **HACS** in Home Assistant.
2. Click the three dots in the top-right corner and select **Custom repositories**.
3. Enter `https://github.com/alainmic/ha-powermate-p2` as the repository URL and select **Integration** as the category.
4. Click **Add**, then install **PowerMate P2 Motorized Shades**.
5. Restart Home Assistant.

### Option 2: Manual Installation

1. Copy the `custom_components/powermate_p2` folder into your Home Assistant `<config>/custom_components/` directory.
2. Restart Home Assistant.

---

## Configuration

1. In Home Assistant, go to **Settings → Devices & Services**.
2. Click **+ Add Integration** and search for **PowerMate P2 Motorized Shades**.
3. Enter the **Email / Username** and **Password** you use in the **PowerMate P2** (or **HomeMate**) mobile app.
4. Your hub and all paired motorized shades will be added automatically.

---

## Protocol Overview

The PowerMate P2 bridge is a white-labeled **Orvibo Allone Pro** (`HomeMate_device`) that communicates using Orvibo's 42-byte binary `hd` framing (`MAGIC = 0x6864` + 2-byte length + `pk`/`dk` packet type + CRC32 + 32-byte `sessionId` + AES-128-ECB PKCS7 payload):

1. **Handshake (`cmd: 0`):** Encrypted with the static bootstrap key (`pk`), returning a 32-byte `sessionId` and dynamic 16-byte session key (`dk`).
2. **Authentication (`cmd: 2`):** Authenticates with `userName` and uppercase MD5 `password` digest (`type: 3`), resolving `familyId` and `gatewayList`.
3. **Device Table Query (`cmd: 4`):** Queries `tableName: "device"` to discover hubs (`deviceType: 67`) and RF shade motors (`deviceType: 42`, etc.).
4. **RF Motor Control (`cmd: 15`):** Sends `"order": "rf control"` with:
   - `value1: 380000` (**Open**)
   - `value1: 380001` (**Close**)
   - `value1: 380002` (**Stop**)

---

## Running Tests

```bash
python3 -m unittest discover -s tests -v
```

---

## License

MIT License
