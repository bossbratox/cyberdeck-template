#!/usr/bin/env python3
"""Procedural sprite builder for mermaid tamagotchi.

Generates large, detailed pixel-grid sprites for 640×480 DSI display.
Target terminal: 106×40 (6×12 font) → 106×80 half-block virtual pixels.
Mermaid fills most of the screen (~70w × 76h pixels).

Usage:
    python3 make_sprites.py           # generate all sprites + PNG previews
    python3 make_sprites.py --preview # also render PNG previews

Palette reference (fbterm slots 0-15):
    0: dark bg       1: pink          2: mint green    3: wheat (skin)
    4: steel blue    5: deep pink     6: mint          7: candy pink
    8: muted purple  9: soft pink    10: pale mint    11: pale yellow
   12: pale blue    13: hot pink     14: pale mint2   15: white
"""

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pet_pixel import new_grid, stamp_grid

# ── Palette color constants ──────────────────────────────────────────
C_DARK     = 0   # dark bg / pupil
C_PINK     = 1   # pink (hair main)
C_MINTGRN  = 2   # mint green
C_SKIN     = 3   # wheat (skin)
C_BLUE     = 4   # steel blue (eye iris)
C_DPINK    = 5   # deep pink (hair shadow, mouth, accents)
C_MINT     = 6   # mint (shell, accessories)
C_CPINK    = 7   # candy pink (hair highlight)
C_OUTLINE  = 8   # muted purple (outline, shadows)
C_BLUSH    = 9   # soft pink (blush, hearts)
C_PMINT    = 10  # pale mint
C_GOLD     = 11  # pale yellow (gold trim, sparkles)
C_LTBLUE   = 12  # pale blue (eye sparkle, highlights)
C_HPINK    = 13  # hot pink (tail, accents)
C_PMINT2   = 14  # pale mint 2
C_WHITE    = 15  # white (sclera, highlights, sparkles)

PALETTE_RGB = {
    0:  (0x2A, 0x1F, 0x28), 1:  (0xE8, 0xA0, 0xBF), 2:  (0xC8, 0xE6, 0xA0),
    3:  (0xF5, 0xDE, 0xB3), 4:  (0xB0, 0xC4, 0xDE), 5:  (0xFF, 0x5F, 0xAF),
    6:  (0xA5, 0xF2, 0xE5), 7:  (0xFF, 0xAF, 0xD7), 8:  (0x6B, 0x54, 0x66),
    9:  (0xF8, 0xC0, 0xDF), 10: (0xD8, 0xF6, 0xC0), 11: (0xFF, 0xED, 0xC3),
    12: (0xD0, 0xE4, 0xEE), 13: (0xFF, 0x87, 0xC7), 14: (0xC5, 0xFF, 0xF5),
    15: (0xFF, 0xFF, 0xFF),
}

SPRITE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sprites")


# ── Drawing Primitives ───────────────────────────────────────────────

def _set(grid, x, y, color):
    """Set pixel if in bounds."""
    if 0 <= y < len(grid) and 0 <= x < len(grid[0]):
        grid[y][x] = color


def _fill_oval(grid, cx, cy, rx, ry, color):
    """Draw a filled oval."""
    h, w = len(grid), len(grid[0])
    for y in range(max(0, int(cy - ry - 1)), min(h, int(cy + ry + 2))):
        for x in range(max(0, int(cx - rx - 1)), min(w, int(cx + rx + 2))):
            dx = (x - cx) / max(rx, 0.5)
            dy = (y - cy) / max(ry, 0.5)
            if dx * dx + dy * dy <= 1.0:
                grid[y][x] = color


def _fill_rect(grid, x1, y1, x2, y2, color):
    """Draw a filled rectangle."""
    h, w = len(grid), len(grid[0])
    for y in range(max(0, y1), min(h, y2 + 1)):
        for x in range(max(0, x1), min(w, x2 + 1)):
            grid[y][x] = color


