"""Campo de trámite retirado (fix del 500 al editar un tipo con trámites)

editar_tipo_tramite borraba y recreaba los campos; con trámites ya
presentados, RespuestaTramite.campo_tramite_id referencia esos campos y
Postgres rechaza el DELETE (FK) -> E-INTERNO-00. Ahora la edición sincroniza
por id, y un campo quitado que ya tiene respuestas se marca retirado=True en
vez de borrarse: sale del formulario pero los trámites viejos conservan su
etiqueta. (En SQLite nunca falló porque no exige FKs -- por eso los tests no
lo vieron.)

Revision ID: b7e3d1a5c942
Revises: a1f5c2d94b18
Create Date: 2026-09-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b7e3d1a5c942'
down_revision: Union[str, None] = 'a1f5c2d94b18'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for tabla in ("campotramite", "campotramiteempleador"):
        with op.batch_alter_table(tabla, schema=None) as batch_op:
            batch_op.add_column(sa.Column('retirado', sa.Boolean(), nullable=False,
                                          server_default=sa.false()))


def downgrade() -> None:
    for tabla in ("campotramite", "campotramiteempleador"):
        with op.batch_alter_table(tabla, schema=None) as batch_op:
            batch_op.drop_column('retirado')
