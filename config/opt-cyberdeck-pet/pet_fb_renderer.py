#!/usr/bin/env python3
"""Framebuffer renderer for cyberdeck pet.

Renders full-color pixel art directly to Linux framebuffer (/dev/fb0).
Falls back to PNG output for testing on systems without framebuffer access.
"""
import os
import sys
import struct
import fcntl
import mmap
import math
import time
import random
from PIL import Image, ImageDraw, ImageFont

# ── Framebuffer detection ─────────────────────────────────────────────

def get_fb_info(fb_path="/dev/fb0"):
    """Read framebuffer geometry via sysfs."""
    try:
        with open(f"/sys/class/graphics/fb0/virtual_size") as f:
            w, h = map(int, f.read().strip().split(","))
        with open(f"/sys/class/graphics/fb0/bits_per_pixel") as f:
            bpp = int(f.read().strip())
        return {"width": w, "height": h, "bpp": bpp, "path": fb_path}
    except Exception as e:
        # Fallback for testing
        return {"width": 640, "height": 480, "bpp": 32, "path": None}


class Framebuffer:
    """Direct framebuffer access."""

    def __init__(self, info=None):
        self.info = info or get_fb_info()
        self.w = self.info["width"]
        self.h = self.info["height"]
        self.bpp = self.info["bpp"]
        self.path = self.info["path"]
        self._fb = None
        self._mm = None
        self._has_fb = False

        if self.path and os.path.exists(self.path) and os.access(self.path, os.W_OK):
            try:
                self._fb = open(self.path, "r+b")
                # FBIOGET_VSCREENINFO would be ideal but requires ioctl
                # Use sysfs values instead
                self._line_bytes = self.w * (self.bpp // 8)
                self._buf_size = self._line_bytes * self.h
                self._mm = mmap.mmap(self._fb.fileno(), self._buf_size, mmap.MAP_SHARED,
                                     mmap.PROT_READ | mmap.PROT_WRITE)
                self._has_fb = True
                print(f"Framebuffer: {self.w}x{self.h} @ {self.bpp}bpp")
            except Exception as e:
                print(f"Framebuffer init failed: {e}, using PNG fallback")
                self._has_fb = False
        else:
            print(f"No writable framebuffer, using PNG fallback ({self.w}x{self.h})")

    def is_real(self):
        return self._has_fb

    def clear(self, color=(0, 0, 0)):
        """Fill screen with solid color."""
        img = Image.new("RGBA", (self.w, self.h), (*color, 255))
        self.blit(img)

    def blit(self, img):
        """Blit a PIL RGBA image to the framebuffer."""
        if img.size != (self.w, self.h):
            img = img.resize((self.w, self.h), Image.LANCZOS)

        if self._has_fb and self.bpp == 32:
            # Convert to BGRA for little-endian framebuffer
            r, g, b, a = img.split()
            bgra = Image.merge("RGBA", (b, g, r, a))
            self._mm.seek(0)
            self._mm.write(bgra.tobytes())
        elif self._has_fb and self.bpp == 16:
            # RGB565 conversion
            rgb565 = img.convert("RGB").convert("RGB", matrix=None, dither=Image.Dither.NONE)
            # PIL doesn't have native RGB565, we'd need numpy or manual conversion
            # For now, skip 16bpp or use RGB565 conversion
            data = bytearray()
            for px in rgb565.getdata():
                r5 = px[0] >> 3
                g6 = px[1] >> 2
                b5 = px[2] >> 3
                val = (r5 << 11) | (g6 << 5) | b5
                data += struct.pack("<H", val)
            self._mm.seek(0)
            self._mm.write(bytes(data))
        else:
            # PNG fallback for testing
            pass

    def save_fallback(self, img, path="/tmp/pet_frame.png"):
        """Save frame as PNG when no framebuffer is available."""
        if img.size != (self.w, self.h):
            img = img.resize((self.w, self.h), Image.LANCZOS)
        img.convert("RGB").save(path)
        return path

    def close(self):
        if self._mm:
            self._mm.close()
        if self._fb:
            self._fb.close()


class Compositor:
    """Layer compositor for pet scene."""

    def __init__(self, width, height):
        self.w = width
        self.h = height
        self.buffer = Image.new("RGBA", (width, height), (0, 0, 0, 255))

    def clear(self, color=(0, 0, 0, 255)):
        self.buffer = Image.new("RGBA", (self.w, self.h), color)

    def draw_background(self, bg_img):
        """Draw background layer."""
        if bg_img.size != (self.w, self.h):
            bg_img = bg_img.resize((self.w, self.h), Image.LANCZOS)
        self.buffer.paste(bg_img, (0, 0))

    def draw_sprite(self, sprite_img, x, y, anchor="center"):
        """Draw sprite with alpha compositing."""
        sw, sh = sprite_img.size
        if anchor == "center":
            x -= sw // 2
            y -= sh // 2
        elif anchor == "bottom_center":
            x -= sw // 2
            y -= sh
        self.buffer.paste(sprite_img, (x, y), sprite_img)

    def draw_text(self, text, x, y, color=(255, 255, 255, 255), size=16):
        """Draw text overlay."""
        draw = ImageDraw.Draw(self.buffer)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
        except:
            font = ImageFont.load_default()
        draw.text((x, y), text, fill=color, font=font)

    def draw_bar(self, x, y, w, h, fill_pct, fill_color, bg_color=(50, 50, 50, 180)):
        """Draw a stat bar."""
        draw = ImageDraw.Draw(self.buffer)
        # Background
        draw.rectangle([x, y, x + w, y + h], fill=bg_color, outline=(100, 100, 100, 200), width=1)
        # Fill
        fill_w = int(w * max(0, min(1, fill_pct)))
        if fill_w > 0:
            draw.rectangle([x + 1, y + 1, x + fill_w - 1, y + h - 1], fill=fill_color)

    def get_frame(self):
        return self.buffer.copy()


if __name__ == "__main__":
    fb = Framebuffer()
    comp = Compositor(fb.w, fb.h)
    
    # Test pattern
    comp.clear((20, 30, 60, 255))
    comp.draw_text("Pet FB Renderer OK", 50, 50, (255, 255, 255), 24)
    comp.draw_bar(50, 100, 200, 20, 0.75, (100, 255, 100, 200))
    
    if fb.is_real():
        fb.blit(comp.get_frame())
        print("Rendered to framebuffer")
    else:
        path = fb.save_fallback(comp.get_frame())
        print(f"Saved fallback: {path}")
