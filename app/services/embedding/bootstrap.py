from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.config import Settings
from app.models.embedding_model import EmbeddingModel

logger = logging.getLogger(__name__)

DEFAULT_DIMENSION = 1024


def ensure_default_embedding_model(db, settings: Settings) -> EmbeddingModel:
    """Settings.embedding_model_key 에 해당하는 EmbeddingModel 이 없으면 시드 생성 + 활성화

    .env 만 바꿔도 재배포 시 자동 반영되도록 Alembic 데이터 마이그레이션 대신
    FastAPI startup 훅에서 매번(멱등하게) 확인한다.
    """
    existing = db.scalar(
        select(EmbeddingModel).where(EmbeddingModel.model_key == settings.embedding_model_key)
    )
    if existing is not None:
        return existing

    has_active = db.scalar(select(EmbeddingModel).where(EmbeddingModel.is_active.is_(True)))

    model = EmbeddingModel(
        model_key=settings.embedding_model_key,
        model_name=settings.embedding_model_name,
        dimension=DEFAULT_DIMENSION,
        max_tokens=settings.embedding_max_seq_length,
        status="ACTIVE" if has_active is None else "TEST",
        is_active=has_active is None,
    )
    db.add(model)
    db.commit()
    db.refresh(model)
    logger.info("bootstrapped embedding model: %s (active=%s)", model.model_key, model.is_active)
    return model
