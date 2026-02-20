from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from app.core.settings import get_settings
from app.core.database import Base
from app import models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata

_MIN_VERSION_NUM_WIDTH = 128


def _ensure_version_num_width(engine) -> None:
    """Widen alembic_version.version_num before migrations run.

    Uses a **separate** connection so that the ALTER TABLE (which causes
    an implicit commit on MySQL) does not interfere with the migration
    connection's transaction state.
    """
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT CHARACTER_MAXIMUM_LENGTH FROM information_schema.columns "
                "WHERE table_schema = DATABASE() "
                "AND table_name = 'alembic_version' "
                "AND column_name = 'version_num'"
            )
        ).first()
        if row is None:
            return  # table does not exist yet; Alembic will create it
        if row[0] is not None and row[0] >= _MIN_VERSION_NUM_WIDTH:
            return  # already wide enough
        conn.execute(
            text(
                f"ALTER TABLE alembic_version "
                f"MODIFY version_num VARCHAR({_MIN_VERSION_NUM_WIDTH}) NOT NULL"
            )
        )
        conn.commit()


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    _ensure_version_num_width(connectable)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            transaction_per_migration=False,
        )

        context.run_migrations()
        connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
