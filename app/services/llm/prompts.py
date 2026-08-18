"""LLM 프롬프트 모음"""

from __future__ import annotations

from collections.abc import Iterable

# ── Proofread ──
KNOWN_CATEGORIES = ("spelling", "spacing", "grammar", "expression")

CATEGORY_LABELS = {
    "spelling": "맞춤법·오탈자",
    "spacing": "띄어쓰기",
    "grammar": "문법(조사·어미·호응)",
    "expression": "어색한 표현·문체",
}

_EXCLUSION_RULES = {
    "expression": (
        "- 문장이 어색하다 / 더 자연스럽게 / 간결하게 같은 표현·문체 제안\n"
        "- 문맥·논리·구성·어투에 대한 의견, 번역투 지적, 용어 통일 제안"
    ),
    "grammar": (
        "- 조사·어미·문장 호응 등 문법 지적 "
        "(단어 자체가 틀린 맞춤법이면 그건 맞춤법으로 본다)"
    ),
    "spacing": "- 띄어쓰기 지적",
    "spelling": "- 맞춤법·오탈자 지적",
}


def _scope(categories: Iterable[str]) -> tuple[str, str, str]:
    """(검사 대상 문구, 제외 규칙 블록, category enum 문구)."""
    active = [c for c in KNOWN_CATEGORIES if c in set(categories)] or ["spelling"]
    target = "·".join(CATEGORY_LABELS[c] for c in active)
    enum = "|".join(active)

    excluded = [c for c in KNOWN_CATEGORIES if c not in active]
    if excluded:
        rules = "\n".join(_EXCLUSION_RULES[c] for c in excluded)
        block = (
            "\n다음은 오류가 아니므로 **절대 지적하지 않는다**:\n"
            f"{rules}\n"
            "확신이 서지 않으면 지적하지 않는다. 명백히 틀린 것만 올린다.\n"
        )
    else:
        block = ""
    return target, block, enum


def proofread_system(categories: Iterable[str]) -> str:
    """단건 교정용 system 프롬프트. user 메시지는 검사할 텍스트."""
    target, exclusions, enum = _scope(categories)
    return (
        f"너는 한국어 문서 교정 전문가다. 입력 텍스트에서 {target} 오류만 찾아 교정한다. "
        "내용을 바꾸거나 새로 쓰지 말고, 실제 오류만 지적한다.\n"
        f"{exclusions}"
        "반드시 다음 형태의 JSON 객체 하나만 출력한다(설명 문장 금지):\n"
        '{"findings": [{"original": "원문 표현", "suggestion": "교정안", '
        f'"reason": "간단한 이유", "category": "{enum}"}}]}}\n'
        "오류가 없으면 findings 를 빈 배열로 둔다."
    )


def proofread_batch_system(categories: Iterable[str]) -> str:
    """배치 교정용. 여러 섹션을 [번호]로 묶어 보내고 index 로 되매핑한다."""
    target, exclusions, enum = _scope(categories)
    return (
        "너는 한국어 문서 교정 전문가다. 여러 텍스트 조각이 각각 [번호] 형식으로 주어진다.\n"
        f"각 조각에서 {target} 오류만 찾아 교정한다. "
        "내용을 바꾸거나 새로 쓰지 말고, 실제 오류만 지적한다.\n"
        f"{exclusions}"
        "반드시 다음 형태의 JSON 객체 하나만 출력한다(설명 문장 금지):\n"
        '{"results": [{"index": 조각번호, "findings": [{"original": "원문 표현", '
        '"suggestion": "교정안", "reason": "간단한 이유", '
        f'"category": "{enum}"}}]}}]}}\n'
        "오류가 없는 조각은 findings 를 빈 배열로 두거나 생략한다."
    )
