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
    llm_provider: str = "auto"
    proofread_categories: list[str] = ["spelling", "spacing"] 
    proofread_max_chars_per_section: int = 4000
    proofread_batch_max_chars: int = 6000
    proofread_batch_max_sections: int = 40


@lru_cache
def get_settings() -> Settings:
    return Settings()
