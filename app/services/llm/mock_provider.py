from __future__ import annotations

import re

from app.services.llm.base import ProofreadFinding

# 키 없이도 데모가 되도록 하는 아주 단순한 규칙 사전
# 실제 교정은 OpenAILLMProvider(GPT)가 담당하고 이건 개발/폴백용
_COMMON_TYPOS: dict[str, tuple[str, str]] = {
    "됬": ("됐", "'되었'의 준말은 '됐'입니다"),
    "안되요": ("안돼요", "'되어요'의 준말이므로 '안돼요'가 맞습니다"),
    "안됀": ("안 된", "'안 된'으로 띄어 씁니다"),
    "왠만": ("웬만", "'웬만하다'가 표준어입니다"),
    "역활": ("역할", "'역할'이 올바른 표기입니다"),
    "몇일": ("며칠", "'며칠'이 올바른 표기입니다"),
    "바램": ("바람", "'바라다'의 명사형은 '바람'입니다"),
    "설레임": ("설렘", "'설레다'의 명사형은 '설렘'입니다"),
    "금새": ("금세", "'지금 바로'의 뜻은 '금세'입니다"),
    "일찌기": ("일찍이", "'일찍이'가 올바른 표기입니다"),
    "오랫만": ("오랜만", "'오래간만'의 준말은 '오랜만'입니다"),
    "어의없": ("어이없", "'어이없다'가 올바른 표기입니다"),
    "희안": ("희한", "'희한하다'가 올바른 표기입니다"),
}

_MULTISPACE = re.compile(r"[^\S\n]{2,}")


class MockLLMProvider:
    """규칙 기반 오탈자 검출기(개발/폴백용, API 키 불필요)."""

    name = "mock"

    def proofread(self, text: str) -> list[ProofreadFinding]:
        findings: list[ProofreadFinding] = []
        seen: set[str] = set()

        for typo, (fix, reason) in _COMMON_TYPOS.items():
            if typo in text and typo not in seen:
                seen.add(typo)
                findings.append(
                    ProofreadFinding(
                        original=typo,
                        suggestion=fix,
                        reason=reason,
                        category="spelling",
                    )
                )

        # 연속 공백(줄바꿈 제외)
        if _MULTISPACE.search(text):
            findings.append(
                ProofreadFinding(
                    original="  ",
                    suggestion=" ",
                    reason="연속된 공백은 하나로 줄입니다",
                    category="spacing",
                )
            )
        return findings

    def proofread_batch(self, texts: list[str]) -> list[list[ProofreadFinding]]:
        # 규칙 기반은 호출 비용이 없으므로 각 텍스트를 그대로 처리한다.
        return [self.proofread(t) for t in texts]
