#!/usr/bin/env python3
"""Animation and particle systems for framebuffer pet."""
import math
import random
import time
from PIL import Image, ImageDraw


class FloatAnimation:
    """Gentle bobbing motion for the mermaid."""

    def __init__(self, amplitude=8, speed=1.2):
        self.amplitude = amplitude
        self.speed = speed
        self.phase = random.uniform(0, math.pi * 2)

    def offset(self, t):
        return int(math.sin(t * self.speed + self.phase) * self.amplitude)


class BubbleParticle:
    """Rising bubble with wobble."""

    def __init__(self, screen_w, screen_h):
        self.x = random.randint(0, screen_w)
        self.y = screen_h + random.randint(10, 50)
        self.r = random.randint(2, 6)
        self.speed = random.uniform(0.8, 2.5)
        self.wobble_phase = random.uniform(0, math.pi * 2)
        self.wobble_freq = random.uniform(1.5, 3.0)
        self.wobble_amp = random.uniform(0.5, 2.0)
        self.pop_y = random.randint(-20, screen_h // 3)

    def update(self, dt):
        self.y -= self.speed
        self.x += math.sin(time.time() * self.wobble_freq + self.wobble_phase) * self.wobble_amp * dt * 60

    def alive(self):
        return self.y > self.pop_y

    def draw(self, draw_ctx):
        draw_ctx.ellipse(
            [(self.x - self.r, self.y - self.r), (self.x + self.r, self.y + self.r)],
            outline=(200, 230, 255, 150), width=1
        )
        # Highlight
        draw_ctx.ellipse(
            [(self.x - self.r // 2, self.y - self.r // 2), (self.x, self.y)],
            fill=(255, 255, 255, 80)
        )


class SparkleParticle:
    """Twinkling star sparkle."""

    def __init__(self, screen_w, screen_h):
        self.x = random.randint(0, screen_w)
        self.y = random.randint(0, screen_h)
        self.size = random.randint(2, 5)
        self.phase = random.uniform(0, math.pi * 2)
        self.freq = random.uniform(2.0, 5.0)
        self.life = random.uniform(2.0, 5.0)
        self.age = 0.0

    def update(self, dt):
        self.age += dt
        self.y -= dt * 5  # drift up slowly

    def alive(self):
        return self.age < self.life

    def alpha(self):
        t = self.age / self.life
        # Fade in then out, with twinkle
        base = math.sin(self.age * self.freq + self.phase) * 0.5 + 0.5
        fade = 1.0 if t < 0.2 else (1.0 - t) if t > 0.5 else 1.0
        return int(255 * base * fade)

    def draw(self, draw_ctx):
        a = self.alpha()
        if a < 10:
            return
        s = self.size
        cx, cy = self.x, self.y
        # 4-point star
        draw_ctx.polygon([
            (cx, cy - s), (cx + s * 0.3, cy - s * 0.3),
            (cx + s, cy), (cx + s * 0.3, cy + s * 0.3),
            (cx, cy + s), (cx - s * 0.3, cy + s * 0.3),
            (cx - s, cy), (cx - s * 0.3, cy - s * 0.3)
        ], fill=(255, 255, 200, a))
        draw_ctx.polygon([
            (cx, cy - s * 0.5), (cx + s * 0.2, cy),
            (cx, cy + s * 0.5), (cx - s * 0.2, cy)
        ], fill=(255, 255, 255, a))


class ZzzParticle:
    """Sleeping Z's that float up and fade."""

    def __init__(self, x, y):
        self.x = x + random.randint(-10, 10)
        self.y = y
        self.size = random.randint(12, 20)
        self.speed = random.uniform(10, 20)
        self.drift = random.uniform(-5, 5)
        self.age = 0.0
        self.life = random.uniform(1.5, 2.5)

    def update(self, dt):
        self.age += dt
        self.y -= self.speed * dt
        self.x += self.drift * dt

    def alive(self):
        return self.age < self.life

    def draw(self, draw_ctx):
        t = self.age / self.life
        a = int(255 * (1.0 - t))
        if a < 10:
            return
        # Draw "Z" as lines (simplified)
        s = self.size
        x, y = self.x, self.y
        draw_ctx.line([(x - s // 2, y - s // 2), (x + s // 2, y - s // 2)], fill=(200, 200, 255, a), width=2)
        draw_ctx.line([(x + s // 2, y - s // 2), (x - s // 2, y + s // 2)], fill=(200, 200, 255, a), width=2)
        draw_ctx.line([(x - s // 2, y + s // 2), (x + s // 2, y + s // 2)], fill=(200, 200, 255, a), width=2)


class HeartParticle:
    """Floating hearts for happy/excited states."""

    def __init__(self, x, y):
        self.x = x + random.randint(-15, 15)
        self.y = y
        self.size = random.randint(6, 12)
        self.speed = random.uniform(15, 30)
        self.wobble = random.uniform(0, math.pi * 2)
        self.age = 0.0
        self.life = random.uniform(1.0, 2.0)

    def update(self, dt):
        self.age += dt
        self.y -= self.speed * dt
        self.x += math.sin(self.age * 3 + self.wobble) * 0.5

    def alive(self):
        return self.age < self.life

    def draw(self, draw_ctx):
        t = self.age / self.life
        a = int(255 * (1.0 - t * t))
        if a < 10:
            return
        s = self.size
        x, y = self.x, self.y
        # Simple heart shape using two circles and triangle
        r = s // 2
        draw_ctx.ellipse([(x - r, y - r), (x, y)], fill=(255, 100, 150, a))
        draw_ctx.ellipse([(x, y - r), (x + r, y)], fill=(255, 100, 150, a))
        draw_ctx.polygon([(x - r, y), (x + r, y), (x, y + r * 1.5)], fill=(255, 100, 150, a))


class StinkParticle:
    """Stink lines for dirty/sick state."""

    def __init__(self, x, y):
        self.x = x + random.randint(-10, 10)
        self.y = y
        self.speed = random.uniform(5, 15)
        self.age = 0.0
        self.life = random.uniform(0.8, 1.5)

    def update(self, dt):
        self.age += dt
        self.y -= self.speed * dt

    def alive(self):
        return self.age < self.life

    def draw(self, draw_ctx):
        t = self.age / self.life
        a = int(200 * (1.0 - t))
        if a < 10:
            return
        x, y = self.x, self.y
        # Wavy stink line
        for i in range(3):
            px = x + math.sin((y + i * 5) * 0.2) * 5
            draw_ctx.ellipse([(px - 2, y + i * 8 - 2), (px + 2, y + i * 8 + 2)], fill=(100, 200, 80, a))


class ParticleSystem:
    """Manages all active particles."""

    def __init__(self, screen_w, screen_h):
        self.sw = screen_w
        self.sh = screen_h
        self.particles = []
        self.bubble_timer = 0.0
        self.sparkle_timer = 0.0

    def spawn_bubbles(self, count=1):
        for _ in range(count):
            self.particles.append(BubbleParticle(self.sw, self.sh))

    def spawn_sparkles(self, count=1):
        for _ in range(count):
            self.particles.append(SparkleParticle(self.sw, self.sh))

    def spawn_zzz(self, x, y, count=1):
        for _ in range(count):
            self.particles.append(ZzzParticle(x, y))

    def spawn_hearts(self, x, y, count=1):
        for _ in range(count):
            self.particles.append(HeartParticle(x, y))

    def spawn_stink(self, x, y, count=1):
        for _ in range(count):
            self.particles.append(StinkParticle(x, y))

    def update(self, dt, state="neutral"):
        # Auto-spawn ambient particles based on state
        self.bubble_timer += dt
        self.sparkle_timer += dt

        if state in ("underwater", "ocean") and self.bubble_timer > 0.3:
            self.spawn_bubbles(random.randint(0, 2))
            self.bubble_timer = 0

        if state in ("happy", "excited") and self.sparkle_timer > 0.2:
            self.spawn_sparkles(random.randint(0, 1))
            self.sparkle_timer = 0

        # Update all particles
        for p in self.particles:
            p.update(dt)
        self.particles = [p for p in self.particles if p.alive()]

    def draw(self, draw_ctx):
        for p in self.particles:
            p.draw(draw_ctx)

    def clear(self):
        self.particles = []
