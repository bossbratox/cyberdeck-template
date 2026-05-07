#!/usr/bin/env python3
# Deploy to: /opt/cyberdeck-shared/cyberdeck_touch.py on Pi
#
# Shared touch listener for all cyberdeck TUIs.
# Reads the cyberdeck-touch-mouse virtual device (BTN_LEFT + ABS_X/ABS_Y)
# published by touch-to-mouse.service. Raw MT protocol (ABS_MT_*) is NOT
# used here -- that is the legacy bt_tui.py approach being replaced.

import os
import struct
import threading
import time as _time_mod

# Diagnostic logger for trackpad event flow. Off by default; enable by setting
# TRACKPAD_DEBUG=1 in the environment of any process that imports this module.
# Output goes to /tmp/trackpad-debug.log on tmpfs (line-buffered).
_TRACKPAD_DEBUG = os.environ.get("TRACKPAD_DEBUG") == "1"
_DBG_FH = None
if _TRACKPAD_DEBUG:
    try:
        _DBG_FH = open("/tmp/trackpad-debug.log", "a", buffering=1)
    except OSError:
        _DBG_FH = None

# Console unblank — write ESC[13] to /dev/tty1 to wake display on input.
# Linux console blanks after `setterm -blank N`; keyboard auto-unblanks via
# kernel TTY layer, but EVIOCGRAB'd touch/trackpad bypass it. Listener threads
# call _unblank() on input events to wake the display. Debounced to ~1/sec.
_TTY1_FH = None
try:
    _TTY1_FH = open("/dev/tty1", "wb", buffering=0)
except OSError:
    pass
_last_unblank_t = 0.0

def _unblank():
    """Wake the console display (best-effort, debounced)."""
    global _last_unblank_t
    if _TTY1_FH is None:
        return
    now = _time_mod.time()
    if now - _last_unblank_t < 1.0:
        return
    _last_unblank_t = now
    try:
        _TTY1_FH.write(b"\x1b[13]")
    except OSError:
        pass


def _dbg(msg):
    """Write a timestamped line to the trackpad debug log if enabled."""
    if _DBG_FH is None:
        return
    try:
        _DBG_FH.write(f"{_time_mod.time():.3f} [{os.getpid()}] {msg}\n")
    except OSError:
        pass

# evdev constants for touch parsing.
# The real input source is /opt/cyberdeck-touch/touch-to-mouse.py, which grabs
# the raw Goodix panel and republishes it as an absolute-pointer uinput device
# named "cyberdeck-touch-mouse" (BTN_LEFT + ABS_X/ABS_Y). We parse *that* device,
# not the raw MT panel -- the translator holds an exclusive grab on the panel.
VIRTUAL_MOUSE_NAME = "cyberdeck-touch-mouse"
EV_KEY = 1
EV_ABS = 3
BTN_LEFT = 0x110
ABS_X = 0x00
ABS_Y = 0x01
INPUT_EVENT_FORMAT = "llHHi"  # struct input_event: sec, usec, type, code, value
INPUT_EVENT_SIZE = struct.calcsize(INPUT_EVENT_FORMAT)
SWIPE_THRESHOLD = 20  # pixels of Y movement before triggering one line of scroll
TAP_THRESHOLD = 15    # total movement (px) below this = tap, not swipe
TAP_MIN_MS = 50       # minimum hold time (ms) for intentional tap

# Mouse / trackpad constants
EV_REL = 2
REL_X = 0x00
REL_Y = 0x01
REL_WHEEL = 0x08
REL_WHEEL_HI_RES = 0x0B
HI_RES_PER_TICK = 120  # Linux standard hi-res units per wheel tick
MOUSE_SWIPE_THRESHOLD = 3  # BBQ10 trackpad sends small REL_Y deltas
MOUSE_CURSOR_X_THRESHOLD = 3   # px per char-cell for trackpad cursor (X)
MOUSE_CURSOR_Y_THRESHOLD = 5   # px per line for trackpad cursor (Y)


def trunc_toward_zero(n, d):
    """Python // rounds toward -inf; we want toward zero so +21//20 == 1
    and -21//20 == -1 symmetrically."""
    q = abs(n) // d
    return q if n >= 0 else -q