def _fill_triangle(grid, x1, y1, x2, y2, x3, y3, color):
    """Draw a filled triangle."""
    h, w = len(grid), len(grid[0])
    min_x = max(0, min(x1, x2, x3))
    max_x = min(w - 1, max(x1, x2, x3))
    min_y = max(0, min(y1, y2, y3))
    max_y = min(h - 1, max(y1, y2, y3))
    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            d = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
            if d == 0:
                continue
            a = ((y2 - y3) * (x - x3) + (x3 - x2) * (y - y3)) / d
            b = ((y3 - y1) * (x - x3) + (x1 - x3) * (y - y3)) / d
            c = 1 - a - b
            if a >= -0.01 and b >= -0.01 and c >= -0.01:
                grid[y][x] = color


def _hline(grid, x1, x2, y, color):
    """Horizontal line."""
    for x in range(min(x1, x2), max(x1, x2) + 1):
        _set(grid, x, y, color)


def _vline(grid, x, y1, y2, color):
    """Vertical line."""
    for y in range(min(y1, y2), max(y1, y2) + 1):
        _set(grid, x, y, color)


def _outline_silhouette(grid, outline_color):
    """Add 1px outline around all non-None pixels."""
    h, w = len(grid), len(grid[0])
    outline_pixels = []
    for y in range(h):
        for x in range(w):
            if grid[y][x] is not None:
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and grid[ny][nx] is None:
                        outline_pixels.append((nx, ny))
    for x, y in outline_pixels:
        grid[y][x] = outline_color


def _shade_oval(grid, cx, cy, rx, ry, light, mid, dark, target):
    """Apply diagonal gradient shading within an oval region matching target color."""
    for y in range(len(grid)):
        for x in range(len(grid[0])):
            if grid[y][x] != target:
                continue
            dx = (x - cx) / max(rx, 1)
            dy = (y - cy) / max(ry, 1)
            # Diagonal: upper-left = light, lower-right = dark
            bias = dx * 0.7 + dy * 0.5
            if bias < -0.3:
                grid[y][x] = light
            elif bias > 0.3:
                grid[y][x] = dark
            else:
                grid[y][x] = mid


def _hair_strands(grid, colors, seed_offset=0):
    """Add strand texture by shifting some hair pixels one shade lighter."""
    for y in range(len(grid)):
        for x in range(len(grid[0])):
            if grid[y][x] not in colors:
                continue
            # Diagonal strand pattern
            if (x * 3 + y * 2 + seed_offset) % 6 == 0:
                c = grid[y][x]
                if c == C_DPINK:
                    grid[y][x] = C_PINK
                elif c == C_PINK:
                    grid[y][x] = C_CPINK
            # Darker strands
            elif (x * 2 + y * 3 + seed_offset) % 9 == 0:
                c = grid[y][x]
                if c == C_CPINK:
                    grid[y][x] = C_PINK
                elif c == C_PINK:
                    grid[y][x] = C_DPINK


def _anti_alias_edges(grid, body_color, aa_color):
    """Add anti-aliasing pixels at sharp corners of body_color regions."""
    h, w = len(grid), len(grid[0])
    aa_pixels = []
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            if grid[y][x] is not None:
                continue
            # Count adjacent body pixels
            adj = 0
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and grid[ny][nx] == body_color:
                    adj += 1
            # Diagonal neighbors
            diag = 0
            for dx, dy in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and grid[ny][nx] == body_color:
                    diag += 1
            if adj == 0 and diag >= 2:
                aa_pixels.append((x, y))
    for x, y in aa_pixels:
        grid[y][x] = aa_color


# ── Large Mermaid Sprite (~70w × 76h) ───────────────────────────────

