from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chunking_config import ChunkingConfig


class ChunkingConfigRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_active(self) -> ChunkingConfig | None:
        return self.db.scalar(select(ChunkingConfig).where(ChunkingConfig.is_active.is_(True)))

    def get(self, config_id: int) -> ChunkingConfig | None:
        return self.db.get(ChunkingConfig, config_id)

    def add(self, config: ChunkingConfig) -> ChunkingConfig:
        self.db.add(config)
        self.db.flush()
        return config

    def activate(self, config: ChunkingConfig) -> ChunkingConfig:
        """다른 설정을 전부 비활성화하고 이 설정만 활성화한다. embedding_models.activate와 동일 패턴."""
        for other in self.db.scalars(
            select(ChunkingConfig).where(ChunkingConfig.is_active.is_(True))
        ):
            other.is_active = False
        config.is_active = True
        self.db.commit()
        self.db.refresh(config)
        return config
