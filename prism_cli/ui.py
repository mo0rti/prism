"""Terminal UI helpers for the Prism CLI."""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import sys
import textwrap
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Style:
    reset: str = "\033[0m"
    bold: str = "\033[1m"
    dim: str = "\033[2m"
    cyan: str = "\033[36m"
    blue: str = "\033[94m"
    yellow: str = "\033[33m"
    green: str = "\033[32m"
    red: str = "\033[31m"
    magenta: str = "\033[35m"
    white: str = "\033[97m"


@dataclass(frozen=True)
class SelectOption:
    value: str
    label: str
    meta: str = ""
    description: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)
    accent: str = "white"


STYLE = Style()
ANSI_PATTERN = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
PALETTE_SIGNAL = object()


def supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty() and os.environ.get("TERM") != "dumb"


def colorize(text: str, *styles: str) -> str:
    if not supports_color():
        return text
    return "".join(styles) + text + STYLE.reset


def terminal_width(default: int = 88) -> int:
    return shutil.get_terminal_size(fallback=(default, 24)).columns


def supports_unicode() -> bool:
    encoding = (sys.stdout.encoding or "").lower()
    return "utf" in encoding


def divider(char: str | None = None) -> str:
    char = char or ("\u2500" if supports_unicode() else "-")
    return char * min(terminal_width(), 88)


def header(subtitle: str | None = None) -> str:
    wordmark = [
        " ____  ____  ___ ____  __  __",
        "|  _ \\|  _ \\|_ _/ ___||  \\/  |",
        "| |_) | |_) || |\\___ \\| |\\/| |",
        "|  __/|  _ < | | ___) | |  | |",
        "|_|   |_| \\_\\___|____/|_|  |_|",
    ]
    logo = "\n".join(colorize(line, STYLE.bold, STYLE.cyan) for line in wordmark)
    parts = [logo, divider()]
    if subtitle:
        parts.append(colorize(subtitle, STYLE.dim))
    parts.append("")
    return "\n".join(parts)


def session_panel(version: str, directory: str, context_label: str | None = None) -> str:
    lines = [
        f"{colorize('Prism CLI', STYLE.bold, STYLE.white)} {colorize(f'v{version}', STYLE.dim)}",
        f"{colorize('directory:', STYLE.dim)} {directory}",
    ]
    if context_label:
        lines.append(f"{colorize('context:', STYLE.dim)} {context_label}")
    return panel("Session", lines)


def section(title: str) -> str:
    return colorize(title, STYLE.bold, STYLE.blue)


def panel(title: str, body_lines: list[str]) -> str:
    width = min(terminal_width(), 88)
    inner_width = max(20, width - 4)
    if supports_unicode():
        left_top, right_top, left_bottom, right_bottom, horizontal, vertical = (
            "\u250c",
            "\u2510",
            "\u2514",
            "\u2518",
            "\u2500",
            "\u2502",
        )
        ellipsis = "\u2026"
    else:
        left_top, right_top, left_bottom, right_bottom, horizontal, vertical = "+", "+", "+", "+", "-", "|"
        ellipsis = "..."

    top = f"{left_top}{horizontal * inner_width}{right_top}"
    bottom = f"{left_bottom}{horizontal * inner_width}{right_bottom}"
    padded_title = f" {title} "
    if visible_length(padded_title) <= inner_width:
        top = f"{left_top}{padded_title}{horizontal * (inner_width - visible_length(padded_title))}{right_top}"

    lines = [top]
    for raw_line in body_lines:
        if visible_length(raw_line) > inner_width:
            line = truncate_visible(raw_line, max(0, inner_width - len(ellipsis))) + ellipsis
        else:
            line = raw_line
        lines.append(f"{vertical}{line}{' ' * (inner_width - visible_length(line))}{vertical}")
    lines.append(bottom)
    return "\n".join(lines)


def maturity_badge(label: str) -> str:
    styles = {
        "validated": (STYLE.green, STYLE.bold),
        "partial": (STYLE.yellow, STYLE.bold),
        "experimental": (STYLE.red, STYLE.bold),
    }
    color = styles.get(label, (STYLE.magenta, STYLE.bold))
    return colorize(label, *color)


