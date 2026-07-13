from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.models import ParseResponse
from app.parsers import PARSERS, ParserError
from app.services.normalizer import normalize_text


def _cyrillic_score(value: str) -> int:
    return sum(1 for char in value if "\u0400" <= char <= "\u04ff")


def _mojibake_score(value: str) -> int:
    return sum(value.count(marker) for marker in ("Р", "С", "Ð", "Ñ", "â"))


def _repair_mojibake(value: str) -> str:
    for encoding in ("cp1251", "latin-1"):
        try:
            repaired = value.encode(encoding).decode("utf-8")
        except UnicodeError:
            continue
        if _cyrillic_score(repaired) >= 3 and _mojibake_score(repaired) < _mojibake_score(value):
            return repaired
    return value


@dataclass
class DocumentPayload:
    filename: str
    mime_type: str | None
    content: bytes


class DocumentExtractor:
    def __init__(self, parsers=None) -> None:
        self.parsers = parsers or PARSERS

    def _pick_parser(self, filename: str, mime_type: str | None):
        for parser in self.parsers:
            if parser.can_handle(filename, mime_type):
                return parser
        return None

    async def extract(self, payload: DocumentPayload) -> ParseResponse:
        parser = self._pick_parser(payload.filename, payload.mime_type)
        if parser is None:
            raise ParserError(f"Unsupported file type: {payload.filename}")

        result = await asyncio.to_thread(
            parser.extract,
            payload.content,
            payload.filename,
            payload.mime_type,
        )
        text = normalize_text(result.text)
        return ParseResponse(
            filename=_repair_mojibake(payload.filename),
            mime_type=payload.mime_type,
            source_type=result.source_type,
            characters=len(text),
            text=text,
            warnings=result.warnings,
        )

