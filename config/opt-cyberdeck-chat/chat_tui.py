#!/usr/bin/env python3
# Deploy to: /opt/cyberdeck-chat/chat_tui.py on Pi
#
# Curses-based chat TUI for cyberdeck shell.
# Connects to <YOUR_LLM_HOST> via OpenAI-compatible SSE streaming.
# Uses only curses (stdlib) + httpx — no Textual dependency.

import curses
import httpx
import json
import os
import select
import ssl
import sys
import threading
import textwrap

from cyberdeck_colors import init_colors, CP_WHITE, CP_PINK_HEADER, CP_MINT, CP_DIM, CP_DIVIDER, CP_REASONING, CP_BLUE
import cyberdeck_touch

sys.path.insert(0, "/opt/cyberdeck-shell")
try:
    from cyberdeck_switch import switch_to
except Exception:
    def switch_to(app_name):
        return False


# Escape sequences for F-keys (full sequences including ESC byte)
_ESC_SEQ_MAP = {
    # VT100 style
    b"\x1bOP": "F1", b"\x1bOQ": "F2", b"\x1bOR": "F3", b"\x1bOS": "F4",
    # Linux console / fbterm style
    b"\x1b[[A": "F1", b"\x1b[[B": "F2", b"\x1b[[C": "F3",
    b"\x1b[[D": "F4", b"\x1b[[E": "F5",
    # xterm style
    b"\x1b[11~": "F1", b"\x1b[12~": "F2", b"\x1b[13~": "F3",
    b"\x1b[14~": "F4", b"\x1b[15~": "F5", b"\x1b[17~": "F6",
    b"\x1b[18~": "F7",
    # arrows / other
    b"\x1b[A": "UP", b"\x1b[B": "DOWN", b"\x1b[C": "RIGHT",
    b"\x1b[D": "LEFT", b"\x1b[5~": "PGUP", b"\x1b[6~": "PGDN",
    b"\x1b[3~": "DEL",
}


def _read_esc_seq_raw():
    """Read the bytes after the leading ESC of an escape sequence.

    Returns bytes without the leading ESC. Recognizes SS3 (\\x1bO?),
    CSI (\\x1b[...<final>), and Linux console (\\x1b[[?). Bare ESC → b"".
    """
    fd = sys.stdin.fileno()
    if not select.select([fd], [], [], 0.05)[0]:
        return b""
    first = os.read(fd, 1)
    if not first:
        return b""
    if first == b"O":
        if select.select([fd], [], [], 0.05)[0]:
            nxt = os.read(fd, 1)
            if nxt:
                return first + nxt
        return first
    if first != b"[":
        return first
    buf = first
    for i in range(16):
        if not select.select([fd], [], [], 0.05)[0]:
            break
        ch = os.read(fd, 1)
        if not ch:
            break
        buf += ch
        if i == 0 and ch == b"[":
            if select.select([fd], [], [], 0.05)[0]:
                tail = os.read(fd, 1)
                if tail:
                    buf += tail
            return buf
        if 0x40 <= ch[0] <= 0x7E:
            break
    return buf


def _handle_fkey(key):
    """Switch to the app mapped to an F-key."""
    mapping = {
        "F1": "term", "F2": "chat", "F3": "pet",
        "F4": "reader", "F5": "dash", "F6": "wifi", "F7": "bt",
    }
    app = mapping.get(key)
    if app:
        switch_to(app)
        return True
    return False

ENDPOINT = "https://<YOUR_LLM_HOST>/v1/chat/completions"
MODEL = "default"
MAX_TOOL_ROUNDS = 10
API_KEY = os.environ.get("LLM_API_KEY", "")


