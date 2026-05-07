#!/usr/bin/env python3
"""Pure Python framebuffer drawing primitives.

No PIL required. Writes directly to RGB565 framebuffer via mmap.
"""
import mmap
import os
import struct

# Framebuffer info (hardcoded for cyberdeck 640x480 RGB565)
FB_W, FB_H = 640, 480
FB_BPP = 16
FB_LINE = 1280  # bytes per line

# ── Color helpers ─────────────────────────────────────────────────────

def rgb565(r, g, b):
    """Convert RGB888 to RGB565."""
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)

# Palette
C_BLACK  = rgb565(0, 0, 0)
C_WHITE  = rgb565(255, 255, 255)
C_RED    = rgb565(255, 80, 80)
C_GREEN  = rgb565(100, 255, 150)
C_BLUE   = rgb565(100, 200, 255)
C_YELLOW = rgb565(255, 255, 100)
C_PINK   = rgb565(255, 100, 150)
C_ORANGE = rgb565(255, 150, 50)
C_PURPLE = rgb565(180, 100, 255)
C_DARK   = rgb565(30, 30, 50)
C_GRAY   = rgb565(120, 120, 120)

# cyberdeck brand colors
C_THEME_PINK    = rgb565(255, 176, 251)  # #FFB0FB
C_THEME_BLUE    = rgb565(135, 206, 250)  # #87CEFA
C_THEME_PURPLE  = rgb565(223, 115, 255)  # #DF73FF
C_THEME_MINT    = rgb565(132, 230, 189)  # #84E6BD
C_THEME_YELLOW  = rgb565(252, 255, 70)   # #FCFF46
C_THEME_PEACH   = rgb565(255, 190, 176)  # #FFBEB0
C_THEME_CYAN    = rgb565(178, 255, 255)  # #B2FFFF
C_THEME_CHART   = rgb565(204, 255, 0)    # #CCFF00
C_CYBER_BG      = rgb565(42, 31, 40)     # #2A1F28
C_CANDY_PINK    = rgb565(255, 175, 215)  # #FFAFD7

# ── Font (3x5 bitmap) ─────────────────────────────────────────────────

FONT = {
    ' ': [0b000,0b000,0b000,0b000,0b000],
    'A': [0b010,0b101,0b111,0b101,0b101],
    'B': [0b110,0b101,0b110,0b101,0b110],
    'C': [0b011,0b100,0b100,0b100,0b011],
    'D': [0b110,0b101,0b101,0b101,0b110],
    'E': [0b111,0b100,0b110,0b100,0b111],
    'F': [0b111,0b100,0b110,0b100,0b100],
    'G': [0b011,0b100,0b101,0b101,0b011],
    'H': [0b101,0b101,0b111,0b101,0b101],
    'I': [0b111,0b010,0b010,0b010,0b111],
    'J': [0b001,0b001,0b001,0b101,0b010],
    'K': [0b101,0b101,0b110,0b101,0b101],
    'L': [0b100,0b100,0b100,0b100,0b111],
    'M': [0b101,0b111,0b101,0b101,0b101],
    'N': [0b111,0b101,0b101,0b101,0b101],
    'O': [0b010,0b101,0b101,0b101,0b010],
    'P': [0b110,0b101,0b110,0b100,0b100],
    'Q': [0b010,0b101,0b101,0b011,0b001],
    'R': [0b110,0b101,0b110,0b101,0b101],
    'S': [0b011,0b100,0b010,0b001,0b110],
    'T': [0b111,0b010,0b010,0b010,0b010],
    'U': [0b101,0b101,0b101,0b101,0b011],
    'V': [0b101,0b101,0b101,0b101,0b010],
    'W': [0b101,0b101,0b101,0b111,0b101],
    'X': [0b101,0b101,0b010,0b101,0b101],
    'Y': [0b101,0b101,0b010,0b010,0b010],
    'Z': [0b111,0b001,0b010,0b100,0b111],
    '0': [0b010,0b101,0b101,0b101,0b010],
    '1': [0b010,0b110,0b010,0b010,0b111],
    '2': [0b110,0b001,0b010,0b100,0b111],
    '3': [0b110,0b001,0b010,0b001,0b110],
    '4': [0b101,0b101,0b111,0b001,0b001],
    '5': [0b111,0b100,0b110,0b001,0b110],
    '6': [0b011,0b100,0b111,0b101,0b011],
    '7': [0b111,0b001,0b010,0b010,0b010],
    '8': [0b011,0b101,0b011,0b101,0b011],
    '9': [0b011,0b101,0b011,0b001,0b011],
    ':': [0b000,0b010,0b000,0b010,0b000],
    '-': [0b000,0b000,0b111,0b000,0b000],
    '_': [0b000,0b000,0b000,0b000,0b111],
    '%': [0b101,0b001,0b010,0b100,0b101],
    '!': [0b010,0b010,0b010,0b000,0b010],
    '?': [0b110,0b001,0b010,0b000,0b010],
    '*': [0b000,0b101,0b010,0b101,0b000],
    '/': [0b001,0b001,0b010,0b100,0b100],
    '=': [0b000,0b111,0b000,0b111,0b000],
    '+': [0b000,0b010,0b111,0b010,0b000],
    '.': [0b000,0b000,0b000,0b000,0b010],
    ',': [0b000,0b000,0b000,0b010,0b100],
    '(': [0b001,0b010,0b010,0b010,0b001],
    ')': [0b100,0b010,0b010,0b010,0b100],
    '[': [0b011,0b010,0b010,0b010,0b011],
    ']': [0b110,0b010,0b010,0b010,0b110],
}

