"""XSII, bloque 2: el sexto uso de IA elegible desde /plataforma

- configuracionplataforma.modelo_xsii: el modelo de «Preguntame» de XSII
  (vacio = el default del modulo, xsii.proyectos.colm3na.herramientas.MODELO).

Idempotente: la columna se crea solo si falta.

Revision ID: c7e1a3b5d9f2
Revises: a4c6e8b0d2f4
Create Date: 2026-11-27 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = 'c7e1a3b5d9f2'
down_revision: Union[str, None] = 'a4c6e8b0d2f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columnas = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("configuracionplataforma")}
    if "modelo_xsii" not in columnas:
        with op.batch_alter_table("configuracionplataforma") as batch_op:
            batch_op.add_column(sa.Column("modelo_xsii", sqlmodel.sql.sqltypes.AutoString(),
                                          nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("configuracionplataforma") as batch_op:
        batch_op.drop_column("modelo_xsii")
