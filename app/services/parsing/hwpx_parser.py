"""HWPX(신형, OWPML) 파서"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from app.services.parsing.base import (
    BODY_LEVEL,
    ParseError,
    UnifiedDocument,
    UnifiedSection,
)

_SECTION_RE = re.compile(r"Contents/section\d+\.xml$", re.IGNORECASE)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _text_excluding_tables(elem: ET.Element) -> str:
    """elem 하위의 <hp:t> 텍스트를 모으되, 중첩된 표(<hp:tbl>) 안쪽은 건너뛴다."""
    parts: list[str] = []

    def rec(node: ET.Element) -> None:
        for child in node:
            local = _local(child.tag)
            if local == "tbl":
                continue
            if local == "t" and child.text:
                parts.append(child.text)
            rec(child)

    rec(elem)
    return "".join(parts).strip()


class HwpxParser:
    name = "hwpx"
    extensions = ("hwpx",)

    def parse(self, path: Path) -> UnifiedDocument:
        sections: list[UnifiedSection] = []
        order = 0
        try:
            with zipfile.ZipFile(path) as zf:
                names = sorted(n for n in zf.namelist() if _SECTION_RE.search(n))
                if not names:
                    raise ParseError("HWPX 본문(Contents/section*.xml)을 찾을 수 없습니다")
                for name in names:
                    root = ET.fromstring(zf.read(name))
                    order = self._walk(root, sections, order)
        except zipfile.BadZipFile as exc:
            raise ParseError(f"HWPX(zip) 열기 실패: {exc}") from exc

        return UnifiedDocument(sections=sections, parser_name=self.name)

    def _walk(self, elem: ET.Element, sections: list[UnifiedSection], order: int) -> int:
        for child in list(elem):
            local = _local(child.tag)
            if local == "tbl":
                text = self._table_text(child)
                if text:
                    sections.append(
                        UnifiedSection(content=text, order=order, level=BODY_LEVEL, section_type="table")
                    )
                    order += 1
                # 표 안쪽은 재귀하지 않는다(셀 텍스트는 _table_text 가 이미 처리).
            elif local == "p":
                text = _text_excluding_tables(child)
                if text:
                    sections.append(
                        UnifiedSection(content=text, order=order, level=BODY_LEVEL, section_type="paragraph")
                    )
                    order += 1
                # 문단 하위에 중첩된 표를 찾기 위해 계속 내려간다.
                order = self._walk(child, sections, order)
            else:
                order = self._walk(child, sections, order)
        return order

    def _table_text(self, tbl_elem: ET.Element) -> str:
        rows: list[str] = []
        for tr in tbl_elem.iter():
            if _local(tr.tag) != "tr":
                continue
            cells = [
                _text_excluding_tables(tc)
                for tc in tr
                if _local(tc.tag) == "tc"
            ]
            cells = [c for c in cells if c]
            if cells:
                rows.append(" | ".join(cells))
        return "\n".join(rows)
