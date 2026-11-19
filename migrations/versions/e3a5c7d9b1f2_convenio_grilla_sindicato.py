"""convenio de la grilla por sindicato

PLAN_CONVENIO_ESCALAS.md, D43: columna `sindicato.convenio_grilla` (texto, vacío =
ninguno) con el convenio cuya grilla y texto ve el afiliado en la app. Idempotente:
la columna se crea solo si falta.

Revision ID: e3a5c7d9b1f2
Revises: d8f2b4a6c0e1
Create Date: 2026-11-19 09:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = 'e3a5c7d9b1f2'
down_revision: Union[str, None] = 'd8f2b4a6c0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columnas() -> set:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("sindicato")}


def upgrade() -> None:
    if "convenio_grilla" not in _columnas():
        op.add_column("sindicato", sa.Column(
            "convenio_grilla", sqlmodel.sql.sqltypes.AutoString(), nullable=False,
            server_default=""))
        op.alter_column("sindicato", "convenio_grilla", server_default=None)


def downgrade() -> None:
    if "convenio_grilla" in _columnas():
        op.drop_column("sindicato", "convenio_grilla")
