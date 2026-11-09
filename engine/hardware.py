"""
MXB Hardware Manager — Bluetooth, Wi-Fi, audio, microphone, brightness and
device inventory on Windows 10/11.

Strategy per feature (best API first, always with a working fallback):
- Radios (Bluetooth / Wi-Fi on/off): WinRT Windows.Devices.Radios -> open Settings page.
- Bluetooth devices + connect/disconnect: Win32 Bluetooth API (bthprops.cpl via ctypes),
  toggling the audio service profiles the same way Windows' own tray does -> Settings page.
- Wi-Fi networks / connect: netsh wlan.
- Volume / mic mute: pycaw (Core Audio) -> media virtual keys.
- Brightness: screen-brightness-control (WMI + DDC/CI) -> PowerShell WMI.
- Device inventory: PowerShell Get-PnpDevice.

Parsing helpers are pure functions so they are tested on any OS.
"""
import json
import os
import re
import subprocess
import sys
import time
import uuid
import ctypes
from ctypes import wintypes
from utils.logger import log

CREATE_NO_WINDOW = 0x08000000

# Bluetooth service class UUIDs used by headphones, earbuds and speakers.
BT_AUDIO_SERVICES = {
    "A2DP sink": "0000110B-0000-1000-8000-00805F9B34FB",
    "AVRCP target": "0000110C-0000-1000-8000-00805F9B34FB",
    "AVRCP": "0000110E-0000-1000-8000-00805F9B34FB",
    "Handsfree": "0000111E-0000-1000-8000-00805F9B34FB",
    "Headset": "00001108-0000-1000-8000-00805F9B34FB",
}

SETTINGS_PAGES = {
    "bluetooth": "ms-settings:bluetooth",
    "wifi": "ms-settings:network-wifi",
    "wi-fi": "ms-settings:network-wifi",
    "network": "ms-settings:network-status",
    "sound": "ms-settings:sound",
    "audio": "ms-settings:sound",
    "display": "ms-settings:display",
    "brightness": "ms-settings:display",
    "battery": "ms-settings:batterysaver",
    "power": "ms-settings:powersleep",
    "privacy": "ms-settings:privacy",
    "microphone": "ms-settings:privacy-microphone",
    "camera": "ms-settings:privacy-webcam",
    "update": "ms-settings:windowsupdate",
    "windows update": "ms-settings:windowsupdate",
    "apps": "ms-settings:appsfeatures",
    "mouse": "ms-settings:mousetouchpad",
    "touchpad": "ms-settings:devices-touchpad",
    "keyboard": "ms-settings:typing",
    "notifications": "ms-settings:notifications",
    "storage": "ms-settings:storagesense",
    "printers": "ms-settings:printers",
    "devices": "ms-settings:connecteddevices",
}

DEVICE_CLASSES = {
    "keyboard": ["Keyboard"],
    "mouse": ["Mouse"],
    "camera": ["Camera", "Image"],
    "audio": ["AudioEndpoint", "MEDIA"],
    "bluetooth": ["Bluetooth"],
    "usb": ["USB"],
    "monitor": ["Monitor"],
    "printer": ["Printer"],
    "disk": ["DiskDrive"],
    "hid": ["HIDClass"],
}

