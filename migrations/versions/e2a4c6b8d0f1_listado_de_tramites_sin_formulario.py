"""el listado de trámites también sin elegir formulario

`descargalistado.tipo_tramite_id` pasa a admitir NULL (2026-10-29): el CSV
baja lo que la bandeja de Trámites tiene filtrado, y el formulario es un
filtro más, no una condición. Una descarga de todos los formularios se
registra igual, con el tipo en NULL y los filtros en texto.

Revision ID: e2a4c6b8d0f1
Revises: d9e1b3c5a7f2
Create Date: 2026-10-29 00:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e2a4c6b8d0f1'
down_revision: Union[str, None] = 'd9e1b3c5a7f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("descargalistado", "tipo_tramite_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM descargalistado WHERE tipo_tramite_id IS NULL")
    op.alter_column("descargalistado", "tipo_tramite_id", existing_type=sa.Integer(), nullable=False)