def make_mermaid_happy():
    """Build detailed mermaid sprite — dark hair, tan skin, cat eyes.

    ~70w × 76h pixels → renders as ~70×38 terminal cells via half-blocks.
    Style: cyberdeck mascot — dark flowing hair, golden eyes, pink accents.
    Hair = C_OUTLINE (8, muted purple, reads as dark), outline = C_DARK (0).
    """
    W, H = 70, 76
    CX = 35  # center x
    grid = new_grid(W, H)

    # Color aliases for this sprite
    HAIR = C_OUTLINE    # 8 muted purple — reads as dark hair
    HAIR_HI = C_BLUE    # 4 steel blue — hair shine/highlight
    OL = C_DARK         # 0 — outlines (black)

    # ── HAIR MASS (dark, flowing) ────────────────────────────────
    # Main dome
    _fill_oval(grid, CX, 22, 26, 22, HAIR)

    # Hair flowing down left side
    _fill_oval(grid, CX - 18, 40, 12, 22, HAIR)
    _fill_rect(grid, CX - 28, 20, CX - 14, 55, HAIR)
    _fill_oval(grid, CX - 20, 55, 10, 8, HAIR)

    # Hair flowing down right side
    _fill_oval(grid, CX + 18, 40, 12, 22, HAIR)
    _fill_rect(grid, CX + 14, 20, CX + 28, 55, HAIR)
    _fill_oval(grid, CX + 20, 55, 10, 8, HAIR)

    # Hair tips flowing outward at bottom
    _fill_oval(grid, CX - 22, 58, 6, 5, HAIR)
    _fill_oval(grid, CX + 22, 58, 6, 5, HAIR)
    _fill_oval(grid, CX - 25, 62, 4, 3, HAIR)
    _fill_oval(grid, CX + 25, 62, 4, 3, HAIR)

    # Top hair volume
    _fill_oval(grid, CX - 5, 2, 8, 4, HAIR)
    _fill_oval(grid, CX + 5, 3, 7, 4, HAIR)
    _fill_oval(grid, CX, 1, 6, 3, HAIR)

    # Hair shine streaks (steel blue highlights — like light reflecting)
    for y in range(6, 50):
        # Left highlight streak
        sx = CX - 14 + (y % 4)
        if 0 <= sx < W and grid[y][sx] == HAIR:
            grid[y][sx] = HAIR_HI
        if 0 <= sx + 1 < W and grid[y][sx + 1] == HAIR:
            grid[y][sx + 1] = HAIR_HI
        # Right highlight streak (offset)
        sx2 = CX + 10 + ((y + 2) % 4)
        if 0 <= sx2 < W and grid[y][sx2] == HAIR:
            grid[y][sx2] = HAIR_HI

    # Sparkles in hair (white dots)
    hair_sparkles = [
        (CX - 10, 8), (CX + 12, 12), (CX - 18, 25), (CX + 20, 20),
        (CX - 8, 15), (CX + 16, 35), (CX - 22, 40), (CX + 22, 45),
        (CX - 15, 50), (CX + 18, 52),
    ]
    for sx, sy in hair_sparkles:
        if 0 <= sy < H and 0 <= sx < W and grid[sy][sx] == HAIR:
            _set(grid, sx, sy, C_WHITE)

    # ── PINK BOW (on top of head) ────────────────────────────────
    bow_y = 5
    # Left loop
    _fill_oval(grid, CX - 5, bow_y, 4, 3, C_HPINK)
    _fill_oval(grid, CX - 5, bow_y, 3, 2, C_CPINK)
    # Right loop
    _fill_oval(grid, CX + 5, bow_y, 4, 3, C_HPINK)
    _fill_oval(grid, CX + 5, bow_y, 3, 2, C_CPINK)
    # Center knot
    _fill_oval(grid, CX, bow_y, 2, 2, C_DPINK)
    # Bow tails
    _set(grid, CX - 2, bow_y + 3, C_HPINK)
    _set(grid, CX - 3, bow_y + 4, C_HPINK)
    _set(grid, CX + 2, bow_y + 3, C_HPINK)
    _set(grid, CX + 3, bow_y + 4, C_HPINK)

    # ── HEAD (FACE) ──────────────────────────────────────────────
    _fill_oval(grid, CX, 28, 17, 17, C_SKIN)

    # Bangs (dark hair fringe across forehead)
    _fill_oval(grid, CX, 15, 16, 6, HAIR)
    # Bangs bottom edge — jagged fringe
    for x in range(CX - 14, CX + 15):
        fringe_y = 19 + (abs(x - CX) % 3)
        for y in range(fringe_y, 22):
            if 0 <= y < H and grid[y][x] == C_SKIN:
                grid[y][x] = HAIR

    # ── FACE FEATURES drawn AFTER outline (see below) ──────────

    # ── NECK ─────────────────────────────────────────────────────
    _fill_rect(grid, CX - 5, 43, CX + 5, 46, C_SKIN)

    # ── SHOULDERS ────────────────────────────────────────────────
    _fill_oval(grid, CX, 50, 12, 5, C_SKIN)
    _fill_oval(grid, CX - 10, 48, 4, 3, C_SKIN)
    _fill_oval(grid, CX + 10, 48, 4, 3, C_SKIN)

    # ── GOLD NECKLACE ────────────────────────────────────────────
    for x in range(CX - 7, CX + 8):
        _set(grid, x, 45, C_GOLD)
    _set(grid, CX, 46, C_GOLD)  # pendant
    _set(grid, CX - 1, 46, C_GOLD)
    _set(grid, CX + 1, 46, C_GOLD)
    _set(grid, CX, 47, C_HPINK)  # gem
    _set(grid, CX - 4, 45, C_WHITE)  # sparkle

    # ── SHELL TOP (hot pink/pink) ────────────────────────────────
    _fill_oval(grid, CX - 5, 51, 4, 3, C_HPINK)
    _fill_oval(grid, CX + 5, 51, 4, 3, C_HPINK)
    _fill_rect(grid, CX - 8, 49, CX + 8, 52, C_HPINK)
    # Shell ridges
    _vline(grid, CX - 5, 49, 52, C_DPINK)
    _vline(grid, CX + 5, 49, 52, C_DPINK)
    _vline(grid, CX, 49, 52, C_DPINK)
    # Shell highlights
    _fill_oval(grid, CX - 5, 50, 2, 1, C_CPINK)
    _fill_oval(grid, CX + 5, 50, 2, 1, C_CPINK)

    # ── WAIST ────────────────────────────────────────────────────
    _fill_oval(grid, CX, 55, 9, 3, C_SKIN)

    # ── GOLD WAIST BAND ─────────────────────────────────────────
    _hline(grid, CX - 9, CX + 9, 56, C_GOLD)
    _hline(grid, CX - 9, CX + 9, 57, C_GOLD)
    _set(grid, CX, 57, C_WHITE)  # gem sparkle

    # ── TAIL (hot pink, scaled) ──────────────────────────────────
    for y in range(58, 68):
        progress = (y - 58) / 10.0
        half_w = int(9 - progress * 5)
        for x in range(CX - half_w, CX + half_w + 1):
            _set(grid, x, y, C_HPINK)

    # Scale pattern
    for y in range(58, 68):
        for x in range(W):
            if grid[y][x] == C_HPINK:
                if ((x + y) % 4 == 0) or ((x - y) % 4 == 0):
                    grid[y][x] = C_DPINK
                if (x + y * 2) % 7 == 0:
                    grid[y][x] = C_CPINK

    # Tail edge shading
    for y in range(58, 68):
        for x in range(W):
            if grid[y][x] in (C_HPINK, C_CPINK):
                progress = (y - 58) / 10.0
                half_w = int(9 - progress * 5)
                if half_w > 0 and abs(x - CX) >= half_w - 1:
                    grid[y][x] = C_DPINK

    # ── TAIL FIN ─────────────────────────────────────────────────
    _fill_triangle(grid, CX - 2, 67, CX - 16, 75, CX - 4, 75, C_HPINK)
    _fill_triangle(grid, CX + 2, 67, CX + 4, 75, CX + 16, 75, C_HPINK)

    # Fin gradient
    for y in range(67, 76):
        for x in range(W):
            if grid[y][x] == C_HPINK:
                if y > 72 and (x + y) % 2 == 0:
                    grid[y][x] = C_CPINK
                if abs(x - CX) > 10:
                    grid[y][x] = C_DPINK

    # ── OUTLINE (black, 1px around entire silhouette) ────────────
    _outline_silhouette(grid, OL)

    # ── FACE FEATURES (drawn AFTER outline so they don't get wrapped) ──

    # ── EYES (kawaii cat-eye — moved inward so skin shows around them) ─
    eye_y = 29
    for side, ecx in [(-1, CX - 7), (1, CX + 7)]:
        # 1. Sclera — fits inside face with skin margin on all sides
        _fill_oval(grid, ecx, eye_y, 6, 5, C_WHITE)

        # 2. Cat-eye: pointed outer corner extension
        for dy in range(-1, 2):
            _set(grid, ecx + 6 * side, eye_y + dy, C_WHITE)
            _set(grid, ecx + 7 * side, eye_y + dy, C_WHITE)
        _set(grid, ecx + 8 * side, eye_y, C_WHITE)

        # 3. Iris (golden, centered-low)
        _fill_oval(grid, ecx, eye_y + 1, 3, 3, C_GOLD)
        # Soft shading at top of iris
        for ix in range(ecx - 2, ecx + 3):
            if 0 <= ix < W and grid[eye_y - 1][ix] == C_GOLD:
                grid[eye_y - 1][ix] = C_BLUSH

        # 4. Pupil
        _fill_oval(grid, ecx, eye_y, 1, 2, OL)

        # 5. Big kawaii sparkle
        _set(grid, ecx - 2, eye_y - 2, C_WHITE)
        _set(grid, ecx - 1, eye_y - 2, C_WHITE)
        _set(grid, ecx - 2, eye_y - 1, C_WHITE)
        _set(grid, ecx + 2, eye_y + 2, C_WHITE)

        # 6. Upper eyelid — thin line above sclera
        _hline(grid, ecx - 5, ecx + 5, eye_y - 5, OL)
        # Cat-eye: outer corner curves up
        _set(grid, ecx + 6 * side, eye_y - 4, OL)
        _set(grid, ecx + 7 * side, eye_y - 3, OL)

        # 7. Lashes — delicate outer flicks
        _set(grid, ecx + 8 * side, eye_y - 4, OL)
        _set(grid, ecx + 9 * side, eye_y - 5, OL)

    # ── EYEBROWS (thin arch, well above eyes) ────────────────────
    for side, ecx in [(-1, CX - 7), (1, CX + 7)]:
        _hline(grid, ecx - 3, ecx + 2, eye_y - 9, OL)
        _set(grid, ecx + 3 * side, eye_y - 10, OL)

    # ── BLUSH (under eyes, on cheeks) ────────────────────────────
    _fill_oval(grid, CX - 12, 35, 3, 2, C_BLUSH)
    _fill_oval(grid, CX + 12, 35, 3, 2, C_BLUSH)

    # ── NOSE ─────────────────────────────────────────────────────
    _set(grid, CX, 36, C_DPINK)
    _set(grid, CX + 1, 37, C_DPINK)

    # ── MOUTH (happy open smile) ─────────────────────────────────
    _hline(grid, CX - 5, CX + 5, 39, C_DPINK)
    _set(grid, CX - 6, 38, C_DPINK)
    _set(grid, CX + 6, 38, C_DPINK)
    _fill_oval(grid, CX, 40, 4, 2, OL)
    _fill_oval(grid, CX, 41, 3, 1, C_BLUSH)
    _hline(grid, CX - 4, CX + 4, 42, C_DPINK)

    # ── SPARKLES ─────────────────────────────────────────────────
    sparkle_positions = [
        (8, 10), (62, 8), (5, 35), (65, 30), (10, 55),
        (60, 55), (15, 68), (55, 70), (3, 20), (67, 45),
    ]
    for sx, sy in sparkle_positions:
        if 0 <= sy < H and 0 <= sx < W:
            _set(grid, sx, sy, C_WHITE)
            _set(grid, sx - 1, sy, C_HPINK)
            _set(grid, sx + 1, sy, C_HPINK)
            _set(grid, sx, sy - 1, C_HPINK)
            _set(grid, sx, sy + 1, C_HPINK)

    return {"width": W, "height": H, "grid": grid}


