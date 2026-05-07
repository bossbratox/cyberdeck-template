#!/usr/bin/env python3
"""Cyberdeck Mermaid Pet — Framebuffer Edition (No PIL).

Uses /boot/firmware/bin/fb_blit (C compositor) for PNG rendering.
Uses pure-Python framebuffer primitives for UI, particles, and sprite overlays.

Controls:
    f      Feed food menu
    p      Play
    c      Clean
    s      Sleep / wake
    b      Cycle background
    o      Cycle outfit
    m      Debug mood
    r      Save game
    Tab    Speedrun toggle
    q      Quit
"""
import os
import sys
import time
import math
import json
import random
import select
import termios
import tty
import signal
import subprocess
import struct

# Shell daemon integration for app switching
sys.path.insert(0, "/opt/cyberdeck-shell")
sys.path.insert(0, "/opt/cyberdeck-shared")
try:
    from cyberdeck_switch import switch_to
except Exception:
    def switch_to(app_name):
        return False
import fcntl
try:
    from cyberdeck_touch import find_touch_device, find_mouse_device
except Exception:
    find_touch_device = None
    find_mouse_device = None

# ── Console cursor helpers ────────────────────────────────────────────

def _hide_console_cursor():
    """Hide the Linux console cursor by writing directly to the active tty."""
    try:
        with open("/dev/tty1", "w") as tty:
            tty.write("\033[?25l")
    except Exception:
        pass


def _clear_console():
    """Clear the Linux console screen and hide cursor."""
    try:
        with open("/dev/tty1", "w") as tty:
            tty.write("\033[2J\033[H\033[?25l")
    except Exception:
        pass


# KDSETMODE ioctl constants (from linux/kd.h)
_KDSETMODE = 0x4B3A
_KD_GRAPHICS = 1
_KD_TEXT = 0


def _set_console_graphics_mode(enable=True):
    """Set console to graphics mode so kernel text never draws over fb.

    Returns True if the ioctl succeeded.
    """
    mode = _KD_GRAPHICS if enable else _KD_TEXT
    for path in ("/dev/tty1", "/dev/console", "/dev/tty"):
        try:
            with open(path, "w") as tty:
                fcntl.ioctl(tty, _KDSETMODE, mode)
            return True
        except OSError:
            continue
    return False


# Debug helper for diagnosing input issues on the Pi
_PET_DEBUG_LOG = "/tmp/pet_input.log"

def _pet_dbg(msg):
    try:
        with open(_PET_DEBUG_LOG, "a") as f:
            f.write(f"[{time.time():.3f}] {msg}\n")
    except Exception:
        pass


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pet_fb_draw import (Framebuffer, rgb565,
    C_BLACK, C_WHITE, C_RED, C_BLUE, C_PINK, C_ORANGE, C_DARK, C_GRAY,
    C_THEME_PINK, C_THEME_BLUE, C_THEME_PURPLE, C_THEME_MINT, C_THEME_YELLOW,
    C_THEME_PEACH, C_THEME_CYAN, C_THEME_CHART)
from pet_fb_blitter import load_raw, blit_to_fb
from pet_fb_progression import ProgressionManager
from pet_fb_friends import FriendManager, Friend

# ── Paths ─────────────────────────────────────────────────────────────

def _save_path():
    # /boot/firmware/persistent is root-owned and not writable by the pet user.
    # Use the user's home directory for a reliable writable location.
    home = os.path.expanduser("~")
    return os.path.join(home, ".pet-save.json")

SAVE_PATH = os.environ.get("PET_SAVE_PATH", _save_path())

_ASSET_CANDIDATES = [
    "/boot/firmware/persistent/cyberdeck-pet/fb_assets",
    "/opt/cyberdeck-pet/fb_assets",
]
ASSET_DIR = next((p for p in _ASSET_CANDIDATES if os.path.isdir(p)), _ASSET_CANDIDATES[-1])
os.environ["PET_ASSET_DIR"] = ASSET_DIR

FBBLIT = "/boot/firmware/bin/fb_blit"

# ── Pet State ─────────────────────────────────────────────────────────

class PetState:
    STAGES = ["egg", "baby", "kid", "adult"]

    def __init__(self, **kwargs):
        self.name = kwargs.get("name", "Mermaid")
        self.hunger = kwargs.get("hunger", 50.0)
        self.happiness = kwargs.get("happiness", 70.0)
        self.energy = kwargs.get("energy", 80.0)
        self.cleanliness = kwargs.get("cleanliness", 80.0)
        self.health = kwargs.get("health", 100.0)
        self.age_days = kwargs.get("age_days", 0.0)
        self.sleeping = kwargs.get("sleeping", False)
        self.dirty = kwargs.get("dirty", False)
        self.outfit_idx = kwargs.get("outfit_idx", 0)
        self.bg_idx = kwargs.get("bg_idx", 0)
        self.unlocked_bgs = kwargs.get("unlocked_bgs", ["coral"])
        self.unlocked_outfits = kwargs.get("unlocked_outfits", ["blue"])
        self.unlocked_friends = kwargs.get("unlocked_friends", [])
        # Progression tracking
        self.visit_counts = kwargs.get("visit_counts", {})
        self.total_feeds = kwargs.get("total_feeds", 0)
        self.max_happiness = kwargs.get("max_happiness", 70.0)
        self.unlocked_milestones = set(kwargs.get("unlocked_milestones", []))
        # Clean state tracking
        self._clean_taps = kwargs.get("_clean_taps", 0)
        self._clean_timer = kwargs.get("_clean_timer", 0.0)
        # Sleep tracking
        self._sleep_timer = kwargs.get("_sleep_timer", 0.0)
        # Hunger escalation timer (hungry too long → pissed)
        self._hunger_timer = kwargs.get("_hunger_timer", 0.0)
        # Lifecycle stage
        self.stage = kwargs.get("stage", "egg")
        self.stage_timer = kwargs.get("stage_timer", 0.0)
        self.stage_feeds = kwargs.get("stage_feeds", 0)
        self.egg_taps = kwargs.get("egg_taps", 0)
        self.egg_phase = kwargs.get("egg_phase", 0)  # 0=normal, 1=cracked, 2=hatching
        self.full_timer = kwargs.get("full_timer", 0.0)  # baby post-feed full state

    def to_dict(self):
        d = self.__dict__.copy()
        d["unlocked_milestones"] = list(d["unlocked_milestones"])
        return d

    @classmethod
    def from_dict(cls, d):
        known = {"name", "hunger", "happiness", "energy", "cleanliness",
                 "health", "age_days", "sleeping", "dirty", "outfit_idx",
                 "bg_idx", "unlocked_bgs", "unlocked_outfits", "unlocked_friends",
                 "visit_counts", "total_feeds", "max_happiness", "unlocked_milestones",
                 "_clean_taps", "_clean_timer", "_sleep_timer", "_hunger_timer",
                 "stage", "stage_timer", "stage_feeds", "egg_taps",
                 "egg_phase", "full_timer"}
        kwargs = {k: v for k, v in d.items() if k in known}
        if "unlocked_milestones" in kwargs:
            kwargs["unlocked_milestones"] = set(kwargs["unlocked_milestones"])
        return cls(**kwargs)

    def mood(self):
        if self.sleeping:
            return "sleep"
        if self.stage == "egg":
            return "neutral"
        # Tired at night/evening when low energy
        if self.stage != "egg" and not self.sleeping:
            period = get_time_period()
            if period in ("evening", "night") and self.energy < 70:
                return "tired"
        if self.health < 30:
            return "sick"
        if self.dirty:
            return "dirty"
        # Hungry too long → pissed (cranky)
        if getattr(self, '_hunger_timer', 0) > 60:
            return "cranky"
        if self.hunger > 75:
            return "hungry"
        if self.happiness > 85 and self.energy > 50:
            return "love"
        if self.happiness > 70:
            return "excited"
        if self.happiness > 50:
            return "happy"
        if self.happiness < 25 and self.energy < 30:
            return "cranky"
        if self.happiness < 30:
            return "sad"
        return "neutral"

    def decay(self, dt):
        if self.stage == "egg":
            return  # egg doesn't decay

        # Manage baby full state timer
        if self.full_timer > 0:
            self.full_timer = max(0, self.full_timer - dt)

        if self.sleeping:
            # Sleep: recover energy and health (rate varies by stage)
            # Sick mermaids recover faster with sleep
            sick_boost = 1.5 if self.health < 30 else 1.0
            if self.stage == "baby":
                self.energy = min(100, self.energy + 0.08 * dt)
                self.health = min(100, self.health + 0.5 * dt * sick_boost)
                self.hunger = min(100, self.hunger + 0.12 * dt)
                self.happiness = max(0, self.happiness - 0.01 * dt)
            elif self.stage == "kid":
                self.energy = min(100, self.energy + 0.05 * dt)
                self.health = min(100, self.health + 0.4 * dt * sick_boost)
                self.hunger = min(100, self.hunger + 0.08 * dt)
                self.happiness = max(0, self.happiness - 0.01 * dt)
            else:  # adult
                self.energy = min(100, self.energy + 0.03 * dt)
                self.health = min(100, self.health + 0.3 * dt * sick_boost)
                self.hunger = min(100, self.hunger + 0.06 * dt)
                self.happiness = max(0, self.happiness - 0.01 * dt)
        else:
            # Awake decay varies by stage — slowed down ~6-8x for better pacing
            if self.stage == "baby":
                # Full baby: 1/4 hunger decay
                hunger_rate = 0.25 if self.full_timer > 0 else 1.0
                self.hunger = min(100, self.hunger + 0.12 * hunger_rate * dt)
                self.happiness = max(0, self.happiness - 0.04 * dt)
                self.energy = max(0, self.energy - 0.05 * dt)
            elif self.stage == "kid":
                self.hunger = min(100, self.hunger + 0.08 * dt)
                self.happiness = max(0, self.happiness - 0.03 * dt)
                self.energy = max(0, self.energy - 0.04 * dt)
            else:  # adult
                self.hunger = min(100, self.hunger + 0.04 * dt)
                self.happiness = max(0, self.happiness - 0.015 * dt)
                self.energy = max(0, self.energy - 0.02 * dt)
            # Only decay cleanliness if not in forced clean state
            if getattr(self, '_clean_timer', 0) <= 0:
                rate = 0.02 if self.stage == "baby" else 0.015 if self.stage == "kid" else 0.01
                self.cleanliness = max(0, self.cleanliness - rate * dt)
        if self.hunger > 80:
            self.health = max(0, self.health - 0.008 * dt)
        if self.cleanliness < 20:
            self.health = max(0, self.health - 0.006 * dt)
        if self.happiness < 20:
            self.health = max(0, self.health - 0.006 * dt)
        # Hunger escalation timer
        if not self.sleeping and self.hunger > 75:
            self._hunger_timer = getattr(self, '_hunger_timer', 0) + dt
        else:
            self._hunger_timer = 0
        # Manage forced-clean timer
        ct = getattr(self, '_clean_timer', 0)
        if ct > 0:
            self._clean_timer = max(0, ct - dt)
            self.cleanliness = 100
        self.dirty = self.cleanliness < 40 and self._clean_timer <= 0

    def feed(self, food_value=25):
        self.hunger = max(0, self.hunger - food_value)
        self.happiness = min(100, self.happiness + 5)
        self.energy = min(100, self.energy + 10)
        self.health = min(100, self.health + 8)  # food restores health
        self.total_feeds += 1
        self.stage_feeds += 1
        self._hunger_timer = 0  # reset hunger escalation
        if self.stage == "baby":
            self.full_timer = 300.0  # 5 minutes full

    def play(self):
        if self.sleeping or self.stage in ("egg", "baby"):
            return
        # Sad mermaids need treats/friends, not just play
        happy_gain = 5 if self.mood() == "sad" else 15
        self.happiness = min(100, self.happiness + happy_gain)
        self.energy = min(100, self.energy + 2)
        self.hunger = min(100, self.hunger + 1)

    def clean(self):
        self.happiness = min(100, self.happiness + 5)
        self.energy = min(100, self.energy + 5)
        self.cleanliness = 100
        self._clean_timer = 300.0  # 5 minutes sparkling clean
        self.dirty = False

    def toggle_sleep(self, speedrun=False):
        if not self.sleeping:
            self.sleeping = True
            self._sleep_timer = time.time()
        else:
            # Only allow wake after minimum 2 minutes (or 2 seconds in speedrun)
            elapsed = time.time() - getattr(self, '_sleep_timer', 0)
            min_sleep = 2 if speedrun else 120
            if elapsed >= min_sleep:
                self.sleeping = False
                self._sleep_timer = 0.0
            # else: ignore wake attempt, still sleeping


