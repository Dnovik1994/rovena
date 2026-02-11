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


def _ensure_version_num_width(connection) -> None:
    """Widen alembic_version.version_num before migrations run.

    Uses raw information_schema queries (not sa_inspect) to avoid
    SQLAlchemy reflection caching issues inside the migration context.
    """
    row = connection.execute(
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
    connection.execute(
        text(
            f"ALTER TABLE alembic_version "
            f"MODIFY version_num VARCHAR({_MIN_VERSION_NUM_WIDTH}) NOT NULL"
        )
    )
    connection.commit()


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

    with connectable.connect() as connection:
        _ensure_version_num_width(connection)

        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
