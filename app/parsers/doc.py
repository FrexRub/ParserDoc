from __future__ import annotations

import re
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

from app.parsers.base import BaseParser, ParseResult, ParserError
from app.services.normalizer import normalize_text


_PRINTABLE_RUN = re.compile(r"[^\x00-\x08\x0e-\x1f]{4,}")
_READABLE_CHAR = re.compile(r"[0-9A-Za-z\u0400-\u04ff]")
_LEADING_NOISE = re.compile(r"^[^0-9A-Za-z\u0400-\u04ff]+")
_CFB_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_END_OF_CHAIN = 0xFFFFFFFE
_FREE_SECTOR = 0xFFFFFFFF


def _clean_doc_run(text: str) -> str:
    text = text.replace("\x0b", "\n").replace("\x0c", "\n")
    text = re.sub(r"[\uf020-\uf0ff]", " ", text)
    text = re.sub(r"[\x00-\x08\x0e-\x1f]", " ", text)
    text = _LEADING_NOISE.sub("", text)
    return normalize_text(text)


def _looks_like_text(text: str) -> bool:
    readable = sum(1 for char in text if _READABLE_CHAR.match(char))
    return readable >= 4 and readable / max(len(text), 1) >= 0.15


class _CompoundBinaryFile:
    def __init__(self, content: bytes) -> None:
        if not content.startswith(_CFB_SIGNATURE):
            raise ValueError("Not a Compound File Binary document")

        self.content = content
        self.sector_size = 1 << struct.unpack_from("<H", content, 0x1E)[0]
        self.mini_sector_size = 1 << struct.unpack_from("<H", content, 0x20)[0]
        self.mini_stream_cutoff = struct.unpack_from("<I", content, 0x38)[0]
        first_dir_sector = struct.unpack_from("<I", content, 0x30)[0]
        first_mini_fat_sector = struct.unpack_from("<I", content, 0x3C)[0]
        fat_sector_count = struct.unpack_from("<I", content, 0x2C)[0]

        self.fat = self._read_fat(fat_sector_count)
        directory_stream = self._read_regular_stream(first_dir_sector)
        self.entries = self._read_directory(directory_stream)

        root = self.entries.get("Root Entry")
        self.mini_stream = b""
        self.mini_fat: list[int] = []
        if root is not None:
            self.mini_stream = self._read_regular_stream(root[1])[: root[2]]
        if first_mini_fat_sector not in {_END_OF_CHAIN, _FREE_SECTOR}:
            self.mini_fat = self._read_sector_table(first_mini_fat_sector)

    def _sector(self, sector_id: int) -> bytes:
        offset = (sector_id + 1) * self.sector_size
        return self.content[offset : offset + self.sector_size]

    def _chain(self, start_sector: int, table: list[int] | None = None) -> list[int]:
        sectors: list[int] = []
        current = start_sector
        sector_table = table if table is not None else self.fat
        seen: set[int] = set()
        while current not in {_END_OF_CHAIN, _FREE_SECTOR} and current < len(sector_table):
            if current in seen:
                break
            seen.add(current)
            sectors.append(current)
            current = sector_table[current]
        return sectors

    def _read_fat(self, fat_sector_count: int) -> list[int]:
        sector_ids = [
            struct.unpack_from("<I", self.content, 0x4C + index * 4)[0]
            for index in range(min(fat_sector_count, 109))
        ]
        fat: list[int] = []
        for sector_id in sector_ids:
            if sector_id in {_END_OF_CHAIN, _FREE_SECTOR}:
                continue
            sector = self._sector(sector_id)
            fat.extend(struct.unpack("<" + "I" * (len(sector) // 4), sector))
        return fat

    def _read_sector_table(self, start_sector: int) -> list[int]:
        values: list[int] = []
        for sector_id in self._chain(start_sector):
            sector = self._sector(sector_id)
            values.extend(struct.unpack("<" + "I" * (len(sector) // 4), sector))
        return values

    def _read_regular_stream(self, start_sector: int) -> bytes:
        return b"".join(self._sector(sector_id) for sector_id in self._chain(start_sector))

    def _read_directory(self, directory_stream: bytes) -> dict[str, tuple[int, int, int]]:
        entries: dict[str, tuple[int, int, int]] = {}
        for offset in range(0, len(directory_stream), 128):
            entry = directory_stream[offset : offset + 128]
            if len(entry) < 128:
                continue
            name_length = struct.unpack_from("<H", entry, 64)[0]
            if name_length < 2:
                continue
            name = entry[: name_length - 2].decode("utf-16le", errors="ignore")
            entry_type = entry[66]
            start_sector = struct.unpack_from("<I", entry, 116)[0]
            size = struct.unpack_from("<Q", entry, 120)[0]
            entries[name] = (entry_type, start_sector, size)
        return entries

    def stream(self, name: str) -> bytes:
        entry = self.entries[name]
        entry_type, start_sector, size = entry
        if entry_type == 2 and size < self.mini_stream_cutoff and self.mini_fat:
            chunks: list[bytes] = []
            for sector_id in self._chain(start_sector, self.mini_fat):
                offset = sector_id * self.mini_sector_size
                chunks.append(self.mini_stream[offset : offset + self.mini_sector_size])
            return b"".join(chunks)[:size]
        return self._read_regular_stream(start_sector)[:size]


def _decode_piece(piece: bytes, compressed: bool) -> str:
    if not compressed:
        return piece.decode("utf-16le", errors="ignore")
    for encoding in ("cp1251", "cp1252", "latin-1"):
        decoded = piece.decode(encoding, errors="ignore")
        if _looks_like_text(decoded):
            return decoded
    return piece.decode("latin-1", errors="ignore")


def _strip_doc_field_noise(text: str) -> str:
    text = re.sub(r'\x13\s*HYPERLINK\s+"([^"]+)"\s*\x01?\x14', "", text, flags=re.IGNORECASE)
    text = text.replace("\x13", "").replace("\x14", "").replace("\x15", "")
    lines = text.splitlines()
    cleaned: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.upper().startswith("HYPERLINK "):
            match = re.search(r'"([^"]+)"', stripped)
            if match and match.group(1) in text:
                continue
        cleaned.append(line)
    return "\n".join(cleaned)


def _word_document_piece_table_text(content: bytes) -> str:
    cfb = _CompoundBinaryFile(content)
    word_document = cfb.stream("WordDocument")
    table_name = "1Table" if struct.unpack_from("<H", word_document, 0x0A)[0] & 0x0200 else "0Table"
    table_stream = cfb.stream(table_name)

    fc_clx, lcb_clx = struct.unpack_from("<II", word_document, 0x1A2)
    clx = table_stream[fc_clx : fc_clx + lcb_clx]
    index = 0
    piece_table = b""
    while index < len(clx):
        marker = clx[index]
        if marker == 0x01:
            if index + 3 > len(clx):
                break
            skip = struct.unpack_from("<H", clx, index + 1)[0]
            index += 3 + skip
            continue
        if marker == 0x02:
            if index + 5 > len(clx):
                break
            size = struct.unpack_from("<I", clx, index + 1)[0]
            piece_table = clx[index + 5 : index + 5 + size]
            break
        break

    if not piece_table:
        return ""

    piece_count = (len(piece_table) - 4) // 12
    if piece_count <= 0:
        return ""
    cp_offsets = list(struct.unpack_from("<" + "I" * (piece_count + 1), piece_table, 0))
    pcd_offset = 4 * (piece_count + 1)

    parts: list[str] = []
    for piece_index in range(piece_count):
        char_count = cp_offsets[piece_index + 1] - cp_offsets[piece_index]
        if char_count <= 0:
            continue
        pcd = piece_table[pcd_offset + piece_index * 8 : pcd_offset + (piece_index + 1) * 8]
        if len(pcd) < 8:
            continue
        fc_value = struct.unpack_from("<I", pcd, 2)[0]
        compressed = bool(fc_value & 0x40000000)
        file_offset = fc_value & 0x3FFFFFFF
        if compressed:
            file_offset //= 2
            byte_count = char_count
        else:
            byte_count = char_count * 2
        piece = word_document[file_offset : file_offset + byte_count]
        parts.append(_decode_piece(piece, compressed))

    return normalize_text(_strip_doc_field_noise("".join(parts)))


def _best_effort_binary_doc_text(content: bytes) -> str:
    candidates: list[str] = []

    utf16_text = content.decode("utf-16le", errors="ignore")
    for run in _PRINTABLE_RUN.findall(utf16_text):
        cleaned = _clean_doc_run(run)
        if _looks_like_text(cleaned):
            candidates.append(cleaned)

    for encoding in ("utf-8", "cp1251", "cp1252", "latin-1"):
        decoded = content.decode(encoding, errors="ignore")
        for run in _PRINTABLE_RUN.findall(decoded):
            cleaned = _clean_doc_run(run)
            if _looks_like_text(cleaned):
                candidates.append(cleaned)

    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        key = candidate.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(candidate)

    return normalize_text("\n".join(unique))


class DocParser(BaseParser):
    def can_handle(self, filename: str, mime_type: str | None) -> bool:
        return filename.lower().endswith(".doc") or mime_type in {
            "application/msword",
            "application/vnd.ms-word",
        }

    def extract(self, content: bytes, filename: str, mime_type: str | None) -> ParseResult:
        antiword = shutil.which("antiword")
        catdoc = shutil.which("catdoc")
        soffice = shutil.which("soffice") or shutil.which("libreoffice")
        converter_error: str | None = None

        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / filename
            src.write_bytes(content)

            if antiword:
                output = subprocess.run([antiword, str(src)], capture_output=True, text=True, check=False)
                text = output.stdout or output.stderr
                if output.returncode == 0 and text.strip():
                    return ParseResult(text=normalize_text(text), source_type="doc")

            if catdoc:
                output = subprocess.run([catdoc, str(src)], capture_output=True, text=True, check=False)
                text = output.stdout or output.stderr
                if output.returncode == 0 and text.strip():
                    return ParseResult(text=normalize_text(text), source_type="doc")

            if soffice:
                outdir = Path(tmpdir) / "out"
                outdir.mkdir(parents=True, exist_ok=True)
                output = subprocess.run(
                    [soffice, "--headless", "--convert-to", "txt:Text", "--outdir", str(outdir), str(src)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                converted = next(outdir.glob("*.txt"), None)
                if converted and converted.exists():
                    text = converted.read_text(encoding="utf-8", errors="ignore")
                    return ParseResult(text=normalize_text(text), source_type="doc")
                if output.stdout or output.stderr:
                    converter_error = output.stdout or output.stderr

        try:
            text = _word_document_piece_table_text(content)
        except Exception:
            text = ""
        if text:
            return ParseResult(
                text=text,
                source_type="doc",
                warnings=["DOC parsed with built-in WordDocument text extraction; install LibreOffice for highest fidelity."],
            )

        text = _best_effort_binary_doc_text(content)
        if text:
            return ParseResult(
                text=text,
                source_type="doc",
                warnings=["DOC parsed with built-in best-effort text extraction; install LibreOffice for higher fidelity."],
            )

        if converter_error:
            raise ParserError(converter_error)

        raise ParserError(
            "DOC parsing requires antiword, catdoc, or LibreOffice/soffice to be installed on the server."
        )
