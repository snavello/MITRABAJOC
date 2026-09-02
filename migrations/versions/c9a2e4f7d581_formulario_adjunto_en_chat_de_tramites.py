"""Formulario adjunto en el chat de trámites

El admin puede adjuntar un formulario (tipo de trámite) en un mensaje del
chat: el trabajador/la empresa ve una tarjeta "Iniciar este trámite" que
abre ese formulario directo. Int sin FK a propósito: un tipo borrado se
muestra "ya no disponible" en el chat en vez de impedir el borrado.

Revision ID: c9a2e4f7d581
Revises: b7e3d1a5c942
Create Date: 2026-09-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c9a2e4f7d581'
down_revision: Union[str, None] = 'b7e3d1a5c942'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for tabla in ("notatramite", "notatramiteempleador"):
        with op.batch_alter_table(tabla, schema=None) as batch_op:
            batch_op.add_column(sa.Column('formulario_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    for tabla in ("notatramite", "notatramiteempleador"):
        with op.batch_alter_table(tabla, schema=None) as batch_op:
            batch_op.drop_column('formulario_id')
