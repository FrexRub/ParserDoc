from __future__ import annotations

from app.parsers.base import BaseParser, ParseResult, ParserError
from app.services.normalizer import normalize_text


class XlsParser(BaseParser):
    def can_handle(self, filename: str, mime_type: str | None) -> bool:
        return filename.lower().endswith(".xls") or mime_type in {
            "application/vnd.ms-excel",
            "application/msexcel",
        }

    def extract(self, content: bytes, filename: str, mime_type: str | None) -> ParseResult:
        try:
            import xlrd  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise ParserError(
                "XLS parsing requires xlrd or a LibreOffice-based fallback. Install xlrd to enable XLS support."
            ) from exc

        try:
            book = xlrd.open_workbook(file_contents=content)
            rows: list[str] = []
            for sheet in book.sheets():
                rows.append(f"[sheet] {sheet.name}")
                for row_idx in range(sheet.nrows):
                    row = [str(sheet.cell_value(row_idx, col_idx)).strip() for col_idx in range(sheet.ncols)]
                    rows.append(" | ".join(cell for cell in row if cell))
        except Exception as exc:  # noqa: BLE001
            raise ParserError(f"XLS parsing failed: {exc}") from exc

        return ParseResult(text=normalize_text("\n".join(rows)), source_type="xls")