_GENERIC_DEVICE_NAMES = re.compile(
    r"(root hub|host controller|composite device|generic|enumerator|hid-compliant (?:vendor|system|consumer|device)|"
    r"usb input device|microsoft bluetooth|rfcomm|le enumerator|bluetooth device \(|avrcp transport|"
    r"service discovery|personal area network|wireless bluetooth|intel\(r\) wireless bluetooth|realtek bluetooth)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Pure helpers (tested cross-platform)
# ---------------------------------------------------------------------------
def parse_on_off(target: str) -> str:
    t = (target or "").lower().strip()
    if t in {"on", "enable", "enabled", "start", "true", "1"}:
        return "on"
    if t in {"off", "disable", "disabled", "stop", "false", "0"}:
        return "off"
    if t in {"toggle", "switch"}:
        return "toggle"
    return "status"


def parse_level(target: str, current: int | None = None, step: int = 10) -> int | None:
    """'50', '50%', 'up', 'down', 'max', 'min' -> 0..100 (None for status)."""
    t = (target or "").lower().strip().rstrip("%").replace("percent", "").strip()
    if t in {"", "status", "level", "current"}:
        return None
    if t in {"max", "maximum", "full", "100"}:
        return 100
    if t in {"min", "minimum", "zero", "0"}:
        return 0
    if t in {"up", "increase", "higher", "louder", "brighter", "more"}:
        return min(100, (current if current is not None else 50) + step)
    if t in {"down", "decrease", "lower", "quieter", "dimmer", "less"}:
        return max(0, (current if current is not None else 50) - step)
    m = re.search(r"\d{1,3}", t)
    if m:
        return max(0, min(100, int(m.group(0))))
    return None


def volume_key_presses(level: int) -> tuple[int, int]:
    """Windows volume keys move 2% per press: (presses down to 0, presses up to level)."""
    return 50, int(round(max(0, min(100, level)) / 2))


def parse_netsh_interfaces(text: str) -> dict:
    info = {}
    for line in (text or "").splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "state":
            info["state"] = value.lower()
        elif key == "ssid":
            info["ssid"] = value
        elif key == "signal":
            info["signal"] = value
        elif key == "radio status" or key.startswith("radio"):
            info.setdefault("radio", value)
    return info


def parse_netsh_networks(text: str) -> list[dict]:
    networks, current = [], None
    for line in (text or "").splitlines():
        m = re.match(r"^\s*SSID\s+\d+\s*:\s*(.*)$", line)
        if m:
            current = {"ssid": m.group(1).strip() or "(hidden network)", "signal": "", "auth": ""}
            networks.append(current)
            continue
        if current is None or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        if key == "signal" and not current["signal"]:
            current["signal"] = value.strip()
        elif key == "authentication":
            current["auth"] = value.strip()
    return networks


def summarize_pnp_devices(records, category: str = "") -> str:
    """records: list of {Class, FriendlyName, Status} from Get-PnpDevice."""
    if isinstance(records, dict):
        records = [records]
    wanted = set()
    if category:
        for c in DEVICE_CLASSES.get(category.lower().rstrip("s"), [category]):
            wanted.add(c.lower())
    groups: dict[str, list[str]] = {}
    for rec in records or []:
        cls = str(rec.get("Class") or "Other")
        name = str(rec.get("FriendlyName") or "").strip()
        if not name or _GENERIC_DEVICE_NAMES.search(name):
            continue
        if wanted and cls.lower() not in wanted:
            continue
        status = str(rec.get("Status") or "")
        label = name if status in ("", "OK") else f"{name} ({status})"
        bucket = groups.setdefault(cls, [])
        if label not in bucket:
            bucket.append(label)
    if not groups:
        return f"No {category + ' ' if category else ''}devices found."
    parts = []
    for cls in sorted(groups):
        names = groups[cls]
        shown = ", ".join(names[:6]) + (f" and {len(names) - 6} more" if len(names) > 6 else "")
        parts.append(f"{cls}: {shown}")
    return "Connected devices — " + "; ".join(parts) + "."


def match_device_name(query: str, names: list[str]) -> str | None:
    from rapidfuzz import fuzz, process
    q = (query or "").lower()
    q = re.sub(r"\b(my|the|bluetooth|device|headphones?|earbuds?|headset|speaker)\b", " ", q).strip() or (query or "").lower()
    if not names:
        return None
    for n in names:
        if q and q in n.lower():
            return n
    best = process.extractOne(q, names, scorer=fuzz.token_set_ratio)
    return best[0] if best and best[1] >= 60 else None


# ---------------------------------------------------------------------------
# Win32 Bluetooth structures
# ---------------------------------------------------------------------------
class _SYSTEMTIME(ctypes.Structure):
    _fields_ = [(n, wintypes.WORD) for n in
                ("wYear", "wMonth", "wDayOfWeek", "wDay", "wHour", "wMinute", "wSecond", "wMilliseconds")]


class _BT_ADDRESS(ctypes.Union):
    _fields_ = [("ullLong", ctypes.c_ulonglong), ("rgBytes", ctypes.c_ubyte * 6)]


class BLUETOOTH_DEVICE_INFO(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("Address", _BT_ADDRESS),
        ("ulClassofDevice", wintypes.ULONG),
        ("fConnected", wintypes.BOOL),
        ("fRemembered", wintypes.BOOL),
        ("fAuthenticated", wintypes.BOOL),
        ("stLastSeen", _SYSTEMTIME),
        ("stLastUsed", _SYSTEMTIME),
        ("szName", wintypes.WCHAR * 248),
    ]


class BLUETOOTH_DEVICE_SEARCH_PARAMS(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("fReturnAuthenticated", wintypes.BOOL),
        ("fReturnRemembered", wintypes.BOOL),
        ("fReturnUnknown", wintypes.BOOL),
        ("fReturnConnected", wintypes.BOOL),
        ("fIssueInquiry", wintypes.BOOL),
        ("cTimeoutMultiplier", ctypes.c_ubyte),
        ("hRadio", wintypes.HANDLE),
    ]


class BLUETOOTH_FIND_RADIO_PARAMS(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD)]


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def from_string(cls, s: str) -> "_GUID":
        u = uuid.UUID(s)
        g = cls()
        g.Data1, g.Data2, g.Data3 = u.time_low, u.time_mid, u.time_hi_version
        for i, b in enumerate(u.bytes[8:]):
            g.Data4[i] = b
        return g


