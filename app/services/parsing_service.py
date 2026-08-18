"""문서 파싱 파이프라인"""

from __future__ import annotations

import logging

from sqlalchemy import delete

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.document_section import DocumentSection
from app.models.document_version import DocumentVersion
from app.services.parsing import ParseError, UnifiedDocument, get_parser
from app.services.storage import LocalStorageProvider

logger = logging.getLogger(__name__)


def _persist_sections(db, version_id: int, unified: UnifiedDocument) -> int:
    """UnifiedDocument 의 섹션을 heading level 기반 계층으로 저장한다."""
    db.execute(
        delete(DocumentSection).where(DocumentSection.document_version_id == version_id)
    )
    # 스택으로 부모를 추적: 현재 level 보다 상위인 최근 노드가 부모
    stack: list[tuple[int, int]] = []  # (level, db_id)
    count = 0
    for sec in unified.sections:
        while stack and stack[-1][0] >= sec.level:
            stack.pop()
        parent_id = stack[-1][1] if stack else None

        # heading 은 구조 라벨이므로 title 만 두고 content 는 비운다
        # 본문/표는 title 없이 content 만 둔다
        if sec.section_type == "heading":
            title = sec.title or sec.content
            content = None
        else:
            title = sec.title
            content = sec.content

        row = DocumentSection(
            document_version_id=version_id,
            parent_section_id=parent_id,
            title=title,
            section_type=sec.section_type,
            level=sec.level,
            page_start=sec.page_start,
            page_end=sec.page_end,
            order_no=sec.order,
            content=content,
            meta=sec.meta or None,
        )
        db.add(row)
        db.flush()
        stack.append((sec.level, row.id))
        count += 1
    return count


def parse_version(db, version_id: int) -> None:
    version = db.get(DocumentVersion, version_id)
    if version is None:
        logger.warning("parse_version: version %s not found", version_id)
        return

    version.processing_status = "PARSING"
    db.commit()

    settings = get_settings()
    storage = LocalStorageProvider(settings.storage_root)

    try:
        ext = version.original_file_name.rsplit(".", 1)[-1].lower()
        parser = get_parser(ext)
        if parser is None:
            raise ParseError(f"'.{ext}' 파서가 아직 없습니다")

        path = storage.resolve(version.storage_path)
        if not path.exists():
            raise ParseError(f"파일을 찾을 수 없습니다: {version.storage_path}")

        unified = parser.parse(path)
        n = _persist_sections(db, version_id, unified)

        suffix = "+ocr" if unified.ocr_used else ""
        version.parser_version = f"{unified.parser_name}{suffix}"
        version.processing_status = "PARSED"
        db.commit()
        logger.info("parsed version %s: %s sections (%s)", version_id, n, version.parser_version)

        if unified.ocr_used:
            line_count = unified.meta.get("ocr_line_count", 0)
            low_conf_count = unified.meta.get("ocr_low_confidence_count", 0)
            if line_count and low_conf_count / line_count >= 0.3:
                logger.warning(
                    "version %s: OCR low-confidence lines %s/%s (%.0f%%) — 재확인 권장",
                    version_id, low_conf_count, line_count, 100 * low_conf_count / line_count,
                )
    except Exception as exc:
        db.rollback()
        version = db.get(DocumentVersion, version_id)
        if version is not None:
            version.processing_status = "FAILED"
            db.commit()
        logger.exception("parse failed for version %s: %s", version_id, exc)


def run_parse_task(version_id: int) -> None:
    """BackgroundTasks 진입점 — 요청 세션과 분리된 자체 세션을 연다"""
    from app.services.chunking_service import chunk_version

    db = SessionLocal()
    try:
        parse_version(db, version_id)
        version = db.get(DocumentVersion, version_id)
        if version is not None and version.processing_status == "PARSED":
            chunk_version(db, version_id)
    finally:
        db.close()
