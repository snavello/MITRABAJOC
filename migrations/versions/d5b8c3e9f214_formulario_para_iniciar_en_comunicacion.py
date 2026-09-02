"""Formulario "para iniciar" en Noticias, Beneficios y Notificaciones

Extiende el formulario adjunto del chat de Trámites a los tres canales de
comunicación: un ícono en la noticia/el beneficio/la notificación abre el
formulario directo ("completá los datos haciendo click acá" lo escribe el
admin en el texto). Int sin FK, mismo criterio que NotaTramite.formulario_id.

Revision ID: d5b8c3e9f214
Revises: c9a2e4f7d581
Create Date: 2026-09-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd5b8c3e9f214'
down_revision: Union[str, None] = 'c9a2e4f7d581'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLAS = ("noticia", "beneficio", "notificacion", "notificacionempleador")


def upgrade() -> None:
    for tabla in TABLAS:
        with op.batch_alter_table(tabla, schema=None) as batch_op:
            batch_op.add_column(sa.Column('formulario_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    for tabla in TABLAS:
        with op.batch_alter_table(tabla, schema=None) as batch_op:
            batch_op.drop_column('formulario_id')