# ── Save / Load ───────────────────────────────────────────────────────

def load_game():
    if os.path.exists(SAVE_PATH):
        try:
            with open(SAVE_PATH) as f:
                return PetState.from_dict(json.load(f))
        except Exception:
            pass
    return PetState()

def save_game(state):
    try:
        # Atomic write: temp file then rename to prevent corruption
        tmp = SAVE_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state.to_dict(), f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, SAVE_PATH)
    except Exception as e:
        print(f"Save failed: {e}")


# ── Assets ────────────────────────────────────────────────────────────

BGS = ["coral", "beach", "night", "castle", "atlantis", "lagoon", "reef", "sunset", "space"]
OUTFITS = ["blue", "galaxy", "green", "rainbow"]
FOODS = ["burger", "cupcake", "ice_cream", "matcha", "oyster", "strawberry", "sushi"]

# Treats: (name, happiness_bonus, energy_bonus)
TREATS = [
    ("comb",      5,  3),
    ("crystal",   10, 5),
    ("fork",      3,  2),
    ("necklace",  8,  4),
    ("oyster",    15, 10),
    ("treasure",  12, 8),
]

# Time-appropriate background pools
BG_POOLS = {
    "day":     ["beach", "coral", "reef"],
    "evening": ["lagoon", "sunset", "castle"],
    "night":   ["atlantis", "night"],
}

def get_time_period():
    """Return current time period: 'day', 'evening', or 'night'."""
    hour = time.localtime().tm_hour
    if 6 <= hour < 18:
        return "day"
    elif 18 <= hour < 21:
        return "evening"
    else:
        return "night"

def get_time_bg_indices():
    """Return list of BGS indices appropriate for current time of day."""
    period = get_time_period()
    return [BGS.index(name) for name in BG_POOLS.get(period, []) if name in BGS]

def get_next_time_bg(current_idx):
    """Get the next background index in the time-appropriate pool."""
    pool = get_time_bg_indices()
    if not pool:
        return current_idx
    if current_idx in pool:
        i = pool.index(current_idx)
        return pool[(i + 1) % len(pool)]
    return pool[0]


def get_time_appropriate_bg():
    """Return the first unlocked background appropriate for current time of day."""
    pool = get_time_bg_indices()
    # Try time-appropriate pool first
    for idx in pool:
        if BGS[idx] in GameState().unlocked_bgs:
            return idx
    # Fallback to first unlocked
    for i, name in enumerate(BGS):
        if name in GameState().unlocked_bgs:
            return i
    return 0


def buoy_bob(t):
    """Gentle single half-sine bob — like a buoy in water. t in [0,1]."""
    if t <= 0 or t >= 1:
        return 0.0
    # One smooth arc: 0 → 1 → 0, peaking at t=0.5
    return math.sin(t * math.pi)

# Mood -> expression sprite name (None = use outfit)
MOOD_TO_EXPRESSION = {
    "sleep": "sleep",
    "sick": "sick",
    "dirty": "dirty",
    "hungry": "hungry",
    "tired": "tired",
    "excited": "excited",
    "happy": "happy",
    "cranky": "pissed",
    "sad": "sad",
    "neutral": None,
}

SPRITE_W, SPRITE_H = 240, 336
MERMAID_X_OFFSET = 10  # sprite art is slightly left-heavy; nudge right

def get_bg_path(idx):
    name = BGS[idx % len(BGS)]
    return os.path.join(ASSET_DIR, f"bg_{name}.png")

def get_expression_path(name, blink=False):
    suffix = "_blink" if blink else ""
    path = os.path.join(ASSET_DIR, f"mermaid_{name}{suffix}.png")
    if os.path.exists(path):
        return path
    if blink:
        return os.path.join(ASSET_DIR, f"mermaid_{name}.png")
    return None

def get_outfit_path(name, blink=False):
    suffix = "_blink" if blink else ""
    path = os.path.join(ASSET_DIR, f"outfit_{name}{suffix}.png")
    if os.path.exists(path):
        return path
    if blink:
        return os.path.join(ASSET_DIR, f"outfit_{name}.png")
    return None

def get_lifecycle_path(stage, variant="", blink=False):
    """Get sprite path for egg/baby/kid lifecycle stages.
    variant: '' (default), 'crack', 'hatch', 'happy', 'cry', 'excite', etc.
    Falls back to non-blink if blink variant doesn't exist.
    """
    suffix = "_blink" if blink else ""
    if variant:
        name = f"mermaid_{stage}_{variant}{suffix}"
    else:
        name = f"mermaid_{stage}{suffix}"
    path = os.path.join(ASSET_DIR, f"{name}.png")
    if os.path.exists(path):
        return path
    if blink:
        return get_lifecycle_path(stage, variant, blink=False)
    return None


# ── Animation Stack ───────────────────────────────────────────────────

class Animation:
    def __init__(self, anim_type, duration, data=None):
        self.type = anim_type
        self.duration = duration
        self.data = data or {}
        self.timer = 0.0
        self.phase = 0
        self.done = False

    def update(self, dt):
        self.timer += dt
        if self.timer >= self.duration:
            self.done = True


class AnimationStack:
    """Priority-ordered animation manager. Highest priority wins."""

    PRIORITY = {
        "unlock_notify": 9,
        "tap_reaction":  8,
        "clean_reaction":7,
        "outfit_change": 6,
        "friend_enter":  5,
        "feed":          4,
        "play":          3,
        "clean":         3,
        "sleep":         3,
        "bg_transition": 2,
    }

    def __init__(self):
        self.anims = []

    def push(self, anim_type, duration, data=None):
        # Don't duplicate tap reactions
        if anim_type == "tap_reaction" and self.is_active("tap_reaction"):
            return None
        anim = Animation(anim_type, duration, data)
        self.anims.append(anim)
        # Sort by priority (highest first)
        self.anims.sort(key=lambda a: self.PRIORITY.get(a.type, 0), reverse=True)
        return anim

    def update(self, dt):
        for anim in self.anims:
            anim.update(dt)
        completed = [a for a in self.anims if a.done]
        self.anims = [a for a in self.anims if not a.done]
        return completed

    def is_active(self, anim_type):
        return any(a.type == anim_type for a in self.anims)

    def get_override(self):
        """Return expression override name from highest-priority animation."""
        for anim in self.anims:
            if anim.type == "tap_reaction":
                return anim.data.get("expression", "wink")
            if anim.type == "clean_reaction":
                return "clean"
            if anim.type == "outfit_change":
                return None  # keep current expression, sparkles handle it
            if anim.type == "feed" and anim.phase >= 1:
                return None
        return None


# ── Input ─────────────────────────────────────────────────────────────

class NonBlockingInput:
    """Read keyboard events directly from /dev/input/event* (evdev).

    The pet runs as a systemd user service that is not the session leader on
    tty1, so the kernel TTY layer does not deliver keypresses to its stdin
    even when /dev/tty1 is opened directly. Reading evdev bypasses TTY
    entirely and works for any process whose user is in the `input` group.
    """

    EV_KEY = 1
    EVIOCGRAB = 0x40044590
    _EV_FORMAT = "llHHi"
    _EV_SIZE = struct.calcsize("llHHi")

    # Linux KEY_* codes → string format expected by handle_input().
    KEYMAP = {
        59: "F1", 60: "F2", 61: "F3", 62: "F4",
        63: "F5", 64: "F6", 65: "F7",
        1:  "\x1b",   # ESC
        15: "\t",     # TAB
        11: "0",
        16: "q",
        18: "e",
        19: "r",
        20: "t",
        24: "o",
        25: "p",
        31: "s",
        33: "f",
        46: "c",
        48: "b",
    }

    def __init__(self):
        self._fd = None
        self._active = False
        self._grabbed = False
        self._dev_path = None
        self._queue = []
        self._reconnect_at = 0.0  # earliest time to retry after a failure

    def _find_keyboard_device(self):
        """Locate the BBQ10 keyboard via /proc/bus/input/devices.

        Only returns devices whose name contains "keyboard"/"q10"/"bbq" —
        a "kbd" handler alone is not enough, because the kernel exposes
        an HDMI-CEC hotkey device (vc4-hdmi) with a kbd handler too, and
        that's never what we want. While the BBQ10 is reconnecting we
        return None and let the caller back off and retry.
        """
        try:
            with open("/proc/bus/input/devices") as f:
                content = f.read()
        except OSError:
            return None

        for block in content.split("\n\n"):
            ev_val = 0
            event_path = None
            has_mouse_handler = False
            name_lower = ""
            for line in block.split("\n"):
                if line.startswith("N: Name="):
                    name_lower = line.lower()
                elif line.startswith("H: Handlers="):
                    if "mouse" in line.lower():
                        has_mouse_handler = True
                    for part in line.split():
                        if part.startswith("event"):
                            event_path = f"/dev/input/{part}"
                elif line.startswith("B: EV="):
                    try:
                        ev_val = int(line.split("=")[1], 16)
                    except ValueError:
                        pass
            if not event_path or not (ev_val & (1 << self.EV_KEY)):
                continue
            if has_mouse_handler:
                continue  # skip the trackpad — handled by TrackpadHandler
            if not os.access(event_path, os.R_OK):
                continue
            if any(k in name_lower for k in ("keyboard", "q10", "bbq")):
                return event_path
        return None

    def _open_kbd(self):
        """Open + grab the keyboard evdev. Returns True on success.

        Called from start() and from getch() after a disconnect — the BBQ10
        is a Bluetooth HID device and re-registers at a new evdev node
        whenever the BT link drops, so we re-resolve via /proc on reconnect.
        """
        dev = self._find_keyboard_device()
        if dev is None:
            return False
        try:
            fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as e:
            _pet_dbg(f"_open_kbd: open {dev} failed: {e}")
            return False
        grabbed = False
        try:
            fcntl.ioctl(fd, self.EVIOCGRAB, 1)
            grabbed = True
        except OSError as e:
            _pet_dbg(f"_open_kbd: EVIOCGRAB failed on {dev}: {e}")
        self._fd = fd
        self._dev_path = dev
        self._grabbed = grabbed
        return True

    def _close_kbd(self):
        """Close the current fd. Safe to call when fd is None."""
        if self._fd is None:
            return
        if self._grabbed:
            try:
                fcntl.ioctl(self._fd, self.EVIOCGRAB, 0)
            except OSError:
                pass
        try:
            os.close(self._fd)
        except OSError:
            pass
        self._fd = None
        self._grabbed = False
        self._dev_path = None

    def start(self):
        if self._active:
            return
        if not self._open_kbd():
            _pet_dbg("start: no keyboard evdev found")
            return
        self._active = True
        _pet_dbg(f"start: kbd evdev={self._dev_path} fd={self._fd} grabbed={self._grabbed}")

    def ensure_raw(self):
        # No-op — evdev is independent of TTY mode.
        return

    def stop(self):
        if not self._active:
            return
        prev_path = self._dev_path
        self._close_kbd()
        self._active = False
        self._queue.clear()
        _pet_dbg(f"stop: kbd evdev={prev_path} released")

    def getch(self, timeout=0.016):
        if not self._active:
            return None
        if self._queue:
            return self._queue.pop(0)
        # If we're between connections, wait the back-off then try to reopen.
        if self._fd is None:
            now = time.time()
            if now < self._reconnect_at:
                return None
            if not self._open_kbd():
                self._reconnect_at = now + 1.0
                return None
            _pet_dbg(f"getch: reconnected to {self._dev_path}")
        if not select.select([self._fd], [], [], timeout)[0]:
            return None
        try:
            while True:
                try:
                    data = os.read(self._fd, self._EV_SIZE)
                except BlockingIOError:
                    break
                if len(data) < self._EV_SIZE:
                    break
                _, _, type_, code, value = struct.unpack(self._EV_FORMAT, data)
                # value: 0=release, 1=press, 2=autorepeat. Treat press and
                # autorepeat as keypresses; ignore release.
                if type_ != self.EV_KEY or value not in (1, 2):
                    continue
                key = self.KEYMAP.get(code)
                if key is not None:
                    _pet_dbg(f"getch: code={code} value={value} -> {key!r}")
                    self._queue.append(key)
        except OSError as e:
            # ENODEV (Errno 19) and friends fire when the BT keyboard drops:
            # close the dead fd and let the next call re-resolve via _open_kbd.
            _pet_dbg(f"getch: read err {e}; closing fd, will reconnect")
            self._close_kbd()
            self._reconnect_at = time.time() + 1.0
            return None
        if self._queue:
            return self._queue.pop(0)
        return None