def find_touch_device():
    """Return evdev path for the cyberdeck virtual touch-mouse.

    Prefers the uinput pointer published by touch-to-mouse.service; falls back
    to any device whose name contains "touch" so a missing translator doesn't
    crash the app (listener will simply see no matching events).
    """
    try:
        with open("/proc/bus/input/devices") as f:
            content = f.read()
    except OSError:
        return None
    blocks = content.split("\n\n")

    def event_path(block):
        for line in block.split("\n"):
            if line.startswith("H: Handlers="):
                for part in line.split():
                    if part.startswith("event"):
                        return f"/dev/input/{part}"
        return None

    # Pass 1: exact virtual-mouse name
    for block in blocks:
        if VIRTUAL_MOUSE_NAME in block:
            path = event_path(block)
            if path:
                return path
    # Pass 2: generic touch fallback (legacy / translator-offline)
    for block in blocks:
        lower = block.lower()
        if "ft5" in lower or "goodix" in lower or "touch" in lower:
            path = event_path(block)
            if path:
                return path
    return None


# Global handle to the running touch thread (for optional stop)
_touch_thread = None


def start_touch_listener(on_scroll, on_tap, on_tap_xy=None):
    """Start daemon thread for touch events. Returns True if listener started.

    on_scroll(delta: int): called with positive int (scroll toward older) or
                           negative int (scroll toward newer). One call per
                           SWIPE_THRESHOLD px of movement.
    on_tap():              called on confirmed tap (e.g., jump to bottom).
    on_tap_xy(x, y):       optional, called with tap coordinates (0-639, 0-479).

    Returns False if no cyberdeck-touch-mouse device found.
    """
    dev = find_touch_device()
    if not dev or not os.path.exists(dev):
        return False
    global _touch_thread
    try:
        t = threading.Thread(
            target=_touch_loop,
            args=(dev, on_scroll, on_tap, on_tap_xy),
            daemon=True
        )
        t.start()
        _touch_thread = t
        return True
    except OSError:
        return False


def stop_touch_listener():
    """No-op for compatibility — touch thread is daemon and exits with app."""
    global _touch_thread
    _touch_thread = None


def _rel_has_scroll(rel_val):
    """True if REL bitmask includes REL_Y, REL_WHEEL, or REL_WHEEL_HI_RES."""
    return bool(rel_val & ((1 << REL_Y) | (1 << REL_WHEEL) | (1 << REL_WHEEL_HI_RES)))


def _event_path(block):
    for line in block.split("\n"):
        if line.startswith("H: Handlers="):
            for part in line.split():
                if part.startswith("event"):
                    return f"/dev/input/{part}"
    return None


def _is_mouse_candidate(block):
    """Return (path, is_strong_match) for a mouse/trackpad candidate, or (None, False)."""
    if VIRTUAL_MOUSE_NAME in block:
        return None, False
    path = _event_path(block)
    if not path or not os.access(path, os.R_OK):
        return None, False

    ev_val = None
    rel_val = None
    has_mouse_handler = False
    has_mouse_name = False
    for line in block.split("\n"):
        if line.startswith("B: EV="):
            try:
                ev_val = int(line.split("=")[1], 16)
            except ValueError:
                pass
        elif line.startswith("B: REL="):
            try:
                rel_val = int(line.split("=")[1], 16)
            except ValueError:
                pass
        elif line.startswith("H: Handlers="):
            if "mouse" in line.lower():
                has_mouse_handler = True
        elif line.startswith("N: Name="):
            name = line.lower()
            if any(k in name for k in ("mouse", "trackpad", "track", "pointer", "bbq", "bb q10")):
                has_mouse_name = True
            # Explicitly reject keyboards so we don't grab the typing interface
            if "keyboard" in name:
                return None, False

    if ev_val is None or not (ev_val & (1 << EV_REL)):
        return None, False

    # Strong match: has EV_REL + scroll axis + mouse indicator.
    if (rel_val is not None and _rel_has_scroll(rel_val)
            and (has_mouse_handler or has_mouse_name)):
        return path, True

    # Weak match: name/handler heuristics (used when REL bitmask is missing
    # or incomplete, but device still has EV_REL).
    if has_mouse_name or has_mouse_handler:
        return path, False

    return None, False


