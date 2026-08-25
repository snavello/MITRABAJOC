"""logo de plataforma para fondo oscuro

Revision ID: 958e950a78f0
Revises: a7e35b91c8d4
Create Date: 2026-08-25 11:49:51.913769

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '958e950a78f0'
down_revision: Union[str, None] = 'a7e35b91c8d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('configuracionplataforma', sa.Column('logo_oscuro', sa.String(), nullable=False, server_default=''))
    op.add_column('configuracionplataforma', sa.Column('logo_datos_oscuro', sa.LargeBinary(), nullable=True))
    op.add_column('configuracionplataforma', sa.Column('logo_mime_oscuro', sa.String(), nullable=False, server_default=''))


def downgrade() -> None:
    op.drop_column('configuracionplataforma', 'logo_mime_oscuro')
    op.drop_column('configuracionplataforma', 'logo_datos_oscuro')
    op.drop_column('configuracionplataforma', 'logo_oscuro')
