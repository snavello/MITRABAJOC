"""foto de perfil del trabajador

Revision ID: f774fd280364
Revises: ce6e53300c75
Create Date: 2026-08-17 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'f774fd280364'
down_revision: Union[str, None] = 'ce6e53300c75'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('cuentatrabajador', schema=None) as batch_op:
        batch_op.add_column(sa.Column('foto_datos', sa.LargeBinary(), nullable=True))
        batch_op.add_column(sa.Column('foto_mime', sqlmodel.sql.sqltypes.AutoString(),
                                       nullable=False, server_default=''))


def downgrade() -> None:
    with op.batch_alter_table('cuentatrabajador', schema=None) as batch_op:
        batch_op.drop_column('foto_mime')
        batch_op.drop_column('foto_datos')
