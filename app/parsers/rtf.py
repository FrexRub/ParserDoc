from __future__ import annotations

import codecs
import re

from app.parsers.base import BaseParser, ParseResult
from app.services.normalizer import normalize_text


_DESTINATIONS_TO_SKIP = {
    "annotation",
    "author",
    "colortbl",
    "comment",
    "datastore",
    "filetbl",
    "fonttbl",
    "footer",
    "footerf",
    "footerl",
    "footerr",
    "header",
    "headerf",
    "headerl",
    "headerr",
    "info",
    "listoverridetable",
    "listtable",
    "object",
    "pict",
    "revtbl",
    "stylesheet",
    "themedata",
    "colorschememapping",
    "datafield",
    "latentstyles",
    "generator",
    "rsidtbl",
    "xmlnstbl",
}

_CONTROL_CHARS = {
    "line": "\n",
    "par": "\n",
    "sect": "\n",
    "tab": "\t",
}
_LEADING_NOISE = re.compile(r"^[^0-9A-Za-z\u0400-\u04ff]+")


def _rtf_codepage(raw: str) -> str:
    match = re.search(r"\\ansicpg(\d+)", raw)
    if not match:
        return "cp1252"

    encoding = f"cp{match.group(1)}"
    try:
        codecs.lookup(encoding)
    except LookupError:
        return "cp1252"
    return encoding


def _unicode_char(value: int) -> str:
    if value < 0:
        value += 65536
    try:
        return chr(value)
    except ValueError:
        return ""


def _fallback_rtf_to_text(raw: str) -> str:
    encoding = _rtf_codepage(raw)
    parts: list[str] = []
    stack: list[bool] = []
    ignorable = False
    unicode_skip = 1
    pending_skip = 0
    index = 0

    while index < len(raw):
        char = raw[index]

        if char == "{":
            stack.append(ignorable)
            index += 1
            continue

        if char == "}":
            ignorable = stack.pop() if stack else False
            index += 1
            continue

        if char != "\\":
            if pending_skip:
                pending_skip -= 1
            elif not ignorable and char not in "\r\n":
                parts.append(char)
            index += 1
            continue

        index += 1
        if index >= len(raw):
            break

        escaped = raw[index]
        if escaped in "{}\\":
            if pending_skip:
                pending_skip -= 1
            elif not ignorable:
                parts.append(escaped)
            index += 1
            continue

        if escaped == "*":
            ignorable = True
            index += 1
            continue

        if escaped == "'":
            hex_value = raw[index + 1 : index + 3]
            if len(hex_value) == 2:
                if pending_skip:
                    pending_skip -= 1
                elif not ignorable:
                    try:
                        parts.append(bytes.fromhex(hex_value).decode(encoding, errors="ignore"))
                    except ValueError:
                        pass
                index += 3
                continue

        if escaped.isalpha():
            start = index
            while index < len(raw) and raw[index].isalpha():
                index += 1
            word = raw[start:index]

            sign = 1
            if index < len(raw) and raw[index] == "-":
                sign = -1
                index += 1
            num_start = index
            while index < len(raw) and raw[index].isdigit():
                index += 1
            argument = None
            if num_start != index:
                argument = sign * int(raw[num_start:index])
            if index < len(raw) and raw[index] == " ":
                index += 1

            if word in _DESTINATIONS_TO_SKIP:
                ignorable = True
                continue
            if word == "uc" and argument is not None:
                unicode_skip = max(argument, 0)
                continue
            if pending_skip:
                pending_skip -= 1
                continue
            if ignorable:
                continue
            if word == "u" and argument is not None:
                parts.append(_unicode_char(argument))
                pending_skip = unicode_skip
                continue
            if word in _CONTROL_CHARS:
                parts.append(_CONTROL_CHARS[word])
            continue

        if pending_skip:
            pending_skip -= 1
        elif not ignorable and escaped in "~_-":
            parts.append(" " if escaped in "~_" else "-")
        index += 1

    text = re.sub(r"^\d+[)\]}.,;:]+(?=[A-Za-z\u0400-\u04ff])", "", "".join(parts))
    return _LEADING_NOISE.sub("", text)


class RtfParser(BaseParser):
    def can_handle(self, filename: str, mime_type: str | None) -> bool:
        return filename.lower().endswith(".rtf") or mime_type in {
            "application/rtf",
            "text/rtf",
        }

    def extract(self, content: bytes, filename: str, mime_type: str | None) -> ParseResult:
        header = content.decode("latin-1", errors="ignore")
        raw = content.decode(_rtf_codepage(header), errors="ignore")
        try:
            from striprtf.striprtf import rtf_to_text  # type: ignore

            text = rtf_to_text(raw)
        except Exception:
            text = _fallback_rtf_to_text(raw)
        return ParseResult(text=normalize_text(text), source_type="rtf")