class Framebuffer:
    """Direct framebuffer access for drawing primitives."""

    def __init__(self, path="/dev/fb0"):
        self.path = path
        self.w = FB_W
        self.h = FB_H
        self.line = FB_LINE
        self._fd = None
        self._mm = None
        self._open()

    def _open(self):
        try:
            self._fd = open(self.path, "r+b")
            self._mm = mmap.mmap(self._fd.fileno(), self.line * self.h,
                                 mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
        except Exception as e:
            print(f"Framebuffer open failed: {e}")
            self._mm = None

    def close(self):
        if self._mm:
            self._mm.close()
        if self._fd:
            self._fd.close()

    def pixel(self, x, y, color):
        if 0 <= x < self.w and 0 <= y < self.h and self._mm:
            off = y * self.line + x * 2
            self._mm[off] = color & 0xFF
            self._mm[off + 1] = (color >> 8) & 0xFF

    def rect(self, x, y, w, h, color):
        x1 = max(0, x)
        y1 = max(0, y)
        x2 = min(self.w, x + w)
        y2 = min(self.h, y + h)
        for py in range(y1, y2):
            off = py * self.line + x1 * 2
            # Write row as bytes
            row = struct.pack('<H', color) * (x2 - x1)
            self._mm[off:off + len(row)] = row

    def circle(self, cx, cy, r, color):
        r2 = r * r
        for y in range(max(0, cy - r), min(self.h, cy + r + 1)):
            dy = y - cy
            dx = int((r2 - dy * dy) ** 0.5)
            x1 = max(0, cx - dx)
            x2 = min(self.w, cx + dx + 1)
            if x1 < x2:
                off = y * self.line + x1 * 2
                row = struct.pack('<H', color) * (x2 - x1)
                self._mm[off:off + len(row)] = row

    def line(self, x1, y1, x2, y2, color):
        """Bresenham line."""
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        sx = 1 if x1 < x2 else -1
        sy = 1 if y1 < y2 else -1
        err = dx - dy
        while True:
            self.pixel(x1, y1, color)
            if x1 == x2 and y1 == y2:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x1 += sx
            if e2 < dx:
                err += dx
                y1 += sy

    def ring(self, cx, cy, r, color, thickness=1):
        for t in range(thickness):
            rr = r + t
            r2 = rr * rr
            for y in range(max(0, cy - rr), min(self.h, cy + rr + 1)):
                dy = y - cy
                dx = int((r2 - dy * dy) ** 0.5)
                for x in [cx - dx, cx + dx]:
                    if 0 <= x < self.w:
                        self.pixel(x, y, color)

    def char(self, ch, x, y, color, scale=1):
        ch = ch.upper()
        bits = FONT.get(ch, FONT.get('?', [0b111,0b001,0b010,0b000,0b010]))
        for row in range(5):
            b = bits[row]
            for col in range(3):
                if b & (1 << (2 - col)):
                    if scale == 1:
                        self.pixel(x + col, y + row, color)
                    else:
                        self.rect(x + col * scale, y + row * scale, scale, scale, color)

    def text(self, s, x, y, color, scale=1):
        cx = x
        for ch in s:
            if ch == ' ':
                cx += 4 * scale
                continue
            self.char(ch, cx, y, color, scale)
            cx += 4 * scale

    def clear(self, color=C_BLACK):
        row = struct.pack('<H', color) * self.w
        for y in range(self.h):
            off = y * self.line
            self._mm[off:off + len(row)] = row

    def hline(self, x, y, w, color):
        x1 = max(0, x)
        x2 = min(self.w, x + w)
        if x1 < x2 and 0 <= y < self.h:
            off = y * self.line + x1 * 2
            self._mm[off:off + (x2 - x1) * 2] = struct.pack('<H', color) * (x2 - x1)

    def bar(self, x, y, w, h, fill_pct, fill_color, bg_color=None):
        """Draw a stat bar. If bg_color is given, draw full bar with fill on top.
        If bg_color is None, only draw the filled portion (no background bar)."""
        fill = max(0, min(1, fill_pct))
        fw = int(w * fill)
        if bg_color is not None:
            self.rect(x, y, w, h, bg_color)
            if fw > 2:
                self.rect(x + 1, y + 1, fw - 2, h - 2, fill_color)
        else:
            # No background — just draw the colored fill portion
            if fw > 0:
                self.rect(x, y, fw, h, fill_color)

    def blit_sprite(self, raw_data, x, y):
        """Blit a raw RGB565+alpha sprite to the framebuffer.

        raw_data: tuple (w, h, rgb565_bytes, alpha_bytes) from pet_fb_blitter.load_raw()
        """
        import struct
        if raw_data is None or self._mm is None:
            return
        w, h, rgb565, alpha = raw_data

        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self.w, x + w)
        y1 = min(self.h, y + h)
        if x0 >= x1 or y0 >= y1:
            return

        src_x_off = x0 - x
        src_y_off = y0 - y

        for dy in range(y0, y1):
            sy = src_y_off + (dy - y0)
            dst_off = dy * self.line + x0 * 2
            for dx in range(x0, x1):
                sx = dx - x0 + src_x_off
                a = alpha[sy * w + sx]
                if a < 128:
                    continue
                src_idx = (sy * w + sx) * 2
                self._mm[dst_off + (dx - x0) * 2] = rgb565[src_idx]
                self._mm[dst_off + (dx - x0) * 2 + 1] = rgb565[src_idx + 1]
