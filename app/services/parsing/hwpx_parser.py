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

SECTION_RE = re.compile(r"Contents/section\d+\.xml$", re.IGNORECASE)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def iter_t_nodes(elem: ET.Element):
    """elem 하위의 <hp:t> 엘리먼트를 순서대로 yield, 중첩된 표(<hp:tbl>) 안쪽은 건너뛴다.

    correction_service 가 이 노드들의 .text 를 직접 고쳐 쓸 수 있도록 텍스트가 아니라
    엘리먼트 자체를 준다.
    """
    for child in elem:
        local = _local(child.tag)
        if local == "tbl":
            continue
        if local == "t":
            yield child
        yield from iter_t_nodes(child)


def text_excluding_tables(elem: ET.Element) -> str:
    """elem 하위의 <hp:t> 텍스트를 모으되, 중첩된 표(<hp:tbl>) 안쪽은 건너뛴다."""
    return "".join(t.text or "" for t in iter_t_nodes(elem)).strip()


def table_text(tbl_elem: ET.Element) -> str:
    rows: list[str] = []
    for tr in tbl_elem.iter():
        if _local(tr.tag) != "tr":
            continue
        cells = [text_excluding_tables(tc) for tc in tr if _local(tc.tag) == "tc"]
        cells = [c for c in cells if c]
        if cells:
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def iter_body_blocks(elem: ET.Element):
    """(kind, element, text) 를 HwpxParser.parse() 와 동일한 순서/스킵 규칙으로 yield.

    kind: "p"(문단) | "tbl"(표). 빈 블록은 건너뛴다. parse() 와 correction_service 가
    section.order 로 같은 블록을 다시 찾아낼 수 있도록 순서/스킵 규칙을 한 곳에 둔다.
    """
    for child in list(elem):
        local = _local(child.tag)
        if local == "tbl":
            text = table_text(child)
            if text:
                yield "tbl", child, text
            # 표 안쪽은 재귀하지 않는다(셀 텍스트는 table_text 가 이미 처리).
        elif local == "p":
            text = text_excluding_tables(child)
            if text:
                yield "p", child, text
            # 문단 하위에 중첩된 표를 찾기 위해 계속 내려간다.
            yield from iter_body_blocks(child)
        else:
            yield from iter_body_blocks(child)


class HwpxParser:
    name = "hwpx"
    extensions = ("hwpx",)

    def parse(self, path: Path) -> UnifiedDocument:
        sections: list[UnifiedSection] = []
        order = 0
        try:
            with zipfile.ZipFile(path) as zf:
                names = sorted(n for n in zf.namelist() if SECTION_RE.search(n))
                if not names:
                    raise ParseError("HWPX 본문(Contents/section*.xml)을 찾을 수 없습니다")
                for name in names:
                    root = ET.fromstring(zf.read(name))
                    for kind, _elem, text in iter_body_blocks(root):
                        section_type = "table" if kind == "tbl" else "paragraph"
                        sections.append(
                            UnifiedSection(
                                content=text, order=order,
                                level=BODY_LEVEL, section_type=section_type,
                            )
                        )
                        order += 1
        except zipfile.BadZipFile as exc:
            raise ParseError(f"HWPX(zip) 열기 실패: {exc}") from exc

        return UnifiedDocument(sections=sections, parser_name=self.name)
