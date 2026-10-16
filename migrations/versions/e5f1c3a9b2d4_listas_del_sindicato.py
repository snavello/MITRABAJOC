"""listas del sindicato

Las listas que sube el admin del sindicato por CSV (PLAN_LISTAS_VALIDACIONES.md,
bloque 1): `listasindicato` (una por plantilla + nombre + seccional, con sus
columnas declaradas y quién la cargó) y `filalista` (una fila por registro,
con las dos claves de búsqueda indexadas y los datos en JSONB).

Revision ID: e5f1c3a9b2d4
Revises: d4e8b2a1c7f3
Create Date: 2026-10-16 20:10:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import sqlmodel

revision: str = 'e5f1c3a9b2d4'
down_revision: Union[str, None] = 'd4e8b2a1c7f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_TIPO = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "listasindicato",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sindicato_id", sa.Integer(), nullable=False),
        sa.Column("plantilla", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("nombre", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("seccional_id", sa.Integer(), nullable=True),
        sa.Column("columnas", JSON_TIPO, nullable=False),
        sa.Column("filas", sa.Integer(), nullable=False),
        sa.Column("archivo", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("cargada_en", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("cargada_por", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(["sindicato_id"], ["sindicato.id"]),
        sa.ForeignKeyConstraint(["seccional_id"], ["seccional.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_listasindicato_sindicato_id", "listasindicato", ["sindicato_id"])
    op.create_index("ix_listasindicato_seccional_id", "listasindicato", ["seccional_id"])
    op.create_table(
        "filalista",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lista_id", sa.Integer(), nullable=False),
        sa.Column("clave1", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("clave2", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("datos", JSON_TIPO, nullable=False),
        sa.ForeignKeyConstraint(["lista_id"], ["listasindicato.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_filalista_lista_id", "filalista", ["lista_id"])
    op.create_index("ix_filalista_claves", "filalista", ["lista_id", "clave1", "clave2"])


def downgrade() -> None:
    op.drop_index("ix_filalista_claves", table_name="filalista")
    op.drop_index("ix_filalista_lista_id", table_name="filalista")
    op.drop_table("filalista")
    op.drop_index("ix_listasindicato_seccional_id", table_name="listasindicato")
    op.drop_index("ix_listasindicato_sindicato_id", table_name="listasindicato")
    op.drop_table("listasindicato")
