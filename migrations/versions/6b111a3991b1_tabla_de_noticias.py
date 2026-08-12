"""tabla de noticias

Revision ID: 6b111a3991b1
Revises: eeaab14b3127
Create Date: 2026-08-12 16:23:07.227559

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '6b111a3991b1'
down_revision: Union[str, None] = 'eeaab14b3127'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('noticia',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sindicato_id', sa.Integer(), nullable=False),
        sa.Column('titulo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('bajada', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('texto_completo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('fecha_desde', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('fecha_hasta', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('creada', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('imagen1_datos', sa.LargeBinary(), nullable=True),
        sa.Column('imagen1_mime', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('imagen2_datos', sa.LargeBinary(), nullable=True),
        sa.Column('imagen2_mime', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['sindicato_id'], ['sindicato.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('noticia', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_noticia_sindicato_id'), ['sindicato_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('noticia', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_noticia_sindicato_id'))
    op.drop_table('noticia')