def make_mermaid_sleepy():
    """Sleepy expression — closed eyes, gentle face."""
    base = make_mermaid_happy()
    grid = base["grid"]
    CX = 35
    eye_y = 29

    # Clear eye area back to skin, then draw closed eyes
    for ecx in [CX - 7, CX + 7]:
        _fill_oval(grid, ecx, eye_y, 9, 6, C_SKIN)
        # Closed eye — gentle downward curve
        _hline(grid, ecx - 5, ecx + 5, eye_y, C_DARK)
        _set(grid, ecx - 6, eye_y - 1, C_DARK)
        _set(grid, ecx + 6, eye_y - 1, C_DARK)
        # Eyelashes from closed lid
        _set(grid, ecx + 6, eye_y - 2, C_DARK)
        _set(grid, ecx + 7, eye_y - 2, C_DARK)

    # Gentle closed mouth
    _fill_oval(grid, CX, 40, 4, 2, C_SKIN)
    _fill_oval(grid, CX, 41, 3, 1, C_SKIN)
    _hline(grid, CX - 3, CX + 3, 39, C_DPINK)

    return base


def make_mermaid_excited():
    """Excited — star eyes, big smile."""
    base = make_mermaid_happy()
    grid = base["grid"]
    CX = 35
    eye_y = 29

    for ecx in [CX - 9, CX + 9]:
        _fill_oval(grid, ecx, eye_y, 10, 6, C_WHITE)
        # Star shape in gold
        _hline(grid, ecx - 5, ecx + 5, eye_y, C_GOLD)
        _vline(grid, ecx, eye_y - 5, eye_y + 5, C_GOLD)
        for i in range(-4, 5):
            _set(grid, ecx + i, eye_y + i, C_GOLD)
            _set(grid, ecx + i, eye_y - i, C_GOLD)
        _fill_oval(grid, ecx, eye_y, 2, 2, C_GOLD)
        _set(grid, ecx, eye_y, C_WHITE)

    return base


