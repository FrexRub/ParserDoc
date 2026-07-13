from __future__ import annotations

from app.parsers.base import BaseParser, ParseResult, ParserError
from app.services.normalizer import normalize_text


class PdfParser(BaseParser):
    def can_handle(self, filename: str, mime_type: str | None) -> bool:
        return filename.lower().endswith(".pdf") or mime_type == "application/pdf"

    def extract(self, content: bytes, filename: str, mime_type: str | None) -> ParseResult:
        try:
            import fitz  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise ParserError(
                "PDF parsing requires PyMuPDF (fitz). Install the dependency to enable PDF support."
            ) from exc

        try:
            doc = fitz.open(stream=content, filetype="pdf")
            text = "\n".join(page.get_text("text") for page in doc)
        except Exception as exc:  # noqa: BLE001
            raise ParserError(f"PDF parsing failed: {exc}") from exc

        return ParseResult(text=normalize_text(text), source_type="pdf")

