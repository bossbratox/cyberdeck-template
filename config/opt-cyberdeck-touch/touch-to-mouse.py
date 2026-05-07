#!/opt/cyberdeck-touch/venv/bin/python
"""
Translate Goodix touchscreen events into a virtual absolute-pointer mouse.

The Goodix panel emits BTN_TOUCH + ABS_MT_POSITION_X/Y (multitouch protocol B)
but never synthesizes BTN_LEFT. kmscon + tmux want standard mouse events with
BTN_LEFT for click-drag text selection.

This daemon opens /dev/input/event0, reads the MT events, and publishes a
second input device via uinput that reports BTN_LEFT + ABS_X/ABS_Y — matching
the screen geometry so touch position maps 1:1 to pointer position.

Single-touch only (ignore second/third fingers). Long-press (>700ms without
movement) emits BTN_RIGHT on release — lets us paste via tmux right-click
without a second hardware button.
"""

import sys
import time
from evdev import InputDevice, UInput, ecodes as e, list_devices, AbsInfo

TOUCH_NAME_PREFIX = "10-005d Goodix"   # match Waveshare DSI touch
LONG_PRESS_MS = 700


def find_touch_device():
    for path in list_devices():
        d = InputDevice(path)
        if d.name.startswith(TOUCH_NAME_PREFIX):
            return d
        d.close()
    raise SystemExit(f"no device matching '{TOUCH_NAME_PREFIX}' found")


def main():
    touch = find_touch_device()
    caps = touch.capabilities()
    abs_caps = dict(caps.get(e.EV_ABS, []))
    if e.ABS_MT_POSITION_X not in abs_caps or e.ABS_MT_POSITION_Y not in abs_caps:
        raise SystemExit("touch device has no ABS_MT_POSITION_X/Y")

    mt_x = abs_caps[e.ABS_MT_POSITION_X]
    mt_y = abs_caps[e.ABS_MT_POSITION_Y]

    ui_caps = {
        e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT],
        e.EV_ABS: [
            (e.ABS_X, AbsInfo(value=0, min=mt_x.min, max=mt_x.max,
                              fuzz=0, flat=0, resolution=mt_x.resolution or 0)),
            (e.ABS_Y, AbsInfo(value=0, min=mt_y.min, max=mt_y.max,
                              fuzz=0, flat=0, resolution=mt_y.resolution or 0)),
        ],
    }

    ui = UInput(ui_caps, name="cyberdeck-touch-mouse", version=1,
                input_props=[e.INPUT_PROP_POINTER])

    # Grab the touchscreen so kmscon doesn't double-process events.
    try:
        touch.grab()
    except OSError as exc:
        print(f"warn: could not grab touch device ({exc}); continuing", file=sys.stderr)

    print(f"translator live: {touch.path} ({touch.name}) -> uinput "
          f"(cyberdeck-touch-mouse); bounds x={mt_x.min}-{mt_x.max} "
          f"y={mt_y.min}-{mt_y.max}", file=sys.stderr, flush=True)

    # Per-touch state
    cur_x = 0
    cur_y = 0
    touch_down = False
    touch_start_ms = 0
    start_x = 0
    start_y = 0
    moved = False

    try:
        for ev in touch.read_loop():
            if ev.type == e.EV_ABS:
                if ev.code == e.ABS_MT_POSITION_X:
                    cur_x = ev.value
                elif ev.code == e.ABS_MT_POSITION_Y:
                    cur_y = ev.value
                # ignore ABS_MT_SLOT, TRACKING_ID, etc. (single-touch only)
            elif ev.type == e.EV_KEY and ev.code == e.BTN_TOUCH:
                if ev.value == 1:  # down
                    touch_down = True
                    touch_start_ms = ev.timestamp() * 1000
                    start_x, start_y = cur_x, cur_y
                    moved = False
                    ui.write(e.EV_ABS, e.ABS_X, cur_x)
                    ui.write(e.EV_ABS, e.ABS_Y, cur_y)
                    ui.write(e.EV_KEY, e.BTN_LEFT, 1)
                    ui.syn()
                else:  # up
                    if not touch_down:
                        continue
                    dur_ms = ev.timestamp() * 1000 - touch_start_ms
                    dist = abs(cur_x - start_x) + abs(cur_y - start_y)
                    long_press = dur_ms > LONG_PRESS_MS and dist < 20
                    ui.write(e.EV_KEY, e.BTN_LEFT, 0)
                    ui.syn()
                    if long_press:
                        # Quick right-click pulse for paste
                        ui.write(e.EV_KEY, e.BTN_RIGHT, 1)
                        ui.syn()
                        time.sleep(0.02)
                        ui.write(e.EV_KEY, e.BTN_RIGHT, 0)
                        ui.syn()
                    touch_down = False
            elif ev.type == e.EV_SYN and ev.code == e.SYN_REPORT:
                if touch_down:
                    ui.write(e.EV_ABS, e.ABS_X, cur_x)
                    ui.write(e.EV_ABS, e.ABS_Y, cur_y)
                    ui.syn()
                    if abs(cur_x - start_x) + abs(cur_y - start_y) > 20:
                        moved = True
    except KeyboardInterrupt:
        pass
    finally:
        try:
            touch.ungrab()
        except Exception:
            pass
        ui.close()
        touch.close()


if __name__ == "__main__":
    main()
