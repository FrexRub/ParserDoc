from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ParseResult:
    text: str
    source_type: str
    warnings: list[str] = field(default_factory=list)


class ParserError(RuntimeError):
    pass


class BaseParser(ABC):
    @abstractmethod
    def can_handle(self, filename: str, mime_type: str | None) -> bool: ...

    @abstractmethod
    def extract(self, content: bytes, filename: str, mime_type: str | None) -> ParseResult: ...

