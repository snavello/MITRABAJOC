"""notificaciones a empleadores

Revision ID: bb24421c03e3
Revises: 826e9627293a
Create Date: 2026-08-17 20:36:51.850462

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import sqlmodel


# JSONB en Postgres, JSON común en SQLite -- mismo patrón que
# Notificacion.criterio_valores (ver f3a9c1d84e27).
JSON_TIPO = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

# revision identifiers, used by Alembic.
revision: str = 'bb24421c03e3'
down_revision: Union[str, None] = '826e9627293a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('notificacionempleador',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sindicato_id', sa.Integer(), nullable=False),
        sa.Column('remitente', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=True),
        sa.Column('texto', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('adjunto_datos', sa.LargeBinary(), nullable=True),
        sa.Column('adjunto_mime', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('adjunto_nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('criterio', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('criterio_valores', JSON_TIPO, nullable=False),
        sa.Column('origen', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('enviado_en', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('cantidad_destinatarios', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['sindicato_id'], ['sindicato.id'], ),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuariosindicato.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('notificacionempleador', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_notificacionempleador_sindicato_id'), ['sindicato_id'], unique=False)

    op.create_table('notificacionempleadordestinatario',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('notificacion_empleador_id', sa.Integer(), nullable=False),
        sa.Column('cuit', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('leida_en', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.ForeignKeyConstraint(['notificacion_empleador_id'], ['notificacionempleador.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('notificacionempleadordestinatario', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_notificacionempleadordestinatario_notificacion_empleador_id'),
                               ['notificacion_empleador_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_notificacionempleadordestinatario_cuit'), ['cuit'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('notificacionempleadordestinatario', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notificacionempleadordestinatario_cuit'))
        batch_op.drop_index(batch_op.f('ix_notificacionempleadordestinatario_notificacion_empleador_id'))
    op.drop_table('notificacionempleadordestinatario')

    with op.batch_alter_table('notificacionempleador', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notificacionempleador_sindicato_id'))
    op.drop_table('notificacionempleador')
