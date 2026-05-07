#!/usr/bin/env python3
# Deploy to: /opt/cyberdeck-shared/cyberdeck_colors.py on Pi
#
# Shared color palette for all cyberdeck TUIs.
# Import with: from cyberdeck_colors import init_colors, CP_WHITE, CP_PINK_HEADER, ...
# Called once per TUI after curses.start_color().
#
# fbterm 16-color palette slots (from ~/.fbtermrc silenvx build):
#   slot  0: #2A1F28 (dark bg)        slot  1: #E8A0BF (pink)
#   slot  2: #C8E6A0 (mint green)     slot  3: #F5DEB3 (wheat)
#   slot  4: #B0C4DE (steel blue)     slot  5: #FF00CC (deep pink)
#   slot  6: #A5F2E5 (mint)           slot  7: #FFAFD7 (candy pink bg)
#   slot  8: #6B5466 (muted purple)   slot  9: #F8C0DF (soft pink)
#   slot 10: #D8F6C0 (pale mint)      slot 11: #FFEDC3 (pale yellow)
#   slot 12: #D0E4EE (pale blue)      slot 13: #FF87C7 (hot pink)
#   slot 14: #C5FFF5 (pale mint)      slot 15: #FFFFFF (white)

import curses

# Curses color pair numbers -- canonical across all TUIs.
# These are PAIR numbers (argument to curses.color_pair()), not slot numbers.
CP_WHITE       = 1   # white text -- general content, values
CP_PINK_HEADER = 2   # deep pink (slot 5 = #FF5FAF) -- headers, ai: labels
CP_MINT        = 3   # mint (slot 6 = #A5F2E5) -- up indicator, connected state
CP_DIM         = 4   # muted purple (slot 8 = #6B5466) -- offline, down, secondary
CP_DIVIDER     = 5   # pale mint (slot 14 = #C5FFF5) -- dividers, footers, status bars
CP_REASONING   = 6   # pale yellow (slot 11 = #FFEDC3) -- reasoning, secondary info
CP_SELECTED_BG = 7   # white on deep pink -- selected list item highlight
CP_BLUE        = 8   # pale blue (slot 12 = #D0E4EE) -- blue accent, header labels


def init_colors():
    """Initialize curses color pairs for candy pink fbterm theme.

    Must be called after curses.start_color(). Uses only color slots 0-15
    (valid in fbterm 16-color mode). Never reference slot numbers > 15
    as a foreground/background argument -- fbterm raises ValueError at runtime.
    """
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(CP_WHITE,       15,  -1)   # white on transparent
    curses.init_pair(CP_PINK_HEADER,  5,  -1)   # deep pink on transparent
    curses.init_pair(CP_MINT,         6,  -1)   # mint on transparent
    curses.init_pair(CP_DIM,          8,  -1)   # muted purple on transparent
    curses.init_pair(CP_DIVIDER,     14,  -1)   # pale mint on transparent
    curses.init_pair(CP_REASONING,   11,  -1)   # pale yellow on transparent
    curses.init_pair(CP_SELECTED_BG, 15,   5)   # white on deep pink
    curses.init_pair(CP_BLUE,        12,  -1)   # pale blue on transparent
