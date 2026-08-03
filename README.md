# Blaster Mac Client

A macOS command-line app that monitors camera and microphone usage and sends IR commands to an ESP32-C3 IR Blaster over Bluetooth Low Energy (BLE). Use it to drive a dome light or "on air" indicator: **Red** when the camera or mic is on, **Green** after they've been off for two minutes. The **client** sends **On** when it connects and arms the ESP32 to run **Off** if the client stops sending heartbeats (e.g. after 15 minutes disconnected).

**License:** MIT — see [LICENSE](LICENSE).

**Privacy:** The app runs entirely on your Mac. It reads local macOS logs for camera/mic state and talks only to your IR Blaster over BLE. No telemetry or external servers.

## How it works

```mermaid
sequenceDiagram
    participant Log as macOS log stream
    participant App as Blaster Mac Client
    participant BLE as ESP32 BLE
    participant IR as IR LED

    Note over App,BLE: App launches, connects via BLE
    App->>BLE: Read Saved Codes, resolve names
    App->>BLE: Send "On" by index
    BLE->>IR: sendNEC(On)
    App->>BLE: Schedule Off in 900s
    loop Every 60s while connected
        App->>BLE: Heartbeat
    end

    Log-->>App: cam or mic detected
    App->>BLE: Send "Red" by name
    BLE->>IR: sendNEC(Red)
    BLE-->>App: Notify OK:Red

    Log-->>App: cam and mic both off
    Note over App: Start 2-min cooldown

    Note over App: 2 minutes elapse, still idle
    App->>BLE: Send "Green" by name
    BLE->>IR: sendNEC(Green)
    BLE-->>App: Notify OK:Green

    Note over App: Mac disconnects
    Note over BLE: No heartbeat for 900s
    BLE->>IR: Run scheduled "Off"
```

- **Camera/mic detection:** Uses macOS `log stream` with the same control-center “sensor-indicators” events that drive the menu bar dots. No polling; events only when state changes.
- **State machine:** IDLE → ACTIVE (cam or mic on) → COOLDOWN (both off) → IDLE after configurable cooldown. The client sends the **Active** command (e.g. Red) when entering ACTIVE and the **Idle** command (e.g. Green) when returning to IDLE.
- **BLE:** Connects to the IR Blaster by name, reads Saved Codes to resolve command **names** to indices, sends commands by name. On connect it sends On, arms the Schedule (e.g. Off in 900s), and sends a heartbeat periodically to reset the timer. Reconnects automatically after disconnect.

## Requirements

- macOS (tested on Sonoma / Sequoia) with Bluetooth
- Python 3.10+
- ESP32-C3 IR Blaster firmware with BLE enabled, powered on, and **paired** with this Mac (default firmware uses Just Works — no passkey)

## Setup

1. **Clone or copy** this project (e.g. next to your `irproject` repo):

   ```bash
   cd ~/Projects
   # create or clone blaster-mac-client
   cd blaster-mac-client
   ```

2. **Create a virtualenv and install dependencies:**

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Bluetooth permission:** The first time you run the app, macOS may prompt for Bluetooth access. If the IR Blaster never appears, open **System Settings → Privacy & Security → Bluetooth** and ensure your terminal (e.g. Terminal.app or Cursor) is allowed.

4. **Pair the IR Blaster once** (e.g. with nRF Connect or by running this app). With default firmware no passkey is required.

## Usage

From the project root with the venv activated:

```bash
python -m blaster
```

Or: `make run` (via `run.sh`).

A local status UI starts at **http://127.0.0.1:8765** (localhost only). Use it to see connection/light status, send commands, edit config, and reconnect.

Optional flags:

```bash
python -m blaster --config /path/to/myconfig.yaml
python -m blaster --port 9000
```

