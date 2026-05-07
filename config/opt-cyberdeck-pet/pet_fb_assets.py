#!/usr/bin/env python3
"""Asset generation for cyberdeck framebuffer pet.

Generates backgrounds, expression overlays, food icons, and outfit variations.
All assets are RGBA PNGs sized for the 640x480 cyberdeck display.
"""
import os
import sys
import math
import random
import colorsys
from PIL import Image, ImageDraw

ASSET_DIR = os.path.join(os.path.dirname(__file__), "fb_assets")
MERMAID_GIF = "/home/<YOUR_USER>/Pictures/mermaid.gif  # replace with your mermaid GIF path"

# ── Helpers ───────────────────────────────────────────────────────────

def ensure_dir():
    os.makedirs(ASSET_DIR, exist_ok=True)

def _gradient(img, color_top, color_bot):
    draw = ImageDraw.Draw(img)
    w, h = img.size
    for y in range(h):
        t = y / h
        r = int(color_top[0] * (1 - t) + color_bot[0] * t)
        g = int(color_top[1] * (1 - t) + color_bot[1] * t)
        b = int(color_top[2] * (1 - t) + color_bot[2] * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b, 255))

def _pixel_dither_line(d, y, x1, x2, color, density=0.3):
    """Draw a dithered horizontal line for pixel-art texture."""
    for x in range(x1, x2):
        if random.random() < density:
            d.point((x, y), fill=color)

def _draw_pixel_circle(d, cx, cy, r, color):
    """Draw a rough pixel-art circle."""
    for y in range(cy - r, cy + r + 1):
        for x in range(cx - r, cx + r + 1):
            dx, dy = x - cx, y - cy
            dist = math.sqrt(dx * dx + dy * dy)
            if dist <= r:
                if dist > r - 1.5 or random.random() > 0.85:
                    if random.random() > 0.1:
                        d.point((x, y), fill=color)

