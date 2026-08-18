"""foto de perfil en cuentaempleador

Revision ID: bd0236c61d6c
Revises: dd4045d6c27b
Create Date: 2026-08-18 17:11:49.432678

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'bd0236c61d6c'
down_revision: Union[str, None] = 'dd4045d6c27b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('cuentaempleador', schema=None) as batch_op:
        batch_op.add_column(sa.Column('foto_datos', sa.LargeBinary(), nullable=True))
        batch_op.add_column(sa.Column('foto_mime', sqlmodel.sql.sqltypes.AutoString(),
                                       nullable=False, server_default=''))


def downgrade() -> None:
    with op.batch_alter_table('cuentaempleador', schema=None) as batch_op:
        batch_op.drop_column('foto_mime')
        batch_op.drop_column('foto_datos')
