#!/usr/bin/env python3
"""Friend companion system for the cyberdeck pet."""
import random
import math


class Friend:
    """An unlockable companion that visits and boosts stats."""

    FRIEND_CONFIG = {
        "crab": {
            "enter_side": "left",
            "enter_y": 360,
            "speed": 70,
            "visit_duration": (30, 60),
            "happiness_bonus": 5,
            "health_per_minute": 1.0,
            "movement": "crab_explore",
        },
        "dolphin": {
            "enter_side": "right",
            "enter_y": 120,
            "speed": 120,
            "visit_duration": (20, 40),
            "happiness_bonus": 10,
            "health_per_minute": 2.0,
            "movement": "dolphin_arc",
        },
        "octopus": {
            "enter_side": "right",
            "enter_y": 380,
            "speed": 40,
            "visit_duration": (25, 50),
            "happiness_bonus": 3,
            "health_per_minute": 1.5,
            "movement": "octopus_wiggle",
        },
        "seahorse": {
            "enter_side": "right",
            "enter_y": 200,
            "speed": 30,
            "visit_duration": (35, 70),
            "happiness_bonus": 8,
            "health_per_minute": 1.0,
            "movement": "pass_through",
        },
        "starfish": {
            "enter_side": "left",
            "enter_y": 420,
            "speed": 20,
            "visit_duration": (40, 80),
            "happiness_bonus": 5,
            "health_per_minute": 2.5,
            "movement": "pass_through",
        },
    }

    # Sprite dimensions for edge clamping
    SPRITE_W = 120
    SPRITE_H = 120

    def __init__(self, name):
        cfg = self.FRIEND_CONFIG[name]
        self.name = name
        self.state = "offscreen"  # offscreen, entering, idle, exiting
        self.x = -150 if cfg["enter_side"] == "left" else 790
        self.y = cfg["enter_y"]
        self.target_x = 50 if cfg["enter_side"] == "left" else 590
        self.speed = cfg["speed"]
        self.timer = 0.0
        self.visit_duration = random.uniform(*cfg["visit_duration"])
        self.happiness_bonus = cfg["happiness_bonus"]
        self.health_per_minute = cfg["health_per_minute"]
        self.enter_side = cfg["enter_side"]
        self.movement = cfg.get("movement", "pass_through")

        # Crab-specific scuttle state
        self._scuttle_timer = 0.0
        self._scuttle_pause = 0.0
        self._scuttle_phase = 0.0
        # Perimeter path state
        self._path_idx = 0
        self._exit_requested = False

    def _clamp_to_screen(self, x, y):
        """Keep sprite fully inside 640x480 screen."""
        max_x = 640 - self.SPRITE_W
        max_y = 480 - self.SPRITE_H
        return max(0, min(max_x, x)), max(0, min(max_y, y))

    def start_visit(self):
        """Begin a visit from offscreen."""
        cfg = self.FRIEND_CONFIG[self.name]
        self.state = "entering"
        self.x = -150 if self.enter_side == "left" else 790
        self.y = cfg["enter_y"]
        # Crab enters flush to corner so legs touch screen edges immediately
        if self.movement == "crab_explore":
            self.target_x = -4 if self.enter_side == "left" else 524
        else:
            self.target_x = 50 if self.enter_side == "left" else 590
        self.timer = 0.0
        self.visit_duration = random.uniform(*cfg["visit_duration"])
        self._scuttle_timer = 0.0
        self._scuttle_pause = 0.0
        self._scuttle_phase = random.uniform(0, math.pi * 2)
        self._path_idx = 0
        self._exit_requested = False

    def _move_toward(self, tx, ty, dt, speed=None):
        """Move toward target point. Returns True if arrived."""
        if speed is None:
            speed = self.speed
        dx = tx - self.x
        dy = ty - self.y
        dist = math.hypot(dx, dy)
        step = speed * dt
        if dist < step or dist < 2:
            self.x = tx
            self.y = ty
            return True
        self.x += (dx / dist) * step
        self.y += (dy / dist) * step
        return False

    def _update_crab_explore(self, dt):
        """Crab walks exactly along each screen edge, turning at corners.
        Sprites are positioned flush: legs touch screen edges, body extends inward.
        Path: bottom (left->right) -> right (bottom->top) -> top (right->left) -> left (top->bottom)
        """
        self._scuttle_timer += dt
        if self._scuttle_pause > 0:
            self._scuttle_pause -= dt
            return

        step = self.speed * dt

        # Sprite canvas is 120x120; flush sprites place feet at canvas edges:
        # bottom: feet at y=120, right: feet at x=120, top: feet at y=0, left: feet at x=0
        # Positions allow slight off-screen so visible content reaches exact corners.
        if self._path_idx == 0:       # bottom: y=360, x -4 -> 524
            self.y = 360
            self.x += step
            if self.x >= 524:
                self.x = 524
                self._scuttle_pause = random.uniform(0.5, 1.0)
                self._path_idx = 1
        elif self._path_idx == 1:     # right: x=524, y 360 -> -4
            self.x = 524
            self.y -= step
            if self.y <= -4:
                self.y = -4
                self._scuttle_pause = random.uniform(0.5, 1.0)
                self._path_idx = 2
        elif self._path_idx == 2:     # top: y=-4, x 524 -> -4
            self.y = -4
            self.x -= step
            if self.x <= -4:
                self.x = -4
                self._scuttle_pause = random.uniform(0.5, 1.0)
                self._path_idx = 3
        elif self._path_idx == 3:     # left: x=-4, y -4 -> 360
            self.x = -4
            self.y += step
            if self.y >= 360:
                self.y = 360
                if self._exit_requested:
                    self.state = "exiting"
                else:
                    self._scuttle_pause = random.uniform(0.5, 1.0)
                    self._path_idx = 0

    def _update_dolphin_arc(self, dt):
        """Dolphin swims back and forth in an arc, jumping over mermaid."""
        # Swim phase: one full back-and-forth every ~6 seconds
        self._swim_phase = getattr(self, '_swim_phase', 0.0) + dt * 1.0

        # Horizontal: sine wave across upper screen (kept within clamp bounds)
        center_x = 320
        amp_x = 180  # x ranges 140-500, well inside 0-520 clamp
        self.x = center_x + math.sin(self._swim_phase) * amp_x

        # Vertical arc: smooth equivalent of abs(sin) — no cusp
        arc_h = 50 * (1 - math.cos(2 * self._swim_phase)) / 2
        # Jump boost: smooth 0->1->0 pulse — no hard on/off
        jump = 40 * (math.sin(self._swim_phase * 3) + 1) / 2
        self.y = self.enter_y - arc_h - jump + math.sin(self._swim_phase * 2) * 4

        # Gentle bob
        self.y += math.sin(self.timer * 2.5) * 3

    def _update_octopus_wiggle(self, dt):
        """Octopus wiggles tentacles while bobbing in place."""
        # Fast horizontal wiggle (tentacles waving)
        wiggle = math.sin(self.timer * 8) * 3
        self.x += wiggle * dt * 2
        # Gentle vertical bob
        self.y += math.sin(self.timer * 2.5) * 0.5
        # Slow drift
        self.x += math.sin(self.timer * 0.7) * 0.15

    def update(self, dt):
        """Update friend position and state. Returns True if visit ended."""
        if self.state == "offscreen":
            return False

        if self.state == "entering":
            dx = self.target_x - self.x
            if abs(dx) < 2:
                self.x = self.target_x
                self.state = "idle"
                self.timer = 0.0
            else:
                step = min(abs(self.speed * dt), abs(dx))
                self.x += math.copysign(step, dx)

        elif self.state == "idle":
            self.timer += dt

            if self.movement == "crab_explore":
                self._update_crab_explore(dt)
            elif self.movement == "dolphin_arc":
                self._update_dolphin_arc(dt)
            elif self.movement == "octopus_wiggle":
                self._update_octopus_wiggle(dt)
            else:
                # Default pass-through: gentle bob
                self.y += math.sin(self.timer * 2) * 0.3

            if self.timer >= self.visit_duration:
                if self.movement == "crab_explore":
                    self._exit_requested = True
                else:
                    self.state = "exiting"

        elif self.state == "exiting":
            if self.movement == "crab_explore":
                # Exit along the bottom edge, legs flush, sliding off to the left
                self.y = 360
                self.x -= self.speed * dt
                if self.x <= -150:
                    self.state = "offscreen"
                    return True
            else:
                exit_x = -150 if self.enter_side == "left" else 790
                dx = exit_x - self.x
                if abs(dx) < 2:
                    self.state = "offscreen"
                    return True
                step = min(abs(self.speed * dt), abs(dx))
                self.x += math.copysign(step, dx)

        # Keep friend on screen during idle (crab manages its own perimeter bounds)
        if self.state == "idle" and self.movement != "crab_explore":
            self.x, self.y = self._clamp_to_screen(self.x, self.y)

        return False

    def is_present(self):
        return self.state in ("entering", "idle", "exiting")

    def get_raw_path(self):
        if self.name == "crab" and self.movement == "crab_explore" and self.state in ("idle", "entering"):
            # Oriented sprites: legs always touch the perimeter edge.
            # Sprites are generated from a bottom-aligned base image, so each
            # rotation places feet flush to the named edge.
            orient = ["bottom", "right", "top", "left"]
            idx = self._path_idx % len(orient)
            return f"friend_crab_{orient[idx]}.raw"
        return f"friend_{self.name}.raw"


