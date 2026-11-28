"""Seccional.responsable: quien responde por la seccional (texto, hasta 120)

Idempotente: la columna se crea solo si falta.

Revision ID: d3f5a7b9c1e4
Revises: c7e1a3b5d9f2
Create Date: 2026-11-27 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = 'd3f5a7b9c1e4'
down_revision: Union[str, None] = 'c7e1a3b5d9f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columnas = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("seccional")}
    if "responsable" not in columnas:
        with op.batch_alter_table("seccional") as batch_op:
            batch_op.add_column(sa.Column("responsable", sqlmodel.sql.sqltypes.AutoString(),
                                          nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("seccional") as batch_op:
        batch_op.drop_column("responsable")
