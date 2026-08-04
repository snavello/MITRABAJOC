"""Entorno de Alembic para Mi Trabajo.

Usa el MISMO engine y modelos que la aplicación (db.py), en vez de una URL
fija en alembic.ini. Así, Alembic lee DATABASE_URL del entorno igual que la app:
apunta a Postgres si está definida, o a SQLite en desarrollo.
"""
from logging.config import fileConfig
from alembic import context

# Importa el engine y los modelos ya definidos por la app.
# SQLModel.metadata conoce todas las tablas (Sindicato, Trabajador, etc.).
import db  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata de todos los modelos SQLModel: lo que Alembic compara para autogenerar.
target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Modo offline: emite SQL sin conectarse (genera scripts)."""
    context.configure(
        url=str(db.engine.url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Modo online: usa el engine real de la app."""
    with db.engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,          # detecta cambios de tipo de columna
            render_as_batch=db.engine.dialect.name == "sqlite",  # ALTER seguro en SQLite
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
