from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.models import ParseResponse
from app.parsers import PARSERS, ParserError
from app.services.normalizer import normalize_text


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
            filename=payload.filename,
            mime_type=payload.mime_type,
            source_type=result.source_type,
            characters=len(text),
            text=text,
            warnings=result.warnings,
        )

