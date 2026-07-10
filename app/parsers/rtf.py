from __future__ import annotations

import re

from app.parsers.base import BaseParser, ParseResult
from app.services.normalizer import normalize_text


class RtfParser(BaseParser):
    def can_handle(self, filename: str, mime_type: str | None) -> bool:
        return filename.lower().endswith(".rtf") or mime_type == "application/rtf"

    def extract(self, content: bytes, filename: str, mime_type: str | None) -> ParseResult:
        try:
            from striprtf.striprtf import rtf_to_text  # type: ignore

            text = rtf_to_text(content.decode("utf-8", errors="ignore"))
        except Exception:
            raw = content.decode("utf-8", errors="ignore")
            raw = re.sub(r"\\'[0-9a-fA-F]{2}", " ", raw)
            raw = re.sub(r"\\[a-zA-Z]+\d* ?", " ", raw)
            raw = raw.replace("{", " ").replace("}", " ")
            text = re.sub(r"\s+", " ", raw)
        return ParseResult(text=normalize_text(text), source_type="rtf")

