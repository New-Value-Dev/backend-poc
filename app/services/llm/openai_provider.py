from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Sequence

import httpx

from app.services.llm.base import LLMConfigError, LLMError, ProofreadFinding
from app.services.llm.prompts import (
    KNOWN_CATEGORIES,
    proofread_batch_system,
    proofread_system,
)

logger = logging.getLogger(__name__)


class OpenAILLMProvider:
    """OpenAI Chat Completions 로 교정하는 provider"""

    def __init__(
        self,
        api_key: str | None,
        *,
        model: str,
        base_url: str,
        categories: Iterable[str] = ("spelling", "spacing"),
        timeout: float = 120.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self.name = f"openai:{model}"

        self._categories = [c for c in KNOWN_CATEGORIES if c in set(categories)] or [
            "spelling"
        ]
        self._allowed = set(self._categories)
        self._system = proofread_system(self._categories)
        self._batch_system = proofread_batch_system(self._categories)

    def proofread(self, text: str) -> list[ProofreadFinding]:
        content = self._chat(self._system, text)
        data = self._load_json(content)
        raw = data.get("findings", []) if isinstance(data, dict) else []
        return self._to_findings(raw)

    def proofread_batch(self, texts: list[str]) -> list[list[ProofreadFinding]]:
        if not texts:
            return []
        # [번호] 마커로 여러 조각을 한 요청에 담는다.
        user = "\n\n".join(f"[{i}] {t}" for i, t in enumerate(texts))
        content = self._chat(self._batch_system, user)
        data = self._load_json(content)

        out: list[list[ProofreadFinding]] = [[] for _ in texts]
        results = data.get("results", []) if isinstance(data, dict) else []
        for item in results:
            if not isinstance(item, dict):
                continue
            idx = item.get("index")
            if not isinstance(idx, int) or not (0 <= idx < len(texts)):
                continue
            out[idx] = self._to_findings(item.get("findings", []))
        return out

    # ── 내부 ──

    def _chat(self, system: str, user: str) -> str:
        if not self._api_key:
            raise LLMConfigError("OPENAI_API_KEY 가 설정되지 않았습니다")
        payload = {
            "model": self._model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            resp = httpx.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
                timeout=self._timeout,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as exc:
            raise LLMError(
                f"OpenAI 응답 오류 {exc.response.status_code}: {exc.response.text[:200]}"
            ) from exc
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            raise LLMError(f"OpenAI 호출 실패: {exc}") from exc

    @staticmethod
    def _load_json(content: str) -> dict:
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError(f"OpenAI 응답 JSON 파싱 실패: {exc}") from exc
        return data if isinstance(data, dict) else {}

    def _to_findings(self, raw) -> list[ProofreadFinding]:
        findings: list[ProofreadFinding] = []
        if not isinstance(raw, list):
            return findings
        dropped = 0
        for item in raw:
            if not isinstance(item, dict):
                continue
            original = str(item.get("original", "")).strip()
            if not original:
                continue
            category = self._normalize_category(item.get("category"))
            if category is None:
                dropped += 1
                continue
            findings.append(
                ProofreadFinding(
                    original=original,
                    suggestion=str(item.get("suggestion", "")).strip(),
                    reason=str(item.get("reason", "")).strip(),
                    category=category,
                )
            )
        if dropped:
            # 프롬프트로 막아도 긴 문서에서는 종종 새어 나온다. 조용히 버리지 않고 남긴다.
            logger.info("검사 범위 밖 지적 %d건 제외 (허용: %s)", dropped, self._categories)
        return findings

    def _normalize_category(self, raw) -> str | None:
        """응답의 category 를 허용 목록에 맞춘다. 제외 대상이면 None"""
        category = str(raw or "").strip().lower()
        if category in self._allowed:
            return category
        if category in KNOWN_CATEGORIES:
            return None
        return self._categories[0]
