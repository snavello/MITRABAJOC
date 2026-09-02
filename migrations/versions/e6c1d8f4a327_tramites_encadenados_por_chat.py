"""Trámites encadenados por chat

Un trámite iniciado desde el formulario adjunto en el CHAT de otro trámite
queda vinculado (origen_tramite_id): ambos chats muestran el vínculo, para
el trabajador/la empresa y para el sindicato. Las aperturas desde noticias/
beneficios/notificaciones no vinculan.

Revision ID: e6c1d8f4a327
Revises: d5b8c3e9f214
Create Date: 2026-09-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e6c1d8f4a327'
down_revision: Union[str, None] = 'd5b8c3e9f214'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for tabla in ("tramite", "tramiteempleador"):
        with op.batch_alter_table(tabla, schema=None) as batch_op:
            batch_op.add_column(sa.Column('origen_tramite_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    for tabla in ("tramite", "tramiteempleador"):
        with op.batch_alter_table(tabla, schema=None) as batch_op:
            batch_op.drop_column('origen_tramite_id')
