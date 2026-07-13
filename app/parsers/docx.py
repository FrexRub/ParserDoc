from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree as ET

from app.parsers.base import BaseParser, ParseResult, ParserError
from app.services.normalizer import normalize_text

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class DocxParser(BaseParser):
    def can_handle(self, filename: str, mime_type: str | None) -> bool:
        return filename.lower().endswith(".docx") or mime_type in {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        }

    def extract(self, content: bytes, filename: str, mime_type: str | None) -> ParseResult:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                xml_data = zf.read("word/document.xml")
        except Exception as exc:  # noqa: BLE001
            raise ParserError(f"DOCX parsing failed: {exc}") from exc

        root = ET.fromstring(xml_data)
        parts: list[str] = []
        for element in root.iter():
            if element.tag == f"{W_NS}t" and element.text:
                parts.append(element.text)
            elif element.tag == f"{W_NS}p":
                parts.append("\n")
        return ParseResult(text=normalize_text("".join(parts)), source_type="docx")