def info(text: str) -> str:
    return colorize(text, STYLE.cyan)


def warn(text: str) -> str:
    return colorize(text, STYLE.yellow)


def success(text: str) -> str:
    return colorize(text, STYLE.green)


def error(text: str) -> str:
    return colorize(text, STYLE.red, STYLE.bold)


def review_key_value(label: str, value: str, *value_styles: str) -> list[str]:
    width = max(20, min(terminal_width(), 88) - 4)
    prefix = f"{label}: "
    value_text = str(value)
    wrapped = textwrap.wrap(value_text, width=max(12, width - len(prefix))) or [""]

    lines = [
        colorize(prefix, STYLE.dim) + colorize(wrapped[0], *(value_styles or (STYLE.white,))),
    ]
    continuation_prefix = " " * len(prefix)
    for extra_line in wrapped[1:]:
        lines.append(continuation_prefix + colorize(extra_line, *(value_styles or (STYLE.white,))))
    return lines


def interactive_multiselect(
    label: str,
    choices: tuple[tuple[str, str], ...],
    selected_keys: list[str],
    allow_empty: bool = False,
) -> list[str]:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return selected_keys

    selection = list(selected_keys)
    cursor_index = 0
    first_render = True
    rendered_lines = 0

    try:
        _set_cursor_visible(False)
        while True:
            lines = _render_multiselect_lines(label, choices, selection, cursor_index, allow_empty)
            if not first_render:
                _rewind_render(rendered_lines)
            sys.stdout.write("\n".join(lines) + "\n")
            sys.stdout.flush()
            rendered_lines = len(lines)
            first_render = False

            key = _read_key()
            if key == "cancel":
                raise KeyboardInterrupt
            if key in {"up", "k"}:
                cursor_index = (cursor_index - 1) % len(choices)
            elif key in {"down", "j"}:
                cursor_index = (cursor_index + 1) % len(choices)
            elif key == "space":
                option_key = choices[cursor_index][0]
                if option_key in selection:
                    selection.remove(option_key)
                else:
                    selection.append(option_key)
            elif key == "enter":
                if selection or allow_empty:
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    return selection
            elif key == "escape":
                if allow_empty:
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    return []
            elif key in {str(index) for index in range(1, min(len(choices), 10) + 1)}:
                index = int(key) - 1
                option_key = choices[index][0]
                if option_key in selection:
                    selection.remove(option_key)
                else:
                    selection.append(option_key)
                cursor_index = index
    finally:
        with contextlib.suppress(Exception):
            _set_cursor_visible(True)
            sys.stdout.flush()


def interactive_single_select(
    label: str,
    options: list[SelectOption],
    default_index: int = 0,
    allow_palette: bool = False,
) -> str | object:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return options[default_index].value

    cursor_index = default_index
    first_render = True
    rendered_lines = 0

    try:
        _set_cursor_visible(False)
        while True:
            lines = _render_single_select_lines(label, options, cursor_index, show_palette_hint=allow_palette)
            if not first_render:
                _rewind_render(rendered_lines)
            sys.stdout.write("\n".join(lines) + "\n")
            sys.stdout.flush()
            rendered_lines = len(lines)
            first_render = False

            key = _read_key()
            if key == "cancel":
                raise KeyboardInterrupt
            if key in {"up", "k"}:
                cursor_index = (cursor_index - 1) % len(options)
            elif key in {"down", "j"}:
                cursor_index = (cursor_index + 1) % len(options)
            elif key == "/" and allow_palette:
                sys.stdout.write("\n")
                sys.stdout.flush()
                return PALETTE_SIGNAL
            elif key in {"space", "enter"}:
                sys.stdout.write("\n")
                sys.stdout.flush()
                return options[cursor_index].value
            elif key in {str(index) for index in range(1, min(len(options), 10) + 1)}:
                cursor_index = int(key) - 1
    finally:
        with contextlib.suppress(Exception):
            _set_cursor_visible(True)
            sys.stdout.flush()


