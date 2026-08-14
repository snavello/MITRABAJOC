"""notificaciones y cuit_empleador del trabajador

Revision ID: f3a9c1d84e27
Revises: 7c7be1978d90
Create Date: 2026-08-14 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import sqlmodel


# JSONB en Postgres, JSON común en SQLite -- mismo patrón que Concepto.alias
# y Sindicato.modulos_habilitados.
JSON_TIPO = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

# revision identifiers, used by Alembic.
revision: str = 'f3a9c1d84e27'
down_revision: Union[str, None] = '7c7be1978d90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Opcional: dato nuevo, las filas existentes quedan sin CUIT de empleador.
    with op.batch_alter_table('trabajador', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cuit_empleador', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.create_index(batch_op.f('ix_trabajador_cuit_empleador'), ['cuit_empleador'], unique=False)

    op.create_table('notificacion',
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
    with op.batch_alter_table('notificacion', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_notificacion_sindicato_id'), ['sindicato_id'], unique=False)

    op.create_table('notificaciondestinatario',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('notificacion_id', sa.Integer(), nullable=False),
        sa.Column('cuil', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('leida_en', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.ForeignKeyConstraint(['notificacion_id'], ['notificacion.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('notificaciondestinatario', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_notificaciondestinatario_notificacion_id'), ['notificacion_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_notificaciondestinatario_cuil'), ['cuil'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('notificaciondestinatario', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notificaciondestinatario_cuil'))
        batch_op.drop_index(batch_op.f('ix_notificaciondestinatario_notificacion_id'))
    op.drop_table('notificaciondestinatario')

    with op.batch_alter_table('notificacion', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notificacion_sindicato_id'))
    op.drop_table('notificacion')

    with op.batch_alter_table('trabajador', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_trabajador_cuit_empleador'))
        batch_op.drop_column('cuit_empleador')