def find_all_mouse_devices():
    """Return a list of evdev paths for all mouse / trackpad candidates.

    Strong matches (EV_REL + scroll axis + mouse indicator) are returned first.
    Weak matches (name/handler only) follow.  This catches composite HID
    devices that split pointing and scroll across separate input nodes.
    """
    try:
        with open("/proc/bus/input/devices") as f:
            content = f.read()
    except OSError:
        return []
    blocks = content.split("\n\n")
    strong = []
    weak = []
    for block in blocks:
        path, is_strong = _is_mouse_candidate(block)
        if path is None:
            continue
        if is_strong:
            strong.append(path)
        else:
            weak.append(path)
    # Deduplicate while preserving order
    seen = set()
    result = []
    for path in strong + weak:
        if path not in seen:
            seen.add(path)
            result.append(path)
    return result


def find_mouse_device():
    """Return evdev path for the first mouse / trackpad candidate.

    Backward-compatible wrapper around find_all_mouse_devices().
    """
    devs = find_all_mouse_devices()
    return devs[0] if devs else None


# Global handles to running listener threads
_touch_thread = None
_mouse_threads = []


def start_mouse_listener(on_scroll, on_tap=None, on_delta=None):
    """Start daemon threads for mouse / trackpad scroll and click events.

    One thread is spawned per matching device so composite HID gadgets
    (e.g. BBQ10) that split REL_Y and REL_WHEEL across separate input
    nodes are all grabbed and monitored.

    on_scroll(delta: int): called with positive int (scroll down) or
                           negative int (scroll up).
    on_tap():              called on BTN_LEFT click (press+release, no drag).
    on_delta(dx, dy):      OPTIONAL. When set, REL_X/REL_Y deltas are
                           thresholded per-axis (MOUSE_CURSOR_X/Y_THRESHOLD)
                           and dispatched here INSTEAD of on_scroll. Used
                           for cell-granular cursor movement (e.g. text
                           editor) rather than viewport scrolling.

    Returns False if no suitable mouse device found.
    """
    devs = find_all_mouse_devices()
    _dbg(f"start_mouse_listener devs={devs}")
    if not devs:
        return False
    global _mouse_threads
    started = False
    for dev in devs:
        if not os.path.exists(dev):
            continue
        try:
            t = threading.Thread(
                target=_mouse_loop,
                args=(dev, on_scroll, on_tap, on_delta),
                daemon=True
            )
            t.start()
            _mouse_threads.append(t)
            started = True
        except OSError as _e:
            _dbg(f"start_mouse_listener thread spawn err dev={dev} err={_e}")
    return started


def stop_mouse_listener():
    """No-op for compatibility — mouse threads are daemon and exit with app."""
    global _mouse_threads
    _mouse_threads = []


