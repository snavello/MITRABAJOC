"""descargas del listado de trámites

`descargalistado` (2026-10-28): cada descarga del CSV de trámites con sus
respuestas, con quién, cuándo, qué formulario, qué filtros y cuántas filas.
Mismo criterio que EventoEncuesta: una planilla con datos de familiares es
dato sensible, y tiene que poder saberse de dónde salió.

Revision ID: d9e1b3c5a7f2
Revises: c4f8a2d6e1b9
Create Date: 2026-10-28 23:50:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd9e1b3c5a7f2'
down_revision: Union[str, None] = 'c4f8a2d6e1b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "descargalistado",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sindicato_id", sa.Integer(), sa.ForeignKey("sindicato.id"), nullable=False),
        sa.Column("tipo_tramite_id", sa.Integer(), sa.ForeignKey("tipotramite.id"), nullable=False),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuariosindicato.id"), nullable=True),
        sa.Column("filtros", sa.String(), nullable=False, server_default=""),
        sa.Column("filas", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fecha", sa.String(), nullable=False, server_default=""),
    )
    op.create_index("ix_descargalistado_sindicato_id", "descargalistado", ["sindicato_id"])
    op.create_index("ix_descargalistado_tipo_tramite_id", "descargalistado", ["tipo_tramite_id"])


def downgrade() -> None:
    op.drop_index("ix_descargalistado_tipo_tramite_id", table_name="descargalistado")
    op.drop_index("ix_descargalistado_sindicato_id", table_name="descargalistado")
    op.drop_table("descargalistado")
