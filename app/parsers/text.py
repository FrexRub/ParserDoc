from __future__ import annotations

import csv
import io
import json
from html.parser import HTMLParser

from app.parsers.base import BaseParser, ParseResult
from app.services.normalizer import normalize_text


def _decode_best_effort(content: bytes) -> str:
    for encoding in ("utf-8", "cp1251", "windows-1251", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


class _HTMLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data)

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"p", "div", "br", "li", "tr", "section", "article", "header", "footer"}:
            self.parts.append("\n")


class PlainTextParser(BaseParser):
    def can_handle(self, filename: str, mime_type: str | None) -> bool:
        lower = filename.lower()
        return lower.endswith((".txt", ".csv", ".json", ".xml", ".html", ".htm"))

    def extract(self, content: bytes, filename: str, mime_type: str | None) -> ParseResult:
        lower = filename.lower()
        raw = _decode_best_effort(content)
        source_type = lower.rsplit(".", 1)[-1]

        if lower.endswith((".html", ".htm")):
            stripper = _HTMLStripper()
            stripper.feed(raw)
            text = normalize_text("".join(stripper.parts))
            return ParseResult(text=text, source_type=source_type)

        if lower.endswith(".csv"):
            rows = list(csv.reader(io.StringIO(raw)))
            text = normalize_text("\n".join(" | ".join(cell.strip() for cell in row) for row in rows))
            return ParseResult(text=text, source_type=source_type)

        if lower.endswith(".json"):
            try:
                parsed = json.loads(raw)
                text = normalize_text(json.dumps(parsed, ensure_ascii=False, indent=2))
            except json.JSONDecodeError:
                text = normalize_text(raw)
            return ParseResult(text=text, source_type=source_type)

        return ParseResult(text=normalize_text(raw), source_type=source_type)