def _mouse_loop(device_path, on_scroll, on_tap, on_delta=None):
    """Read relative mouse events: REL_Y / REL_WHEEL scroll, BTN_LEFT clicks.

    Tap detection uses accumulated REL_X/REL_Y rather than absolute position
    deltas so devices that emit both REL and ABS (e.g. bbq10 trackpad) still
    register clean clicks.

    Reconnects automatically if the device disconnects (e.g. BT drops).
    """
    import fcntl, errno, time as _time
    EVIOCGRAB = 0x40044590
    buf_size = INPUT_EVENT_SIZE * 16

    while True:
        # Use find_mouse_device() on each reconnect so we follow device-node
        # changes (e.g. BT reconnect may re-register at a different event node).
        dev = find_mouse_device() or device_path
        try:
            fd = os.open(dev, os.O_RDONLY)
        except OSError as _e:
            _dbg(f"_mouse_loop open failed dev={dev} err={_e}")
            _time.sleep(2)
            continue

        # Grab device exclusively so fbterm doesn't also process trackpad events
        # (which would inject cursor-movement escape sequences into the TUI stdin).
        # Retry on EBUSY: pet's TrackpadHandler may still hold the grab briefly
        # after pet is stopped; 10 × 100ms gives it 1 second to release.
        grabbed = False
        for _attempt in range(10):
            try:
                fcntl.ioctl(fd, EVIOCGRAB, 1)
                grabbed = True
                break
            except OSError as _e:
                if _e.errno == errno.EBUSY and _attempt < 9:
                    _time.sleep(0.1)
                else:
                    _dbg(f"_mouse_loop EVIOCGRAB failed dev={dev} attempt={_attempt} err={_e}")
                    break
        if not grabbed:
            # Another process (e.g. touch-to-mouse) owns this device.
            # Reading would block forever, so close and retry later.
            try:
                os.close(fd)
            except OSError:
                pass
            _time.sleep(2)
            continue

        _dbg(f"_mouse_loop start dev={dev} fd={fd} grabbed={grabbed}")

        accumulated = 0
        hi_res_accumulated = 0
        cursor_acc_x = 0  # for on_delta: cell-granular X
        cursor_acc_y = 0  # for on_delta: cell-granular Y
        pressed = False
        press_time = 0
        rel_dx = 0
        rel_dy = 0
        try:
            while True:
                data = os.read(fd, buf_size)
                if data:
                    _unblank()
                while len(data) >= INPUT_EVENT_SIZE:
                    _sec, _usec, ev_type, code, value = struct.unpack(
                        INPUT_EVENT_FORMAT, data[:INPUT_EVENT_SIZE])
                    data = data[INPUT_EVENT_SIZE:]

                    if ev_type != 0:  # skip SYN noise
                        _dbg(f"_mouse_loop ev type={ev_type} code={code} val={value}")

                    if ev_type == EV_REL:
                        if code == REL_Y:
                            accumulated += value
                            rel_dy += value
                            cursor_acc_y += value
                        elif code == REL_X:
                            rel_dx += value
                            cursor_acc_x += value
                        elif code == REL_WHEEL and value != 0:
                            _dbg(f"_mouse_loop on_scroll(wheel) delta={value}")
                            try:
                                on_scroll(value)
                            except Exception as _e:
                                _dbg(f"_mouse_loop on_scroll err={_e}")
                            accumulated = 0
                        elif code == REL_WHEEL_HI_RES:
                            hi_res_accumulated += value
                    elif ev_type == EV_KEY and code == BTN_LEFT:
                        if value == 1:  # press
                            pressed = True
                            press_time = _sec + _usec / 1e6
                            rel_dx = 0
                            rel_dy = 0
                        elif value == 0 and pressed:  # release
                            dur_ms = (_sec + _usec / 1e6 - press_time) * 1000
                            moved = abs(rel_dx) + abs(rel_dy)
                            if dur_ms < 500 and moved < TAP_THRESHOLD and on_tap is not None:
                                _dbg(f"_mouse_loop on_tap dur_ms={dur_ms:.0f} moved={moved}")
                                try:
                                    on_tap()
                                except Exception as _e:
                                    _dbg(f"_mouse_loop on_tap err={_e}")
                            pressed = False
                            rel_dx = 0
                            rel_dy = 0

                # on_scroll: viewport-granular Y dispatch (always fires if set)
                if accumulated != 0:
                    ticks = trunc_toward_zero(accumulated, MOUSE_SWIPE_THRESHOLD)
                    if ticks != 0:
                        _dbg(f"_mouse_loop on_scroll(rel_y) delta={ticks} accum={accumulated}")
                        try:
                            on_scroll(ticks)
                        except Exception as _e:
                            _dbg(f"_mouse_loop on_scroll err={_e}")
                        accumulated -= ticks * MOUSE_SWIPE_THRESHOLD

                if hi_res_accumulated != 0:
                    ticks = trunc_toward_zero(hi_res_accumulated, HI_RES_PER_TICK)
                    if ticks != 0:
                        _dbg(f"_mouse_loop on_scroll(wheel_hi) delta={ticks} accum={hi_res_accumulated}")
                        try:
                            on_scroll(ticks)
                        except Exception as _e:
                            _dbg(f"_mouse_loop on_scroll err={_e}")
                        hi_res_accumulated -= ticks * HI_RES_PER_TICK

                # on_delta: cell-granular X/Y dispatch (parallel; caller routes by mode)
                if on_delta is not None:
                    dx_ticks = trunc_toward_zero(cursor_acc_x, MOUSE_CURSOR_X_THRESHOLD)
                    dy_ticks = trunc_toward_zero(cursor_acc_y, MOUSE_CURSOR_Y_THRESHOLD)
                    if dx_ticks != 0 or dy_ticks != 0:
                        _dbg(f"_mouse_loop on_delta dx={dx_ticks} dy={dy_ticks}")
                        try:
                            on_delta(dx_ticks, dy_ticks)
                        except Exception as _e:
                            _dbg(f"_mouse_loop on_delta err={_e}")
                        cursor_acc_x -= dx_ticks * MOUSE_CURSOR_X_THRESHOLD
                        cursor_acc_y -= dy_ticks * MOUSE_CURSOR_Y_THRESHOLD
        except OSError as _e:
            _dbg(f"_mouse_loop read err dev={dev} err={_e}")
            pass  # device disconnected — fall through to close and retry
        finally:
            try:
                os.close(fd)
            except OSError:
                pass

        _time.sleep(1)  # brief pause before reconnect attempt


