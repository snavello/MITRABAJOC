"""tabla accesolog -- accesos por rol para el dashboard de Actividad

Revision ID: b7d4e1f92a06
Revises: a1c8f5b2e934
Create Date: 2026-09-09 21:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'b7d4e1f92a06'
down_revision: Union[str, None] = 'a1c8f5b2e934'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'accesolog',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('rol', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('sindicato_id', sa.Integer(), nullable=True),
        sa.Column('fecha', sqlmodel.sql.sqltypes.AutoString(), nullable=False,
                   server_default=''),
        sa.ForeignKeyConstraint(['sindicato_id'], ['sindicato.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_accesolog_sindicato_id'), 'accesolog', ['sindicato_id'], unique=False)
    op.create_index(op.f('ix_accesolog_fecha'), 'accesolog', ['fecha'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_accesolog_fecha'), table_name='accesolog')
    op.drop_index(op.f('ix_accesolog_sindicato_id'), table_name='accesolog')
    op.drop_table('accesolog')
