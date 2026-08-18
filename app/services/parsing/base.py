"""파서 공통 모델"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

BODY_LEVEL = 100  # heading 이 아닌 콘텐츠


@dataclass
class UnifiedSection:
    content: str
    order: int
    title: str | None = None
    level: int = BODY_LEVEL
    section_type: str = "paragraph"  # heading | paragraph | table | list | image
    page_start: int | None = None
    page_end: int | None = None
    # bbox: [x0, y0, x1, y1] (페이지 좌표, PDF/OCR), ocr confidence 등
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class UnifiedDocument:
    sections: list[UnifiedSection]
    parser_name: str
    page_count: int | None = None
    ocr_used: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


class ParseError(Exception):
    """파싱 실패."""


class DocumentParser(Protocol):
    name: str
    extensions: tuple[str, ...]

    def parse(self, path: Path) -> UnifiedDocument: ...