class HardwareManager:
    RADIO_WIFI = 1
    RADIO_BLUETOOTH = 3

    def __init__(self):
        self.is_windows = sys.platform == "win32"
        self._bt = None

    # ------------------------------------------------------------------ shell helpers
    def _run(self, args: list[str], timeout: float = 12.0) -> tuple[int, str]:
        try:
            kwargs = {"capture_output": True, "text": True, "timeout": timeout}
            if self.is_windows:
                kwargs["creationflags"] = CREATE_NO_WINDOW
            proc = subprocess.run(args, **kwargs)
            return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
        except Exception as e:
            return 1, str(e)

    def _ps(self, script: str, timeout: float = 15.0) -> tuple[int, str]:
        return self._run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                          "-Command", script], timeout)

    def open_settings(self, page: str) -> str:
        key = (page or "").lower().replace(" settings", "").strip()
        uri = SETTINGS_PAGES.get(key) or SETTINGS_PAGES.get(key.rstrip("s")) or "ms-settings:"
        try:
            os.startfile(uri)  # type: ignore[attr-defined]
            return f"Opened {key or 'Windows'} settings."
        except Exception as e:
            return f"Could not open settings: {e}"

    # ------------------------------------------------------------------ radios
    def _set_radio(self, kind: int, state: str) -> str:
        import asyncio

        async def _go():
            from winrt.windows.devices.radios import Radio, RadioState
            await Radio.request_access_async()
            radios = await Radio.get_radios_async()
            matched = [r for r in radios if int(r.kind) == kind]
            if not matched:
                return None
            r = matched[0]
            current = "on" if int(r.state) == 1 else "off"
            if state == "status":
                return current
            desired = state if state != "toggle" else ("off" if current == "on" else "on")
            enum_val = getattr(RadioState, "ON" if desired == "on" else "OFF", None)
            if enum_val is None:
                enum_val = getattr(RadioState, "On" if desired == "on" else "Off")
            result = await r.set_state_async(enum_val)
            return desired if int(result) == 1 else f"denied:{int(result)}"  # RadioAccessStatus.Allowed == 1

        return asyncio.run(_go())

    def _radio(self, kind: int, label: str, target: str, settings_page: str) -> str:
        state = parse_on_off(target)
        try:
            res = self._set_radio(kind, state)
        except Exception as e:
            log.warning(f"Hardware: WinRT radio control unavailable ({e}).")
            res = "error"
        if res is None:
            return f"No {label} radio found on this PC."
        if res in ("on", "off"):
            return f"{label} is {res}." if state == "status" else f"{label} turned {res}."
        self.open_settings(settings_page)
        return f"Windows didn't let me switch {label} directly, so I opened {label} settings for you."

    def bluetooth_power(self, target: str) -> str:
        return self._radio(self.RADIO_BLUETOOTH, "Bluetooth", target, "bluetooth")

    def wifi_power(self, target: str) -> str:
        state = parse_on_off(target)
        if state == "status":
            return self.wifi_status()
        return self._radio(self.RADIO_WIFI, "Wi-Fi", target, "wifi")

    # ------------------------------------------------------------------ bluetooth devices
    def _bt_api(self):
        if self._bt is None:
            bt = ctypes.WinDLL("bthprops.cpl")
            bt.BluetoothFindFirstRadio.argtypes = [ctypes.POINTER(BLUETOOTH_FIND_RADIO_PARAMS), ctypes.POINTER(wintypes.HANDLE)]
            bt.BluetoothFindFirstRadio.restype = wintypes.HANDLE
            bt.BluetoothFindRadioClose.argtypes = [wintypes.HANDLE]
            bt.BluetoothFindRadioClose.restype = wintypes.BOOL
            bt.BluetoothFindFirstDevice.argtypes = [ctypes.POINTER(BLUETOOTH_DEVICE_SEARCH_PARAMS), ctypes.POINTER(BLUETOOTH_DEVICE_INFO)]
            bt.BluetoothFindFirstDevice.restype = wintypes.HANDLE
            bt.BluetoothFindNextDevice.argtypes = [wintypes.HANDLE, ctypes.POINTER(BLUETOOTH_DEVICE_INFO)]
            bt.BluetoothFindNextDevice.restype = wintypes.BOOL
            bt.BluetoothFindDeviceClose.argtypes = [wintypes.HANDLE]
            bt.BluetoothFindDeviceClose.restype = wintypes.BOOL
            bt.BluetoothSetServiceState.argtypes = [wintypes.HANDLE, ctypes.POINTER(BLUETOOTH_DEVICE_INFO), ctypes.POINTER(_GUID), wintypes.DWORD]
            bt.BluetoothSetServiceState.restype = wintypes.DWORD
            self._bt = bt
        return self._bt

    def _first_radio(self):
        bt = self._bt_api()
        params = BLUETOOTH_FIND_RADIO_PARAMS(ctypes.sizeof(BLUETOOTH_FIND_RADIO_PARAMS))
        h_radio = wintypes.HANDLE()
        h_find = bt.BluetoothFindFirstRadio(ctypes.byref(params), ctypes.byref(h_radio))
        if not h_find:
            return None
        bt.BluetoothFindRadioClose(h_find)
        return h_radio if h_radio.value else None

    def _paired_devices(self) -> list[BLUETOOTH_DEVICE_INFO]:
        bt = self._bt_api()
        params = BLUETOOTH_DEVICE_SEARCH_PARAMS()
        params.dwSize = ctypes.sizeof(BLUETOOTH_DEVICE_SEARCH_PARAMS)
        params.fReturnAuthenticated = True
        params.fReturnRemembered = True
        params.fReturnConnected = True
        params.fReturnUnknown = False
        params.fIssueInquiry = False
        params.cTimeoutMultiplier = 0
        params.hRadio = None
        devices = []
        info = BLUETOOTH_DEVICE_INFO()
        info.dwSize = ctypes.sizeof(BLUETOOTH_DEVICE_INFO)
        h = bt.BluetoothFindFirstDevice(ctypes.byref(params), ctypes.byref(info))
        if not h:
            return devices
        try:
            while True:
                devices.append(info)  # each iteration fills a fresh struct, so no copy is needed
                info = BLUETOOTH_DEVICE_INFO()
                info.dwSize = ctypes.sizeof(BLUETOOTH_DEVICE_INFO)
                if not bt.BluetoothFindNextDevice(h, ctypes.byref(info)):
                    break
        finally:
            bt.BluetoothFindDeviceClose(h)
        return devices

    def bluetooth_devices(self) -> str:
        try:
            devices = self._paired_devices()
        except Exception as e:
            log.warning(f"Hardware: Bluetooth API failed: {e}")
            return self._bt_devices_powershell()
        if not devices:
            return "No paired Bluetooth devices found (or Bluetooth is off)."
        parts = [f"{d.szName} ({'connected' if d.fConnected else 'not connected'})" for d in devices if d.szName]
        return "Paired Bluetooth devices: " + ", ".join(parts) + "."

    def _bt_devices_powershell(self) -> str:
        code, out = self._ps("Get-PnpDevice -Class Bluetooth | Select-Object Class,FriendlyName,Status | ConvertTo-Json -Compress")
        if code != 0 or not out.strip():
            return "Could not read Bluetooth devices."
        try:
            return summarize_pnp_devices(json.loads(out), "bluetooth")
        except Exception:
            return "Could not read Bluetooth devices."

    def _set_bt_services(self, name_query: str, enable: bool) -> str:
        devices = self._paired_devices()
        names = [d.szName for d in devices if d.szName]
        match = match_device_name(name_query, names)
        if not match:
            listing = ", ".join(names) if names else "none"
            return f"I couldn't find a paired Bluetooth device called '{name_query}'. Paired devices: {listing}."
        dev = next(d for d in devices if d.szName == match)
        if enable and dev.fConnected:
            return f"{match} is already connected."
        if not enable and not dev.fConnected:
            return f"{match} is already disconnected."
        h_radio = self._first_radio()
        if h_radio is None:
            return "Bluetooth seems to be off. Say 'turn on bluetooth' first."
        bt = self._bt_api()
        ok = 0
        for guid_str in BT_AUDIO_SERVICES.values():
            guid = _GUID.from_string(guid_str)
            if enable:
                bt.BluetoothSetServiceState(h_radio, ctypes.byref(dev), ctypes.byref(guid), 0)
                time.sleep(0.15)
            if bt.BluetoothSetServiceState(h_radio, ctypes.byref(dev), ctypes.byref(guid), 1 if enable else 0) == 0:
                ok += 1
        try:
            ctypes.windll.kernel32.CloseHandle(h_radio)
        except Exception:
            pass
        if ok:
            return f"{'Connecting' if enable else 'Disconnected'} {match}."
        self.open_settings("bluetooth")
        return f"Windows refused to {'connect' if enable else 'disconnect'} {match} directly (it may need admin rights), so I opened Bluetooth settings."

    def bluetooth_connect(self, name: str) -> str:
        try:
            return self._set_bt_services(name, enable=True)
        except Exception as e:
            log.warning(f"Hardware: bluetooth connect failed: {e}")
            self.open_settings("bluetooth")
            return "I couldn't control Bluetooth directly, so I opened Bluetooth settings."

    def bluetooth_disconnect(self, name: str) -> str:
        try:
            return self._set_bt_services(name, enable=False)
        except Exception as e:
            log.warning(f"Hardware: bluetooth disconnect failed: {e}")
            self.open_settings("bluetooth")
            return "I couldn't control Bluetooth directly, so I opened Bluetooth settings."

    # ------------------------------------------------------------------ wi-fi
    def wifi_status(self) -> str:
        code, out = self._run(["netsh", "wlan", "show", "interfaces"])
        info = parse_netsh_interfaces(out)
        if code != 0 and not info:
            return "Could not read Wi-Fi status."
        if info.get("state") == "connected":
            sig = f" at {info['signal']} signal" if info.get("signal") else ""
            return f"Wi-Fi is connected to {info.get('ssid', 'a network')}{sig}."
        return f"Wi-Fi is not connected (state: {info.get('state', 'unknown')})."

    def wifi_networks(self) -> str:
        code, out = self._run(["netsh", "wlan", "show", "networks", "mode=bssid"])
        nets = parse_netsh_networks(out)
        if not nets:
            return "No Wi-Fi networks found (is Wi-Fi on?)."
        nets.sort(key=lambda n: int(re.sub(r"\D", "", n["signal"]) or 0), reverse=True)
        shown = ", ".join(f"{n['ssid']} ({n['signal'] or '?'})" for n in nets[:8])
        return f"Nearby Wi-Fi networks: {shown}."

    def wifi_connect(self, ssid: str) -> str:
        ssid = (ssid or "").strip().strip('"')
        if not ssid:
            return "Which Wi-Fi network should I connect to?"
        code, out = self._run(["netsh", "wlan", "connect", f"name={ssid}"])
        if code == 0:
            return f"Connecting to {ssid}."
        if "no profile" in out.lower() or "not found" in out.lower():
            self.open_settings("wifi")
            return f"{ssid} isn't a saved network, so I opened Wi-Fi settings for you to enter its password."
        return f"Could not connect to {ssid}: {out.strip()[:120]}"

    def wifi_disconnect(self) -> str:
        code, out = self._run(["netsh", "wlan", "disconnect"])
        return "Disconnected from Wi-Fi." if code == 0 else f"Could not disconnect: {out.strip()[:120]}"

    # ------------------------------------------------------------------ audio
    @staticmethod
    def _com_init():
        try:
            import comtypes
            comtypes.CoInitialize()
        except Exception:
            pass

    def _endpoint_volume(self, microphone: bool = False):
        self._com_init()
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        device = AudioUtilities.GetMicrophone() if microphone else AudioUtilities.GetSpeakers()
        if device is None:
            raise RuntimeError("no audio device")
        ev = getattr(device, "EndpointVolume", None)
        if ev is not None:
            return ev
        from comtypes import CLSCTX_ALL
        iface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return ctypes.cast(iface, ctypes.POINTER(IAudioEndpointVolume))

    def set_volume(self, target: str, keyboard=None) -> str:
        try:
            ev = self._endpoint_volume()
            current = int(round(ev.GetMasterVolumeLevelScalar() * 100))
            level = parse_level(target, current)
            if level is None:
                muted = bool(ev.GetMute())
                return f"Volume is at {current}%{' (muted)' if muted else ''}."
            ev.SetMute(0, None)
            ev.SetMasterVolumeLevelScalar(level / 100.0, None)
            return f"Volume set to {level}%."
        except Exception as e:
            log.warning(f"Hardware: pycaw volume unavailable ({e}); using media keys.")
        level = parse_level(target, None)
        if keyboard is None:
            return "Volume control is unavailable."
        if level is None:
            return "I can't read the exact volume without pycaw installed."
        down, up = volume_key_presses(level)
        for _ in range(down):
            keyboard.tap_key("volume_down")
        for _ in range(up):
            keyboard.tap_key("volume_up")
        return f"Volume set to about {level}%."

    def mic_mute(self, target: str) -> str:
        state = parse_on_off(target)
        try:
            ev = self._endpoint_volume(microphone=True)
            muted = bool(ev.GetMute())
            if state == "status":
                return f"Microphone is {'muted' if muted else 'on'}."
            want_muted = (not muted) if state == "toggle" else (state == "on")
            ev.SetMute(1 if want_muted else 0, None)
            return "Microphone muted. I can't hear you until you unmute it with the chat or hotkey." if want_muted else "Microphone unmuted."
        except Exception as e:
            log.warning(f"Hardware: microphone mute failed: {e}")
            self.open_settings("microphone")
            return "I couldn't change the microphone directly, so I opened microphone settings."

    def audio_devices(self) -> str:
        try:
            import sounddevice as sd
            devs = sd.query_devices()
            outs, ins = [], []
            for d in devs:
                name = d["name"]
                if d.get("max_output_channels", 0) > 0 and name not in outs:
                    outs.append(name)
                if d.get("max_input_channels", 0) > 0 and name not in ins:
                    ins.append(name)
            return f"Speakers: {', '.join(outs[:6]) or 'none'}. Microphones: {', '.join(ins[:6]) or 'none'}."
        except Exception as e:
            return f"Could not list audio devices: {e}"

    # ------------------------------------------------------------------ display
    def set_brightness(self, target: str) -> str:
        try:
            import screen_brightness_control as sbc
            current_list = sbc.get_brightness()
            current = int(current_list[0]) if current_list else None
            level = parse_level(target, current)
            if level is None:
                return f"Screen brightness is {current}%."
            sbc.set_brightness(level)
            return f"Brightness set to {level}%."
        except Exception as e:
            log.warning(f"Hardware: screen_brightness_control unavailable ({e}); trying WMI.")
        code, out = self._ps("(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness).CurrentBrightness")
        current = int(re.findall(r"\d+", out)[0]) if code == 0 and re.findall(r"\d+", out) else None
        level = parse_level(target, current)
        if level is None:
            return f"Screen brightness is {current}%." if current is not None else "I couldn't read the brightness on this display."
        code, out = self._ps(
            "Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods | "
            f"Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{{Timeout=1; Brightness={level}}}"
        )
        if code == 0:
            return f"Brightness set to {level}%."
        self.open_settings("display")
        return "This monitor doesn't accept brightness commands, so I opened display settings."

    # ------------------------------------------------------------------ inventory
    def list_devices(self, category: str = "") -> str:
        classes = ["Bluetooth", "USB", "HIDClass", "Keyboard", "Mouse", "Camera", "Image",
                   "AudioEndpoint", "Monitor", "Printer", "DiskDrive", "MEDIA"]
        class_list = ",".join(f"'{c}'" for c in classes)
        script = (f"Get-PnpDevice -PresentOnly | Where-Object {{ $_.Class -in @({class_list}) }} | "
                  "Select-Object Class,FriendlyName,Status | ConvertTo-Json -Compress")
        code, out = self._ps(script, timeout=25)
        if code != 0 or not out.strip():
            return "Could not read the device list."
        try:
            return summarize_pnp_devices(json.loads(out), category)
        except Exception as e:
            return f"Could not parse the device list: {e}"

    # ------------------------------------------------------------------ power
    def power_action(self, target: str) -> str:
        t = (target or "").lower().replace(" ", "_").replace("-", "_")
        if t in {"shutdown", "shut_down", "power_off", "turn_off"}:
            self._run(["shutdown", "/s", "/t", "5"])
            return "Shutting down in 5 seconds. Say 'cancel shutdown' to stop it."
        if t in {"restart", "reboot"}:
            self._run(["shutdown", "/r", "/t", "5"])
            return "Restarting in 5 seconds. Say 'cancel shutdown' to stop it."
        if t in {"sign_out", "log_off", "log_out", "logout", "signout"}:
            self._run(["shutdown", "/l"])
            return "Signing out."
        if t in {"sleep", "suspend"}:
            try:
                ctypes.windll.powrprof.SetSuspendState(False, False, False)
                return "Going to sleep."
            except Exception as e:
                return f"Could not sleep: {e}"
        if t in {"cancel", "abort", "cancel_shutdown"}:
            self._run(["shutdown", "/a"])
            return "Cancelled the pending shutdown."
        return f"Unknown power action '{target}'."