def _touch_loop(device_path, on_scroll, on_tap, on_tap_xy):
    """Read absolute-pointer mouse events: vertical drags scroll, taps jump to bottom.

    Input source is the cyberdeck-touch-mouse virtual device published by
    touch-to-mouse.service. It emits:
      EV_KEY / BTN_LEFT  (value 1 = press, 0 = release)
      EV_ABS / ABS_X     (absolute screen X, 0..639 on 3.5")
      EV_ABS / ABS_Y     (absolute screen Y, 0..479 on 3.5")
      EV_KEY / BTN_RIGHT (long-press; we ignore it here)

    Scroll is driven by Y-delta accumulated between successive ABS_Y events
    *while BTN_LEFT is held*. Because this is an absolute-pointer device,
    raw values are screen coords, not relative deltas -- we compute deltas
    ourselves from the previous sample.
    """
    try:
        fd = os.open(device_path, os.O_RDONLY)
    except OSError:
        return

    # Grab device exclusively so fbterm doesn't also see touch events via
    # /dev/input/mice (cyberdeck-touch-mouse is registered as mouse1, which
    # flows through the kernel mice multiplexer; fbterm reads that and draws
    # a framebuffer cursor, causing candy-pink erase artifacts on the TUI).
    EVIOCGRAB = 0x40044590
    import fcntl
    try:
        fcntl.ioctl(fd, EVIOCGRAB, 1)
    except OSError:
        pass  # device busy or not supported — continue without exclusive grab

    pressed = False
    press_time = 0
    cur_x = None
    cur_y = None
    start_x = None
    start_y = None
    last_y = None
    total_dx = 0
    total_dy = 0
    accumulated = 0  # Y pixels pending since last scroll tick (signed)

    buf_size = INPUT_EVENT_SIZE * 16
    try:
        while True:
            data = os.read(fd, buf_size)
            if data:
                _unblank()
            while len(data) >= INPUT_EVENT_SIZE:
                _sec, _usec, ev_type, code, value = struct.unpack(
                    INPUT_EVENT_FORMAT, data[:INPUT_EVENT_SIZE])
                data = data[INPUT_EVENT_SIZE:]

                if ev_type == EV_ABS:
                    if code == ABS_X:
                        cur_x = value
                    elif code == ABS_Y:
                        cur_y = value
                        if pressed and last_y is not None:
                            delta = value - last_y
                            total_dy += delta
                            accumulated += delta
                            ticks = trunc_toward_zero(accumulated, SWIPE_THRESHOLD)
                            if ticks != 0:
                                # Drag content with the finger:
                                # swipe down (positive delta) = older msgs.
                                # swipe up   (negative delta) = newer msgs.
                                on_scroll(ticks)
                                accumulated -= ticks * SWIPE_THRESHOLD
                        if pressed:
                            last_y = value
                elif ev_type == EV_KEY and code == BTN_LEFT:
                    if value == 1:  # press
                        pressed = True
                        press_time = _sec + _usec / 1e6
                        start_x = cur_x
                        start_y = cur_y
                        last_y = cur_y
                        total_dx = 0
                        total_dy = 0
                        accumulated = 0
                        _dbg(f"_touch_loop press x={cur_x} y={cur_y}")
                    elif value == 0:  # release
                        # Tap = small movement + held long enough.
                        dur_ms = (_sec + _usec / 1e6 - press_time) * 1000
                        moved = (abs((cur_x or 0) - (start_x or 0))
                                 + abs((cur_y or 0) - (start_y or 0)))
                        _dbg(f"_touch_loop release dur_ms={dur_ms:.0f} moved={moved} x={cur_x} y={cur_y}")
                        if (dur_ms >= TAP_MIN_MS
                                and start_x is not None and cur_x is not None
                                and start_y is not None and cur_y is not None
                                and abs(cur_x - start_x) + abs(cur_y - start_y)
                                    < TAP_THRESHOLD):
                            _dbg(f"_touch_loop on_tap_xy x={cur_x} y={cur_y}")
                            if on_tap_xy is not None:
                                on_tap_xy(cur_x, cur_y)
                            on_tap()
                        pressed = False
                        start_x = None
                        start_y = None
                        last_y = None
                        total_dx = 0
                        total_dy = 0
                        accumulated = 0
    except OSError:
        pass
    finally:
        os.close(fd)
