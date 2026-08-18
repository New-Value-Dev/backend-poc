from __future__ import annotations

import re
from pathlib import Path

from app.services.parsing.base import (
    BODY_LEVEL,
    UnifiedDocument,
    UnifiedSection,
)

BLANK_LINE_RE = re.compile(r"\n\s*\n")


class TextParser:
    name = "text"
    extensions = ("txt", "md")

    def parse(self, path: Path) -> UnifiedDocument:
        text = path.read_text(encoding="utf-8", errors="replace")
        is_md = path.suffix.lower() == ".md"

        sections: list[UnifiedSection] = []
        order = 0
        for block in BLANK_LINE_RE.split(text):
            stripped = block.strip()
            if not stripped:
                continue
            if is_md and stripped.startswith("#"):
                hashes = len(stripped) - len(stripped.lstrip("#"))
                title = stripped[hashes:].strip()
                sections.append(
                    UnifiedSection(
                        content=title,
                        title=title,
                        order=order,
                        level=min(max(hashes, 1), 6),
                        section_type="heading",
                    )
                )
            else:
                sections.append(
                    UnifiedSection(
                        content=stripped, order=order, level=BODY_LEVEL, section_type="paragraph"
                    )
                )
            order += 1

        return UnifiedDocument(sections=sections, parser_name=self.name)