def make_mermaid_sad():
    """Sad — teary eyes, frown."""
    base = make_mermaid_happy()
    grid = base["grid"]
    CX = 35
    eye_y = 29

    # Tear drops streaming down cheeks
    for ecx in [CX - 9, CX + 9]:
        tear_x = ecx + 4
        for ty in range(eye_y + 7, eye_y + 16):
            _set(grid, tear_x, ty, C_LTBLUE)
            if ty < eye_y + 10:
                _set(grid, tear_x + 1, ty, C_LTBLUE)

    # Sad mouth (frown)
    _fill_oval(grid, CX, 40, 4, 2, C_SKIN)
    _fill_oval(grid, CX, 41, 3, 1, C_SKIN)
    _hline(grid, CX - 4, CX + 4, 41, C_DPINK)
    _set(grid, CX - 5, 40, C_DPINK)
    _set(grid, CX + 5, 40, C_DPINK)

    return base


def make_mermaid_loving():
    """Loving — heart eyes."""
    base = make_mermaid_happy()
    grid = base["grid"]
    CX = 35
    eye_y = 29

    for ecx in [CX - 9, CX + 9]:
        _fill_oval(grid, ecx, eye_y, 10, 6, C_WHITE)
        # Heart shape (two bumps + triangle bottom)
        _fill_oval(grid, ecx - 2, eye_y - 2, 3, 3, C_HPINK)
        _fill_oval(grid, ecx + 2, eye_y - 2, 3, 3, C_HPINK)
        _fill_triangle(grid, ecx - 5, eye_y - 1, ecx + 5, eye_y - 1, ecx, eye_y + 5, C_HPINK)
        # Heart highlight
        _fill_oval(grid, ecx - 2, eye_y - 3, 1, 1, C_WHITE)

    return base