def interactive_command_palette(label: str, options: list[SelectOption]) -> str | None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return None

    query = ""
    cursor_index = 0
    first_render = True
    rendered_lines = 0

    try:
        _set_cursor_visible(False)
        while True:
            filtered = filter_select_options(options, query)
            if cursor_index >= len(filtered):
                cursor_index = max(0, len(filtered) - 1)

            lines = _render_command_palette_lines(label, query, filtered, cursor_index)
            if not first_render:
                _rewind_render(rendered_lines)
            sys.stdout.write("\n".join(lines) + "\n")
            sys.stdout.flush()
            rendered_lines = len(lines)
            first_render = False

            key = _read_key()
            if key == "cancel":
                raise KeyboardInterrupt
            if key == "escape":
                sys.stdout.write("\n")
                sys.stdout.flush()
                return None
            if key in {"up", "k"} and filtered:
                cursor_index = (cursor_index - 1) % len(filtered)
            elif key in {"down", "j"} and filtered:
                cursor_index = (cursor_index + 1) % len(filtered)
            elif key == "backspace":
                query = query[:-1]
            elif key == "enter" and filtered:
                sys.stdout.write("\n")
                sys.stdout.flush()
                return filtered[cursor_index].value
            elif len(key) == 1 and key.isprintable() and key != "/":
                query += key
    finally:
        with contextlib.suppress(Exception):
            _set_cursor_visible(True)
            sys.stdout.flush()


def _render_multiselect_lines(
    label: str,
    choices: tuple[tuple[str, str], ...],
    selected_keys: list[str],
    cursor_index: int,
    allow_empty: bool,
) -> list[str]:
    cursor = "\u203a" if supports_unicode() else ">"
    checked = "\u2713" if supports_unicode() else "x"
    unchecked = " "
    helper = "Use \u2191/\u2193 to move, space to toggle, enter to confirm."
    if not supports_unicode():
        helper = "Use up/down to move, space to toggle, enter to confirm."
    if allow_empty:
        helper += " Press Esc to submit an empty selection."

    lines = [section(label), colorize(helper, STYLE.dim)]
    for index, (key, description) in enumerate(choices, start=1):
        is_selected = key in selected_keys
        is_current = index - 1 == cursor_index
        pointer = f"{cursor} " if is_current else "  "
        marker = checked if is_selected else unchecked
        box = f"[{marker}]"
        line = f"{pointer}{box} {description}"
        if is_current and is_selected:
            line = colorize(line, STYLE.bold, STYLE.green)
        elif is_current:
            line = colorize(line, STYLE.bold, STYLE.cyan)
        elif is_selected:
            line = colorize(line, STYLE.green)
        else:
            line = colorize(line, STYLE.white)

        meta = colorize(f"  {index}  [{key}]", STYLE.dim)
        lines.append(_pad_line(line + meta))
    return lines


def _render_single_select_lines(
    label: str,
    options: list[SelectOption],
    cursor_index: int,
    show_palette_hint: bool = False,
) -> list[str]:
    cursor = "\u203a" if supports_unicode() else ">"
    checked = "\u2713" if supports_unicode() else "x"
    unchecked = " "
    helper = "Use \u2191/\u2193 to move, enter to choose."
    if not supports_unicode():
        helper = "Use up/down to move, enter to choose."
    if show_palette_hint:
        helper += " Press / for the command palette."

    lines = [section(label), colorize(helper, STYLE.dim)]
    for index, option in enumerate(options, start=1):
        is_current = index - 1 == cursor_index
        pointer = f"{cursor} " if is_current else "  "
        marker = checked if is_current else unchecked
        box = f"[{marker}]"
        title = f"{pointer}{box} {option.label}"
        if option.meta:
            title += f" {colorize(option.meta, STYLE.dim)}"

        if is_current:
            lines.append(_pad_line(colorize(title, STYLE.bold, STYLE.cyan)))
        else:
            lines.append(_pad_line(colorize(title, STYLE.white)))

        if option.description:
            lines.append(_pad_line("    " + colorize(option.description, STYLE.dim)))
        if option.accent:
            badge_styles = {
                "validated": (STYLE.green, STYLE.bold),
                "partial": (STYLE.yellow, STYLE.bold),
                "experimental": (STYLE.red, STYLE.bold),
                "advanced": (STYLE.magenta, STYLE.bold),
                "action": (STYLE.cyan, STYLE.bold),
            }.get(option.accent, (STYLE.white,))
            lines.append(_pad_line("    " + colorize(option.accent, *badge_styles)))
        for note in option.notes:
            lines.append(_pad_line("    " + warn(note)))
    return lines


