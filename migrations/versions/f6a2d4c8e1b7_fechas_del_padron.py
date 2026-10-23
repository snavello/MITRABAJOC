"""fechas del padrón

Las dos fechas de PLAN_LISTAS_VALIDACIONES.md (D4, bloque 2):
`trabajador.fecha_afiliacion` (del empadronamiento: la carga solo el
sindicato) y `cuentatrabajador.fecha_nacimiento` (de la persona: la carga el
afiliado o el sindicato). Texto ISO, NULL = no se cargó. Son hechos, no
derivados: la antigüedad y la edad se calculan donde hacen falta.

Revision ID: f6a2d4c8e1b7
Revises: e5f1c3a9b2d4
Create Date: 2026-10-16 21:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = 'f6a2d4c8e1b7'
down_revision: Union[str, None] = 'e5f1c3a9b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("trabajador", sa.Column("fecha_afiliacion", sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.add_column("cuentatrabajador", sa.Column("fecha_nacimiento", sqlmodel.sql.sqltypes.AutoString(), nullable=True))


def downgrade() -> None:
    op.drop_column("cuentatrabajador", "fecha_nacimiento")
    op.drop_column("trabajador", "fecha_afiliacion")
