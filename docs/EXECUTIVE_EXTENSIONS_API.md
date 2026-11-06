# MXB v2.3 Executive Extensions & API Reference

This document provides architectural and technical documentation for all executive extensions integrated into **MXB (Machine eXecutive Brain) v2.3**.

---

## 1. Battery & Power Telemetry (`PowerManager`)

Located in [`utils/power_manager.py`](file:///c:/Users/Asus/OneDrive/Desktop/PROJECTS/MXB/mxb_app/utils/power_manager.py).

### Capabilities
- Monitors battery percentage, AC adapter connection status, and remaining runtime estimates.
- Categorizes battery state into health tiers: `full`, `charging`, `good`, `low` (<= 30%), and `critical` (<= 15%).
- Provides `is_power_saving_needed()` to dynamically throttle background polling when on low battery.
- Detects desktop workstations without batteries and reports AC power gracefully.

### Action Invocation
```python
executor.execute_action("check_battery")
# Returns: "Battery is at 100 percent and plugged in."
```

---

## 2. Advanced Window Geometry & Tiling (`WindowManager`)

Located in [`engine/window_manager.py`](file:///c:/Users/Asus/OneDrive/Desktop/PROJECTS/MXB/mxb_app/engine/window_manager.py).

### Capabilities
- 64-bit safe ctypes declarations for `user32.GetForegroundWindow` and `user32.MoveWindow`.
- Snaps focused windows into quadrants: `top_left`, `top_right`, `bottom_left`, `bottom_right`.
- Centers windows at 70% viewport scale.
- **Aero Shake**: `minimize_all_except_active()` minimizes background windows to declutter workspace.

### Action Invocation
```python
executor.execute_action("snap_window", "top_left")
executor.execute_action("aero_shake")
```

---

## 3. Hardware-Anchored Secure Vault (`SecureVault`)

Located in [`utils/vault.py`](file:///c:/Users/Asus/OneDrive/Desktop/PROJECTS/MXB/mxb_app/utils/vault.py).

### Capabilities
- Encrypts API keys and private notes using the **Windows Data Protection API (DPAPI)** via `crypt32.dll`.
- Cryptographic keys are anchored to the user's Windows login credentials and cannot be decrypted on other machines.
- Plaintext is never written to disk.

### Action Invocation
```python
executor.execute_action("vault_store", "openai_key::sk-proj-xyz123")
executor.execute_action("vault_get", "openai_key")
executor.execute_action("vault_list")
```

---

## 4. Meteorological Intelligence (`WeatherProbe`)

Located in [`utils/weather.py`](file:///c:/Users/Asus/OneDrive/Desktop/PROJECTS/MXB/mxb_app/utils/weather.py).

### Capabilities
- Fetches real-time temperature (Celsius and Fahrenheit), weather description, humidity, and "feels like" metric without proprietary API keys.
- Conversational city extraction regex supports phrases like *"what's the weather in Paris?"* or *"temperature in Tokyo"*.
- Built-in 3.5s timeout with offline fallback.

---

## 5. Process Lifecycle & Port Mapper (`ProcessManager`)

Located in [`utils/process_manager.py`](file:///c:/Users/Asus/OneDrive/Desktop/PROJECTS/MXB/mxb_app/utils/process_manager.py).

### Capabilities
- **Kernel Protection Guards**: Prevents accidental termination of critical Windows system processes (`explorer.exe`, `svchost.exe`, `csrss.exe`, `dwm.exe`, `services.exe`, etc.).
- **Listening Port Mapper**: `find_process_by_port(port)` resolves local TCP listeners (e.g. port 8080, 11434) to active PIDs and executable names.
- **Memory Inspector**: `get_top_processes(limit=5)` ranks active processes by physical RAM consumption.

### Action Invocation
```python
executor.execute_action("top_processes")
executor.execute_action("find_port", "11434")
executor.execute_action("kill_process", "notepad")
```

---

## 6. Native Screen Color Eyedropper (`ColorPicker`)

Located in [`engine/color_picker.py`](file:///c:/Users/Asus/OneDrive/Desktop/PROJECTS/MXB/mxb_app/engine/color_picker.py).

### Capabilities
- Samples pixels via 64-bit Windows GDI `gdi32.GetPixel` (<0.01ms per query).
- Automatically calculates Euclidean RGB distance to approximate nearest human-friendly color names (e.g. "Crimson", "Navy Blue", "Lime", "Gold").
- Queries either specific screen coordinates `(x, y)` or current mouse cursor location.

### Action Invocation
```python
executor.execute_action("pick_color", "100, 200")
executor.execute_action("cursor_color")
```

---

## 7. Countdown Timers (`TimerManager`)

Located in [`utils/timer_manager.py`](file:///c:/Users/Asus/OneDrive/Desktop/PROJECTS/MXB/mxb_app/utils/timer_manager.py).

### Capabilities
- Natural language duration parsing: *"5 minutes"*, *"1 minute 30 seconds"*, *"45s"*, *"2 hours"*.
- Non-blocking background threads with remaining time queries.
- Automatic auditory alert earcon (`audio_feedback.play("alert")`) on completion.