def _render_command_palette_lines(
    label: str,
    query: str,
    options: list[SelectOption],
    cursor_index: int,
) -> list[str]:
    cursor = "\u203a" if supports_unicode() else ">"
    query_line = colorize(f"{cursor} /{query}", STYLE.bold, STYLE.cyan)
    body_lines = [
        colorize("Type to filter commands. Enter selects. Esc returns to the launcher.", STYLE.dim),
        "",
        query_line,
        "",
    ]

    if not options:
        body_lines.append(colorize("No matching commands.", STYLE.dim))
        return panel(label, body_lines).splitlines()

    display_options = options[:6]
    for index, option in enumerate(display_options):
        is_current = index == cursor_index
        command_text = f"/{option.value}"
        command_text = colorize(command_text, STYLE.bold, STYLE.cyan if is_current else STYLE.white)
        description = colorize(option.description, STYLE.dim) if option.description else ""

        if description:
            gap = max(2, 18 - len(option.value))
            line = f"{command_text}{' ' * gap}{description}"
        else:
            line = command_text
        if is_current:
            line = f"{cursor} {line}"
        else:
            line = f"  {line}"
        body_lines.append(line)

    if len(options) > len(display_options):
        remaining = len(options) - len(display_options)
        body_lines.append("")
        body_lines.append(colorize(f"... and {remaining} more command(s)", STYLE.dim))

    return panel(label, body_lines).splitlines()


def filter_select_options(options: list[SelectOption], query: str) -> list[SelectOption]:
    normalized = query.strip().lower()
    if not normalized:
        return list(options)

    filtered: list[SelectOption] = []
    for option in options:
        haystack = " ".join(
            [
                option.value,
                option.label,
                option.meta,
                option.description,
                " ".join(option.notes),
            ]
        ).lower()
        if normalized in haystack:
            filtered.append(option)
    return filtered


def _pad_line(line: str) -> str:
    width = min(terminal_width(), 88)
    visible = visible_length(line)
    if visible >= width:
        return line
    return line + (" " * (width - visible))


def visible_length(text: str) -> int:
    return len(ANSI_PATTERN.sub("", text))


def truncate_visible(text: str, max_visible_length: int) -> str:
    if max_visible_length <= 0:
        return ""

    visible = 0
    index = 0
    chunks: list[str] = []
    while index < len(text):
        if text[index] == "\033":
            match = ANSI_PATTERN.match(text, index)
            if match:
                chunks.append(match.group(0))
                index = match.end()
                continue
        if visible >= max_visible_length:
            break
        chunks.append(text[index])
        visible += 1
        index += 1
    return "".join(chunks)


def _rewind_render(lines: int) -> None:
    if lines <= 0:
        return
    sys.stdout.write(f"\033[{lines}F")
    sys.stdout.write("\033[J")


def _set_cursor_visible(visible: bool) -> None:
    sys.stdout.write("\033[?25h" if visible else "\033[?25l")


def _read_key() -> str:
    if os.name == "nt":
        import msvcrt

        first = msvcrt.getwch()
        if first in {"\x00", "\xe0"}:
            second = msvcrt.getwch()
            return {
                "H": "up",
                "P": "down",
                "K": "left",
                "M": "right",
            }.get(second, second)
        if first == "\r":
            return "enter"
        if first == " ":
            return "space"
        if first in {"\x08"}:
            return "backspace"
        if first in {"\x03", "\x1a"}:
            return "cancel"
        if first == "\x1b":
            return "escape"
        return first.lower()

    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        first = sys.stdin.read(1)
        if first == "\x1b":
            second = sys.stdin.read(1)
            if second == "[":
                third = sys.stdin.read(1)
                return {
                    "A": "up",
                    "B": "down",
                    "C": "right",
                    "D": "left",
                }.get(third, "escape")
            return "escape"
        if first in {"\r", "\n"}:
            return "enter"
        if first == " ":
            return "space"
        if first in {"\x08", "\x7f"}:
            return "backspace"
        if first in {"\x03", "\x1a"}:
            return "cancel"
        return first.lower()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
