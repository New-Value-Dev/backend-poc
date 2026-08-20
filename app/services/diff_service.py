"""문서 버전 비교(Version Diff). 수많은 문서 중에서 찾는 검색 문제가 아니라 이미 정해진
두 버전만 비교하는 문제라 임베딩/LLM 없이 표준 라이브러리 difflib만으로 동기 처리한다.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.document_section import DocumentSection
from app.repositories.document_repository import DocumentVersionRepository
from app.schemas.diff import DiffResult, DiffSummary, DiffToken, SectionDiff, VersionRef
from app.services.document_service import VersionNotFoundError

_WS_RE = re.compile(r"\S+|\s+")
# replace 블록 안에서 이 유사도 미만이면 "수정"으로 안 묶고 삭제+추가로 따로 취급한다
_MODIFY_RATIO_THRESHOLD = 0.4


def _section_text(section: DocumentSection) -> str:
    return (section.title if section.section_type == "heading" else section.content) or ""


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _section_key(section: DocumentSection) -> tuple:
    return (section.level, section.section_type, _normalize(_section_text(section)))


def _token_diff(before: str, after: str) -> list[DiffToken]:
    before_tokens = _WS_RE.findall(before)
    after_tokens = _WS_RE.findall(after)
    matcher = SequenceMatcher(None, before_tokens, after_tokens, autojunk=False)
    tokens: list[DiffToken] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            tokens.append(DiffToken(op="equal", text="".join(before_tokens[i1:i2])))
        elif tag == "delete":
            tokens.append(DiffToken(op="delete", text="".join(before_tokens[i1:i2])))
        elif tag == "insert":
            tokens.append(DiffToken(op="insert", text="".join(after_tokens[j1:j2])))
        elif tag == "replace":
            tokens.append(DiffToken(op="delete", text="".join(before_tokens[i1:i2])))
            tokens.append(DiffToken(op="insert", text="".join(after_tokens[j1:j2])))
    return tokens


def _whole_section_diff(section: DocumentSection, op: str, token_op: str) -> SectionDiff:
    text = _section_text(section)
    from_id = section.id if op == "deleted" else None
    to_id = section.id if op == "added" else None
    return SectionDiff(
        op=op,
        from_section_id=from_id,
        to_section_id=to_id,
        level=section.level,
        section_type=section.section_type,
        title=section.title,
        tokens=[DiffToken(op=token_op, text=text)] if text else [],
    )


def _match_replace_block(
    from_block: list[DocumentSection], to_block: list[DocumentSection]
) -> list[SectionDiff]:
    """개수가 다른 replace 구간 안에서 유사도 기준으로 "수정" 쌍을 그리디하게 골라내고,
    나머지는 개별 삭제/추가로 강등한다 — 엉뚱한 섹션끼리 억지로 짝짓지 않기 위함."""
    used_to: set[int] = set()
    pairs: dict[int, int] = {}
    for fi, from_section in enumerate(from_block):
        best_j, best_ratio = None, 0.0
        for ti, to_section in enumerate(to_block):
            if ti in used_to or from_section.level != to_section.level:
                continue
            ratio = SequenceMatcher(
                None, _normalize(_section_text(from_section)), _normalize(_section_text(to_section))
            ).ratio()
            if ratio > best_ratio:
                best_ratio, best_j = ratio, ti
        if best_j is not None and best_ratio >= _MODIFY_RATIO_THRESHOLD:
            pairs[fi] = best_j
            used_to.add(best_j)

    result: list[SectionDiff] = []
    for fi, from_section in enumerate(from_block):
        if fi not in pairs:
            result.append(_whole_section_diff(from_section, "deleted", "delete"))
            continue
        to_section = to_block[pairs[fi]]
        result.append(
            SectionDiff(
                op="modified",
                from_section_id=from_section.id,
                to_section_id=to_section.id,
                level=to_section.level,
                section_type=to_section.section_type,
                title=to_section.title,
                tokens=_token_diff(_section_text(from_section), _section_text(to_section)),
            )
        )
    for ti, to_section in enumerate(to_block):
        if ti not in used_to:
            result.append(_whole_section_diff(to_section, "added", "insert"))
    return result


def _match_sections(
    from_sections: list[DocumentSection], to_sections: list[DocumentSection]
) -> list[SectionDiff]:
    from_keys = [_section_key(s) for s in from_sections]
    to_keys = [_section_key(s) for s in to_sections]
    matcher = SequenceMatcher(None, from_keys, to_keys, autojunk=False)

    result: list[SectionDiff] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for fi, ti in zip(range(i1, i2), range(j1, j2)):
                from_section, to_section = from_sections[fi], to_sections[ti]
                text = _section_text(to_section)
                result.append(
                    SectionDiff(
                        op="unchanged",
                        from_section_id=from_section.id,
                        to_section_id=to_section.id,
                        level=to_section.level,
                        section_type=to_section.section_type,
                        title=to_section.title,
                        tokens=[DiffToken(op="equal", text=text)] if text else [],
                    )
                )
        elif tag == "delete":
            result.extend(
                _whole_section_diff(s, "deleted", "delete") for s in from_sections[i1:i2]
            )
        elif tag == "insert":
            result.extend(
                _whole_section_diff(s, "added", "insert") for s in to_sections[j1:j2]
            )
        elif tag == "replace":
            result.extend(_match_replace_block(from_sections[i1:i2], to_sections[j1:j2]))
    return result


def _summarize(sections: list[SectionDiff]) -> DiffSummary:
    counts = {"added": 0, "deleted": 0, "modified": 0, "unchanged": 0}
    for s in sections:
        counts[s.op] += 1
    return DiffSummary(**counts)


class DiffService:
    def __init__(self, versions: DocumentVersionRepository) -> None:
        self.versions = versions

    def get_diff(self, document_id: int, from_version_id: int, to_version_id: int) -> DiffResult:
        from_version = self._get_owned_version(document_id, from_version_id)
        to_version = self._get_owned_version(document_id, to_version_id)

        from_sections = self.versions.list_sections(from_version_id)
        to_sections = self.versions.list_sections(to_version_id)
        sections = _match_sections(from_sections, to_sections)

        return DiffResult(
            document_id=document_id,
            from_version=VersionRef(id=from_version.id, version_no=from_version.version_no),
            to_version=VersionRef(id=to_version.id, version_no=to_version.version_no),
            sections=sections,
            summary=_summarize(sections),
        )

    def _get_owned_version(self, document_id: int, version_id: int):
        version = self.versions.get(version_id)
        if version is None or version.document_id != document_id:
            raise VersionNotFoundError(version_id)
        return version


def get_diff_service(db: Session = Depends(get_db)) -> DiffService:
    return DiffService(DocumentVersionRepository(db))
