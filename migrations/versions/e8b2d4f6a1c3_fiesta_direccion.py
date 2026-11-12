"""direccion del lugar del evento de la Fiesta (para el mapa)

Revision ID: e8b2d4f6a1c3
Revises: d7a1c3e5f9b2
Create Date: 2026-11-12 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'e8b2d4f6a1c3'
down_revision: Union[str, None] = 'd7a1c3e5f9b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('fiestaevento', sa.Column('direccion', sqlmodel.sql.sqltypes.AutoString(),
                                            nullable=False, server_default=''))
    op.alter_column('fiestaevento', 'direccion', server_default=None)


def downgrade() -> None:
    op.drop_column('fiestaevento', 'direccion')
