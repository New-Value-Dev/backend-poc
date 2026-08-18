from __future__ import annotations

from pathlib import Path

from docx import Document as load_docx
from docx.document import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.services.parsing.base import (
    BODY_LEVEL,
    UnifiedDocument,
    UnifiedSection,
)


def iter_block_items(document: DocxDocument):
    """문서 본문의 문단/표를 순서대로 순회한다."""
    body = document.element.body
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def _heading_level(style_name: str | None) -> int | None:
    if not style_name:
        return None
    name = style_name.strip()
    if name == "Title":
        return 1
    if name.startswith("Heading"):
        tail = name[len("Heading"):].strip()
        if tail.isdigit():
            return min(int(tail), 9)
        return 1
    return None


def table_text(table: Table) -> str:
    rows = []
    for row in table.rows:
        rows.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n".join(rows)


class DocxParser:
    name = "docx"
    extensions = ("docx",)

    def parse(self, path: Path) -> UnifiedDocument:
        document = load_docx(str(path))
        sections: list[UnifiedSection] = []
        order = 0

        for block in iter_block_items(document):
            if isinstance(block, Paragraph):
                text = block.text.strip()
                if not text:
                    continue
                level = _heading_level(block.style.name if block.style else None)
                if level is not None:
                    sections.append(
                        UnifiedSection(
                            content=text, title=text, order=order,
                            level=level, section_type="heading",
                        )
                    )
                else:
                    sections.append(
                        UnifiedSection(
                            content=text, order=order,
                            level=BODY_LEVEL, section_type="paragraph",
                        )
                    )
                order += 1
            elif isinstance(block, Table):
                text = table_text(block)
                if not text.strip():
                    continue
                sections.append(
                    UnifiedSection(
                        content=text, order=order,
                        level=BODY_LEVEL, section_type="table",
                    )
                )
                order += 1

        return UnifiedDocument(sections=sections, parser_name=self.name)
