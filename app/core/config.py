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
    # structure 청킹의 하한. 섹션은 파서/교정 apply용 fine-grained 단위(문단 1개 = 섹션 1개)라
    # 그대로 청크로 쓰면 불릿 한 줄이 검색 단위가 된다 — 같은 heading 아래 인접 본문을 이 길이까지
    # 뭉친다. 0이면 뭉치지 않는다(구버전 동작).
    chunk_min_chars: int = 300
    # 구조(heading) 유무로 structure/semantic 청킹을 자동 분기할지. False면 항상 structure.
    chunk_strategy_auto: bool = True
    chunk_semantic_sentence_window: int = 3
    chunk_semantic_breakpoint_percentile: float = 95.0

    # ── Embedding (RAG, local) ──
    # 로컬 모델을 프로세스 안에서 직접 로드(sentence-transformers). 최초 로드 시 HF 캐시로 다운로드됨.
    embedding_provider: str = "local"
    embedding_model_key: str = "kure-v1" # embedding_models.model_key 와 일치
    embedding_model_name: str = "nlpai-lab/KURE-v1"
    embedding_device: str = "cpu" # "cpu" | "cuda"
    # 모델 가중치 저장 위치 — OS 공용 캐시 대신 프로젝트 하위(docker-compose.yml이
    # 애초에 염두에 둔 models/ 디렉토리)에 둬서 컨테이너 재시작 시 재다운로드를 피한다.
    embedding_cache_dir: str = "../models"
    embedding_batch_size: int = 16
    embedding_max_seq_length: int = 512
    # 프로세스 내 동시 로드 가능한 모델 수 상한(LRU eviction). 벤치마크가 여러 모델을
    # 순회할 때 매번 재로딩하면 로딩 시간이 latency 지표를 왜곡시켜 캐시가 필요하다.
    embedding_max_loaded_models: int = 2

    # ── RAG ──
    rag_top_k: int = 6
    rag_min_score: float = 0.3 # 코사인 유사도 하한(너무 안 비슷한 매치 컷)
    rag_context_max_chars: int = 1200 # LLM에 넘길 chunk당 최대 글자수
    rag_expand_siblings: bool = True # 같은 조(article_key)의 나머지 청크를 컨텍스트에 같이 넣을지
    rag_expand_max_extra: int = 6 # 형제 확장으로 추가할 청크 최대 개수(비용/길이 억제)
    # GPT 프롬프트에 넣을 이전 대화 턴 수(후속 질문용)
    rag_history_turns: int = 4
    # 하이브리드 검색(벡터 + PostgreSQL FTS, RRF 융합). False면 예전처럼 벡터 단독
    rag_hybrid_enabled: bool = True
    # 융합 전 각 검색 방식에서 뽑는 후보 수
    rag_hybrid_candidate_k: int = 20
    # RRF 감쇠 상수 — 값이 클수록 순위 차이의 영향이 완만해진다. 업계 표준값(Elasticsearch 기본).
    rag_hybrid_rrf_k: int = 60
    # 후속 질문을 검색 전에 독립 질문으로 재작성
    rag_query_rewrite_enabled: bool = True

    # ── LLM (GPT) ──
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    openai_admin_api_key: str | None = None
    openai_usage_api_key_id: str | None = None
    openai_reasoning_effort: str | None = None  # gpt-5.x 추론 강도(minimal|low|medium|high). low 는 속도 개선 없이 사이시옷 등 실제 오류를 놓쳐 기본값은 미지정(모델 기본 추론)으로 되돌림
    llm_provider: str = "auto"
    proofread_categories: list[str] = ["spelling", "spacing"] 
    proofread_max_chars_per_section: int = 4000
    proofread_batch_max_chars: int = 6000
    proofread_batch_max_sections: int = 40
    proofread_batch_concurrency: int = 4  # 배치 호출 동시 실행 수. 섹션이 많은 문서는 배치가 수십 개로 나뉘어 순차 호출 시 매우 느려짐

    # ── 퀴즈 AI 생성 ──
    # 출제는 검색(질의→top_k)이 아니라 커버리지 문제라 벡터 검색을 쓰지 않는다 — 대상 문서의
    # 청크를 chunk_index 순서대로 전부 가져와 연속 배치로 나눠 출제하므로 문서 앞·중간·뒤가
    # 모두 다뤄지고, 임베딩이 없는 버전(CHUNKED)에서도 동작한다. 근거 절단은 rag_context_max_chars 재사용.
    quiz_gen_max_questions: int = 50
    quiz_gen_questions_per_call: int = 5   # LLM 호출 1회당 요청할 문항 수 → 배치 수를 결정
    quiz_gen_batch_max_chars: int = 6000   # 배치 1개의 근거 총량 상한(프롬프트 길이/비용 억제)
    quiz_gen_concurrency: int = 4          # 배치 병렬 호출 수(proofread_batch_concurrency 와 같은 취지)
    quiz_gen_avoid_sample: int = 50        # 중복 회피용으로 프롬프트에 넣을 기존 문항 수 상한
    # 단답형 채점: 정규화 후에도 불일치하면 활성 임베딩 모델로 코사인 유사도를 보고 유사도 점수 애매하면 GPT 채점
    quiz_short_answer_similarity_high: float = 0.90
    quiz_short_answer_similarity_low: float = 0.60
    # 마감 임박 리마인더
    quiz_due_reminder_window_hours: int = 24
    quiz_due_reminder_interval_seconds: int = 3600

    # ── 관리자 AI 사용량/비용 대시보드 ──
    exchange_rate_api_url: str = "https://open.er-api.com/v6/latest/USD"
    exchange_rate_cache_ttl_seconds: int = 6 * 3600
    # litellm이 공개 유지하는 모델별 단가표
    price_table_url: str = (
        "https://raw.githubusercontent.com/BerriAI/litellm/main/"
        "model_prices_and_context_window.json"
    )
    price_table_cache_ttl_seconds: int = 24 * 3600

    # ── Web Push (VAPID) ──
    vapid_public_key: str | None = None
    vapid_private_key: str | None = None
    vapid_claims_email: str = "mailto:admin@example.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