- The app scans for the device named **IR Blaster**, connects, sends **On** (optionally after a short delay), arms the ESP32 to run **Off** after a configurable delay with no heartbeat, and starts sending heartbeats periodically.
- When any app starts using the camera or microphone, the client sends the **Active** command (e.g. Red) by name.
- When both camera and microphone have been idle for the configured cooldown, it sends the **Idle** command (e.g. Green) by name.
- If the Mac disconnects (sleep, out of range), heartbeats stop; the ESP32 runs the scheduled command (e.g. Off) after the configured delay.
- Saving config in the UI writes `config.yaml` and safely restarts the BLE session with the new settings.

Stop with **Ctrl+C**; the client disconnects cleanly.

### Run at login (LaunchAgent)

Quick installer — from the project root:

```bash
chmod +x install.sh && ./install.sh
```

This:

1. Copies the project to `~/Library/Application Support/blaster-mac-client` (excluding `.git`, `dist`, caches, and any existing installed `config.yaml`).
2. Creates the virtualenv there and installs dependencies.
3. Writes `~/Library/LaunchAgents/com.blaster-mac-client.plist` from `com.blaster-mac-client.plist` (substituting the install and log directories) and loads it.

The client starts at login and restarts if it exits or crashes. Logs: `~/Library/Logs/blaster-mac-client/stdout.log` and `stderr.log`.

The installed copy is what runs — re-run `./install.sh` after changing code in the source tree. Editing config is safe either way: `install.sh` never overwrites an existing `~/Library/Application Support/blaster-mac-client/config.yaml`.

- **Uninstall (stop, disable, remove the installed copy):** `./uninstall.sh`
- **Reload:** `launchctl unload ~/Library/LaunchAgents/com.blaster-mac-client.plist` then `launchctl load …` (saving config in the UI restarts the BLE session on its own, so no reload is needed for config changes)

You can also run `./install-launchd.sh` (it calls `install.sh`).

#### Why it installs to `~/Library/Application Support`

A LaunchAgent inherits no privacy (TCC) grants, so launchd cannot read `~/Desktop`, `~/Documents`, `~/Downloads`, or iCloud Drive. An agent pointed at a project in one of those folders dies immediately with:

```
shell-init: error retrieving current directory: getcwd: cannot access parent directories: Operation not permitted
bash: /Users/you/Downloads/blaster-mac-client/run.sh: Operation not permitted
```

`~/Library/Application Support` is not protected, so installing there means the agent runs with **no permission prompts and no Full Disk Access**. The agent also launches `.venv/bin/python -m blaster` directly rather than going through `run.sh`, so it needs no shell and never installs dependencies at login.

The one permission that can still be required is **Bluetooth**: if the light never responds after installing, check **System Settings → Privacy & Security → Bluetooth** and allow `blaster-mac-client`.

## Configuration

Edit `config.yaml` next to the `blaster/` package — the project root when running from source, or `~/Library/Application Support/blaster-mac-client/config.yaml` once installed (the status UI always edits the one the running app loaded). All commands are specified by **name** (the client resolves names to indices using the device’s Saved Codes).

```yaml
ble:
  device_name: "IR Blaster"

events:
  OnConnect:
    - NamedCommand: "On"
      Delay: 0
    - NamedCommand: "Green"
      Delay: 2
  HeartbeatStopped:         # first item: schedule + HeartbeatInterval
    - NamedCommand: "Off"
      Delay: 900
      HeartbeatInterval: 60
  Active:
    - NamedCommand: "Red"
  Idle:                     # first item's Delay = cooldown before Idle
    - NamedCommand: "Green"
      Delay: 120
```

Every event is a **list** of `{ NamedCommand, Delay? }`. Commands run in order; each `Delay` is seconds to wait before that command (0 = immediately). Single `{ NamedCommand, Delay }` still works for one command.

| Event | Description |
|-------|-------------|
| **OnConnect** | Commands to run when the client connects, in order. |
| **HeartbeatStopped** | First item only: ESP32 runs `NamedCommand` when no heartbeat for `Delay` seconds; `HeartbeatInterval` = how often the client sends a heartbeat. Must be less than `Delay` (or 0 to disable heartbeats), otherwise the config is rejected. |
| **Active** | Commands when camera or mic turns on (e.g. "Red"). |
| **Idle** | First item's `Delay` = cooldown (seconds) before Idle; then all commands run in order. |

