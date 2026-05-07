#!/usr/bin/env python3
"""Pure-Python RGB565 sprite blitter for framebuffer overlays.

Reads pre-converted .raw files (RGB565 + alpha) and writes directly
to the framebuffer via mmap. No PIL required on the device.

Raw format: [uint16 w][uint16 h][w*h*2 bytes RGB565][w*h bytes alpha]
"""
import os
import struct


def load_raw(path):
    """Load a raw sprite file. Returns (width, height, rgb565_bytes, alpha_bytes).

    Returns None if file missing or corrupt.
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            data = f.read()
        if len(data) < 4:
            return None
        w, h = struct.unpack("<HH", data[:4])
        expected = 4 + (w * h * 2) + (w * h)
        if len(data) != expected:
            return None
        rgb565 = data[4:4 + w * h * 2]
        alpha = data[4 + w * h * 2:]
        return w, h, rgb565, alpha
    except Exception:
        return None


def blit_to_fb(fb, raw_data, x, y):
    """Blit a raw sprite to the framebuffer at (x, y) top-left.

    Uses contiguous-row-segment copying for speed (slice assignments
    are ~100x faster than byte-by-byte in Python).

    fb: Framebuffer instance with .w, .h, .line, ._mm attributes
    raw_data: tuple from load_raw()
    """
    if raw_data is None or fb._mm is None:
        return
    w, h, rgb565, alpha = raw_data

    # Clip to screen bounds
    x0 = max(0, x)
    y0 = max(0, y)
    x1 = min(fb.w, x + w)
    y1 = min(fb.h, y + h)

    if x0 >= x1 or y0 >= y1:
        return

    src_x_off = x0 - x
    src_y_off = y0 - y
    row_width = x1 - x0

    for dy in range(y0, y1):
        sy = src_y_off + (dy - y0)
        alpha_row_start = sy * w + src_x_off
        rgb_row_start = alpha_row_start * 2
        dst_off = dy * fb.line + x0 * 2

        # Find contiguous opaque segments in this row and copy each
        # as a single slice assignment (C-level memcpy speed)
        seg_start = None
        for col in range(row_width):
            a = alpha[alpha_row_start + col]
            if a >= 128:
                if seg_start is None:
                    seg_start = col
            else:
                if seg_start is not None:
                    seg_len = col - seg_start
                    s = rgb_row_start + seg_start * 2
                    d = dst_off + seg_start * 2
                    fb._mm[d:d + seg_len * 2] = rgb565[s:s + seg_len * 2]
                    seg_start = None

        # Handle segment that runs to end of row
        if seg_start is not None:
            seg_len = row_width - seg_start
            s = rgb_row_start + seg_start * 2
            d = dst_off + seg_start * 2
            fb._mm[d:d + seg_len * 2] = rgb565[s:s + seg_len * 2]
