"""requisitos de un tipo de trámite

`tipotramite.requisitos` (PLAN_LISTAS_VALIDACIONES.md, bloque 3): la lista
de validaciones de fuente `funcion` que hay que cumplir para INICIAR el
trámite. JSONB como las reglas de consistencia; vacía = sin requisitos.

Revision ID: a9c4e7f2d1b6
Revises: f6a2d4c8e1b7
Create Date: 2026-10-16 21:40:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a9c4e7f2d1b6'
down_revision: Union[str, None] = 'f6a2d4c8e1b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_TIPO = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("tipotramite") as batch_op:
        batch_op.add_column(sa.Column("requisitos", JSON_TIPO, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tipotramite") as batch_op:
        batch_op.drop_column("requisitos")
