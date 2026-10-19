"""borrador de tipo de trámite

`tipotramite.borrador` (SDN, 2026-10-19): un formulario guardado a medias
para seguirlo otro día. Nace inactivo y sin exigir campos ni área; el
afiliado nunca lo ve. Es una marca aparte de `activo`, porque un formulario
publicado y apagado a propósito no es un borrador. Las filas que ya existen
quedan en falso: todas fueron publicadas.

Revision ID: c7e9a1d3f5b2
Revises: b8d2f6a4c1e9
Create Date: 2026-10-19 08:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c7e9a1d3f5b2'
down_revision: Union[str, None] = 'b8d2f6a4c1e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tipotramite", sa.Column("borrador", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("tipotramite", "borrador")
