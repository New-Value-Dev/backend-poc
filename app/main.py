from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app.models  # noqa: F401  -- 모든 SQLAlchemy 매퍼가 등록되도록 import
from app.api.v1.router import api_router
from app.core.config import get_settings

settings = get_settings()

# Swagger UI 상단에 노출되는 API 전체 설명.
API_DESCRIPTION = f"""
{settings.app_description}

프로젝트 단위로 비정형 문서를 **Document Core**(File → Version → Section → Chunk → Embedding)에
적재하고, 그 위에 AI 기능(오탈자 검증 · 분류 · 버전 비교 · 규정 검증 · RAG)을 얹는 플랫폼입니다.

### 인증
`auth` 태그를 제외한 대부분의 엔드포인트는 **`Authorization: Bearer <access_token>`** 이 필요합니다.

1. `GET /auth/providers` 로 활성 로그인 수단 확인 (dev 는 `mock` 사용 가능)
2. **브라우저 주소창**에서 `GET /auth/login/{{provider}}` 실행 → IdP 로그인 → 콜백에서 refresh 토큰이
   httpOnly 쿠키로 심어집니다. *(리다이렉트라 Swagger 의 "Try it out" 으로는 동작하지 않습니다)*
3. `POST /auth/token/refresh` 로 access 토큰 발급
4. 우측 상단 **Authorize** 버튼에 access 토큰을 넣으면 이 문서에서 바로 호출할 수 있습니다.

### 문서 처리 상태 흐름
`UPLOADED → PARSING → PARSED → CHUNKING → CHUNKED → EMBEDDING → READY` (실패 시 `FAILED`).
업로드 한 번으로 파싱·청킹·임베딩(로컬 KURE-v1)까지 자동으로 이어져 `READY`에 도달합니다.

### 비동기 작업 규약
업로드와 AI 분석은 즉시 `202 Accepted` 를 돌려주고 실제 처리는 백그라운드에서 진행합니다.
진행 상황은 폴링으로 확인합니다 — 파싱은 `GET /versions/{{id}}/status`,
AI 분석은 `GET /documents/{{id}}/analyses/{{analysis_id}}`.
"""

# 태그별 그룹 설명 (Swagger 의 섹션 헤더).
TAGS_METADATA = [
    {
        "name": "health",
        "description": "서버·DB 생존 확인. 인증 불필요.",
    },
    {
        "name": "auth",
        "description": (
            "Google OAuth + 백엔드 발급 JWT. access 토큰은 `Authorization: Bearer`, "
            "refresh 토큰은 httpOnly 쿠키로 오갑니다. dev 용 `mock` provider 로 "
            "크리덴셜 없이 로그인할 수 있습니다."
        ),
    },
    {
        "name": "dashboard",
        "description": (
            "홈 대시보드 집계와 활동 피드. **이 그룹의 응답 필드만 camelCase** 입니다 "
            "(프론트가 먼저 확정한 계약에 맞춤). 나머지 API 는 snake_case."
        ),
    },
    {
        "name": "projects",
        "description": "프로젝트 CRUD. 모든 문서·폴더가 속하는 최상위 단위입니다.",
    },
    {
        "name": "folders",
        "description": "프로젝트 내부 폴더 트리. `parent_id` 로 계층을 만들며 이동 시 순환을 차단합니다.",
    },
    {
        "name": "documents",
        "description": (
            "Document Core. 업로드(멀티파트) → 파싱 → 청킹 파이프라인과 "
            "버전·섹션·청크 조회를 담당합니다."
        ),
    },
    {
        "name": "ai-proofread",
        "description": (
            "오탈자 검증(MVP1의 첫 AI 모듈)과 AI 분석 이력 조회. 결과는 모든 AI 모듈이 공유하는 "
            "`ai_analysis_results` 테이블에 적재됩니다."
        ),
    },
    {
        "name": "rag",
        "description": (
            "문서 기반 질의응답. 로컬 임베딩(KURE-v1) → pgvector 벡터 검색 → LLM 답변 생성 "
            "순으로 동작하며, 단일 활성 모델·순수 벡터 검색 MVP입니다."
        ),
    },
]

app = FastAPI(
    title=settings.app_name,
    description=API_DESCRIPTION,
    version=settings.app_version,
    openapi_tags=TAGS_METADATA,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_prefix)