Command names must match the **name** of a saved code on the IR Blaster (web UI or `GET /saved`). The ESP32 has no built-in "On" or "Off"; the client sends On and arms the delayed Off via the Schedule characteristic.

## Running tests

No device required; unit tests only.

```bash
source .venv/bin/activate
pytest tests/ -v
```

## Troubleshooting

- **“Could not find or connect to IR Blaster”**  
  Ensure the IR Blaster is powered, in range, and already paired with this Mac. Check **System Settings → Bluetooth**. If you use a different terminal (e.g. Cursor), grant it Bluetooth access under **Privacy & Security → Bluetooth**.

- **“Device not found”**  
  macOS often does not list custom BLE GATT servers in the Bluetooth menu. Use this app (or nRF Connect) to connect; after pairing once, reconnection is automatic.

- **Camera/mic state not updating**  
  The app uses `log stream` with `com.apple.controlcenter` / `sensor-indicators`. If you’re on an older macOS, the predicate or message format may differ; run `blaster/av_monitor.py` as a script to print initial state and live events and confirm events are received.

- **Command not found**  
  Command names in `config.yaml` (e.g. "Red", "Green", "On", "Off") must match the **name** of a saved code on the IR Blaster. Check the web UI or `GET /saved` for the exact names.

- **`Operation not permitted` in the LaunchAgent logs**  
  The agent is pointed at a privacy-protected folder (`~/Desktop`, `~/Documents`, `~/Downloads`, iCloud Drive). Run `./install.sh` again to reinstall to `~/Library/Application Support/blaster-mac-client`; see [Why it installs to `~/Library/Application Support`](#why-it-installs-to-libraryapplication-support).

## Packaging for another Mac (e.g. send via Teams)

From the project root:

```bash
make package
```

This writes `dist/blaster-mac-client.zip`, excluding `.venv`, `.git`, caches, and logs. Send that zip (e.g. via Teams). It includes **QUICKSTART.txt** with these steps for the recipient. On the other Mac:

1. Unzip the file (anywhere, including Downloads).
2. Open Terminal, then: `cd blaster-mac-client`
3. Install to run at login: `chmod +x install.sh && ./install.sh`

The installer copies the app out of the unzipped folder, so the recipient can delete it afterwards. To try it once without installing, run `chmod +x run.sh && ./run.sh` instead and stop with **Ctrl+C**.

## Project layout

```
blaster-mac-client/
  Makefile              # make venv / test / run / install / package / clean
  config.yaml           # Device name, events (NamedCommand, Delay, HeartbeatInterval)
  requirements.txt
  run.sh                # One-step run from source (creates venv if needed, then starts app)
  install.sh            # Installer: copy to ~/Library/Application Support + LaunchAgent
  uninstall.sh          # Unload the agent and delete the installed copy
  com.blaster-mac-client.plist  # LaunchAgent template (INSTALL_DIR / LOG_DIR substituted by install.sh)
  QUICKSTART.txt        # Short instructions for someone running on another Mac
  blaster/
    __init__.py
    __main__.py         # Entry point (python -m blaster)
    app.py              # AppController: BLE lifecycle, status, safe config restart
    web.py              # Localhost HTTP UI + JSON API (default :8765)
    static/             # Status / controls / config UI
    config.py           # Load/save config with defaults
    ble_client.py       # BLE scan, connect, send_command, reconnect
    av_monitor.py       # Camera/mic via log stream
    state_machine.py    # IDLE / ACTIVE / COOLDOWN, 2-min timer
  tests/
    test_config.py
    test_av_monitor.py
    test_state_machine.py
```

This repo is intended to live separately from the IR Blaster firmware repo; point the “IR Blaster” link above to your actual firmware project.
