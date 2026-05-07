#!/usr/bin/env python3
# Deploy to: /opt/cyberdeck-pet/pet_pixel.py on Pi
#
# Half-block pixel renderer + braille dot overlay for mermaid tamagotchi.
#
# Pixel grids use color indices 0-15 (fbterm palette slots) or None (transparent).
# Two pixel rows collapse into one terminal row via ▀▄█ characters.
# Dynamic color pair registry handles arbitrary fg/bg combos on demand.
#
# Target: 106×33 terminal (6×12 font on 640×400 DSI display)
# Half-block: 106 × 66 virtual pixels
# Braille:    212 × 132 virtual dots (2×4 per cell)

import curses

# ── cyberdeck fbterm palette (16 slots) ──────────────────────────────
# Index → (name, hex) for reference and palette remap
PALETTE = {
    0:  ("dark bg",      0x2A, 0x1F, 0x28),
    1:  ("pink",         0xE8, 0xA0, 0xBF),
    2:  ("mint green",   0xC8, 0xE6, 0xA0),
    3:  ("wheat",        0xF5, 0xDE, 0xB3),
    4:  ("steel blue",   0xB0, 0xC4, 0xDE),
    5:  ("deep pink",    0xFF, 0x5F, 0xAF),
    6:  ("mint",         0xA5, 0xF2, 0xE5),
    7:  ("candy pink",   0xFF, 0xAF, 0xD7),
    8:  ("muted purple", 0x6B, 0x54, 0x66),
    9:  ("soft pink",    0xF8, 0xC0, 0xDF),
    10: ("pale mint",    0xD8, 0xF6, 0xC0),
    11: ("pale yellow",  0xFF, 0xED, 0xC3),
    12: ("pale blue",    0xD0, 0xE4, 0xEE),
    13: ("hot pink",     0xFF, 0x87, 0xC7),
    14: ("pale mint2",   0xC5, 0xFF, 0xF5),
    15: ("white",        0xFF, 0xFF, 0xFF),
}

# Palette slot names for editor display
PALETTE_NAMES = {i: v[0] for i, v in PALETTE.items()}