class ChatApp:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.messages = []          # OpenAI message history
        self.display_lines = []     # rendered lines for display
        self.input_buf = ""
        self.scroll_offset = 0
        self.lock = threading.Lock()
        self.streaming = False
        self.touch_active = False
        self.mouse_active = False
        self.current_model = None
        self.reasoning_buf = ""         # Full reasoning text (separate from display_lines)
        self.reasoning_tokens = 0       # Word count as token proxy
        self.overlay_expanded = False   # Tab toggle state
        self.overlay_visible = False    # True once first reasoning chunk arrives
        self.content_started = False    # True once first content chunk arrives
        self._auto_collapsed = False    # True after first auto-collapse fires
        self.overlay_scroll = 0         # Scroll offset within expanded overlay

    def run(self):
        curses.curs_set(1)
        # Short escape delay so unrecognized sequences resolve quickly
        try:
            curses.set_escdelay(50)
        except Exception:
            pass
        self.stdscr.nodelay(False)
        self.stdscr.timeout(100)  # 100ms poll for display updates
        init_colors()

        def _on_scroll(delta):
            with self.lock:
                if self.overlay_expanded:
                    # Overlay: positive delta = swipe up = scroll up (lower offset)
                    if delta > 0:
                        self.overlay_scroll = max(0, self.overlay_scroll - delta)
                    else:
                        self.overlay_scroll -= delta  # negative delta → increase offset
                else:
                    if delta > 0:
                        self.scroll_offset += delta
                    else:
                        self.scroll_offset = max(0, self.scroll_offset + delta)

        def _on_tap():
            with self.lock:
                if self.input_buf.strip() and not self.streaming:
                    self.submit()
                else:
                    self.scroll_offset = 0

        self.touch_active = cyberdeck_touch.start_touch_listener(_on_scroll, _on_tap)
        self.mouse_active = cyberdeck_touch.start_mouse_listener(_on_scroll, _on_tap)
        touch_msg = " | swipe scroll, tap = send" if (self.touch_active or self.mouse_active) else ""
        self.add_status(f"cyberdeck chat — enter to send, ctrl+c to quit{touch_msg}")
        self.draw()

        while True:
            try:
                ch = self.stdscr.get_wch()
            except curses.error:
                # timeout — redraw to pick up touch scroll + streaming updates
                self.draw()
                continue

            if ch == '\x03':  # Ctrl+C
                break
            elif ch == '\x11':  # Ctrl+Q
                break
            elif ch == curses.KEY_F1:
                switch_to("term")
                break
            elif ch == curses.KEY_F2:
                switch_to("chat")
                break
            elif ch == curses.KEY_F3:
                switch_to("pet")
                break
            elif ch == curses.KEY_F4:
                switch_to("reader")
                break
            elif ch == curses.KEY_F5:
                switch_to("dash")
                break
            elif ch == curses.KEY_F6:
                switch_to("wifi")
                break
            elif ch == curses.KEY_F7:
                switch_to("bt")
                break
            elif ch in (27, '\x1b'):  # ESC — read rest from stdin directly
                rest = _read_esc_seq_raw()
                if not rest:  # bare Esc = back/quit
                    break
                seq = b"\x1b" + rest
                key = _ESC_SEQ_MAP.get(seq)
                if _handle_fkey(key):
                    break
                if key == "UP":
                    with self.lock:
                        if self.overlay_expanded:
                            self.overlay_scroll = max(0, self.overlay_scroll - 1)
                        else:
                            self.scroll_offset += 1
                    self.draw()
                elif key == "DOWN":
                    with self.lock:
                        if self.overlay_expanded:
                            self.overlay_scroll += 1
                        else:
                            self.scroll_offset = max(0, self.scroll_offset - 1)
                    self.draw()
                elif key == "PGUP":
                    self.scroll_offset += 5
                    self.draw()
                elif key == "PGDN":
                    self.scroll_offset = max(0, self.scroll_offset - 5)
                    self.draw()
            elif ch in ('\n', '\r', curses.KEY_ENTER):
                if self.input_buf.strip() and not self.streaming:
                    self.submit()
            elif ch in ('\x7f', '\b', curses.KEY_BACKSPACE, 263):
                self.input_buf = self.input_buf[:-1]
                self.draw()
            elif isinstance(ch, str) and len(ch) == 1 and ch.isprintable():
                self.input_buf += ch
                self.draw()
            elif ch == curses.KEY_PPAGE:  # Page Up
                self.scroll_offset += 5
                self.draw()
            elif ch == curses.KEY_NPAGE:  # Page Down
                self.scroll_offset = max(0, self.scroll_offset - 5)
                self.draw()
            elif ch == curses.KEY_UP:
                with self.lock:
                    if self.overlay_expanded:
                        self.overlay_scroll = max(0, self.overlay_scroll - 1)
                    else:
                        self.scroll_offset += 1
                self.draw()
            elif ch == curses.KEY_DOWN:
                with self.lock:
                    if self.overlay_expanded:
                        self.overlay_scroll += 1
                    else:
                        self.scroll_offset = max(0, self.scroll_offset - 1)
                self.draw()
            elif ch == curses.KEY_RESIZE:
                self.draw()
            elif ch == '\t':  # Tab -- toggle reasoning overlay per D-03
                with self.lock:
                    if self.overlay_visible:
                        self.overlay_expanded = not self.overlay_expanded
                self.draw()

    def submit(self):
        text = self.input_buf.strip()
        self.input_buf = ""
        with self.lock:
            self.reasoning_buf = ""
            self.reasoning_tokens = 0
            self.overlay_visible = False
            self.overlay_expanded = False
            self.content_started = False
            self._auto_collapsed = False
            self.overlay_scroll = 0
        self.add_user_line(text)
        self.messages.append({"role": "user", "content": text})
        self.streaming = True
        self.draw()
        t = threading.Thread(target=self.stream_response, daemon=True)
        t.start()

    def _append_line(self, entry):
        """Append entry and preserve reader's scroll position.

        If scrolled up (offset > 0), bump offset so the visible window
        stays locked to the same content instead of sliding down. If at
        bottom (offset == 0), stay at bottom and follow new content.

        Note: `rendered` in draw() applies word-wrap, so one entry may
        expand to >1 display lines. We approximate with 1 bump per
        append — draw() clamps offset to max_scroll so overshooting is
        harmless and undershooting causes a small (≤ wrap-count) drift.
        """
        self.display_lines.append(entry)
        if self.scroll_offset > 0:
            self.scroll_offset += 1

    def add_user_line(self, text):
        with self.lock:
            self._append_line(("you", text))

    def add_bot_line(self, text):
        with self.lock:
            self._append_line(("ai", text))

    def update_reasoning(self, text):
        with self.lock:
            self.reasoning_buf = text
            self.reasoning_tokens = len(text.split())
            if not self.overlay_visible:
                self.overlay_visible = True
                self.overlay_expanded = True  # auto-expand on first reasoning
            # Auto-scroll to bottom while streaming (follow new content)
            if self.overlay_expanded and not self.content_started:
                self.overlay_scroll = 999999  # draw() clamps to max_scroll

    def update_bot_line(self, text):
        with self.lock:
            if self.display_lines and self.display_lines[-1][0] == "ai":
                self.display_lines[-1] = ("ai", text)
            else:
                self.display_lines.append(("ai", text))

    def add_status(self, text):
        with self.lock:
            self._append_line(("status", text))

    def add_tool_line(self, name):
        with self.lock:
            self._append_line(("tool", name))

    def stream_response(self):
        try:
            self._run_chat_loop()
        except httpx.ConnectError:
            self.update_bot_line("[connection failed — check VPN]")
        except httpx.TimeoutException:
            self.update_bot_line("[request timed out]")
        except Exception as e:
            self.update_bot_line(f"[error: {e}]")
        finally:
            self.streaming = False

    def _run_chat_loop(self):
        # Trust mkcert self-signed cert on internal Tailscale network
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        def dbg(msg):
            try:
                with open("/tmp/chat_tui_debug.log", "a") as _f:
                    _f.write(f"{msg}\n")
            except OSError:
                pass

        dbg(f"=== NEW REQUEST, msg_count={len(self.messages)} ===")

        for _ in range(MAX_TOOL_ROUNDS):
            collected = ""
            reasoning = ""
            tool_calls_buf = []
            finish = None
            chunk_count = 0

            headers = {}
            if API_KEY:
                headers["Authorization"] = f"Bearer {API_KEY}"
            with httpx.Client(timeout=httpx.Timeout(120.0, connect=5.0), verify=ctx) as client:
                with client.stream("POST", ENDPOINT, json={
                    "model": MODEL, "messages": self.messages, "stream": True,
                    # NOTE: gemma4 thinking mode burns ~450 tokens reasoning
                    # before emitting any content. Server currently caps output
                    # around ~430-485 tokens → finish_reason:"length" fires before
                    # real response starts. Raise llama.cpp server -n / --predict
                    # flag server-side; client max_tokens is ignored by this build.
                    "max_tokens": 4096,
                }, headers=headers) as resp:
                    resp.raise_for_status()
                    for raw_line in resp.iter_lines():
                        line = raw_line.strip()
                        if not line.startswith("data: "):
                            continue
                        payload = line[6:]
                        if payload == "[DONE]":
                            break
                        try:
                            data = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        if not self.current_model and data.get("model"):
                            self.current_model = data["model"]

                        choice = data["choices"][0]
                        delta = choice.get("delta", {})
                        finish = choice.get("finish_reason") or finish
                        chunk_count += 1

                        # Reasoning stream (gemma4 thinking mode)
                        reason_chunk = delta.get("reasoning_content") or ""
                        if reason_chunk:
                            reasoning += reason_chunk
                            self.update_reasoning(reasoning)

                        # Content stream
                        chunk = delta.get("content") or ""
                        if chunk:
                            collected += chunk
                            if not self.content_started:
                                with self.lock:
                                    self.content_started = True
                            self.update_bot_line(collected)

                        if chunk_count <= 3 or finish or chunk:
                            dbg(f"chunk#{chunk_count} keys={list(delta.keys())} finish={finish!r} reas_len={len(reasoning)} coll_len={len(collected)}")

                        if "tool_calls" in delta:
                            for tc_d in delta["tool_calls"]:
                                idx = tc_d.get("index", 0)
                                while len(tool_calls_buf) <= idx:
                                    tool_calls_buf.append(
                                        {"id": "", "type": "function",
                                         "function": {"name": "", "arguments": ""}})
                                tc = tool_calls_buf[idx]
                                if tc_d.get("id"):
                                    tc["id"] = tc_d["id"]
                                fn = tc_d.get("function", {})
                                if fn.get("name"):
                                    tc["function"]["name"] += fn["name"]
                                if fn.get("arguments"):
                                    tc["function"]["arguments"] += fn["arguments"]

                        if finish in ("stop", "tool_calls"):
                            break

            dbg(f"stream end: finish={finish!r} chunks={chunk_count} coll_len={len(collected)} reas_len={len(reasoning)} tool_calls={len(tool_calls_buf)}")
            if finish == "stop" or (not tool_calls_buf and finish != "tool_calls"):
                if collected:
                    self.messages.append({"role": "assistant", "content": collected})
                elif reasoning:
                    # Model only produced reasoning with no content.
                    # Reasoning already visible in overlay — just show a note
                    # in chat history so user knows there was no real response.
                    if finish == "length":
                        self.update_bot_line("[hit output token cap while thinking — raise llama.cpp -n flag]")
                    else:
                        self.update_bot_line("[reasoning only — see overlay]")
                return

            if finish == "tool_calls" and tool_calls_buf:
                self.messages.append({
                    "role": "assistant", "content": None,
                    "tool_calls": tool_calls_buf,
                })
                for tc in tool_calls_buf:
                    self.add_tool_line(tc["function"]["name"] or "unknown")
                for tc in tool_calls_buf:
                    self.messages.append({
                        "role": "tool", "tool_call_id": tc["id"],
                        "content": "[proxy executed]",
                    })
                self.add_bot_line("...")
                continue
            break

    def draw(self):
        with self.lock:
            try:
                self.stdscr.erase()
                h, w = self.stdscr.getmaxyx()
                if h < 3 or w < 10:
                    return

                # Auto-collapse: once content starts, collapse overlay (per D-02)
                # Only auto-collapse once — after that, Tab toggle controls it
                if self.content_started and self.overlay_expanded and not self._auto_collapsed:
                    self.overlay_expanded = False
                    self._auto_collapsed = True

                # Calculate overlay height
                overlay_h = 0
                if self.overlay_visible:
                    if self.overlay_expanded:
                        max_overlay = min(h // 2, 8)  # Cap at 8 rows per Pitfall 3
                        wrapped = textwrap.wrap(self.reasoning_buf, w - 4) or [""]
                        overlay_h = min(len(wrapped) + 2, max_overlay)  # +2 for border
                    else:
                        overlay_h = 1  # collapsed summary line


                # Region boundaries
                hist_start = overlay_h
                hist_end = h - 2  # divider at h-2, input at h-1
                hist_h = hist_end - hist_start

                # Render overlay (rows 0..overlay_h-1)
                self._draw_overlay(w, overlay_h)

                # Render chat history (rows hist_start..hist_end-1)
                self._draw_history(hist_start, hist_h, w)

                # Render divider (row h-2)
                self._draw_divider(h - 2, w)

                # Render input (row h-1)
                self._draw_input(h - 1, w)

                self.stdscr.refresh()
            except curses.error:
                pass

    def _draw_overlay(self, w, overlay_h):
        """Render reasoning overlay at top of screen. Per D-01, D-02, D-03, D-04."""
        if not self.overlay_visible or overlay_h == 0:
            return

        if not self.overlay_expanded:
            # Collapsed: one-line summary in CP_REASONING (per D-04)
            summary = f"~ thinking ({self.reasoning_tokens} tokens) [Tab]"
            self.stdscr.addnstr(0, 0, summary, w - 1,
                               curses.color_pair(CP_REASONING))
            return

        # Expanded: box border in CP_DIVIDER, text in CP_REASONING + A_DIM (per D-04)
        wrapped = textwrap.wrap(self.reasoning_buf, w - 4) or [""]
        content_rows = overlay_h - 2  # rows available for text (minus borders)

        # Clamp overlay_scroll
        max_scroll = max(0, len(wrapped) - content_rows)
        if self.overlay_scroll > max_scroll:
            self.overlay_scroll = max_scroll

        # Top border — show token count + scroll position if scrollable
        scroll_hint = f" {self.reasoning_tokens}tok"
        if len(wrapped) > content_rows:
            scroll_hint += f" [{self.overlay_scroll + content_rows}/{len(wrapped)}]"
        scroll_hint += " "
        top = "\u250c" + "\u2500" * max(0, w - 3 - len(scroll_hint)) + scroll_hint + "\u2510"
        self.stdscr.addnstr(0, 0, top[:w - 1], w - 1, curses.color_pair(CP_DIVIDER))

        # Visible slice of wrapped text
        start = self.overlay_scroll
        visible = wrapped[start:start + content_rows]

        for i, line in enumerate(visible):
            row = i + 1
            padded = line.ljust(w - 4)[:w - 4]
            interior = "\u2502 " + padded + " \u2502"
            self.stdscr.addnstr(row, 0, interior[:w - 1], w - 1,
                               curses.color_pair(CP_REASONING) | curses.A_DIM)
            # Redraw border chars in CP_DIVIDER
            self.stdscr.addnstr(row, 0, "\u2502", 1,
                               curses.color_pair(CP_DIVIDER))
            try:
                self.stdscr.addnstr(row, w - 2, "\u2502", 1,
                                   curses.color_pair(CP_DIVIDER))
            except curses.error:
                pass

        bot = "\u2514" + "\u2500" * max(0, w - 3) + "\u2518"
        self.stdscr.addnstr(overlay_h - 1, 0, bot, w - 1,
                           curses.color_pair(CP_DIVIDER))

    def _draw_history(self, start_row, hist_h, w):
        """Render chat history lines in the middle region."""
        if hist_h <= 0:
            return

        # Word-wrap display_lines (reasoning kind no longer appears here)
        rendered = []
        for kind, text in self.display_lines:
            if kind == "you":
                prefix = "you: "
                lines = textwrap.wrap(prefix + text, w - 1) or [prefix]
                for i, ln in enumerate(lines):
                    rendered.append(("you" if i == 0 else "you_cont", ln))
            elif kind == "ai":
                prefix = "ai: "
                lines = textwrap.wrap(prefix + text, w - 1) or [prefix]
                for i, ln in enumerate(lines):
                    rendered.append(("ai" if i == 0 else "ai_cont", ln))
            elif kind == "tool":
                rendered.append(("tool", f"  [tool: {text}]"))
            elif kind == "status":
                rendered.append(("status", text))
            # NOTE: "reasoning" kind no longer appears in display_lines

        # Clamp scroll_offset
        max_scroll = max(0, len(rendered) - hist_h)
        if self.scroll_offset > max_scroll:
            self.scroll_offset = max_scroll

        end = len(rendered) - self.scroll_offset
        start = max(0, end - hist_h)
        visible = rendered[start:end]

        for i, (kind, text) in enumerate(visible):
            if i >= hist_h:
                break
            row = start_row + i
            if kind == "you":
                self.stdscr.addnstr(row, 0, "you: ", w - 1,
                                   curses.color_pair(CP_WHITE) | curses.A_BOLD)
                self.stdscr.addnstr(row, 4, text[4:], w - 5,
                                   curses.color_pair(CP_WHITE))
            elif kind == "you_cont":
                self.stdscr.addnstr(row, 0, text, w - 1,
                                   curses.color_pair(CP_WHITE))
            elif kind == "ai":
                self.stdscr.addnstr(row, 0, "ai: ", w - 1,
                                   curses.color_pair(CP_PINK_HEADER) | curses.A_BOLD)
                self.stdscr.addnstr(row, 4, text[4:], w - 5,
                                   curses.color_pair(CP_WHITE))
            elif kind == "ai_cont":
                self.stdscr.addnstr(row, 0, text, w - 1,
                                   curses.color_pair(CP_WHITE))
            elif kind == "tool":
                # D-09: Tool calls in CP_BLUE (was CP_REASONING)
                self.stdscr.addnstr(row, 0, text, w - 1,
                                   curses.color_pair(CP_BLUE))
            elif kind == "status":
                # D-10: Status in CP_MINT (was CP_DIVIDER)
                self.stdscr.addnstr(row, 0, text, w - 1,
                                   curses.color_pair(CP_MINT))

    def _draw_divider(self, div_y, w):
        """Render divider bar with model tag or scroll indicator."""
        if self.scroll_offset > 0:
            indicator = f" {self.scroll_offset} more below "
            pad = max(0, w - 1 - len(indicator)) // 2
            divider = "\u2500" * pad + indicator + "\u2500" * pad
            divider = divider[:w - 1]
        else:
            model_tag = f" {self.current_model or MODEL} "
            pad = max(0, w - 1 - len(model_tag)) // 2
            divider = ("\u2500" * pad + model_tag
                       + "\u2500" * max(0, w - 1 - pad - len(model_tag)))
        self.stdscr.addnstr(div_y, 0, divider, w - 1,
                           curses.color_pair(CP_DIVIDER))

    def _draw_input(self, inp_y, w):
        """Render input prompt and buffer."""
        prompt = "\u2665 "
        self.stdscr.addnstr(inp_y, 0, prompt, w - 1,
                           curses.color_pair(CP_PINK_HEADER))
        avail = w - len(prompt) - 1
        visible_input = (self.input_buf[-avail:]
                         if len(self.input_buf) > avail else self.input_buf)
        self.stdscr.addnstr(inp_y, len(prompt), visible_input, avail,
                           curses.color_pair(CP_WHITE))
        self.stdscr.move(inp_y, len(prompt) + len(visible_input))


def main(stdscr):
    app = ChatApp(stdscr)
    app.run()


if __name__ == "__main__":
    curses.wrapper(main)