class FriendManager:
    """Manages all friend companions."""

    def __init__(self, state):
        self.state = state
        self.friends = {}
        self.active_friend = None
        self.spawn_timer = 0.0
        self.next_spawn = random.uniform(5, 15)

    def update(self, dt):
        """Update active friend and handle spawning."""
        # Update current friend
        if self.active_friend:
            ended = self.active_friend.update(dt)
            if ended:
                self.active_friend = None
                self.spawn_timer = 0.0
                self.next_spawn = random.uniform(5, 15)
            else:
                # Apply health boost while present
                if self.active_friend.state == "idle":
                    hp = self.active_friend.health_per_minute * dt / 60
                    self.state.health = min(100, self.state.health + hp)

        # Try to spawn a new friend
        elif self.state.unlocked_friends:
            self.spawn_timer += dt
            if self.spawn_timer >= self.next_spawn:
                self._try_spawn()

    def _try_spawn(self):
        """Attempt to spawn a random unlocked friend."""
        candidates = [n for n in self.state.unlocked_friends if n in Friend.FRIEND_CONFIG]
        if not candidates:
            return
        name = random.choice(candidates)
        self.active_friend = Friend(name)
        self.active_friend.start_visit()
        # Apply immediate happiness bonus
        self.state.happiness = min(100, self.state.happiness + self.active_friend.happiness_bonus)

    def draw(self, fb, blit_func):
        """Draw active friend using the provided blit function."""
        if self.active_friend and self.active_friend.is_present():
            import os
            raw_path = os.path.join(os.environ.get("PET_ASSET_DIR", "/opt/cyberdeck-pet/fb_assets"), self.active_friend.get_raw_path())
            blit_func(raw_path, int(self.active_friend.x), int(self.active_friend.y))
