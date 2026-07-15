from __future__ import annotations

import re
import struct
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from io import BytesIO
from xml.etree import ElementTree

from app.parsers.base import BaseParser, ParseResult, ParserError
from app.services.normalizer import normalize_text

_CFBF_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_FREE_SECTOR = 0xFFFFFFFF
_END_OF_CHAIN = 0xFFFFFFFE
_FAT_SECTOR = 0xFFFFFFFD
_DIFAT_SECTOR = 0xFFFFFFFC
_MINI_STREAM_CUTOFF = 4096


@dataclass
class _BiffString:
    value: str
    offset: int


class XlsParser(BaseParser):
    def can_handle(self, filename: str, mime_type: str | None) -> bool:
        lower = filename.lower()
        return lower.endswith((".xls", ".xlsx")) or mime_type in {
            "application/vnd.ms-excel",
            "application/msexcel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }

    def extract(self, content: bytes, filename: str, mime_type: str | None) -> ParseResult:
        if filename.lower().endswith(".xlsx") or mime_type == (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ):
            return self._extract_xlsx(content)

        try:
            import xlrd  # type: ignore
        except Exception as exc:  # noqa: BLE001
            return self._extract_xls_without_xlrd(content, exc)

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

    def _extract_xls_without_xlrd(self, content: bytes, missing_dependency: Exception) -> ParseResult:
        try:
            workbook = self._read_cfbf_stream(content, {"Workbook", "Book"})
            rows = self._read_biff_workbook(workbook)
        except Exception as exc:  # noqa: BLE001
            raise ParserError(
                "XLS parsing requires xlrd for this file. Install project dependencies with "
                "`python -m pip install -e .` to enable full XLS support."
            ) from missing_dependency or exc

        return ParseResult(
            text=normalize_text("\n".join(rows)),
            source_type="xls",
            warnings=["XLS parsed with built-in best-effort fallback; install xlrd for highest fidelity."],
        )

    def _read_cfbf_stream(self, content: bytes, stream_names: set[str]) -> bytes:
        if not content.startswith(_CFBF_SIGNATURE):
            raise ValueError("not an OLE compound file")

        sector_size = 1 << struct.unpack_from("<H", content, 30)[0]
        mini_sector_size = 1 << struct.unpack_from("<H", content, 32)[0]
        first_dir_sector = struct.unpack_from("<I", content, 48)[0]
        first_mini_fat_sector = struct.unpack_from("<I", content, 60)[0]
        mini_fat_sector_count = struct.unpack_from("<I", content, 64)[0]
        first_difat_sector = struct.unpack_from("<I", content, 68)[0]
        difat_sector_count = struct.unpack_from("<I", content, 72)[0]

        difat = [
            sector
            for sector in struct.unpack_from("<109I", content, 76)
            if sector not in {_FREE_SECTOR, _END_OF_CHAIN}
        ]
        next_difat = first_difat_sector
        for _ in range(difat_sector_count):
            if next_difat in {_FREE_SECTOR, _END_OF_CHAIN}:
                break
            sector = self._cfbf_sector(content, next_difat, sector_size)
            entries_per_sector = sector_size // 4 - 1
            difat.extend(
                entry
                for entry in struct.unpack_from(f"<{entries_per_sector}I", sector, 0)
                if entry not in {_FREE_SECTOR, _END_OF_CHAIN}
            )
            next_difat = struct.unpack_from("<I", sector, entries_per_sector * 4)[0]

        fat: list[int] = []
        for fat_sector in difat:
            if fat_sector in {_DIFAT_SECTOR, _FAT_SECTOR}:
                continue
            sector = self._cfbf_sector(content, fat_sector, sector_size)
            fat.extend(struct.unpack_from(f"<{sector_size // 4}I", sector, 0))

        directory = self._read_cfbf_chain(content, fat, first_dir_sector, sector_size)
        entries = self._read_cfbf_directory(directory)
        root = next((entry for entry in entries if entry["type"] == 5), None)
        if root is None:
            raise ValueError("missing CFBF root entry")

        mini_fat: list[int] = []
        if mini_fat_sector_count and first_mini_fat_sector not in {_FREE_SECTOR, _END_OF_CHAIN}:
            mini_fat_bytes = self._read_cfbf_chain(content, fat, first_mini_fat_sector, sector_size)
            mini_fat = list(struct.unpack_from(f"<{len(mini_fat_bytes) // 4}I", mini_fat_bytes, 0))
        mini_stream = b""
        if root["start"] not in {_FREE_SECTOR, _END_OF_CHAIN} and root["size"]:
            mini_stream = self._read_cfbf_chain(content, fat, root["start"], sector_size)[: root["size"]]

        for entry in entries:
            if entry["type"] != 2 or entry["name"] not in stream_names:
                continue
            if entry["size"] < _MINI_STREAM_CUTOFF and mini_fat:
                return self._read_cfbf_mini_chain(mini_stream, mini_fat, entry["start"], mini_sector_size)[
                    : entry["size"]
                ]
            return self._read_cfbf_chain(content, fat, entry["start"], sector_size)[: entry["size"]]

        raise ValueError("missing Workbook stream")

    def _cfbf_sector(self, content: bytes, sector_id: int, sector_size: int) -> bytes:
        offset = (sector_id + 1) * sector_size
        return content[offset : offset + sector_size]

    def _read_cfbf_chain(self, content: bytes, fat: list[int], start: int, sector_size: int) -> bytes:
        chunks: list[bytes] = []
        sector = start
        seen: set[int] = set()
        while sector not in {_FREE_SECTOR, _END_OF_CHAIN}:
            if sector in seen or sector >= len(fat):
                raise ValueError("invalid CFBF sector chain")
            seen.add(sector)
            chunks.append(self._cfbf_sector(content, sector, sector_size))
            sector = fat[sector]
        return b"".join(chunks)

    def _read_cfbf_mini_chain(self, mini_stream: bytes, mini_fat: list[int], start: int, mini_sector_size: int) -> bytes:
        chunks: list[bytes] = []
        sector = start
        seen: set[int] = set()
        while sector not in {_FREE_SECTOR, _END_OF_CHAIN}:
            if sector in seen or sector >= len(mini_fat):
                raise ValueError("invalid CFBF mini sector chain")
            seen.add(sector)
            offset = sector * mini_sector_size
            chunks.append(mini_stream[offset : offset + mini_sector_size])
            sector = mini_fat[sector]
        return b"".join(chunks)

    def _read_cfbf_directory(self, directory: bytes) -> list[dict[str, int | str]]:
        entries: list[dict[str, int | str]] = []
        for offset in range(0, len(directory), 128):
            entry = directory[offset : offset + 128]
            if len(entry) < 128:
                continue
            name_size = struct.unpack_from("<H", entry, 64)[0]
            if name_size < 2:
                continue
            name = entry[: name_size - 2].decode("utf-16le", errors="ignore")
            entries.append(
                {
                    "name": name,
                    "type": entry[66],
                    "start": struct.unpack_from("<I", entry, 116)[0],
                    "size": struct.unpack_from("<Q", entry, 120)[0],
                }
            )
        return entries

    def _read_biff_workbook(self, workbook: bytes) -> list[str]:
        records = list(self._iter_biff_records(workbook))
        sheet_names = self._read_biff_sheet_names(records)
        shared_strings = self._read_biff_shared_strings(records)
        rows_by_sheet: list[tuple[str, dict[int, dict[int, str]]]] = []
        current_rows: dict[int, dict[int, str]] | None = None
        sheet_index = 0

        for offset, record_type, data in records:
            if record_type == 0x0809 and len(data) >= 4 and struct.unpack_from("<H", data, 2)[0] == 0x0010:
                sheet_index += 1
                name = sheet_names.get(offset, f"Sheet{sheet_index}")
                current_rows = defaultdict(dict)
                rows_by_sheet.append((name, current_rows))
                continue
            if current_rows is None:
                continue
            if record_type == 0x000A:
                current_rows = None
                continue
            self._read_biff_cell(record_type, data, current_rows, shared_strings)

        rows: list[str] = []
        for name, sheet_rows in rows_by_sheet:
            rows.append(f"[sheet] {name}")
            for row_idx in sorted(sheet_rows):
                row = sheet_rows[row_idx]
                rows.append(" | ".join(row[col_idx] for col_idx in sorted(row) if row[col_idx]))
        return rows

    def _iter_biff_records(self, workbook: bytes):
        offset = 0
        while offset + 4 <= len(workbook):
            record_type, size = struct.unpack_from("<HH", workbook, offset)
            data_start = offset + 4
            data_end = data_start + size
            if data_end > len(workbook):
                break
            yield offset, record_type, workbook[data_start:data_end]
            offset = data_end

    def _read_biff_sheet_names(self, records: list[tuple[int, int, bytes]]) -> dict[int, str]:
        names: dict[int, str] = {}
        for _, record_type, data in records:
            if record_type != 0x0085 or len(data) < 8:
                continue
            sheet_offset = struct.unpack_from("<I", data, 0)[0]
            name_size = data[6]
            flags = data[7]
            raw = data[8:]
            if flags & 0x01:
                name = raw[: name_size * 2].decode("utf-16le", errors="ignore")
            else:
                name = raw[:name_size].decode("latin-1", errors="ignore")
            names[sheet_offset] = name
        return names

    def _read_biff_shared_strings(self, records: list[tuple[int, int, bytes]]) -> list[str]:
        payload = b""
        for _, record_type, data in records:
            if record_type == 0x00FC:
                payload = data
            elif payload and record_type == 0x003C:
                payload += data
            elif payload:
                break

        if len(payload) < 8:
            return []

        strings: list[str] = []
        unique_count = struct.unpack_from("<I", payload, 4)[0]
        offset = 8
        for _ in range(unique_count):
            parsed = self._read_biff_unicode_string(payload, offset)
            strings.append(parsed.value)
            offset = parsed.offset
            if offset >= len(payload):
                break
        return strings

    def _read_biff_unicode_string(self, data: bytes, offset: int) -> _BiffString:
        if offset + 3 > len(data):
            return _BiffString("", len(data))

        char_count = struct.unpack_from("<H", data, offset)[0]
        flags = data[offset + 2]
        offset += 3
        rich_runs = 0
        phonetic_size = 0
        if flags & 0x08 and offset + 2 <= len(data):
            rich_runs = struct.unpack_from("<H", data, offset)[0]
            offset += 2
        if flags & 0x04 and offset + 4 <= len(data):
            phonetic_size = struct.unpack_from("<I", data, offset)[0]
            offset += 4

        is_utf16 = bool(flags & 0x01)
        byte_size = char_count * (2 if is_utf16 else 1)
        raw = data[offset : offset + byte_size]
        offset += byte_size
        value = raw.decode("utf-16le" if is_utf16 else "latin-1", errors="ignore")
        offset += rich_runs * 4 + phonetic_size
        return _BiffString(value.strip(), min(offset, len(data)))

    def _read_biff_cell(
        self,
        record_type: int,
        data: bytes,
        rows: dict[int, dict[int, str]],
        shared_strings: list[str],
    ) -> None:
        if len(data) < 6:
            return
        row_idx, col_idx = struct.unpack_from("<HH", data, 0)
        value = ""
        if record_type == 0x00FD and len(data) >= 10:
            sst_index = struct.unpack_from("<I", data, 6)[0]
            if sst_index < len(shared_strings):
                value = shared_strings[sst_index]
        elif record_type == 0x0204 and len(data) >= 8:
            parsed = self._read_biff_unicode_string(data, 6)
            value = parsed.value
        elif record_type == 0x0203 and len(data) >= 14:
            value = self._format_number(struct.unpack_from("<d", data, 6)[0])
        elif record_type == 0x027E and len(data) >= 10:
            value = self._format_number(self._decode_rk(struct.unpack_from("<I", data, 6)[0]))
        elif record_type == 0x0006:
            value = self._read_biff_formula_value(data)
        elif record_type == 0x0205 and len(data) >= 8:
            value = "TRUE" if data[6] else "FALSE"
        elif record_type == 0x00BD and len(data) >= 10:
            self._read_biff_mulrk(data, rows)
            return

        if value:
            rows[row_idx][col_idx] = value

    def _read_biff_mulrk(self, data: bytes, rows: dict[int, dict[int, str]]) -> None:
        if len(data) < 10:
            return
        row_idx, first_col = struct.unpack_from("<HH", data, 0)
        last_col = struct.unpack_from("<H", data, len(data) - 2)[0]
        offset = 4
        for col_idx in range(first_col, last_col + 1):
            if offset + 6 > len(data):
                break
            rk_value = struct.unpack_from("<I", data, offset + 2)[0]
            rows[row_idx][col_idx] = self._format_number(self._decode_rk(rk_value))
            offset += 6

    def _decode_rk(self, value: int) -> float:
        multiplier = 0.01 if value & 0x01 else 1.0
        if value & 0x02:
            number = struct.unpack("<i", struct.pack("<I", value & 0xFFFFFFFC))[0] >> 2
            return number * multiplier
        raw = (value & 0xFFFFFFFC) << 32
        return struct.unpack("<d", struct.pack("<Q", raw))[0] * multiplier

    def _read_biff_formula_value(self, data: bytes) -> str:
        if len(data) < 14:
            return ""
        raw = data[6:14]
        if raw[6:] == b"\xff\xff":
            if raw[0] == 1:
                return "TRUE" if raw[2] else "FALSE"
            return ""
        return self._format_number(struct.unpack_from("<d", data, 6)[0])

    def _format_number(self, value: float) -> str:
        if value.is_integer():
            return str(int(value))
        return str(value)

    def _extract_xlsx(self, content: bytes) -> ParseResult:
        try:
            with zipfile.ZipFile(BytesIO(content)) as archive:
                shared_strings = self._read_shared_strings(archive)
                sheet_names = self._read_sheet_names(archive)
                rows: list[str] = []
                sheet_paths = sorted(
                    (
                        name
                        for name in archive.namelist()
                        if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
                    ),
                    key=self._sheet_number,
                )

                for index, sheet_path in enumerate(sheet_paths, start=1):
                    rows.append(f"[sheet] {sheet_names.get(index, f'Sheet{index}')}")
                    root = ElementTree.fromstring(archive.read(sheet_path))
                    for row in root.findall(".//{*}sheetData/{*}row"):
                        cells = [
                            value
                            for value in (
                                self._cell_value(cell, shared_strings)
                                for cell in row.findall("{*}c")
                            )
                            if value
                        ]
                        if cells:
                            rows.append(" | ".join(cells))
        except Exception as exc:  # noqa: BLE001
            raise ParserError(f"XLSX parsing failed: {exc}") from exc

        return ParseResult(text=normalize_text("\n".join(rows)), source_type="xlsx")

    def _read_shared_strings(self, archive: zipfile.ZipFile) -> list[str]:
        if "xl/sharedStrings.xml" not in archive.namelist():
            return []

        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
        strings: list[str] = []
        for item in root.findall("{*}si"):
            strings.append("".join(text.text or "" for text in item.findall(".//{*}t")))
        return strings

    def _read_sheet_names(self, archive: zipfile.ZipFile) -> dict[int, str]:
        if "xl/workbook.xml" not in archive.namelist():
            return {}

        root = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        sheet_names: dict[int, str] = {}
        for fallback_index, sheet in enumerate(root.findall(".//{*}sheet"), start=1):
            name = sheet.attrib.get("name")
            sheet_id = sheet.attrib.get("sheetId")
            if not name:
                continue
            try:
                index = int(sheet_id) if sheet_id else fallback_index
            except ValueError:
                index = fallback_index
            sheet_names[index] = name
        return sheet_names

    def _cell_value(self, cell: ElementTree.Element, shared_strings: list[str]) -> str:
        cell_type = cell.attrib.get("t")
        if cell_type == "inlineStr":
            return "".join(text.text or "" for text in cell.findall(".//{*}t")).strip()

        value = cell.find("{*}v")
        if value is None or value.text is None:
            return ""

        raw = value.text.strip()
        if cell_type == "s":
            try:
                return shared_strings[int(raw)].strip()
            except (ValueError, IndexError):
                return raw
        if cell_type == "b":
            return "TRUE" if raw == "1" else "FALSE"
        return raw

    def _sheet_number(self, path: str) -> int:
        match = re.search(r"sheet(\d+)\.xml$", path)
        return int(match.group(1)) if match else 0

