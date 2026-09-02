"""Visto de trámites para el globo de novedades

Las novedades de un trámite dejan de generar Notificacion: el globo va en
Trámites (decisión de Sd 2026-09-02). Se marca cuándo el trabajador/la
empresa abrió el detalle por última vez; actualizado > visto = novedad.

Revision ID: f2a7b9c4d156
Revises: e6c1d8f4a327
Create Date: 2026-09-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f2a7b9c4d156'
down_revision: Union[str, None] = 'e6c1d8f4a327'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tramite", schema=None) as batch_op:
        batch_op.add_column(sa.Column('visto_trabajador_en', sa.String(), nullable=True))
    with op.batch_alter_table("tramiteempleador", schema=None) as batch_op:
        batch_op.add_column(sa.Column('visto_empresa_en', sa.String(), nullable=True))
    # Backfill: lo existente se considera visto (nadie estrena un globo
    # lleno por historia vieja).
    op.execute("UPDATE tramite SET visto_trabajador_en = actualizado")
    op.execute("UPDATE tramiteempleador SET visto_empresa_en = actualizado")


def downgrade() -> None:
    with op.batch_alter_table("tramiteempleador", schema=None) as batch_op:
        batch_op.drop_column('visto_empresa_en')
    with op.batch_alter_table("tramite", schema=None) as batch_op:
        batch_op.drop_column('visto_trabajador_en')
