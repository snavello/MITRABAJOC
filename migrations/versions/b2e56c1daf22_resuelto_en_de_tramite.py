"""resuelto_en de tramite (Panel Sindical)

Cuándo pasó el trámite a "terminado", para calcular días de resolución. El
backfill desde `actualizado` es EXACTO, no aproximado: un trámite terminado
queda bloqueado (no admite cambios de estado ni notas), así que su
`actualizado` congelado ES el momento en que se terminó.

Revision ID: b2e56c1daf22
Revises: a1d45b0c9e11
Create Date: 2026-08-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = 'b2e56c1daf22'
down_revision: Union[str, None] = 'a1d45b0c9e11'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('tramite', schema=None) as batch_op:
        batch_op.add_column(sa.Column('resuelto_en', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.execute("UPDATE tramite SET resuelto_en = actualizado WHERE estado = 'terminado'")


def downgrade() -> None:
    with op.batch_alter_table('tramite', schema=None) as batch_op:
        batch_op.drop_column('resuelto_en')
