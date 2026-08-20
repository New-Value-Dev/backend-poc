from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "사이드프로젝트 API"
    app_description: str = "사이드프로젝트 백엔드 API"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"

    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/ai_platform"

    cors_allow_origins: list[str] = ["http://localhost:3000"]

    jwt_secret: str = "dev-secret-change-me"  # 운영에서는 반드시 .env 로 교체
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 14

    # 로그인 콜백 후 프론트로 돌아갈 주소
    frontend_url: str = "http://localhost:3000"
    auth_providers: list[str] = ["mock"]

    # refresh 토큰 쿠키
    cookie_secure: bool = False  # https 배포 시 True
    cookie_samesite: str = "lax"

    # ── Google OAuth ──
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str | None = None

    # ── Storage (로컬 파일) ──
    storage_root: str = "../storage"
    max_upload_mb: int = 50
    allowed_upload_extensions: list[str] = [
        "pdf", "hwpx", "hwp", "docx", "xlsx", "pptx", "txt", "md",
    ]

    # ── Chunking ──
    chunk_max_chars: int = 1000
    chunk_overlap_chars: int = 150

    # ── LLM (GPT) ──
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    openai_reasoning_effort: str | None = None  # gpt-5.x 추론 강도(minimal|low|medium|high). low 는 속도 개선 없이 사이시옷 등 실제 오류를 놓쳐 기본값은 미지정(모델 기본 추론)으로 되돌림
    llm_provider: str = "auto"
    proofread_categories: list[str] = ["spelling", "spacing"] 
    proofread_max_chars_per_section: int = 4000
    proofread_batch_max_chars: int = 6000
    proofread_batch_max_sections: int = 40
    proofread_batch_concurrency: int = 4  # 배치 호출 동시 실행 수. 섹션이 많은 문서는 배치가 수십 개로 나뉘어 순차 호출 시 매우 느려짐

    # ── Embedding (RAG, local) ──
    # 로컬 모델을 백엔드 프로세스 안에서 직접 로드한다(문서를 외부로 안 보냄).
    # embedding-lab mockup에서 팀원이 이미 "한국어 문서라 KURE-v1을 활성 모델로 선정" 이라고
    # 결론 내려둔 걸 따른다(Recall@5 기준 가장 높음).
    embedding_provider: str = "local"          # 현재는 "local"만 지원
    embedding_model_key: str = "kure-v1"       # embedding_models.model_key 와 일치
    embedding_model_name: str = "nlpai-lab/KURE-v1"
    embedding_device: str = "cpu"              # "cpu" | "cuda"
    # 모델 가중치 저장 위치 — OS 공용 캐시 대신 프로젝트 하위(docker-compose.yml이
    # 애초에 염두에 둔 models/ 디렉토리)에 둬서 컨테이너 재시작 시 재다운로드를 피한다.
    embedding_cache_dir: str = "../models"
    embedding_batch_size: int = 16
    embedding_max_seq_length: int = 512

    # ── RAG ──
    rag_top_k: int = 6
    rag_min_score: float = 0.3           # 코사인 유사도 하한(너무 안 비슷한 매치 컷)
    rag_context_max_chars: int = 1200    # LLM에 넘길 chunk당 최대 글자수
    rag_expand_siblings: bool = True     # 같은 조(article_key)의 나머지 청크를 컨텍스트에 같이 넣을지
    rag_expand_max_extra: int = 6        # 형제 확장으로 추가할 청크 최대 개수(비용/길이 억제)


@lru_cache
def get_settings() -> Settings:
    return Settings()
