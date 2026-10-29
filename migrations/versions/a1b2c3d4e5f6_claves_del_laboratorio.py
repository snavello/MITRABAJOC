"""claves de los proveedores del Laboratorio de modelos

`configuracionplataforma.claves_laboratorio` (2026-10-29): las claves de Kimi
y Qwen pegadas desde la pantalla del laboratorio, {variable: clave}. Solo
evaluación; una variable de entorno con el mismo nombre manda.

Revision ID: a1b2c3d4e5f6
Revises: e2a4c6b8d0f1
Create Date: 2026-10-29 02:20:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'e2a4c6b8d0f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("configuracionplataforma",
                  sa.Column("claves_laboratorio", sa.JSON().with_variant(JSONB, "postgresql"), nullable=True))


def downgrade() -> None:
    op.drop_column("configuracionplataforma", "claves_laboratorio")