def remap_palette():
    """Remap curses color slots 0-15 to cyberdeck fbterm palette.

    Only works when curses.can_change_color() (xterm-256color, etc).
    On fbterm these are already correct via ~/.fbtermrc.
    """
    if not curses.can_change_color():
        return
    for slot, (name, r, g, b) in PALETTE.items():
        try:
            curses.init_color(slot, r * 1000 // 255, g * 1000 // 255, b * 1000 // 255)
        except curses.error:
            pass


class ColorPairRegistry:
    """Dynamic curses color pair allocator.

    Half-block rendering needs arbitrary fg/bg combos. This allocates
    curses color pairs on demand and caches them.

    Reserves pairs 1-29 for static use (shared cyberdeck + legacy pet pairs).
    Dynamic pairs start at 30.
    """

    def __init__(self, start=30):
        self._map = {}
        self._next = start
        # curses typically supports up to 256 pairs (or 32767 on newer)
        # 16×16 = 256 possible combos with our palette, fits easily
        self._max = curses.COLOR_PAIRS - 1 if hasattr(curses, 'COLOR_PAIRS') else 255

    def get(self, fg, bg):
        """Get curses color_pair attribute for fg/bg color slot combo.

        Args:
            fg: foreground color slot (0-15)
            bg: background color slot (0-15), or -1 for default

        Returns:
            curses color_pair attribute (ready for addstr)
        """
        key = (fg, bg)
        if key in self._map:
            return curses.color_pair(self._map[key])

        if self._next > self._max:
            # Fallback: return closest existing pair or default
            return curses.color_pair(0)

        curses.init_pair(self._next, fg, bg)
        self._map[key] = self._next
        self._next += 1
        return curses.color_pair(self._map[key])

    def reset(self):
        """Clear registry (call if palette changes)."""
        self._map.clear()
        self._next = 30


# Module-level singleton — initialized after curses.start_color()
_registry = None


def get_registry():
    """Get or create the global ColorPairRegistry."""
    global _registry
    if _registry is None:
        _registry = ColorPairRegistry()
    return _registry


def init_pixel_colors():
    """Initialize pixel rendering system. Call after curses.start_color()."""
    curses.start_color()
    curses.use_default_colors()
    remap_palette()
    global _registry
    _registry = ColorPairRegistry()


# ── Half-Block Renderer ──────────────────────────────────────────────

def render_halfblock(pixel_grid, default_bg=0):
    """Convert a pixel grid to half-block terminal cells.

    Args:
        pixel_grid: list of rows, each row = list of color indices (0-15) or None.
                    Height should be even (padded with None if odd).
        default_bg: background color for transparent pixels (default: 0 dark bg)

    Returns:
        list of terminal rows, each row = list of (char, curses_attr) tuples.
        Height = len(pixel_grid) // 2
    """
    reg = get_registry()
    rows = pixel_grid
    h = len(rows)
    if h == 0:
        return []

    # Pad to even height
    w = max(len(r) for r in rows) if rows else 0
    if h % 2 != 0:
        rows = list(rows) + [[None] * w]
        h += 1

    result = []
    for y in range(0, h, 2):
        top_row = rows[y]
        bot_row = rows[y + 1] if y + 1 < h else [None] * w
        term_row = []
        max_x = max(len(top_row), len(bot_row))
        for x in range(max_x):
            top = top_row[x] if x < len(top_row) else None
            bot = bot_row[x] if x < len(bot_row) else None

            # Resolve None → default_bg for rendering
            t = top if top is not None else default_bg
            b = bot if bot is not None else default_bg

            if t == b:
                # Both same color — full block (or space if both bg)
                if t == default_bg and top is None and bot is None:
                    term_row.append((" ", reg.get(default_bg, default_bg)))
                else:
                    term_row.append(("█", reg.get(t, default_bg)))
            else:
                # ▀ = top is fg, bottom is bg
                term_row.append(("▀", reg.get(t, b)))
        result.append(term_row)
    return result


def render_halfblock_to_win(win, pixel_grid, start_y=0, start_x=0, default_bg=0):
    """Render pixel grid directly to a curses window.

    Args:
        win: curses window
        pixel_grid: 2D list of color indices or None
        start_y, start_x: top-left position in window
        default_bg: background color for transparent pixels
    """
    term_rows = render_halfblock(pixel_grid, default_bg)
    max_y, max_x = win.getmaxyx()

    for dy, row in enumerate(term_rows):
        y = start_y + dy
        if y >= max_y:
            break
        for dx, (ch, attr) in enumerate(row):
            x = start_x + dx
            if x >= max_x - 1:  # -1 to avoid curses corner write error
                break
            try:
                win.addstr(y, x, ch, attr)
            except curses.error:
                pass


# ── Braille Renderer ─────────────────────────────────────────────────
# Braille chars: U+2800 + dot_bits
# Dot positions in a 2×4 grid per cell:
#   (0,0)=0x01  (1,0)=0x08
#   (0,1)=0x02  (1,1)=0x10
#   (0,2)=0x04  (1,2)=0x20
#   (0,3)=0x40  (1,3)=0x80

BRAILLE_DOT = [
    [0x01, 0x08],
    [0x02, 0x10],
    [0x04, 0x20],
    [0x40, 0x80],
]


def render_braille(dot_grid, fg_color=15, bg_color=0):
    """Convert a dot grid to braille terminal cells.

    Args:
        dot_grid: 2D list of bool/truthy. Each cell = one dot.
                  Width mapped 2 dots per terminal col, height 4 dots per terminal row.
        fg_color: foreground color slot for braille chars
        bg_color: background color slot

    Returns:
        list of terminal rows, each row = list of (char, curses_attr) or None (empty cell).
        Height = ceil(dot_h / 4), Width = ceil(dot_w / 2)
    """
    reg = get_registry()
    dot_h = len(dot_grid)
    if dot_h == 0:
        return []
    dot_w = max(len(r) for r in dot_grid)

    term_h = (dot_h + 3) // 4
    term_w = (dot_w + 1) // 2
    attr = reg.get(fg_color, bg_color)

    result = []
    for ty in range(term_h):
        row = []
        for tx in range(term_w):
            bits = 0
            for dy in range(4):
                for dx in range(2):
                    gy = ty * 4 + dy
                    gx = tx * 2 + dx
                    if gy < dot_h and gx < len(dot_grid[gy]) and dot_grid[gy][gx]:
                        bits |= BRAILLE_DOT[dy][dx]
            if bits == 0:
                row.append(None)  # empty — transparent
            else:
                row.append((chr(0x2800 + bits), attr))
        result.append(row)
    return result


# ── Pixel Grid Utilities ─────────────────────────────────────────────

def new_grid(width, height, fill=None):
    """Create a new pixel grid filled with a color (or None for transparent)."""
    return [[fill] * width for _ in range(height)]


def stamp_grid(dest, src, dx, dy):
    """Stamp src pixel grid onto dest at position (dx, dy). None = transparent (skip)."""
    for sy, row in enumerate(src):
        ty = dy + sy
        if ty < 0 or ty >= len(dest):
            continue
        for sx, pixel in enumerate(row):
            if pixel is None:
                continue
            tx = dx + sx
            if tx < 0 or tx >= len(dest[ty]):
                continue
            dest[ty][tx] = pixel


def grid_dimensions(grid):
    """Return (width, height) of a pixel grid."""
    if not grid:
        return (0, 0)
    return (max(len(r) for r in grid), len(grid))