def make_egg():
    """Egg sprite (20w × 28h)."""
    W, H = 20, 28
    CX = 10
    grid = new_grid(W, H)

    _fill_oval(grid, CX, 14, 8, 13, C_WHITE)
    # Pink spots
    _fill_oval(grid, CX - 3, 8, 2, 2, C_BLUSH)
    _fill_oval(grid, CX + 4, 12, 1, 1, C_CPINK)
    _fill_oval(grid, CX - 2, 18, 1, 2, C_BLUSH)
    _fill_oval(grid, CX + 3, 20, 2, 1, C_CPINK)
    # Heart decoration
    _set(grid, CX, 10, C_HPINK)
    _set(grid, CX - 1, 9, C_HPINK)
    _set(grid, CX + 1, 9, C_HPINK)

    # Crack line
    for i, x in enumerate(range(CX - 4, CX + 5)):
        y = 14 + (1 if i % 2 == 0 else -1)
        _set(grid, x, y, C_OUTLINE)

    _outline_silhouette(grid, C_OUTLINE)
    return {"width": W, "height": H, "grid": grid}


def make_baby_mermaid():
    """Baby mermaid (30w × 38h) — smaller but still detailed."""
    W, H = 30, 38
    CX = 15
    grid = new_grid(W, H)

    # Hair
    _fill_oval(grid, CX, 10, 12, 10, C_PINK)
    _shade_oval(grid, CX, 10, 12, 10, C_CPINK, C_PINK, C_DPINK, C_PINK)
    _hair_strands(grid, {C_CPINK, C_PINK, C_DPINK})

    # Head
    _fill_oval(grid, CX, 13, 8, 8, C_SKIN)

    # Eyes (medium, 5×4)
    for ecx in [CX - 4, CX + 3]:
        _fill_oval(grid, ecx, 12, 3, 3, C_OUTLINE)
        _fill_oval(grid, ecx, 12, 2, 2, C_WHITE)
        _fill_oval(grid, ecx, 13, 2, 2, C_BLUE)
        _set(grid, ecx, 12, C_DARK)
        _set(grid, ecx + 1, 12, C_DARK)
        _set(grid, ecx - 1, 11, C_WHITE)

    # Blush
    _fill_oval(grid, CX - 6, 15, 2, 1, C_BLUSH)
    _fill_oval(grid, CX + 6, 15, 2, 1, C_BLUSH)

    # Mouth
    _hline(grid, CX - 1, CX + 1, 17, C_DPINK)

    # Body
    _fill_rect(grid, CX - 4, 22, CX + 4, 26, C_SKIN)
    _fill_rect(grid, CX - 4, 24, CX + 4, 26, C_MINT)

    # Stubby tail
    for y in range(27, 34):
        hw = max(1, 4 - (y - 27) // 2)
        _fill_rect(grid, CX - hw, y, CX + hw, y, C_HPINK)

    # Mini fin
    _set(grid, CX - 3, 34, C_HPINK)
    _set(grid, CX - 4, 35, C_HPINK)
    _set(grid, CX + 3, 34, C_HPINK)
    _set(grid, CX + 4, 35, C_HPINK)

    _outline_silhouette(grid, C_OUTLINE)
    return {"width": W, "height": H, "grid": grid}


# ── Save / Preview ───────────────────────────────────────────────────

def save_sprite(name, sprite_data, frames=None):
    os.makedirs(SPRITE_DIR, exist_ok=True)
    path = os.path.join(SPRITE_DIR, f"{name}.json")
    if frames:
        data = {
            "name": name, "width": sprite_data["width"],
            "height": sprite_data["height"],
            "anchor": [sprite_data["width"] // 2, 0],
            "frames": [f["grid"] for f in frames],
        }
    else:
        data = {
            "name": name, "width": sprite_data["width"],
            "height": sprite_data["height"],
            "anchor": [sprite_data["width"] // 2, 0],
            "frames": [sprite_data["grid"]],
        }
    with open(path, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    print(f"  Saved: {name}.json ({sprite_data['width']}×{sprite_data['height']}px)")


def render_png(name, grid, scale=4):
    """Render sprite to PNG for preview."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return
    h = len(grid)
    w = len(grid[0]) if grid else 0
    BG = PALETTE_RGB[0]
    img = Image.new("RGB", (w * scale, h * scale), BG)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        for x in range(w):
            c = grid[y][x]
            if c is not None:
                color = PALETTE_RGB.get(c, BG)
                draw.rectangle(
                    [x * scale, y * scale, (x + 1) * scale - 1, (y + 1) * scale - 1],
                    fill=color,
                )
    path = os.path.join(SPRITE_DIR, f"{name}.png")
    img.save(path)
    print(f"  PNG: {name}.png ({w * scale}×{h * scale})")


def main():
    print("Generating mermaid sprites (large, detailed)...")

    moods = {
        "mermaid_happy": make_mermaid_happy,
        "mermaid_sleepy": make_mermaid_sleepy,
        "mermaid_excited": make_mermaid_excited,
        "mermaid_sad": make_mermaid_sad,
        "mermaid_loving": make_mermaid_loving,
    }

    for name, builder in moods.items():
        sprite = builder()
        save_sprite(name, sprite)
        if "--preview" in sys.argv or True:  # always generate PNGs
            render_png(name, sprite["grid"])

    save_sprite("egg", make_egg())
    render_png("egg", make_egg()["grid"])

    save_sprite("baby_mermaid", make_baby_mermaid())
    render_png("baby_mermaid", make_baby_mermaid()["grid"])

    print("\nDone!")


if __name__ == "__main__":
    main()
