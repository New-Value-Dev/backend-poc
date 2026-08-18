from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# 앱 설정과 모델을 불러온다. (app 패키지는 alembic 을 backend/ 에서 실행할 때 import 가능)
from app.core.config import get_settings
from app.core.database import Base
import app.models  # noqa: F401  -- 모든 테이블을 Base.metadata 에 등록하기 위해 import

config = context.config

# DATABASE_URL 은 코드(설정)에서 주입한다. 컨테이너=db:5432, 로컬=localhost:5432 를 env 로 구분.
config.set_main_option("sqlalchemy.url", get_settings().database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def render_item(type_, obj, autogen_context):
    """pgvector 의 Vector 타입을 마이그레이션에 올바른 import 와 함께 렌더링한다."""
    if type_ == "type" and obj.__class__.__module__.startswith("pgvector"):
        autogen_context.imports.add("import pgvector.sqlalchemy")
        return f"pgvector.sqlalchemy.Vector(dim={obj.dim})"
    return False


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_item=render_item,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_item=render_item,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
