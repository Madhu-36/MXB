# MXB Two-Hands Desktop Automation Guide

## 1. Overview & Core Philosophy

MXB automates Windows desktops by mimicking a skilled human operator using **"Two Hands"**:
1. **Perception Hand (Ears & Eyes)**: Continuous, non-blocking audio capture, Silero Neural VAD, live Whisper ASR, and Windows Native OCR vision.
2. **Execution Hand (Mouse & Keyboard)**: Thread-decoupled, 64-bit ctypes OS automation that manipulates windows, types text, and moves the mouse pointer with natural acceleration curves.

Because the perception hand never blocks on the execution hand, the user can speak commands while previous actions are in progress or immediately say **"Stop!"** to cancel an active task in less than 1 millisecond.

---

## 2. Mouse Mechanics & Safety Boundaries

All cursor interactions in MXB use native `user32.dll` APIs configured with explicit 64-bit ctypes signatures (`argtypes`/`restype`) to prevent stack canary overruns (`STATUS_STACK_BUFFER_OVERRUN - 0xC0000409`).

```
                    Screen Bounds Clamping
 (0, 0) +------------------------------------------+ (Max_X, 0)
        |  Margin (Safe Region)                    |
        |      +----------------------------+      |
        |      | Target Element             |      |
        |      | (Center X, Y)              |      |
        |      +----------------------------+      |
        |                                          |
 (0, Max_Y) +--------------------------------------+ (Max_X, Max_Y)
```

### Safety Features
- **Viewport Boundary Clamping**: Targets are automatically bounded within `[0, GetSystemMetrics(0) - 1]` and `[0, GetSystemMetrics(1) - 1]`.
- **Smooth Trajectory Easing**: Mouse movement calculates cubic Bezier interpolation points to prevent robotic snapping and trigger modern UI hover events.
- **Micro-Delays**: 20ms–40ms delays between `MOUSEEVENTF_LEFTDOWN` and `MOUSEEVENTF_LEFTUP` guarantee that native Windows message queues register standard click events.

---

## 3. Keyboard Automation & Hotkey Validation

Keyboard inputs are managed by `KeyboardExtended` (`engine/keyboard_ext.py`).

### Key Validation & Canonical Ordering
When executing shortcut sequences (e.g. `Ctrl + Shift + Esc`), MXB verifies:
1. **Modifier Precedence**: Modifiers (`ctrl`, `alt`, `shift`, `win`) are sorted before trigger keys.
2. **Reverse Release Order**: Keys are pressed `M1 -> M2 -> T` and released `T -> M2 -> M1` to ensure correct OS shortcut triggering.
3. **OS-Reserved Conflict Detection**: Unsafe combinations such as `Ctrl + Alt + Del` are rejected before simulation.

### Fast Unicode Clipboard Pasting
For long text blocks (> 15 characters), MXB bypasses slow keystroke simulation by safely injecting text via the Windows clipboard and simulating `Ctrl + V`, preserving the user's prior clipboard history.

---

## 4. Screen Vision & Coordinate Localization

```
Desktop Window Grab (Qt QGuiApplication / grabWindow)
                       │
                       ▼
           PNG In-Memory Stream (<15ms)
                       │
                       ▼
          Windows Native OCR (WinRT)
                       │
                       ▼
      Bounding Rects: [x, y, width, height]
                       │
                       ▼
     Fuzzy Search Matching (rapidfuzz > 75%)
                       │
                       ▼
     Target Coordinates: (center_x, center_y)
```

### Active Window ROI Targeting
When a user targets the active window, `ScreenVision.get_active_window_rect()` uses `GetForegroundWindow()` and `GetWindowRect()` to isolate the focused application, reducing OCR search scope and eliminating desktop background interference.

---

## 5. Fail-Safe Voice Interruption

If MXB begins executing an action (such as typing or scrolling), the user can interrupt at any point:
- **Zero-Latency Earcon**: `audio_feedback.play("abort")` plays an instant system earcon.
- **Atomic Abort Flag**: `ActionPlanner._abort_event.set()` signals running worker loops to immediately exit without completing remaining queue steps.
- **Non-Destructive SAPI Teardown**: Voice synthesis purges queued speech with `SVSFPurgeBeforeSpeak` before uninitializing COM apartments.