# ── Touch Input ───────────────────────────────────────────────────────

class TouchHandler:
    """Read from virtual mouse (cyberdeck-touch-mouse)."""
    EV_ABS = 3
    EV_KEY = 1
    EV_SYN = 0
    ABS_X = 0
    ABS_Y = 1
    BTN_LEFT = 272
    SYN_REPORT = 0

    def __init__(self, device=None):
        if device is None:
            device = find_touch_device() if find_touch_device else None
        if device is None:
            device = "/dev/input/event3"  # legacy fallback
        self.device = device
        self.fd = None
        self.x = 0
        self.y = 0
        self.down = False
        self.start_x = 0
        self.start_y = 0
        self.start_t = 0
        self.swipe = None
        self.tap = None
        try:
            self.fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
            # Try to grab exclusively — ok to fail if terminal is already dead
            try:
                EVIOCGRAB = 0x40044590
                fcntl.ioctl(self.fd, EVIOCGRAB, 1)
            except OSError:
                pass  # device busy, but we can still read it
        except Exception as e:
            print(f"Touch init failed: {e}")

    def close(self):
        """Release exclusive grab and close device."""
        if self.fd is not None:
            try:
                EVIOCGRAB = 0x40044590
                fcntl.ioctl(self.fd, EVIOCGRAB, 0)
                os.close(self.fd)
            except Exception:
                pass
            self.fd = None

    def poll(self):
        if self.fd is None:
            return
        self.swipe = None
        self.tap = None
        EV_SIZE = struct.calcsize("llHHi")
        while True:
            try:
                data = os.read(self.fd, EV_SIZE)
                if len(data) < EV_SIZE:
                    break
                _, _, type_, code, value = struct.unpack("llHHi", data)
                if type_ == self.EV_ABS:
                    if code == self.ABS_X:
                        self.x = value
                    elif code == self.ABS_Y:
                        self.y = value
                elif type_ == self.EV_KEY:
                    if code == self.BTN_LEFT:
                        if value == 1:
                            self.down = True
                            self.start_x = self.x
                            self.start_y = self.y
                            self.start_t = time.time()
                        elif value == 0:
                            if self.down:
                                dx = self.x - self.start_x
                                dy = self.y - self.start_y
                                dt = time.time() - self.start_t
                                if abs(dx) > 50 and abs(dx) > abs(dy):
                                    self.swipe = "left" if dx < 0 else "right"
                                elif abs(dy) > 50 and abs(dy) > abs(dx):
                                    self.swipe = "up" if dy < 0 else "down"
                                elif dt < 0.5:
                                    self.tap = (self.x, self.y)
                            self.down = False
            except BlockingIOError:
                break
            except Exception:
                break

    def get_tap(self):
        t = self.tap
        self.tap = None
        return t

    def get_swipe(self):
        s = self.swipe
        self.swipe = None
        return s


class TrackpadHandler:
    """Read BB Q10 optical trackpad (EV_REL) with exclusive EVIOCGRAB.

    Exclusive grab prevents the kernel from drawing a framebuffer cursor that
    would leave black pixel trails over the pet's rendering.
    """
    EV_REL = 2
    EV_KEY = 1
    REL_X = 0x00
    REL_Y = 0x01
    BTN_LEFT = 0x110
    SCROLL_THRESHOLD = 3  # accumulated REL_Y per scroll tick

    def __init__(self):
        self.fd = None
        self._accum = 0
        self._pressed = False
        self._press_time = 0.0
        self._rel_dx = 0
        self._rel_dy = 0
        self.scroll = 0   # net ticks this poll: +1 = down, -1 = up
        self.click = False
        # BBQ10 is a Bluetooth HID device; the trackpad evdev node disappears
        # and re-registers whenever the BT link drops. Track a back-off so
        # we retry the open without spinning every poll.
        self._reconnect_at = 0.0
        self._open()

    def _open(self):
        """Open + grab the trackpad evdev. No-op if already open or no
        device is currently published."""
        if self.fd is not None:
            return
        dev = find_mouse_device() if find_mouse_device else None
        if not dev:
            _pet_dbg("trackpad _open: no device found")
            return
        try:
            self.fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
            EVIOCGRAB = 0x40044590
            fcntl.ioctl(self.fd, EVIOCGRAB, 1)
            _pet_dbg(f"trackpad _open: dev={dev} fd={self.fd} grabbed=True")
        except Exception as e:
            _pet_dbg(f"trackpad _open: dev={dev} err={e}")
            if self.fd is not None:
                try:
                    os.close(self.fd)
                except Exception:
                    pass
                self.fd = None

    def _drop(self):
        """Close the current fd after a read failure; let _open retry later."""
        if self.fd is None:
            return
        try:
            EVIOCGRAB = 0x40044590
            fcntl.ioctl(self.fd, EVIOCGRAB, 0)
        except Exception:
            pass
        try:
            os.close(self.fd)
        except Exception:
            pass
        self.fd = None
        self._reconnect_at = time.time() + 1.0

    def close(self):
        self._drop()

    def poll(self):
        self.scroll = 0
        self.click = False
        if self.fd is None:
            if time.time() >= self._reconnect_at:
                self._open()
            if self.fd is None:
                return
        EV_SIZE = struct.calcsize("llHHi")
        while True:
            try:
                data = os.read(self.fd, EV_SIZE)
            except BlockingIOError:
                break
            except Exception:
                # Likely ENODEV from a BT keyboard/mouse disconnect — drop
                # the fd; the next poll will try to re-resolve via /proc.
                self._drop()
                return
            if len(data) < EV_SIZE:
                break
            _, _, type_, code, value = struct.unpack("llHHi", data)
            if type_ == self.EV_REL:
                if code == self.REL_Y:
                    self._accum += value
                    self._rel_dy += value
                elif code == self.REL_X:
                    self._rel_dx += value
            elif type_ == self.EV_KEY and code == self.BTN_LEFT:
                if value == 1:
                    self._pressed = True
                    self._press_time = time.time()
                    self._rel_dx = 0
                    self._rel_dy = 0
                elif value == 0 and self._pressed:
                    dt = time.time() - self._press_time
                    moved = abs(self._rel_dx) + abs(self._rel_dy)
                    if dt < 0.5 and moved < 15:
                        self.click = True
                    self._pressed = False
                    self._rel_dx = 0
                    self._rel_dy = 0
        ticks = int(self._accum / self.SCROLL_THRESHOLD)
        if ticks != 0:
            self.scroll = ticks
            self._accum -= ticks * self.SCROLL_THRESHOLD


# ── Particles (pure Python) ───────────────────────────────────────────