def _draw_cute_fish(d, cx, cy, size, body_color, eye_color=(0, 0, 0)):
    """Draw a cute round fish with big eyes."""
    # Body
    d.ellipse([(cx - size, cy - size // 2), (cx + size, cy + size // 2)], fill=body_color)
    # Tail
    d.polygon([(cx + size, cy), (cx + size + size // 2, cy - size // 2), (cx + size + size // 2, cy + size // 2)], fill=body_color)
    # Fins
    d.polygon([(cx, cy - size // 2), (cx - size // 3, cy - size), (cx + size // 3, cy - size // 2)], fill=body_color)
    d.polygon([(cx, cy + size // 2), (cx - size // 3, cy + size), (cx + size // 3, cy + size // 2)], fill=body_color)
    # Big eye
    d.ellipse([(cx - size // 3, cy - size // 3), (cx + 1, cy + 1)], fill=(255, 255, 255))
    d.ellipse([(cx - size // 4, cy - size // 4), (cx - 1, cy - 1)], fill=eye_color)
    # Small smile
    d.arc([(cx - size // 3, cy), (cx + size // 4, cy + size // 3)], start=200, end=340, fill=(200, 80, 100), width=1)

def _draw_coral_cluster(d, cx, cy, w, h, colors):
    """Draw a detailed coral cluster like the reference images."""
    # Main coral branches - round bubbly shapes
    for i in range(random.randint(4, 7)):
        bx = cx + random.randint(-w // 2, w // 2)
        by = cy - random.randint(h // 4, h)
        br = random.randint(6, 14)
        color = random.choice(colors)
        d.ellipse([(bx - br, by - br), (bx + br, by + br)], fill=color)
        # Highlight
        d.ellipse([(bx - br // 2, by - br // 2), (bx + br // 3, by + br // 3)], fill=tuple(min(255, c + 30) for c in color))
    # Base rocks
    d.ellipse([(cx - w // 2, cy - 10), (cx + w // 2, cy + 10)], fill=(120, 100, 90))

def _draw_seaweed_cluster(d, x, base_y, height, color, n=3):
    for i in range(n):
        sx = x + i * 8 - (n * 4)
        for y in range(base_y - height, base_y):
            wobble = int(math.sin((y - (base_y - height)) * 0.15 + i) * 6)
            yy = y + random.randint(-1, 1)
            d.ellipse([(sx + wobble - 3, yy), (sx + wobble + 3, yy + 4)], fill=color)

def _draw_light_rays(d, screen_w, screen_h, n_rays=5, alpha=20):
    rays = Image.new("RGBA", (screen_w, screen_h), (0, 0, 0, 0))
    dr = ImageDraw.Draw(rays)
    for i in range(n_rays):
        x = screen_w // (n_rays + 1) * (i + 1) + random.randint(-30, 30)
        top_w = random.randint(20, 50)
        bot_w = top_w + random.randint(60, 120)
        dr.polygon([
            (x - top_w // 2, 0), (x + top_w // 2, 0),
            (x + bot_w // 2, screen_h), (x - bot_w // 2, screen_h)
        ], fill=(255, 255, 220, alpha))
    return rays

def _draw_cloud(d, cx, cy, w, h):
    """Draw a fluffy pixel-art cloud."""
    d.ellipse([(cx - w, cy - h), (cx + w, cy + h)], fill=(255, 255, 255, 230))
    d.ellipse([(cx - w * 0.6, cy - h * 1.3), (cx + w * 0.6, cy + h * 0.7)], fill=(255, 255, 255, 250))
    d.ellipse([(cx - w * 0.3, cy - h * 0.8), (cx + w * 0.8, cy + h * 0.5)], fill=(255, 255, 255, 240))

# ── Mermaid ───────────────────────────────────────────────────────────

def load_mermaid_base():
    img = Image.open(MERMAID_GIF)
    img.seek(0)
    return img.convert("RGBA")

def load_mermaid_frame(frame_idx):
    img = Image.open(MERMAID_GIF)
    img.seek(frame_idx)
    return img.convert("RGBA")

def generate_mermaid_frames():
    """Extract and resize mermaid animation frames from GIF."""
    ensure_dir()
    target_h = 264
    for i in range(6):
        img = load_mermaid_frame(i)
        # Resize maintaining aspect ratio, target height 264
        w, h = img.size
        ratio = target_h / h
        new_w = int(w * ratio)
        img = img.resize((new_w, target_h), Image.LANCZOS)
        # Center crop/pad to 158 width
        if new_w > 158:
            left = (new_w - 158) // 2
            img = img.crop((left, 0, left + 158, target_h))
        elif new_w < 158:
            new_img = Image.new("RGBA", (158, target_h), (0, 0, 0, 0))
            left = (158 - new_w) // 2
            new_img.paste(img, (left, 0))
            img = new_img
        img.save(os.path.join(ASSET_DIR, f"mermaid_frame_{i:02d}.png"))
    print("Generated mermaid frames:", [f"mermaid_frame_{i:02d}.png" for i in range(6)])

# ── Expression Overlays (full-face redrawn) ───────────────────────────

def generate_expression_overlays():
    """Generate full-size expression overlays that completely cover/redraw the face."""
    ensure_dir()
    W, H = 158, 264

    # Face landmarks on the 158x264 sprite
    LEYE = (58, 72)
    REYE = (98, 72)
    MOUTH = (78, 95)
    LCHEEK = (48, 88)
    RCHEEK = (108, 88)
    FOREHEAD = (78, 52)

    def _eye_white(d, cx, cy, w, h):
        d.ellipse([(cx - w, cy - h), (cx + w, cy + h)], fill=(255, 255, 255, 240))

    def _pupil(d, cx, cy, r, color=(60, 40, 30)):
        d.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=(*color, 250))
        d.ellipse([(cx - r // 3, cy - r // 3), (cx + r // 3, cy + r // 3)], fill=(255, 255, 255, 220))

    # ── HAPPY: closed happy eyes, big smile, blush ──
    happy = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(happy)
    for cx, cy in [LEYE, REYE]:
        # Closed happy eye (upward curve)
        d.arc([(cx - 10, cy - 6), (cx + 10, cy + 8)], start=200, end=340, fill=(80, 50, 50, 240), width=3)
        # Eyelash
        d.line([(cx - 8, cy - 3), (cx - 12, cy - 8)], fill=(80, 50, 50, 200), width=2)
        d.line([(cx + 8, cy - 3), (cx + 12, cy - 8)], fill=(80, 50, 50, 200), width=2)
    # Big smile (open mouth)
    d.pieslice([(MOUTH[0] - 12, MOUTH[1] - 4), (MOUTH[0] + 12, MOUTH[1] + 14)], start=0, end=180, fill=(200, 80, 100, 230))
    d.arc([(MOUTH[0] - 12, MOUTH[1] - 4), (MOUTH[0] + 12, MOUTH[1] + 14)], start=0, end=180, fill=(160, 60, 80, 250), width=2)
    # Blush
    d.ellipse([LCHEEK[0] - 10, LCHEEK[1] - 6, LCHEEK[0] + 10, LCHEEK[1] + 6], fill=(255, 150, 170, 120))
    d.ellipse([RCHEEK[0] - 10, RCHEEK[1] - 6, RCHEEK[0] + 10, RCHEEK[1] + 6], fill=(255, 150, 170, 120))
    happy.save(os.path.join(ASSET_DIR, "overlay_happy.png"))

    # ── SAD: big teary eyes, downturned mouth, tears ──
    sad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(sad)
    for cx, cy in [LEYE, REYE]:
        _eye_white(d, cx, cy, 10, 8)
        _pupil(d, cx, cy + 2, 5, (80, 100, 140))
        # Eyebrow (sad arc)
        d.arc([(cx - 10, cy - 14), (cx + 10, cy - 2)], start=20, end=160, fill=(100, 70, 70, 220), width=2)
    # Tears
    for cx, cy in [LEYE, REYE]:
        for i in range(3):
            ty = cy + 10 + i * 10
            d.ellipse([(cx - 4, ty), (cx + 4, ty + 8)], fill=(150, 200, 255, 180 - i * 40))
    # Downturned mouth
    d.arc([(MOUTH[0] - 10, MOUTH[1] - 2), (MOUTH[0] + 10, MOUTH[1] + 10)], start=180, end=360, fill=(150, 80, 100, 230), width=3)
    sad.save(os.path.join(ASSET_DIR, "overlay_sad.png"))

    # ── EXCITED: wide star eyes, open mouth, sparkles ──
    excited = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(excited)
    for cx, cy in [LEYE, REYE]:
        # Big wide eye
        _eye_white(d, cx, cy, 11, 10)
        _pupil(d, cx, cy, 6, (80, 60, 40))
        # Star sparkle in eye
        star_pts = [(cx, cy - 7), (cx + 3, cy - 2), (cx + 7, cy), (cx + 3, cy + 2), (cx, cy + 7), (cx - 3, cy + 2), (cx - 7, cy), (cx - 3, cy - 2)]
        d.polygon(star_pts, fill=(255, 220, 50, 200))
    # Open mouth (oval)
    d.ellipse([(MOUTH[0] - 10, MOUTH[1] - 2), (MOUTH[0] + 10, MOUTH[1] + 14)], fill=(180, 100, 120, 230))
    # Tongue
    d.ellipse([(MOUTH[0] - 5, MOUTH[1] + 6), (MOUTH[0] + 5, MOUTH[1] + 13)], fill=(255, 150, 170, 200))
    # Blush
    d.ellipse([LCHEEK[0] - 8, LCHEEK[1] - 5, LCHEEK[0] + 8, LCHEEK[1] + 5], fill=(255, 150, 170, 100))
    d.ellipse([RCHEEK[0] - 8, RCHEEK[1] - 5, RCHEEK[0] + 8, RCHEEK[1] + 5], fill=(255, 150, 170, 100))
    excited.save(os.path.join(ASSET_DIR, "overlay_excited.png"))

    # ── SICK: droopy half-closed eyes, green tint, sweat, pale mouth ──
    sick = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(sick)
    # Greenish face tint
    d.ellipse([(LEYE[0] - 30, LEYE[1] - 20), (REYE[0] + 30, MOUTH[1] + 20)], fill=(150, 220, 150, 50))
    for cx, cy in [LEYE, REYE]:
        # Half-closed droopy eye (horizontal line)
        d.line([(cx - 9, cy + 2), (cx + 9, cy + 2)], fill=(80, 70, 70, 220), width=3)
        # Bag under eye
        d.arc([(cx - 8, cy + 2), (cx + 8, cy + 8)], start=0, end=180, fill=(120, 100, 100, 180), width=2)
    # Pale mouth
    d.line([(MOUTH[0] - 8, MOUTH[1]), (MOUTH[0] + 8, MOUTH[1])], fill=(180, 140, 140, 200), width=2)
    # Sweat drop on forehead
    d.polygon([(FOREHEAD[0] + 15, FOREHEAD[1] - 5), (FOREHEAD[0] + 20, FOREHEAD[1] + 8), (FOREHEAD[0] + 10, FOREHEAD[1] + 8)], fill=(180, 220, 255, 200))
    d.ellipse([(FOREHEAD[0] + 12, FOREHEAD[1] - 10), (FOREHEAD[0] + 18, FOREHEAD[1] - 2)], fill=(180, 220, 255, 200))
    sick.save(os.path.join(ASSET_DIR, "overlay_sick.png"))

    # ── HUNGRY: big swirly eyes, drool, slight blush ──
    hungry = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(hungry)
    for cx, cy in [LEYE, REYE]:
        _eye_white(d, cx, cy, 11, 10)
        # Swirly pupil (concentric circles)
        for r in range(7, 1, -1):
            color = (100, 100, 100, 200) if r % 2 == 0 else (255, 255, 255, 200)
            d.ellipse([(cx - r, cy - r), (cx + r, cy + r)], outline=color, width=1)
        d.ellipse([(cx - 2, cy - 2), (cx + 2, cy + 2)], fill=(60, 40, 30, 250))
    # Slightly open mouth
    d.ellipse([(MOUTH[0] - 6, MOUTH[1] - 2), (MOUTH[0] + 6, MOUTH[1] + 6)], fill=(200, 120, 140, 220))
    # Drool
    d.line([(MOUTH[0] + 5, MOUTH[1] + 4), (MOUTH[0] + 8, MOUTH[1] + 18)], fill=(180, 210, 255, 180), width=2)
    d.ellipse([(MOUTH[0] + 5, MOUTH[1] + 16), (MOUTH[0] + 11, MOUTH[1] + 22)], fill=(180, 210, 255, 150))
    hungry.save(os.path.join(ASSET_DIR, "overlay_hungry.png"))

    # ── CRANKY: angry slanted eyebrows, frown, red anger mark ──
    cranky = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(cranky)
    for cx, cy in [LEYE, REYE]:
        _eye_white(d, cx, cy, 9, 7)
        _pupil(d, cx, cy, 4, (120, 40, 40))
    # Angry slanted eyebrows
    d.line([(LEYE[0] - 12, LEYE[1] - 12), (LEYE[0] + 8, LEYE[1] - 6)], fill=(80, 50, 50, 240), width=3)
    d.line([(REYE[0] - 8, REYE[1] - 6), (REYE[0] + 12, REYE[1] - 12)], fill=(80, 50, 50, 240), width=3)
    # Frown
    d.arc([(MOUTH[0] - 10, MOUTH[1] - 2), (MOUTH[0] + 10, MOUTH[1] + 10)], start=180, end=360, fill=(150, 60, 80, 240), width=3)
    # Red anger mark on forehead
    ax, ay = FOREHEAD[0] + 18, FOREHEAD[1] - 5
    d.polygon([(ax, ay - 8), (ax + 4, ay), (ax + 2, ay + 2), (ax + 6, ay + 10), (ax, ay + 4), (ax - 4, ay + 10), (ax - 2, ay + 2), (ax - 6, ay)], fill=(255, 80, 80, 220))
    cranky.save(os.path.join(ASSET_DIR, "overlay_cranky.png"))

    print("Generated expression overlays:", sorted([f for f in os.listdir(ASSET_DIR) if f.startswith("overlay_")]))

# ── Backgrounds (matching reference pixel-art style) ──────────────────

def generate_backgrounds(screen_w=640, screen_h=480):
    """Generate detailed pixel-art backgrounds matching reference images."""
    ensure_dir()

    # ── 1. PASTEL CORAL REEF (like images1.jpg) ──
    bg = Image.new("RGBA", (screen_w, screen_h))
    # Sky-like top
    _gradient(bg, (180, 220, 255), (140, 200, 250))
    d = ImageDraw.Draw(bg)
    # White clouds at top
    random.seed(1)
    for _ in range(8):
        cx = random.randint(0, screen_w)
        cy = random.randint(10, 60)
        _draw_cloud(d, cx, cy, random.randint(30, 60), random.randint(12, 22))
    # Light rays
    rays = _draw_light_rays(d, screen_w, screen_h, n_rays=6, alpha=18)
    bg.alpha_composite(rays)
    # Sandy bottom
    for y in range(screen_h - 70, screen_h):
        t = (y - (screen_h - 70)) / 70
        shade = int(245 - t * 25)
        d.line([(0, y), (screen_w, y)], fill=(shade, shade - 15, shade - 35, 255))
        # Sand texture dots
        for _ in range(3):
            dx = random.randint(0, screen_w)
            d.point((dx, y), fill=(shade + 10, shade - 5, shade - 20, 150))
    # Dense coral clusters on left and right (like reference)
    random.seed(42)
    coral_colors = [
        [(255, 160, 180), (255, 200, 210), (255, 130, 160)],  # pinks
        [(180, 160, 255), (210, 200, 255), (160, 140, 240)],  # purples
        [(150, 210, 255), (180, 230, 255), (130, 190, 240)],  # blues
        [(255, 200, 150), (255, 220, 180), (255, 180, 120)],  # peaches
    ]
    for side in [0, 1]:
        base_x = 60 if side == 0 else screen_w - 60
        for _ in range(5):
            cx = base_x + random.randint(-50, 50)
            cy = screen_h - random.randint(20, 60)
            colors = random.choice(coral_colors)
            _draw_coral_cluster(d, cx, cy, random.randint(30, 60), random.randint(50, 90), colors)
    # Small cute fish
    fish_colors = [(255, 180, 80), (255, 120, 120), (120, 200, 255), (255, 160, 200), (180, 255, 180)]
    for i in range(10):
        fx = random.randint(80, screen_w - 80)
        fy = random.randint(100, screen_h - 100)
        fc = (*fish_colors[i % len(fish_colors)], 220)
        _draw_cute_fish(d, fx, fy, random.randint(6, 10), fc)
    # Bubbles
    for _ in range(25):
        x, y, r = random.randint(0, screen_w), random.randint(20, screen_h - 80), random.randint(2, 5)
        d.ellipse([(x - r, y - r), (x + r, y + r)], outline=(255, 255, 255, 100), width=1)
        d.ellipse([(x - r + 1, y - r + 1), (x - r + 2, y - r + 2)], fill=(255, 255, 255, 150))
    bg.save(os.path.join(ASSET_DIR, "bg_coral.png"))

    # ── 2. TROPICAL BEACH ──
    bg = Image.new("RGBA", (screen_w, screen_h))
    _gradient(bg, (160, 230, 255), (255, 250, 210))
    d = ImageDraw.Draw(bg)
    # Big bright sun
    d.ellipse([(screen_w - 150, 5), (screen_w - 20, 135)], fill=(255, 245, 150, 230))
    d.ellipse([(screen_w - 130, 25), (screen_w - 40, 115)], fill=(255, 255, 200, 200))
    # Ocean with waves
    for y in range(screen_h // 2 + 20, screen_h - 60):
        t = (y - (screen_h // 2 + 20)) / (screen_h // 2 - 80)
        r = int(20 + t * 30)
        g = int(180 + t * 50)
        b = int(220 + t * 30)
        # Wave texture
        wave = int(math.sin(y * 0.08) * 3)
        for x in range(0, screen_w, 2):
            d.point((x + wave, y), fill=(r, g, b, 255))
            d.point((x + 1 + wave, y), fill=(r + 10, g + 5, b, 255))
    # Sand beach
    for y in range(screen_h - 60, screen_h):
        t = (y - (screen_h - 60)) / 60
        shade = int(250 - t * 20)
        d.line([(0, y), (screen_w, y)], fill=(shade, shade - 8, shade - 25, 255))
    # Palm tree
    trunk_x = 90
    for y in range(screen_h - 230, screen_h - 70):
        w = max(2, 9 - int((y - (screen_h - 230)) * 0.035))
        d.line([(trunk_x - w, y), (trunk_x + w, y)], fill=(130, 90, 55, 255))
    for angle in range(0, 360, 45):
        rad = math.radians(angle)
        for t in range(12, 65):
            x = trunk_x + int(math.cos(rad) * t)
            y = screen_h - 230 + int(math.sin(rad) * t * 0.22)
            d.ellipse([(x - 5, y - 3), (x + 5, y + 3)], fill=(50, 150, 60, 240))
    # Fish in water
    for i in range(5):
        fx = random.randint(50, screen_w - 50)
        fy = random.randint(screen_h // 2 + 40, screen_h - 90)
        _draw_cute_fish(d, fx, fy, random.randint(7, 11), (255, 190, 80, 230))
    # Shell on sand
    d.ellipse([(420, screen_h - 45), (455, screen_h - 18)], fill=(255, 210, 210, 240))
    d.ellipse([(425, screen_h - 40), (450, screen_h - 22)], fill=(255, 230, 230, 220))
    bg.save(os.path.join(ASSET_DIR, "bg_beach.png"))

    # ── 3. DEEP OCEAN NIGHT (bioluminescent) ──
    bg = Image.new("RGBA", (screen_w, screen_h))
    _gradient(bg, (15, 25, 70), (40, 70, 140))
    d = ImageDraw.Draw(bg)
    # Stars
    random.seed(77)
    for _ in range(70):
        x, y, r = random.randint(0, screen_w), random.randint(0, screen_h // 4), random.randint(1, 2)
        twinkle = random.randint(150, 255)
        d.ellipse([(x - r, y - r), (x + r, y + r)], fill=(255, 255, 240, twinkle))
    # Moon
    d.ellipse([(screen_w - 100, 15), (screen_w - 25, 90)], fill=(255, 255, 240, 220))
    d.ellipse([(screen_w - 85, 30), (screen_w - 40, 75)], fill=(255, 255, 250, 160))
    # Light rays from surface
    rays = _draw_light_rays(d, screen_w, screen_h, n_rays=4, alpha=12)
    bg.alpha_composite(rays)
    # Silhouetted seaweed (like images3.jpg)
    for x in [40, 120, 500, 580]:
        h = random.randint(80, 160)
        for y in range(screen_h - 40 - h, screen_h - 30):
            wobble = int(math.sin((y - (screen_h - 40 - h)) * 0.08) * 10)
            d.ellipse([(x + wobble - 4, y), (x + wobble + 4, y + 5)], fill=(20, 50, 80, 200))
    # Sand dunes at bottom
    for x in range(screen_w):
        dune_y = screen_h - 50 + int(math.sin(x * 0.02) * 15) + int(math.sin(x * 0.05) * 8)
        for y in range(dune_y, screen_h):
            t = (y - dune_y) / (screen_h - dune_y)
            shade = int(30 + t * 20)
            d.point((x, y), fill=(shade, shade + 10, shade + 30, 255))
    # Bioluminescent jellyfish
    jelly_colors = [(150, 255, 200), (200, 150, 255), (150, 200, 255), (255, 200, 150)]
    for i in range(5):
        jx = 80 + i * 130
        jy = 120 + (i % 2) * 80
        jc = (*jelly_colors[i % len(jelly_colors)], 160)
        # Bell
        d.pieslice([(jx - 18, jy - 18), (jx + 18, jy + 18)], 0, 180, fill=jc)
        d.arc([(jx - 18, jy - 18), (jx + 18, jy + 18)], 0, 180, fill=(255, 255, 255, 80), width=2)
        # Tentacles
        for tx in range(jx - 14, jx + 14, 7):
            for ty in range(jy, jy + 25, 3):
                wobble = int(math.sin(ty * 0.4 + tx) * 3)
                d.ellipse([(tx + wobble - 1, ty), (tx + wobble + 1, ty + 3)], fill=jc)
    # Glowing plankton
    for _ in range(50):
        x, y = random.randint(0, screen_w), random.randint(screen_h // 3, screen_h)
        d.ellipse([(x - 1, y - 1), (x + 1, y + 1)], fill=(150, 255, 200, random.randint(60, 160)))
    bg.save(os.path.join(ASSET_DIR, "bg_night.png"))

    # ── 4. MERMAID CASTLE ──
    bg = Image.new("RGBA", (screen_w, screen_h))
    _gradient(bg, (200, 230, 255), (160, 200, 250))
    d = ImageDraw.Draw(bg)
    # Light rays
    rays = _draw_light_rays(d, screen_w, screen_h, n_rays=5, alpha=15)
    bg.alpha_composite(rays)
    # Clouds
    for _ in range(5):
        cx = random.randint(0, screen_w)
        cy = random.randint(10, 50)
        _draw_cloud(d, cx, cy, random.randint(25, 45), random.randint(10, 18))
    # Castle towers
    towers = [(160, 220), (320, 170), (480, 220)]
    for tx, ty in towers:
        # Tower body
        d.rectangle([(tx - 28, ty), (tx + 28, screen_h - 45)], fill=(255, 230, 245, 240))
        d.rectangle([(tx - 22, ty), (tx + 22, screen_h - 45)], fill=(255, 240, 250, 220))
        # Tower roof
        d.polygon([(tx - 32, ty), (tx + 32, ty), (tx, ty - 55)], fill=(255, 200, 230, 250))
        # Windows (arched)
        d.pieslice([(tx - 7, ty + 25), (tx + 7, ty + 45)], 0, 180, fill=(180, 230, 255, 200))
        d.pieslice([(tx - 7, ty + 65), (tx + 7, ty + 85)], 0, 180, fill=(180, 230, 255, 200))
    # Castle wall
    d.rectangle([(160, screen_h - 130), (480, screen_h - 45)], fill=(255, 220, 240, 235))
    d.rectangle([(170, screen_h - 120), (470, screen_h - 45)], fill=(255, 230, 245, 220))
    # Pearl gate
    d.ellipse([(300, screen_h - 100), (340, screen_h - 55)], fill=(255, 255, 240, 240))
    d.ellipse([(305, screen_h - 95), (335, screen_h - 60)], fill=(255, 255, 255, 220))
    # Garden coral
    _draw_coral_cluster(d, 70, screen_h - 35, 35, 50, [(255, 160, 190), (255, 200, 210)])
    _draw_coral_cluster(d, 570, screen_h - 40, 40, 55, [(180, 160, 255), (210, 200, 255)])
    # Fish
    for i in range(4):
        fx = random.randint(60, screen_w - 60)
        fy = random.randint(100, screen_h - 160)
        _draw_cute_fish(d, fx, fy, 8, (255, 200, 120, 230))
    bg.save(os.path.join(ASSET_DIR, "bg_castle.png"))

    # ── 5. ATLANTIS RUINS (like images2.jpg) ──
    bg = Image.new("RGBA", (screen_w, screen_h))
    _gradient(bg, (40, 100, 130), (80, 160, 180))
    d = ImageDraw.Draw(bg)
    # Light rays from surface
    rays = _draw_light_rays(d, screen_w, screen_h, n_rays=5, alpha=15)
    bg.alpha_composite(rays)
    # Stone floor/path
    for x in range(screen_w):
        floor_y = screen_h - 80 + int(math.sin(x * 0.015) * 10)
        for y in range(floor_y, screen_h):
            t = (y - floor_y) / (screen_h - floor_y)
            shade = int(140 - t * 30)
            d.point((x, y), fill=(shade, shade + 10, shade + 5, 255))
            # Stone tile pattern
            if (x // 20 + y // 10) % 2 == 0:
                d.point((x, y), fill=(shade - 10, shade, shade - 5, 255))
    # Ruined pillars with vines
    for px in [90, 220, 420, 550]:
        h = random.randint(180, 300)
        # Pillar
        d.rectangle([(px - 18, screen_h - 80 - h), (px + 18, screen_h - 80)], fill=(110, 130, 120, 240))
        d.rectangle([(px - 12, screen_h - 80 - h), (px + 12, screen_h - 80)], fill=(130, 150, 140, 220))
        # Capital (top)
        d.rectangle([(px - 24, screen_h - 80 - h), (px + 24, screen_h - 72 - h)], fill=(100, 120, 110, 240))
        # Broken top detail
        d.polygon([(px - 20, screen_h - 80 - h), (px + 20, screen_h - 80 - h), (px, screen_h - 90 - h)], fill=(90, 110, 100, 240))
        # Vines on pillar
        for vy in range(screen_h - 80 - h + 20, screen_h - 100, 15):
            d.ellipse([(px + 15, vy), (px + 25, vy + 10)], fill=(80, 150, 80, 200))
            d.ellipse([(px - 25, vy + 5), (px - 15, vy + 15)], fill=(80, 150, 80, 200))
    # Glowing crystals
    crystals = [(160, 280), (480, 240), (320, 320)]
    for cx, cy in crystals:
        d.polygon([(cx, cy - 22), (cx + 12, cy), (cx, cy + 22), (cx - 12, cy)], fill=(150, 255, 220, 220))
        d.polygon([(cx, cy - 12), (cx + 6, cy), (cx, cy + 12), (cx - 6, cy)], fill=(200, 255, 240, 240))
        # Glow
        d.ellipse([(cx - 20, cy - 20), (cx + 20, cy + 20)], fill=(150, 255, 220, 40))
    # Coral around ruins
    _draw_coral_cluster(d, 60, screen_h - 50, 30, 40, [(255, 140, 160), (255, 180, 190)])
    _draw_coral_cluster(d, 590, screen_h - 55, 35, 45, [(160, 220, 255), (180, 240, 255)])
    # Fish
    for i in range(5):
        fx = random.randint(80, screen_w - 80)
        fy = random.randint(120, screen_h - 140)
        colors = [(255, 180, 100), (255, 120, 120), (120, 255, 200), (255, 180, 220)]
        _draw_cute_fish(d, fx, fy, random.randint(7, 11), (*colors[i % 4], 230))
    # Bubbles
    for _ in range(15):
        x, y, r = random.randint(0, screen_w), random.randint(50, screen_h - 80), random.randint(2, 4)
        d.ellipse([(x - r, y - r), (x + r, y + r)], outline=(200, 240, 255, 100), width=1)
    bg.save(os.path.join(ASSET_DIR, "bg_atlantis.png"))

    # ── 6. TROPICAL LAGOON ──
    bg = Image.new("RGBA", (screen_w, screen_h))
    _gradient(bg, (120, 240, 220), (70, 200, 180))
    d = ImageDraw.Draw(bg)
    # Waterfall on left
    for y in range(0, screen_h // 2 + 60):
        x = 45 + int(math.sin(y * 0.06) * 6)
        d.line([(0, y), (x, y)], fill=(210, 250, 255, 200))
        if y % 3 == 0:
            d.ellipse([(x - 4, y), (x + 4, y + 3)], fill=(230, 255, 255, 160))
    # Rocks around waterfall
    for ry in range(screen_h // 2 + 30, screen_h):
        d.ellipse([(5, ry - 12), (75, ry + 12)], fill=(90, 100, 90, 240))
    # Floating lily pads / flowers
    for i in range(7):
        fx = random.randint(160, screen_w - 40)
        fy = random.randint(screen_h // 2, screen_h - 40)
        d.ellipse([(fx - 12, fy - 7), (fx + 12, fy + 7)], fill=(255, 190, 210, 220))
        d.ellipse([(fx - 4, fy - 10), (fx + 4, fy - 3)], fill=(255, 160, 190, 240))
    # Colorful fish
    fish_colors = [(255, 130, 130), (255, 210, 110), (130, 255, 190), (255, 170, 230)]
    for i in range(7):
        fx = random.randint(100, screen_w - 50)
        fy = random.randint(80, screen_h - 90)
        fc = (*fish_colors[i % len(fish_colors)], 240)
        _draw_cute_fish(d, fx, fy, random.randint(7, 12), fc)
    # Sparkles
    for _ in range(20):
        x, y = random.randint(0, screen_w), random.randint(0, screen_h)
        d.ellipse([(x - 1, y - 1), (x + 1, y + 1)], fill=(255, 255, 200, random.randint(80, 180)))
    # Light rays
    rays = _draw_light_rays(d, screen_w, screen_h, n_rays=4, alpha=12)
    bg.alpha_composite(rays)
    bg.save(os.path.join(ASSET_DIR, "bg_lagoon.png"))

    print("Generated backgrounds:", sorted([f for f in os.listdir(ASSET_DIR) if f.startswith("bg_")]))

# ── Food Icons (emoji-style cute food) ────────────────────────────────

def generate_food_icons(size=48):
    """Generate emoji-style cute food icons with faces."""
    ensure_dir()

    # Seaweed - cute green curly strips with face
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i in range(3):
        x = 12 + i * 11
        for y in range(6, size - 6):
            wobble = int(math.sin((y - 6) * 0.35 + i) * 3)
            d.ellipse([(x + wobble - 3, y), (x + wobble + 3, y + 2)], fill=(60, 180, 80, 230))
    # Face
    d.ellipse([(18, 16), (22, 20)], fill=(255, 255, 255, 240))
    d.ellipse([(28, 16), (32, 20)], fill=(255, 255, 255, 240))
    d.ellipse([(19, 17), (21, 19)], fill=(40, 40, 40, 255))
    d.ellipse([(29, 17), (31, 19)], fill=(40, 40, 40, 255))
    d.arc([(20, 22), (30, 28)], start=200, end=340, fill=(40, 40, 40, 255), width=2)
    img.save(os.path.join(ASSET_DIR, "food_seaweed.png"))

    # Fish - cute orange fish with big eyes and smile
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([(6, 12), (36, 36)], fill=(255, 150, 50, 240))
    d.polygon([(36, 16), (46, 24), (36, 32)], fill=(255, 150, 50, 240))
    # Fin on top
    d.polygon([(16, 12), (22, 4), (28, 12)], fill=(255, 140, 40, 240))
    # Big eyes
    d.ellipse([(12, 16), (20, 24)], fill=(255, 255, 255, 250))
    d.ellipse([(24, 16), (32, 24)], fill=(255, 255, 255, 250))
    d.ellipse([(14, 18), (18, 22)], fill=(40, 40, 40, 255))
    d.ellipse([(26, 18), (30, 22)], fill=(40, 40, 40, 255))
    # Smile
    d.arc([(16, 24), (28, 32)], start=200, end=340, fill=(180, 60, 80, 255), width=2)
    # Cheeks
    d.ellipse([(10, 26), (14, 30)], fill=(255, 180, 180, 150))
    d.ellipse([(30, 26), (34, 30)], fill=(255, 180, 180, 150))
    img.save(os.path.join(ASSET_DIR, "food_fish.png"))

    # Shrimp - cute pink shrimp
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Body segments
    d.arc([(8, 10), (40, 42)], start=200, end=340, fill=(255, 160, 160, 240), width=7)
    d.arc([(8, 10), (40, 42)], start=200, end=340, fill=(255, 200, 200, 200), width=4)
    # Segment lines
    for angle in [230, 260, 290]:
        rad = math.radians(angle)
        cx = 24 + int(math.cos(rad) * 14)
        cy = 26 + int(math.sin(rad) * 14)
        d.line([(cx - 3, cy - 3), (cx + 3, cy + 3)], fill=(255, 140, 140, 200), width=1)
    # Tail
    d.polygon([(8, 24), (2, 18), (2, 30)], fill=(255, 140, 140, 240))
    # Eye
    d.ellipse([(30, 16), (36, 22)], fill=(255, 255, 255, 250))
    d.ellipse([(32, 18), (34, 20)], fill=(40, 40, 40, 255))
    # Smile
    d.arc([(26, 20), (34, 26)], start=200, end=340, fill=(180, 60, 80, 255), width=1)
    img.save(os.path.join(ASSET_DIR, "food_shrimp.png"))

    # Pearl - shiny pearl with sparkle
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([(8, 8), (40, 40)], fill=(245, 245, 255, 240))
    d.ellipse([(12, 12), (24, 24)], fill=(255, 255, 255, 220))
    d.ellipse([(24, 24), (32, 32)], fill=(220, 220, 240, 120))
    # Sparkle
    d.polygon([(20, 4), (22, 10), (28, 12), (22, 14), (20, 20), (18, 14), (12, 12), (18, 10)], fill=(255, 255, 200, 220))
    img.save(os.path.join(ASSET_DIR, "food_pearl.png"))

    # Cake - cute layered cake with cherry
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Bottom layer
    d.rounded_rectangle([(8, 26), (40, 38)], radius=3, fill=(255, 220, 180, 240))
    # Top layer
    d.rounded_rectangle([(12, 16), (36, 28)], radius=3, fill=(255, 200, 210, 240))
    # Frosting drip
    for fx in range(14, 34, 5):
        d.ellipse([(fx, 26), (fx + 4, 32)], fill=(255, 220, 230, 240))
    # Cherry
    d.ellipse([(20, 6), (28, 14)], fill=(255, 60, 80, 250))
    d.line([(24, 6), (24, 2)], fill=(100, 150, 60, 255), width=2)
    # Sprinkles
    for sx, sy in [(15, 20), (22, 22), (30, 19), (18, 24), (28, 23)]:
        d.ellipse([(sx, sy), (sx + 2, sy + 2)], fill=(random.choice([(255,255,100),(100,255,200),(255,150,255)])),)
    # Face
    d.ellipse([(18, 30), (21, 33)], fill=(255, 255, 255, 240))
    d.ellipse([(27, 30), (30, 33)], fill=(255, 255, 255, 240))
    d.ellipse([(19, 31), (20, 32)], fill=(40, 40, 40, 255))
    d.ellipse([(28, 31), (29, 32)], fill=(40, 40, 40, 255))
    d.arc([(20, 33), (28, 38)], start=200, end=340, fill=(180, 60, 80, 255), width=1)
    img.save(os.path.join(ASSET_DIR, "food_cake.png"))

    # Ice cream - swirled cone with face
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Cone
    d.polygon([(20, 22), (12, 44), (28, 44)], fill=(220, 180, 120, 240))
    d.line([(16, 32), (24, 32)], fill=(200, 160, 100, 200), width=1)
    d.line([(14, 38), (26, 38)], fill=(200, 160, 100, 200), width=1)
    # Scoop 1 (pink)
    d.ellipse([(10, 6), (30, 24)], fill=(255, 200, 220, 240))
    # Scoop 2 (blue)
    d.ellipse([(16, 2), (34, 18)], fill=(200, 240, 255, 240))
    # Face on bottom scoop
    d.ellipse([(16, 14), (19, 17)], fill=(255, 255, 255, 240))
    d.ellipse([(21, 14), (24, 17)], fill=(255, 255, 255, 240))
    d.ellipse([(17, 15), (18, 16)], fill=(40, 40, 40, 255))
    d.ellipse([(22, 15), (23, 16)], fill=(40, 40, 40, 255))
    d.arc([(17, 17), (23, 21)], start=200, end=340, fill=(180, 60, 80, 255), width=1)
    img.save(os.path.join(ASSET_DIR, "food_icecream.png"))

    print("Generated food icons:", sorted([f for f in os.listdir(ASSET_DIR) if f.startswith("food_")]))

# ── Outfit Hue Shifts (skin-safe) ─────────────────────────────────────

def generate_outfits():
    """Generate outfit color variations that preserve skin tone."""
    ensure_dir()
    base = load_mermaid_base()
    w, h = base.size

    def is_skin_pixel(r, g, b):
        """Detect skin-colored pixels using HSV."""
        hr, hg, hb = r / 255.0, g / 255.0, b / 255.0
        hue, sat, val = colorsys.rgb_to_hsv(hr, hg, hb)
        # Skin: yellow-orange hue (15-55°), moderate saturation, high value
        hue_deg = hue * 360
        if 15 <= hue_deg <= 55 and 0.08 <= sat <= 0.55 and val > 0.75:
            return True
        # Also catch very light skin highlights
        if 20 <= hue_deg <= 50 and sat < 0.15 and val > 0.88:
            return True
        return False

    def shift_outfit(img, hue_shift_deg):
        """Shift hue of non-skin pixels."""
        pixels = img.load()
        out = Image.new("RGBA", img.size)
        out_pixels = out.load()
        shift = hue_shift_deg / 360.0
        for y in range(h):
            for x in range(w):
                r, g, b, a = pixels[x, y]
                if a < 10:
                    out_pixels[x, y] = (0, 0, 0, 0)
                    continue
                if is_skin_pixel(r, g, b):
                    out_pixels[x, y] = (r, g, b, a)
                    continue
                # Shift hue
                hr, hg, hb = r / 255.0, g / 255.0, b / 255.0
                hue, sat, val = colorsys.rgb_to_hsv(hr, hg, hb)
                new_hue = (hue + shift) % 1.0
                nr, ng, nb = colorsys.hsv_to_rgb(new_hue, sat, val)
                out_pixels[x, y] = (int(nr * 255), int(ng * 255), int(nb * 255), a)
        return out

    # Target colors: blue (-60° from pink ~330° → ~270°), purple, mint
    # Original pink hair is hue ~330°. To get:
    # Blue: shift to ~210° (cool blue) → shift -120° or +240°
    # Purple: already close to tail at ~290°, shift -40°  
    # Mint/Green: shift to ~140° (green) → shift -190° or +170°
    variations = {
        "outfit_blue": -110,    # pink → blue
        "outfit_purple": -50,   # pink → purple
        "outfit_mint": +130,    # pink → mint/green
    }

    for name, shift_deg in variations.items():
        shifted = shift_outfit(base, shift_deg)
        shifted.save(os.path.join(ASSET_DIR, f"{name}.png"))

    print("Generated outfits:", sorted([f for f in os.listdir(ASSET_DIR) if f.startswith("outfit_")]))

# ── Init ──────────────────────────────────────────────────────────────

def generate_all_assets():
    print("Generating all framebuffer pet assets...")
    generate_mermaid_frames()
    generate_expression_overlays()
    generate_backgrounds()
    generate_food_icons()
    generate_outfits()
    print(f"All assets ready in: {ASSET_DIR}")


if __name__ == "__main__":
    generate_all_assets()
