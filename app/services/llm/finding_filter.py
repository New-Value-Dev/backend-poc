"""교정 제안(finding) 후처리 검증

모델 응답은 프롬프트로 막아도 정상 표기를 오류로 보거나, 띄어쓰기 항목에 글자 수정을 섞거나,
원문에 없는 구절을 인용하는 일이 생긴다. 이 모듈은 그런 제안을 사용자에게 보이기 전에 걸러낸다.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

# 축약 코드(o/s/c/n 스키마의 c) → 카테고리
CATEGORY_CODES = {
    "s": "spelling",
    "p": "spacing",
    "g": "grammar",
    "e": "expression",
}


def parse_finding(
    finding: dict,
    active_categories: set[str] | list[str],
    protected_terms: list[str] | None = None,
) -> dict | None:
    """축약 finding({o, s, c, n})을 검증해 내부 형식으로 바꾼다. 버려야 하면 None."""
    if not isinstance(finding, dict):
        return None

    original = finding.get("o", finding.get("original", ""))
    suggestion = finding.get("s", finding.get("suggestion", ""))
    if not isinstance(original, str) or not isinstance(suggestion, str):
        return None
    if not original or not suggestion or original == suggestion:
        return None

    # 등록된 고유명사는 그대로 두고 주변 오류만 고칠 수 있다.
    # 실제 변경 구간이 등록어와 겹칠 때만 차단하고, 등록어의 일부만 인용한 교정도 차단한다.
    changes: list[tuple[int, int]] | None = None
    for term in protected_terms or []:
        term = str(term).strip()
        if not term:
            continue
        if original in term:
            return None
        if term not in original:
            continue
        if changes is None:
            changes = [
                (a, b)
                for op, a, b, _, _ in SequenceMatcher(
                    None, original, suggestion, autojunk=False
                ).get_opcodes()
                if op != "equal"
            ]
        start = original.find(term)
        while start >= 0:
            end = start + len(term)
            if any(
                (a < end and start < b) if a != b else (start < a < end)
                for a, b in changes
            ):
                return None
            start = original.find(term, start + 1)

    category = str(finding.get("c", finding.get("category", ""))).strip().lower()
    category = CATEGORY_CODES.get(category, category)
    if category not in active_categories:
        return None

    # 띄어쓰기는 공백만 달라져야 한다. 조사 추가·문장부호 삭제 같은 글자 수정을
    # spacing 으로 우회 적용하지 못하게 막는다.
    if category == "spacing":
        if re.sub(r"\s+", "", original) != re.sub(r"\s+", "", suggestion):
            return None

    # 맞춤법은 어절 수와 구분 공백을 유지한 채 글자만 바뀌어야 하고,
    # 문장부호·숫자 구분점만 바꾸는 편집 제안은 제외한다.
    if category == "spelling":
        if re.sub(r"\S+", "_", original) != re.sub(r"\S+", "_", suggestion):
            # 한 어절 안에 철자 오류와 띄어쓰기 오류가 함께 있으면(예: 않좋았다→안 좋았다)
            # 따로 적용할 때 서로 겹쳐 어긋난다. 띄어쓰기 검사가 켜져 있으면 하나로 합친 교정을 허용하되,
            # 글자가 많이 달라지는 구절 재작성은 계속 막는다.
            if "spacing" not in active_categories:
                return None
            a = re.sub(r"\s+", "", original)
            b = re.sub(r"\s+", "", suggestion)
            # 공백을 뺀 글자 수가 같아야(치환만 허용, 글자 추가·삭제 금지) 하고 바뀐 글자는 절반 이하
            if len(a) != len(b) or sum(x != y for x, y in zip(a, b)) > max(1, len(a) // 2):
                return None
        original_letters = re.sub(r"[^\w]", "", original, flags=re.UNICODE)
        suggestion_letters = re.sub(r"[^\w]", "", suggestion, flags=re.UNICODE)
        if original_letters == suggestion_letters:
            return None

    occurrence = finding.get("n", finding.get("occurrence", 1))
    if type(occurrence) is not int or occurrence < 1:
        return None

    return {
        "original": original,
        "suggestion": suggestion,
        "category": category,
        "occurrence": occurrence,
    }