class BubbleParticle:
    def __init__(self, sw, sh):
        self.x = random.randint(0, sw)
        self.y = sh + random.randint(10, 50)
        self.r = random.randint(2, 5)
        self.speed = random.uniform(0.5, 2.0)
        self.wobble_phase = random.uniform(0, math.pi * 2)
        self.wobble_freq = random.uniform(1.5, 3.0)
        self.pop_y = random.randint(-20, sh // 3)

    def update(self, dt):
        self.y -= self.speed
        self.x += math.sin(time.time() * self.wobble_freq + self.wobble_phase) * 0.3

    def alive(self):
        return self.y > self.pop_y

    def draw(self, fb):
        fb.ring(int(self.x), int(self.y), self.r, rgb565(200, 230, 255), 1)

HEART_SPRITES = [
    "particle_heart_pink_32",
    "particle_heart_pink_48",
    "particle_heart_pink_64",
]

class HeartParticle:
    def __init__(self, x, y):
        # Wide spread so hearts don't overlap into a pink blob
        self.x = x + random.randint(-140, 140)
        self.y = y + random.randint(-60, 40)
        self.speed = random.uniform(15, 30)
        self.age = 0.0
        self.life = random.uniform(1.0, 2.0)
        self.sprite = random.choice(HEART_SPRITES)

    def update(self, dt):
        self.age += dt
        self.y -= self.speed * dt
        self.x += math.sin(self.age * 3) * 0.3

    def alive(self):
        return self.age < self.life

    def draw(self, fb, sprite_raw):
        if sprite_raw is None:
            return
        w, h, _, _ = sprite_raw
        blit_to_fb(fb, sprite_raw, int(self.x - w // 2), int(self.y - h // 2))

class SparkleParticle:
    def __init__(self, sw, sh):
        self.x = random.randint(0, sw)
        self.y = random.randint(0, sh)
        self.size = random.randint(1, 5)
        self.phase = random.uniform(0, math.pi * 2)
        self.freq = random.uniform(2.0, 5.0)
        self.life = random.uniform(0.8, 2.0)
        self.age = 0.0

    def update(self, dt):
        self.age += dt
        self.y -= dt * 12

    def alive(self):
        return self.age < self.life

    def draw(self, fb):
        t = self.age / self.life
        a = int(255 * (1.0 - t))
        if a < 20:
            return
        # Gold sparkle with slight hue wobble
        gold_shift = int(30 * math.sin(self.age * self.freq + self.phase))
        color = rgb565(255, 215 + gold_shift, 50)
        s = self.size
        x, y = int(self.x), int(self.y)
        # Four-point star / sparkle shape
        fb.pixel(x, y, color)
        if s >= 2:
            fb.pixel(x, y - s, color)
            fb.pixel(x, y + s, color)
            fb.pixel(x - s, y, color)
            fb.pixel(x + s, y, color)
        if s >= 4:
            fb.pixel(x - s//2, y - s//2, color)
            fb.pixel(x + s//2, y - s//2, color)
            fb.pixel(x - s//2, y + s//2, color)
            fb.pixel(x + s//2, y + s//2, color)

class ZzzParticle:
    def __init__(self, x, y):
        self.x = x + random.randint(-10, 10)
        self.y = y
        self.speed = random.uniform(8, 15)
        self.age = 0.0
        self.life = random.uniform(1.5, 2.5)

    def update(self, dt):
        self.age += dt
        self.y -= self.speed * dt
        self.x += math.sin(self.age * 2) * 0.5

    def alive(self):
        return self.age < self.life

    def draw(self, fb):
        t = self.age / self.life
        a = int(255 * (1.0 - t))
        if a < 20:
            return
        color = rgb565(200, 200, 255)
        fb.text("Z", int(self.x), int(self.y), color, scale=1)

class CleanSparkle:
    """Sparkle that washes down during clean animation."""
    def __init__(self, x, y):
        self.x = x + random.randint(-5, 5)
        self.y = y
        self.speed = random.uniform(30, 60)
        self.size = random.randint(1, 3)
        self.age = 0.0
        self.life = random.uniform(0.3, 0.7)
        self.color = random.choice([
            rgb565(255, 255, 200),
            rgb565(200, 255, 255),
            rgb565(255, 255, 255),
        ])

    def update(self, dt):
        self.age += dt
        self.y += self.speed * dt

    def alive(self):
        return self.age < self.life

    def draw(self, fb):
        t = self.age / self.life
        if t > 0.8:
            return
        s = self.size
        fb.pixel(int(self.x), int(self.y), self.color)
        if s > 1:
            fb.pixel(int(self.x)-1, int(self.y), self.color)
            fb.pixel(int(self.x)+1, int(self.y), self.color)
            fb.pixel(int(self.x), int(self.y)-1, self.color)
            fb.pixel(int(self.x), int(self.y)+1, self.color)

class CleanBubble:
    """Bubble that rises up from the mermaid during clean cascade."""
    def __init__(self, x, y):
        self.x = x + random.randint(-50, 50)
        self.y = y + random.randint(-40, 40)
        self.r = random.randint(3, 6)
        self.speed = random.uniform(1.5, 4.0)
        self.wobble_phase = random.uniform(0, math.pi * 2)
        self.wobble_freq = random.uniform(1.5, 3.0)
        self.pop_y = y - random.randint(120, 250)

    def update(self, dt):
        self.y -= self.speed
        self.x += math.sin(time.time() * self.wobble_freq + self.wobble_phase) * 0.4

    def alive(self):
        return self.y > self.pop_y

    def draw(self, fb):
        fb.circle(int(self.x), int(self.y), self.r, rgb565(220, 245, 255))

class StinkParticle:
    def __init__(self, x, y):
        self.x = x + random.randint(-10, 10)
        self.y = y
        self.speed = random.uniform(5, 12)
        self.age = 0.0
        self.life = random.uniform(0.8, 1.5)

    def update(self, dt):
        self.age += dt
        self.y -= self.speed * dt

    def alive(self):
        return self.age < self.life

    def draw(self, fb):
        t = self.age / self.life
        if t > 0.9:
            return
        color = rgb565(100, 200, 80)
        x, y = int(self.x), int(self.y)
        for i in range(3):
            px = x + int(math.sin((y + i * 5) * 0.2) * 4)
            fb.pixel(px, y + i * 6, color)
            fb.pixel(px + 1, y + i * 6, color)


# ── Main App ──────────────────────────────────────────────────────────

class PetApp:
    def __init__(self):
        self.state = load_game()
        self.fb = Framebuffer()
        self.input = NonBlockingInput()
        self.running = True
        self.last_t = time.time()
        self.frame = 0
        self.message = ""
        self.message_timer = 0.0
        self.food_on_screen = None  # {"name": str, "x": int, "y": int, "state": "idle"|"dragging", "timer": float}
        self.float_phase = random.uniform(0, math.pi * 2)
        self.particles = []
        self.bubble_timer = 0.0
        self.sparkle_timer = 0.0
        self.mermaid_x = 320  # center of screen
        self.mermaid_y = 270  # center of mermaid sprite
        # Wander / float
        self.wander_phase = random.uniform(0, math.pi * 2)
        self.wander_x = 0.0
        # Blink animation
        self.blink_timer = 0.0
        self.blink_next = random.uniform(1.5, 4.0)
        self.blinking = False

        # Touch
        self.touch = TouchHandler()
        self._touch_was_down = False
        self.trackpad = TrackpadHandler()
        self.selected_action = 0  # 0=CLEAN 1=FEED 2=SLEEP 3=INFO

        # Page: 0 = pet view, 1 = stats view
        self.page = 0
        # New systems
        self.anims = AnimationStack()
        self.progression = ProgressionManager(self.state)
        self.friends = FriendManager(self.state)
        # Treat gift
        self.treat = None
        self.treat_timer = 0.0
        self.treat_next = random.uniform(60, 180)
        # Pre-load raw sprites
        self._raw_cache = {}
        # Pre-load heart particle sprites
        self._heart_sprites = {}
        for name in HEART_SPRITES:
            self._heart_sprites[name] = load_raw(os.path.join(ASSET_DIR, f"{name}.raw"))
        # Back buffer for atomic frame updates (eliminates tearing)
        self._backbuf = bytearray(640 * 480 * 2)
        # Touch-reactive bobbing
        self.tap_bob_timer = 0.0
        self.tap_bob_duration = 1.0  # Slow gentle buoy bob
        # Long-press tracking for quit (robust: tracks drag distance)
        self._press_start_time = 0.0
        self._press_start_pos = None
        self._max_drag_dist = 0.0
        # Background auto-rotation timer
        self.bg_rotation_timer = 0.0
        # Speedrun mode
        self._speedrun = False
        # Egg hatch display timer
        self._hatch_display_timer = 0.0

    def _get_raw(self, name):
        if name not in self._raw_cache:
            self._raw_cache[name] = load_raw(os.path.join(ASSET_DIR, name))
        return self._raw_cache[name]

    def set_message(self, msg, duration=2.0):
        self.message = msg
        self.message_timer = duration

    def handle_input(self, key):
        if key is None:
            return
        # F-key app switching
        if key == "F1":
            switch_to("term")
        elif key == "F2":
            switch_to("chat")
        elif key == "F3":
            switch_to("pet")
        elif key == "F4":
            switch_to("reader")
        elif key == "F5":
            switch_to("dash")
        elif key == "F6":
            switch_to("wifi")
        elif key == "F7":
            switch_to("bt")
        elif key == "\x1b":
            switch_to("term")
        elif key == "q":
            self.running = False
        elif key == "f":
            self._spawn_food()
        elif key == "p":
            if self.state.sleeping:
                self.set_message("Zzz...")
            else:
                self.state.play()
                self.anims.push("play", 1.2)
                self._check_progression("play")
        elif key == "c":
            if self.state.dirty:
                self.state.clean()
                self._spawn_clean_cascade()
                self.set_message("All clean! *sparkle*")
                self.anims.push("clean", 1.0)
                self.anims.push("clean_reaction", 2.0)
                self._check_progression("clean")
            else:
                self.set_message("Already clean!")
        elif key == "s":
            self.state.toggle_sleep(speedrun=self._speedrun)
            if self.state.sleeping:
                self.anims.push("sleep", 2.0)
                self.set_message("Goodnight...")
            else:
                self.set_message("Morning!")
                self.state.bg_idx = BGS.index("coral") if "coral" in self.state.unlocked_bgs else 0
        elif key == "t":
            self.page = 1 - self.page  # toggle stats page
        elif key == "b":
            old_bg = BGS[self.state.bg_idx % len(BGS)]
            self._cycle_bg()
            new_bg = BGS[self.state.bg_idx % len(BGS)]
            if new_bg != old_bg:
                self.anims.push("bg_transition", 0.3, {"from_bg": old_bg, "to_bg": new_bg})
                unlocks = self.progression.check_bg_visit(new_bg)
                self._handle_unlocks(unlocks)
            self.set_message(f"Bg: {new_bg}")
        elif key == "o":
            self._cycle_outfit()
            self.anims.push("outfit_change", 1.0)
            self.set_message(f"Outfit: {OUTFITS[self.state.outfit_idx % len(OUTFITS)]}")
        elif key == "r":
            save_game(self.state)
            self.set_message("Saved!")
        elif key == "\t":
            self._toggle_speedrun()
        elif key == "0":
            self._reset_game()

    def _cycle_bg(self):
        """Cycle to next unlocked background."""
        for _ in range(len(BGS)):
            self.state.bg_idx = (self.state.bg_idx + 1) % len(BGS)
            if BGS[self.state.bg_idx] in self.state.unlocked_bgs:
                break

    def _toggle_speedrun(self):
        """Toggle speedrun mode for rapid lifecycle testing."""
        self._speedrun = not self._speedrun
        if self._speedrun:
            # Unlock everything for testing
            self.state.unlocked_bgs = list(BGS)
            self.state.unlocked_outfits = list(OUTFITS)
            self.state.unlocked_friends = list(Friend.FRIEND_CONFIG.keys())
            self.friends.spawn_timer = 0.0
            self.friends.next_spawn = 3.0  # Friend appears in 3 sec
            self.set_message("SPEEDRUN ON!")
        else:
            self.set_message("Speedrun off")

    def _reset_game(self):
        """Wipe state back to egg and save."""
        self.state = PetState()
        self.friends = FriendManager(self.state)
        self.anims = AnimationManager()
        self.particles = []
        self.food_on_screen = None
        self.treat = None
        self._speedrun = False
        save_game(self.state)
        self.set_message("NEW GAME — TAP THE EGG!")

    def _cycle_outfit(self):
        """Cycle to next unlocked outfit."""
        for _ in range(len(OUTFITS)):
            self.state.outfit_idx = (self.state.outfit_idx + 1) % len(OUTFITS)
            if OUTFITS[self.state.outfit_idx] in self.state.unlocked_outfits:
                break

    def _spawn_food(self):
        """Spawn a random food item somewhere on screen."""
        if self.food_on_screen:
            # Despawn old food first
            self.food_on_screen = None
        self.food_on_screen = {
            "name": random.choice(FOODS),
            "x": random.randint(80, 560),
            "y": random.randint(80, 380),
            "state": "idle",
            "timer": 0.0,
        }

    def _do_feed(self, food, drop_x=None, drop_y=None):
        """Trigger feed animation. If drop coords given, skip to munch phase."""
        self.state.feed(20)
        # Feed triggers excited reaction
        self.anims.push("tap_reaction", 1.5, {"expression": "excited"})
        if drop_x is not None:
            anim = self.anims.push("feed", 0.7, {
                "food": food,
                "fx": drop_x - 40,
                "fy": drop_y - 40,
            })
            if anim:
                anim.phase = 1
                anim.timer = 0.0
                for _ in range(4):
                    self.particles.append(HeartParticle(self.mermaid_x, self.mermaid_y - 60))
        self.set_message(f"Yum! {food}")
        unlocks = self.progression.check_feed()
        self._handle_unlocks(unlocks)

    def _check_progression(self, action):
        unlocks = self.progression.check_all()
        self._handle_unlocks(unlocks)

    def _check_stage_progression(self):
        """Advance lifecycle stage when thresholds are met."""
        stage = self.state.stage
        timer = self.state.stage_timer
        feeds = self.state.stage_feeds
        taps = self.state.egg_taps
        phase = self.state.egg_phase
        # Speedrun divides time thresholds by 7200 (1 day → 12 sec)
        spd = 7200 if self._speedrun else 1

        if stage == "egg":
            # Phase 0→1: crack after 1 day (86400s) AND 24 taps
            if phase == 0 and timer >= (86400 // spd) and taps >= (3 if spd > 1 else 24):
                self.state.egg_phase = 1
                self.set_message("CRACK!", 3.0)
                for _ in range(5):
                    self.particles.append(SparkleParticle(640, 480))
            # Phase 1→2: hatch after 3 days total (259200s) AND 48 taps
            elif phase == 1 and timer >= (259200 // spd) and taps >= (6 if spd > 1 else 48):
                self.state.egg_phase = 2
                self.set_message("It's hatching!", 4.0)
                for _ in range(8):
                    self.particles.append(SparkleParticle(640, 480))
                # Start hatch display timer — evolve after animation plays
                self._hatch_display_timer = 3.0
        elif stage == "baby":
            # Grow to kid after 3 days (259200s) AND 24 feeds
            if timer >= (259200 // spd) and feeds >= (4 if spd > 1 else 24):
                self._evolve_to("kid")
        elif stage == "kid":
            # Grow to adult after 4 days (345600s) AND 24 feeds
            if timer >= (345600 // spd) and feeds >= (4 if spd > 1 else 24):
                self._evolve_to("adult")

    def _evolve_to(self, new_stage):
        """Transition to a new lifecycle stage with fanfare."""
        old_stage = self.state.stage
        self.state.stage = new_stage
        self.state.stage_timer = 0.0
        self.state.stage_feeds = 0
        self.state.egg_taps = 0
        self.state.egg_phase = 0
        self.state.full_timer = 0.0
        # Fresh stage = fresh stats
        self.state.health = 100.0
        self.state.energy = 100.0
        self.state.happiness = 100.0
        self.state.hunger = 50.0
        self.state.cleanliness = 100.0
        self.state.dirty = False
        self.state._clean_timer = 0.0
        self.state._hunger_timer = 0.0

        stage_names = {"egg": "EGG", "baby": "BABY", "kid": "KID", "adult": "ADULT"}
        self.set_message(f"{stage_names.get(old_stage, old_stage)} → {stage_names.get(new_stage, new_stage)}!", 4.0)
        self.anims.push("evolve", 3.0)
        for _ in range(10):
            self.particles.append(SparkleParticle(640, 480))
        for _ in range(5):
            self.particles.append(HeartParticle(self.mermaid_x, self.mermaid_y - 60))

        # Unlock friends at milestones
        if new_stage == "baby" and "seahorse" not in self.state.unlocked_friends:
            self.state.unlocked_friends.append("seahorse")
            self.set_message("UNLOCKED: SEAHORSE!", 3.0)
        elif new_stage == "kid" and "octopus" not in self.state.unlocked_friends:
            self.state.unlocked_friends.append("octopus")
            self.set_message("UNLOCKED: OCTOPUS!", 3.0)
        elif new_stage == "adult" and "starfish" not in self.state.unlocked_friends:
            self.state.unlocked_friends.append("starfish")
            self.set_message("UNLOCKED: STARFISH!", 3.0)

    def _handle_unlocks(self, unlocks):
        if not unlocks:
            return
        for key in unlocks:
            name = key.replace("outfit_", "").replace("bg_", "").replace("friend_", "")
            self.set_message(f"UNLOCKED: {name.upper()}!", 3.0)
            self.anims.push("unlock_notify", 2.5)
            for _ in range(5):
                self.particles.append(SparkleParticle(640, 480))

    def _handle_swipe(self):
        """Handle swipe gestures for page navigation."""
        # Suppress swipe if dragging food
        if self.food_on_screen and self.food_on_screen.get("state") == "dragging":
            self.touch.get_swipe()  # consume and discard
            return
        swipe = self.touch.get_swipe()
        if swipe == "right":
            if self.page == 1:
                self.page = 0

    def _handle_trackpad(self):
        """Trackpad scroll cycles CLEAN/FEED/SLEEP/INFO; click executes selected."""
        self.trackpad.poll()
        # Stats page: any click closes it (acts as X button)
        if self.page == 1:
            if self.trackpad.click:
                self.page = 0
            return
        if self.state.stage == "egg":
            return
        if self.trackpad.scroll != 0:
            n = 1 if self.trackpad.scroll > 0 else -1
            self.selected_action = (self.selected_action + n) % 4
        if self.trackpad.click:
            if self.selected_action == 0:  # CLEAN
                if self.state.dirty:
                    self.state.clean()
                    self._spawn_clean_cascade()
                    self.set_message("All clean! *sparkle*")
                    self.anims.push("clean", 1.0)
                    self.anims.push("clean_reaction", 2.0)
                    self._check_progression("clean")
                else:
                    self.set_message("Already clean!")
            elif self.selected_action == 1:  # FEED
                if self.state.stage == "baby" and self.state.full_timer > 0:
                    self.set_message("Too full!")
                else:
                    self._spawn_food()
            elif self.selected_action == 2:  # SLEEP
                self.state.toggle_sleep(speedrun=self._speedrun)
                if self.state.sleeping:
                    self.anims.push("sleep", 2.0)
                    self.set_message("Goodnight...")
                else:
                    self.set_message("Morning!")
                    self.state.bg_idx = (BGS.index("coral")
                                         if "coral" in self.state.unlocked_bgs else 0)
            elif self.selected_action == 3:  # INFO
                self.page = 1

    def _on_touch_down(self, x, y):
        """Handle finger press."""
        if self.page == 1:
            return  # stats page — release will go back

        # Track press start for quit detection
        self._press_start_time = time.time()
        self._press_start_pos = (x, y)
        self._max_drag_dist = 0.0

        # ── Egg stage: any tap warms the egg ───────────────────────────
        if self.state.stage == "egg":
            self.state.egg_taps += 1
            if self.state.egg_taps >= 3:
                self.set_message("It's hatching!", 2.0)
            elif self.state.egg_taps == 2:
                self.set_message("Crack!", 1.5)
            else:
                self.set_message("*warmth*", 1.5)
            self.tap_bob_timer = self.tap_bob_duration
            for _ in range(3):
                self.particles.append(HeartParticle(self.mermaid_x, self.mermaid_y - 60))
            for _ in range(4):
                self.particles.append(SparkleParticle(640, 480))
            return

        # Check treat tap first
        if self.treat and self._hit_treat(x, y):
            self._collect_treat()
            return

        # Check friend tap
        friend = self._hit_friend(x, y)
        if friend:
            self.state.happiness = min(100, self.state.happiness + 5)
            self.state.energy = min(100, self.state.energy + 3)
            # Friend tap triggers excited reaction (breaks sad state)
            self.anims.push("tap_reaction", 1.5, {"expression": "excited"})
            self.set_message(f"*{friend.name}* +happy +energy")
            # Floating hearts and sparkles around the friend
            for _ in range(4):
                self.particles.append(HeartParticle(int(friend.x) + 60, int(friend.y) + 20))
            for _ in range(4):
                self.particles.append(SparkleParticle(640, 480))
            return

        # Check spawned food pickup
        if self.food_on_screen and self.food_on_screen["state"] == "idle":
            fx, fy = self.food_on_screen["x"], self.food_on_screen["y"]
            if abs(x - fx) < 50 and abs(y - fy) < 50:
                self.food_on_screen["state"] = "dragging"
                # Dragging cancels any quit intent
                self._max_drag_dist = 999.0
                return

        # Bottom zones: CLEAN | FEED | SLEEP (subtle, no button bar)
        if y > 420:
            if x < 213:
                # Clean handled on touch_up
                pass
            elif x < 426:
                # Baby can't eat while full
                if self.state.stage == "baby" and self.state.full_timer > 0:
                    self.set_message("Too full!")
                    return
                self._spawn_food()
            else:
                self.state.toggle_sleep(speedrun=self._speedrun)
                if self.state.sleeping:
                    self.anims.push("sleep", 2.0)
                    self.set_message("Goodnight...")
                else:
                    self.set_message("Morning!")
                    self.state.bg_idx = BGS.index("coral") if "coral" in self.state.unlocked_bgs else 0
            return

        # Mermaid tap area
        if 180 < x < 460 and 100 < y < 440:
            if self.state.sleeping:
                return
            # Sick comfort (all stages) — reduced tap healing, needs food+rest
            if self.state.health < 30:
                self.state.health = min(100, self.state.health + 1)
                self.state.happiness = min(100, self.state.happiness + 2)
                self.state.energy = min(100, self.state.energy + 1)
                self.set_message("*comfort* Needs food & rest")
                self.tap_bob_timer = self.tap_bob_duration
                self.anims.push("tap_reaction", 1.0, {"expression": "happy"})
                self.blinking = True
                self.blink_timer = 0.0
                for _ in range(2):
                    self.particles.append(HeartParticle(self.mermaid_x, self.mermaid_y - 60))
                return
            # Baby: comfort tap instead of play
            if self.state.stage == "baby":
                # Sad babies need treats/friends, not just taps
                happy_gain = 3 if self.state.mood() == "sad" else 8
                self.state.happiness = min(100, self.state.happiness + happy_gain)
                self.state.energy = min(100, self.state.energy + 2)
                self.state.health = min(100, self.state.health + 5)
                self.set_message("*coo*")
                self.tap_bob_timer = self.tap_bob_duration
                self.anims.push("tap_reaction", 1.0, {"expression": "happy"})
                self.blinking = True
                self.blink_timer = 0.0
                for _ in range(3):
                    self.particles.append(HeartParticle(self.mermaid_x, self.mermaid_y - 60))
                for _ in range(4):
                    self.particles.append(SparkleParticle(640, 480))
                return
            # Kid / Adult: play
            self.state.play()
            self.state.energy = min(100, self.state.energy + 2)
            self.anims.push("tap_reaction", 1.0, {"expression": "happy"})
            self.blinking = True
            self.blink_timer = 0.0
            self.set_message("*splash!*")
            self.tap_bob_timer = self.tap_bob_duration
            for _ in range(3):
                self.particles.append(HeartParticle(self.mermaid_x, self.mermaid_y - 60))
            for _ in range(4):
                self.particles.append(SparkleParticle(640, 480))

    def _on_touch_drag(self, x, y):
        """Handle finger drag while held down."""
        # Track max drag distance from press start
        if self._press_start_pos:
            dx = x - self._press_start_pos[0]
            dy = y - self._press_start_pos[1]
            self._max_drag_dist = max(self._max_drag_dist, (dx*dx + dy*dy) ** 0.5)

        if self.food_on_screen and self.food_on_screen["state"] == "dragging":
            self.food_on_screen["x"] = x
            self.food_on_screen["y"] = y

    def _on_touch_up(self, x, y):
        """Handle finger release."""
        # Stats page: X button or tap anywhere to close
        if self.page == 1:
            self.page = 0
            self.touch.get_tap()  # consume
            return

        # Main page: info button (upper right) opens stats
        if (x - 608) ** 2 + (y - 32) ** 2 < 400:
            self.page = 1
            self.touch.get_tap()
            self._press_start_time = 0.0
            self._press_start_pos = None
            self._max_drag_dist = 0.0
            return

        # Check long-press quit (top-right corner, held 2s, finger barely moved)
        if self._press_start_pos:
            sx, sy = self._press_start_pos
            held = time.time() - self._press_start_time
            in_corner = sx > 580 and sy < 50
            held_still = self._max_drag_dist < 25
            if in_corner and held_still and held >= 2.0:
                self.set_message("Saving...")
                save_game(self.state)
                self.running = False
                return
        self._press_start_time = 0.0
        self._press_start_pos = None
        self._max_drag_dist = 0.0

        if self.food_on_screen and self.food_on_screen["state"] == "dragging":
            # Check if dropped near mermaid's mouth
            mouth_x = self.mermaid_x
            mouth_y = self.mermaid_y - 80
            dx = x - mouth_x
            dy = y - mouth_y
            dist = (dx * dx + dy * dy) ** 0.5

            if dist < 120:
                # Baby can't eat while full
                if self.state.stage == "baby" and self.state.full_timer > 0:
                    self.set_message("Too full!")
                    self.food_on_screen["state"] = "idle"
                else:
                    # Eaten!
                    self._do_feed(self.food_on_screen["name"], x, y)
                    self.food_on_screen = None
            else:
                # Plop — food stays where dropped
                self.food_on_screen["state"] = "idle"
                self.set_message("*plop*")
            self.touch.get_tap()
            return

        # Normal tap handling (when not dragging food)
        tap = self.touch.get_tap()
        if tap is None:
            return
        x, y = tap

        # Check treat
        if self.treat and self._hit_treat(x, y):
            self._collect_treat()
            return

        # Bottom zones
        if y > 420:
            if x < 213:
                if self.state.dirty:
                    self.state.clean()
                    self._spawn_clean_cascade()
                    self.set_message("All clean! *sparkle*")
                    self.anims.push("clean", 1.0)
                    self.anims.push("clean_reaction", 2.0)
                    self._check_progression("clean")
                else:
                    self.set_message("Already clean!")
            elif x < 426:
                pass  # FEED handled in _on_touch_down
            else:
                self.state.toggle_sleep(speedrun=self._speedrun)
                if self.state.sleeping:
                    self.anims.push("sleep", 2.0)
                    self.set_message("Goodnight...")
                else:
                    self.set_message("Morning!")
                    self.state.bg_idx = BGS.index("coral") if "coral" in self.state.unlocked_bgs else 0
        elif 180 < x < 460 and 100 < y < 440 and not self.state.sleeping:
            if self.state.stage == "baby":
                happy_gain = 3 if self.state.mood() == "sad" else 8
                self.state.happiness = min(100, self.state.happiness + happy_gain)
                self.state.energy = min(100, self.state.energy + 2)
                self.set_message("*coo*")
                self.tap_bob_timer = self.tap_bob_duration
                self.anims.push("tap_reaction", 1.0, {"expression": "happy"})
                self.blinking = True
                self.blink_timer = 0.0
                for _ in range(3):
                    self.particles.append(HeartParticle(self.mermaid_x, self.mermaid_y - 60))
                for _ in range(4):
                    self.particles.append(SparkleParticle(640, 480))
            else:
                self.state.play()
                self.state.health = min(100, self.state.health + 5)
                self.tap_bob_timer = self.tap_bob_duration
                self.anims.push("tap_reaction", 1.0, {"expression": "happy"})
                self.blinking = True
                self.blink_timer = 0.0
                self.set_message("*splash!*")
                for _ in range(3):
                    self.particles.append(HeartParticle(self.mermaid_x, self.mermaid_y - 60))
                for _ in range(4):
                    self.particles.append(SparkleParticle(640, 480))

    def _hit_treat(self, x, y):
        if not self.treat:
            return False
        tx, ty = self.treat["x"], self.treat["y"]
        return abs(x - tx) < 50 and abs(y - ty) < 50

    def _hit_friend(self, x, y):
        """Check if touch hits the active friend. Returns friend or None."""
        if not self.friends.active_friend or not self.friends.active_friend.is_present():
            return None
        f = self.friends.active_friend
        cx = f.x + 60
        cy = f.y + 60
        if abs(x - cx) < 60 and abs(y - cy) < 60:
            return f
        return None

    def _spawn_clean_cascade(self):
        """Spawn rising bubbles and sparkles over the mermaid during clean."""
        mx, my = self.mermaid_x, self.mermaid_y
        # Rising bubbles
        for _ in range(12):
            self.particles.append(CleanBubble(mx, my))
        # Rising sparkles
        for _ in range(10):
            s = SparkleParticle(640, 480)
            s.x = mx + random.randint(-60, 60)
            s.y = my + random.randint(-30, 40)
            s.life = random.uniform(1.0, 2.5)
            self.particles.append(s)
        # A few hearts for joy
        for _ in range(3):
            self.particles.append(HeartParticle(mx, my - 40))

    def _collect_treat(self):
        name = self.treat["name"]
        bonus = next((b for b in TREATS if b[0] == name), ("oyster", 5, 3))
        _, happy_bonus, energy_bonus = bonus
        self.state.happiness = min(100, self.state.happiness + happy_bonus)
        self.state.energy = min(100, self.state.energy + energy_bonus)
        # Treat triggers excited reaction (breaks sad state)
        self.anims.push("tap_reaction", 1.5, {"expression": "excited"})
        self.set_message(f"{name.upper()}! +happy +energy", 2.5)
        for _ in range(6):
            self.particles.append(SparkleParticle(640, 480))
        self.treat = None
        self.treat_timer = 0.0
        self.treat_next = random.uniform(60, 180)
        # Small chance to unlock a friend
        unlocks = self.progression.check_all()
        self._handle_unlocks(unlocks)

    def _get_float_amplitude(self):
        """Return float amplitude based on mood/energy."""
        if self.state.sleeping:
            return 0
        mood = self.state.mood()
        if mood == "sad":
            return 4
        if self.state.energy < 30:
            return 3
        return 8

    def update(self, dt):
        # Speedrun accelerates everything (decay, aging, timers)
        spd_mult = 100 if self._speedrun else 1
        sim_dt = dt * spd_mult

        self.state.decay(sim_dt)
        self.state.age_days += sim_dt / 86400

        # Sleep auto-wake: min 2 min, max 10 min, wake at 95+ energy
        if self.state.sleeping and self.state._sleep_timer > 0:
            slept = time.time() - self.state._sleep_timer
            min_sleep = 2 if self._speedrun else 120
            max_sleep = 10 if self._speedrun else 600
            if slept >= max_sleep:  # max sleep time
                self.state.sleeping = False
                self.state._sleep_timer = 0.0
                self.set_message("Morning!")
                self.state.bg_idx = BGS.index("coral") if "coral" in self.state.unlocked_bgs else 0
            elif slept >= min_sleep and self.state.energy >= 95:
                self.state.sleeping = False
                self.state._sleep_timer = 0.0
                self.set_message("Morning!")
                self.state.bg_idx = BGS.index("coral") if "coral" in self.state.unlocked_bgs else 0

        # Stage progression (accelerated in speedrun)
        spd_mult = 100 if self._speedrun else 1
        self.state.stage_timer += dt * spd_mult
        self._check_stage_progression()

        # Egg hatch: after showing hatch sprite for a few seconds, evolve to baby
        if self.state.stage == "egg" and self.state.egg_phase == 2:
            self._hatch_display_timer -= dt
            if self._hatch_display_timer <= 0:
                self._evolve_to("baby")

        # Background time-of-day check (every 60 seconds)
        self.bg_rotation_timer += dt
        if self.bg_rotation_timer > 60:
            self.bg_rotation_timer = 0
            # If current bg is not time-appropriate, switch to one that is
            pool = get_time_bg_indices()
            if pool and self.state.bg_idx not in pool:
                for idx in pool:
                    if BGS[idx] in self.state.unlocked_bgs:
                        self.state.bg_idx = idx
                        break
            else:
                # Cycle within time-appropriate pool
                next_bg = get_next_time_bg(self.state.bg_idx)
                if next_bg != self.state.bg_idx and BGS[next_bg] in self.state.unlocked_bgs:
                    self.state.bg_idx = next_bg

        # Update animation stack
        for anim in self.anims.anims:
            if anim.type == "feed":
                if anim.phase == 0:
                    t = min(1.0, anim.timer / 0.8)
                    start_y = anim.data.get("fy", 400)
                    target_y = anim.data.get("target_y", 200)
                    anim.data["fy"] = int(start_y - t * (start_y - target_y))
                    if anim.timer >= 0.8:
                        anim.phase = 1
                        anim.timer = 0
                        for _ in range(3):
                            self.particles.append(HeartParticle(self.mermaid_x, self.mermaid_y - 50))
                elif anim.phase == 1:
                    if anim.timer >= 0.6:
                        anim.done = True

        completed = self.anims.update(dt)
        for anim in completed:
            if anim.type == "play":
                self.set_message("*splash!*")
            elif anim.type == "clean":
                self.set_message("*sparkle*")
            elif anim.type == "sleep":
                self.set_message("Zzz...")

        # Float animation with mood-based amplitude
        amplitude = self._get_float_amplitude()
        float_y = int(math.sin(time.time() * 1.2 + self.float_phase) * amplitude)
        self.mermaid_y = 270 + float_y

        # Swimming motion — drift + flutter makes existing flippers appear animated
        t = time.time()
        if not self.state.sleeping:
            # Slow drift (swimming around)
            drift_x = math.sin(t * 0.35 + self.wander_phase) * 55
            drift_y = math.sin(t * 0.8 + self.float_phase) * amplitude
            # Fast flutter (tail propulsion vibration)
            flutter_x = math.sin(t * 3.2 + self.wander_phase) * 4
            flutter_y = math.sin(t * 4.0 + self.float_phase * 1.3) * 3
            self.wander_x = drift_x + flutter_x
            self.mermaid_y = 270 + int(drift_y + flutter_y)
        else:
            # Sleeping: barely drifts
            self.wander_x = math.sin(t * 0.15 + self.wander_phase) * 8
            self.mermaid_y = 270 + int(math.sin(t * 0.5 + self.float_phase) * 2)
        self.mermaid_x = 320 + int(self.wander_x) + MERMAID_X_OFFSET

        # Decay touch-reactive bob
        if self.tap_bob_timer > 0:
            self.tap_bob_timer -= dt

        # Blink logic — all stages blink, including sleep
        self.blink_timer += dt
        if self.blinking:
            if self.blink_timer > 0.3:
                self.blinking = False
                self.blink_timer = 0.0
                self.blink_next = random.uniform(2.0, 5.0)
        else:
            if self.blink_timer > self.blink_next:
                self.blinking = True
                self.blink_timer = 0.0

        # Ambient particles
        self.bubble_timer += dt
        self.sparkle_timer += dt
        mood = self.state.mood()

        if self.bubble_timer > 0.5:
            if random.random() < 0.6:
                self.particles.append(BubbleParticle(640, 480))
            self.bubble_timer = 0

        if mood in ("happy", "excited") and self.sparkle_timer > 0.3:
            if random.random() < 0.5:
                self.particles.append(SparkleParticle(640, 480))
            self.sparkle_timer = 0

        if mood == "sleep" and self.frame % 60 == 0:
            self.particles.append(ZzzParticle(self.mermaid_x, self.mermaid_y - 80))
        elif mood == "happy" and self.frame % 120 == 0:
            self.particles.append(HeartParticle(self.mermaid_x + 50, self.mermaid_y - 60))
        elif mood == "excited" and self.frame % 30 == 0:
            self.particles.append(SparkleParticle(640, 480))
            self.particles.append(HeartParticle(self.mermaid_x, self.mermaid_y - 70))
        elif self.state.dirty and self.frame % 40 == 0:
            self.particles.append(StinkParticle(self.mermaid_x, self.mermaid_y - 100))

        # Update friends
        self.friends.update(dt)

        # Friend presence bonus: +1 energy/sec when any friend is visiting
        if self.friends.active_friend and self.friends.active_friend.is_present():
            self.state.energy = min(100, self.state.energy + 1.0 * dt)

        # Food timeout — despawn if left too long
        if self.food_on_screen and self.food_on_screen["state"] == "idle":
            self.food_on_screen["timer"] += dt
            if self.food_on_screen["timer"] > 15.0:
                self.food_on_screen = None

        # Treat spawn logic
        if not self.treat and self.state.happiness > 50:
            self.treat_timer += dt
            if self.treat_timer >= self.treat_next:
                self.treat = {
                    "name": random.choice([t[0] for t in TREATS]),
                    "x": random.randint(80, 560),
                    "y": random.randint(300, 440),
                }
                self.treat_timer = 0.0

        # Update particles
        for p in self.particles:
            p.update(dt)
        self.particles = [p for p in self.particles if p.alive()]

        if self.message_timer > 0:
            self.message_timer -= dt
            if self.message_timer <= 0:
                self.message = ""

        self.frame += 1

    def _pick_sprite(self):
        """Choose the correct sprite based on lifecycle stage, state, mood, and blink."""
        stage = self.state.stage

        # ── Egg stage ──────────────────────────────────────────────────
        if stage == "egg":
            phase = self.state.egg_phase
            if phase == 2:
                return get_lifecycle_path("egg", "hatch") or get_lifecycle_path("egg", "crack") or get_lifecycle_path("egg", "")
            elif phase == 1:
                return get_lifecycle_path("egg", "crack") or get_lifecycle_path("egg", "")
            return get_lifecycle_path("egg", "")

        # ── Baby stage ─────────────────────────────────────────────────
        if stage == "baby":
            # Full state takes priority
            if self.state.full_timer > 0 and not self.state.sleeping:
                return get_lifecycle_path("baby", "full", blink=self.blinking) or get_lifecycle_path("baby", "", blink=self.blinking)
            if self.state.sleeping:
                path = get_lifecycle_path("baby", "sleep", blink=self.blinking)
                if path:
                    return path
                return get_lifecycle_path("baby", "", blink=self.blinking)
            if self.state.dirty:
                path = get_lifecycle_path("baby", "dirty", blink=self.blinking)
                if path:
                    return path
            mood = self.state.mood()
            expr = self.anims.get_override()
            if expr is None:
                expr = MOOD_TO_EXPRESSION.get(mood)
            # Baby uses default for happy/neutral, cry for sad/cranky/sick, excite for excited
            if expr in ("sad", "cranky", "sick"):
                path = get_lifecycle_path("baby", "cry", blink=self.blinking)
                if path:
                    return path
            elif expr == "excited":
                path = get_lifecycle_path("baby", "excite", blink=self.blinking)
                if path:
                    return path
            return get_lifecycle_path("baby", "", blink=self.blinking)

        # ── Kid stage ──────────────────────────────────────────────────
        if stage == "kid":
            if self.state.sleeping:
                path = get_lifecycle_path("kid", "sleep", blink=self.blinking)
                if path:
                    return path
                return get_lifecycle_path("kid", "", blink=self.blinking)
            if self.state.dirty:
                path = get_lifecycle_path("kid", "dirty", blink=self.blinking)
                if path:
                    return path
            mood = self.state.mood()
            expr = self.anims.get_override()
            if expr is None:
                expr = MOOD_TO_EXPRESSION.get(mood)
            # Kid uses default for happy/neutral, cry for sad/cranky/sick, excite for excited
            if expr in ("sad", "cranky", "sick"):
                path = get_lifecycle_path("kid", "cry", blink=self.blinking)
                if path:
                    return path
            elif expr == "excited":
                path = get_lifecycle_path("kid", "excite", blink=self.blinking)
                if path:
                    return path
            return get_lifecycle_path("kid", "", blink=self.blinking)

        # ── Adult stage ────────────────────────────────────────────────
        outfit = OUTFITS[self.state.outfit_idx % len(OUTFITS)]

        if self.state.sleeping:
            path = get_expression_path("sleep", blink=self.blinking)
            if path:
                return path
            return get_outfit_path(outfit, blink=self.blinking)

        # Forced clean state: show clean sprite for full duration
        if self.state._clean_timer > 0:
            path = get_expression_path("clean", blink=self.blinking)
            if path:
                return path

        mood = self.state.mood()
        expr = self.anims.get_override()
        if expr is None:
            expr = MOOD_TO_EXPRESSION.get(mood)

        if expr:
            path = get_expression_path(expr, blink=self.blinking)
            if path:
                return path

        return get_outfit_path(outfit, blink=self.blinking)

    def _get_sprite_size(self):
        """Return (width, height) for the current stage's sprite."""
        if self.state.stage == "egg":
            return 160, 224
        return SPRITE_W, SPRITE_H

    def draw(self):
        if self.page == 1:
            self._draw_stats_page()
            return

        bg = get_bg_path(self.state.bg_idx)
        sprite = self._pick_sprite()

        # Sprite size varies by stage
        sp_w, sp_h = self._get_sprite_size()
        # Touch-reactive bob: gentle buoy dip when tapped
        bob = 0
        if self.tap_bob_timer > 0:
            t = self.tap_bob_timer / self.tap_bob_duration
            # Single smooth half-sine arc — down then up, like a buoy
            bob = int(buoy_bob(1.0 - t) * 14)
        draw_y = self.mermaid_y + bob
        ox = self.mermaid_x - sp_w // 2
        oy = draw_y - sp_h // 2

        # 1. Render base frame off-screen via fb_blit (writes to RAM, not fb0)
        shm_path = "/dev/shm/pet_frame.raw"
        cmd = [
            FBBLIT,
            "--bg", bg,
            "--sprite", sprite,
            "--sx", str(ox),
            "--sy", str(oy),
            "--out", shm_path,
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except Exception as e:
            print(f"fb_blit error: {e}")

        # 2. Load composited frame into back buffer from RAM file
        try:
            with open(shm_path, "rb") as f:
                self._backbuf[:] = f.read()
        except Exception as e:
            print(f"frame read error: {e}")
            return

        original_mm = self.fb._mm
        self.fb._mm = self._backbuf

        # 3. Draw all overlays into back buffer
        self._draw_overlays()

        # 4. Draw particles into back buffer
        for p in self.particles:
            if isinstance(p, HeartParticle):
                p.draw(self.fb, self._heart_sprites.get(p.sprite))
            else:
                p.draw(self.fb)

        # 5. Draw UI text into back buffer
        if self.message:
            self.fb.text(self.message.upper(), 15, 15, C_WHITE, scale=3)

        if getattr(self, '_speedrun', False):
            self.fb.text(">> SPEEDRUN >>", 15, 8, rgb565(255, 50, 50), scale=2)
        # Info button (upper right) — highlighted pink when selected by trackpad
        _info_color = C_THEME_PINK if self.selected_action == 3 else C_WHITE
        self.fb.ring(608, 32, 16, _info_color, 2)
        self.fb.text("i", 604, 24, _info_color, scale=2)


        if self.state.stage == "egg":
            self.fb.text("TAP TO WARM", 188, 450, C_PINK, scale=3)
        else:
            for i, (label, cx) in enumerate([("CLEAN", 80), ("FEED", 320), ("SLEEP", 560)]):
                tx = cx - (len(label) * 12) // 2
                self.fb.text(label, tx + 1, 451, rgb565(20, 20, 20), scale=3)
                color = C_THEME_PINK if i == self.selected_action else C_WHITE
                self.fb.text(label, tx, 450, color, scale=3)
                if i == self.selected_action:
                    self.fb.hline(tx, 467, len(label) * 12, C_THEME_PINK)

        # 6. Atomically write complete frame to framebuffer (single copy, no tearing)
        self.fb._mm = original_mm
        self.fb._mm[:] = self._backbuf

    def _draw_overlays(self):
        """Draw sprite overlays via pure Python blitter."""
        # Draw active friend (uses oriented sprites for crab perimeter walk)
        if self.friends.active_friend and self.friends.active_friend.is_present():
            f = self.friends.active_friend
            raw = self._get_raw(f.get_raw_path())
            if raw:
                blit_to_fb(self.fb, raw, int(f.x), int(f.y))

        # Draw food during feed animation
        feed_anim = None
        for a in self.anims.anims:
            if a.type == "feed":
                feed_anim = a
                break
        if feed_anim:
            food_name = feed_anim.data.get("food", "")
            fx = int(feed_anim.data.get("fx", 0))
            fy = int(feed_anim.data.get("fy", 0))
            if feed_anim.phase == 0:
                raw = self._get_raw(f"food_{food_name}.raw")
                if raw:
                    blit_to_fb(self.fb, raw, fx, fy)
            elif feed_anim.phase == 1:
                raw = self._get_raw(f"food_{food_name}_eaten.raw")
                if raw:
                    blit_to_fb(self.fb, raw, fx, fy)

        # Draw spawned food on screen
        if self.food_on_screen:
            raw = self._get_raw(f"food_{self.food_on_screen['name']}.raw")
            if raw:
                fx = self.food_on_screen["x"] - 40
                fy = self.food_on_screen["y"] - 40
                blit_to_fb(self.fb, raw, fx, fy)
            # If dragging, show mouth target indicator
            if self.food_on_screen["state"] == "dragging":
                mouth_x = self.mermaid_x
                mouth_y = self.mermaid_y - 80
                pulse = int(4 + math.sin(time.time() * 8) * 2)
                self.fb.ring(mouth_x, mouth_y, 30 + pulse, rgb565(255, 255, 200), 2)

        # Draw treat
        if self.treat:
            raw = self._get_raw(f"treat_{self.treat['name']}.raw")
            if raw:
                blit_to_fb(self.fb, raw, self.treat["x"] - 40, self.treat["y"] - 40)
            # Sparkle ring around treat
            t = time.time()
            for i in range(4):
                angle = t * 3 + i * (math.pi / 2)
                px = int(self.treat["x"] + math.cos(angle) * 30)
                py = int(self.treat["y"] + math.sin(angle) * 30)
                self.fb.pixel(px, py, rgb565(255, 255, 200))

        # Draw outfit change sparkles
        if self.anims.is_active("outfit_change"):
            for i in range(3):
                sx = self.mermaid_x + random.randint(-60, 60)
                sy = self.mermaid_y - 80 + random.randint(-20, 20)
                self.particles.append(CleanSparkle(sx, sy))

    def _draw_stats_page(self):
        """Full-screen translucent stats page — tap anywhere to go back."""

        # 1. Render background off-screen via fb_blit (no sprite)
        bg = get_bg_path(self.state.bg_idx)
        shm_path = "/dev/shm/pet_frame.raw"
        try:
            subprocess.run([FBBLIT, "--bg", bg, "--out", shm_path], check=True, capture_output=True)
        except Exception:
            pass

        # 2. Load composited frame into back buffer from RAM file
        try:
            with open(shm_path, "rb") as f:
                self._backbuf[:] = f.read()
        except Exception:
            pass

        original_mm = self.fb._mm
        self.fb._mm = self._backbuf

        # 3. Translucent dark overlay — denser scanlines for readability without hiding backdrop
        for y_dim in range(0, 480, 2):
            self.fb.rect(0, y_dim, 640, 1, rgb565(8, 6, 14))

        try:
            # Helper for shadowed text
            def _txt(text, x, y, color, scale=2, align="left"):
                w_px = len(text) * (8 * scale)
                x0 = x if align == "left" else x - w_px // 2 if align == "center" else x - w_px
                self.fb.text(text, x0 + 1, y + 1, rgb565(15, 10, 20), scale=scale)
                self.fb.text(text, x0, y, color, scale=scale)

            # ── Title ──
            _txt("STATS", 320, 14, C_THEME_PINK, scale=3, align="center")

            # ── X close button — always highlighted since trackpad click closes ──
            self.fb.ring(608, 32, 16, C_THEME_PINK, 2)
            self.fb.text("X", 600, 24, C_THEME_PINK, scale=2)

            # ── Mood badge ──
            mood = self.state.mood()
            mood_colors = {
                "happy": C_THEME_MINT, "excited": C_THEME_YELLOW, "love": C_THEME_PINK,
                "sad": C_THEME_BLUE, "sick": C_RED, "hungry": C_ORANGE,
                "tired": C_THEME_PURPLE, "dirty": rgb565(160, 120, 60),
                "sleep": C_THEME_BLUE, "cranky": C_RED, "neutral": C_GRAY,
            }
            mc = mood_colors.get(mood, C_WHITE)
            self.fb.rect(244, 50, 152, 28, mc)
            _txt(mood.upper(), 320, 54, C_DARK, scale=2, align="center")

            # ── Stat bars ──
            x = 40
            y = 84
            w = 560
            bar_h = 22
            gap = 58

            stats = [
                ("HUNGER", 1 - self.state.hunger / 100, C_THEME_PEACH),
                ("HAPPINESS", self.state.happiness / 100, C_THEME_PINK),
                ("ENERGY", self.state.energy / 100, C_THEME_BLUE),
                ("CLEANLINESS", self.state.cleanliness / 100, C_THEME_MINT),
                ("HEALTH", self.state.health / 100, C_THEME_YELLOW),
            ]

            for name, pct, color in stats:
                val = int(pct * 100)
                label_color = C_RED if val < 20 else C_THEME_CYAN
                _txt(name, x, y, label_color, scale=2)
                val_str = f"{val}%"
                _txt(val_str, x + w, y, C_WHITE, scale=2, align="right")

                # Bar background
                self.fb.rect(x, y + 20, w, bar_h, rgb565(20, 15, 28))
                self.fb.rect(x, y + 20, w, 1, rgb565(60, 50, 75))
                self.fb.rect(x, y + 20 + bar_h - 1, w, 1, rgb565(12, 9, 18))

                # Bar fill
                fill_color = C_RED if val < 20 else color
                self.fb.bar(x + 1, y + 21, w - 2, bar_h - 2, pct, fill_color)

                y += gap

            # ── Info block ──
            y += 4
            stage_label = self.state.stage.upper()
            _txt(f"STAGE: {stage_label}", x, y, C_THEME_CHART, scale=2)

            if self.state.stage == "adult":
                outfit = OUTFITS[self.state.outfit_idx % len(OUTFITS)]
                _txt(f"OUTFIT: {outfit.upper()}", x + 300, y, C_THEME_PEACH, scale=2)

            y += 26
            if self.state.sleeping:
                _txt("SLEEPING", x, y, C_THEME_BLUE, scale=2)
            else:
                _txt("AWAKE", x, y, C_THEME_MINT, scale=2)
            _txt(f"AGE {self.state.age_days:.1f}D", x + 300, y, C_THEME_CYAN, scale=2)

            y += 26
            stage = self.state.stage
            if stage == "egg":
                progress = min(100, int(self.state.egg_taps / 48 * 100))
                _txt(f"HATCH {progress}%", x, y, C_THEME_PINK, scale=2)
            elif stage in ("baby", "kid"):
                progress = min(100, int(self.state.stage_feeds / 24 * 100))
                _txt(f"GROW {progress}%", x, y, C_THEME_PINK, scale=2)

            if self.state._clean_timer > 0:
                y += 26
                mins = int(self.state._clean_timer // 60)
                secs = int(self.state._clean_timer % 60)
                _txt(f"SPARKLE {mins}:{secs:02d}", x, y, C_THEME_PINK, scale=2)

            # ── Unlocks ──
            y += 24
            _txt(
                f"BGS {len(self.state.unlocked_bgs)}/{len(BGS)}   "
                f"OUTFITS {len(self.state.unlocked_outfits)}/{len(OUTFITS)}   "
                f"FRIENDS {len(self.state.unlocked_friends)}/5",
                320, y, C_GRAY, scale=2, align="center"
            )

            # ── Close hint ──
            _txt("TAP TO CLOSE", 320, 456, C_GRAY, scale=2, align="center")

        finally:
            # 4. Write complete frame to framebuffer via fd.write() — required for
            # vc4 DRM fbdev emulation, which only flushes to the display compositor
            # when writes go through the fbdev write() path. mmap slice assignment
            # updates the shadow buffer but never triggers the DRM scanout.
            self.fb._mm = original_mm
            self.fb._fd.seek(0)
            self.fb._fd.write(self._backbuf)

    def run(self):
        print("cyberdeck Mermaid Pet")
        print("Controls: f=feed c=clean s=sleep t=stats b=bg o=outfit r=save 0=reset Tab=speedrun q=quit")
        print("F-keys: F1=term F2=chat F3=pet F4=reader F5=dash F6=wifi F7=bt")
        # fbterm/getty management is now handled by cyberdeck-shell daemon.
        # Pet focuses on rendering only.
        # Check initial unlocks
        self._check_progression("init")
        # Prevent underlying console text from flashing through the framebuffer
        _clear_console()
        _set_console_graphics_mode(True)
        _hide_console_cursor()
        self.input.start()
        _last_auto_save = time.time()
        # [is_blanked, last_check_time] — sysfs read cached every 2s
        _blank_cache = [False, 0.0]
        try:
            while self.running:
                now = time.time()
                dt = min(now - self.last_t, 0.1)
                self.last_t = now

                # Refresh screen-blank state every 2s (avoid per-frame sysfs I/O).
                # Only treat as blanked when the file explicitly contains a non-zero
                # integer — empty reads (DSI displays) mean not blanked.
                if now - _blank_cache[1] >= 2.0:
                    try:
                        with open("/sys/class/graphics/fb0/blank") as _bf:
                            _v = _bf.read().strip()
                            _blank_cache[0] = bool(_v) and _v != "0"
                    except Exception:
                        _blank_cache[0] = False
                    _blank_cache[1] = now
                fb_blanked = _blank_cache[0]

                # poll_timeout drives loop rate:
                #   blanked  → 1 fps (screen off, just watch for wakeup input)
                #   sleeping → 15 fps (pet asleep, nothing animating)
                #   active   → ~30 fps (getch 16ms + sleep 16ms below)
                if fb_blanked:
                    poll_timeout = 1.0
                elif self.state.sleeping:
                    poll_timeout = 0.066
                else:
                    poll_timeout = 0.016

                # Re-assert raw mode in case fbterm cleanup or getty reset it
                self.input.ensure_raw()
                key = self.input.getch(timeout=poll_timeout)
                self.handle_input(key)

                # Touch handling with drag-and-drop support
                self.touch.poll()
                was_down = self._touch_was_down
                is_down = self.touch.down
                self._touch_was_down = is_down

                if not was_down and is_down:
                    self._on_touch_down(self.touch.x, self.touch.y)
                elif was_down and is_down:
                    self._on_touch_drag(self.touch.x, self.touch.y)
                elif was_down and not is_down:
                    self._on_touch_up(self.touch.x, self.touch.y)

                self._handle_swipe()
                self._handle_trackpad()
                self.update(dt)

                # Auto-save every 60 seconds
                if now - _last_auto_save >= 60:
                    save_game(self.state)
                    _last_auto_save = now

                if not fb_blanked:
                    self.draw()
                if not fb_blanked and not self.state.sleeping:
                    time.sleep(0.016)
        except KeyboardInterrupt:
            pass
        finally:
            self.input.stop()
            self.touch.close()
            self.trackpad.close()
            save_game(self.state)
            self.fb.close()
            # Restore console text mode before exiting so fbterm apps work
            _set_console_graphics_mode(False)
            try:
                with open("/dev/tty1", "w") as tty:
                    tty.write("\033[?25h")
            except Exception:
                pass
            print("\nSaved. Bye!")


def main():
    app = None

    def sigint_handler(signum, frame):
        print("\nInterrupted.")
        sys.exit(0)

    def sigterm_handler(signum, frame):
        print("\nSIGTERM received, saving...")
        if app is not None:
            save_game(app.state)
        sys.exit(0)

    signal.signal(signal.SIGINT, sigint_handler)
    signal.signal(signal.SIGTERM, sigterm_handler)
    app = PetApp()
    app.run()


if __name__ == "__main__":
    main()
