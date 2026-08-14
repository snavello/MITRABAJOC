"""tramites: formularios dinamicos con seguimiento de expediente

Revision ID: a8c25f9b6d31
Revises: f3a9c1d84e27
Create Date: 2026-08-14 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'a8c25f9b6d31'
down_revision: Union[str, None] = 'f3a9c1d84e27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('tipotramite',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sindicato_id', sa.Integer(), nullable=False),
        sa.Column('titulo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('codigo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('activo', sa.Boolean(), nullable=False),
        sa.Column('creado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['sindicato_id'], ['sindicato.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('tipotramite', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tipotramite_sindicato_id'), ['sindicato_id'], unique=False)

    op.create_table('campotramite',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tipo_tramite_id', sa.Integer(), nullable=False),
        sa.Column('orden', sa.Integer(), nullable=False),
        sa.Column('etiqueta', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('tipo_dato', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('longitud_maxima', sa.Integer(), nullable=True),
        sa.Column('longitud_exacta', sa.Integer(), nullable=True),
        sa.Column('decimales', sa.Integer(), nullable=True),
        sa.Column('tipos_archivo_permitidos', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('obligatorio', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['tipo_tramite_id'], ['tipotramite.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('campotramite', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_campotramite_tipo_tramite_id'), ['tipo_tramite_id'], unique=False)

    op.create_table('tramite',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sindicato_id', sa.Integer(), nullable=False),
        sa.Column('tipo_tramite_id', sa.Integer(), nullable=False),
        sa.Column('numero_expediente', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('cuil', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('estado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('creado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('actualizado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['sindicato_id'], ['sindicato.id'], ),
        sa.ForeignKeyConstraint(['tipo_tramite_id'], ['tipotramite.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('tramite', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tramite_sindicato_id'), ['sindicato_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_tramite_tipo_tramite_id'), ['tipo_tramite_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_tramite_numero_expediente'), ['numero_expediente'], unique=True)
        batch_op.create_index(batch_op.f('ix_tramite_cuil'), ['cuil'], unique=False)

    op.create_table('respuestatramite',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tramite_id', sa.Integer(), nullable=False),
        sa.Column('campo_tramite_id', sa.Integer(), nullable=False),
        sa.Column('valor_texto', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('archivo_datos', sa.LargeBinary(), nullable=True),
        sa.Column('archivo_mime', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('archivo_nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['tramite_id'], ['tramite.id'], ),
        sa.ForeignKeyConstraint(['campo_tramite_id'], ['campotramite.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('respuestatramite', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_respuestatramite_tramite_id'), ['tramite_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_respuestatramite_campo_tramite_id'), ['campo_tramite_id'], unique=False)

    op.create_table('notatramite',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tramite_id', sa.Integer(), nullable=False),
        sa.Column('autor', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('texto', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('adjunto_datos', sa.LargeBinary(), nullable=True),
        sa.Column('adjunto_mime', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('adjunto_nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('creado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['tramite_id'], ['tramite.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('notatramite', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_notatramite_tramite_id'), ['tramite_id'], unique=False)

    op.create_table('tramitelog',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tramite_id', sa.Integer(), nullable=False),
        sa.Column('evento', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('detalle', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('creado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['tramite_id'], ['tramite.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('tramitelog', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tramitelog_tramite_id'), ['tramite_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('tramitelog', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tramitelog_tramite_id'))
    op.drop_table('tramitelog')

    with op.batch_alter_table('notatramite', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notatramite_tramite_id'))
    op.drop_table('notatramite')

    with op.batch_alter_table('respuestatramite', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_respuestatramite_campo_tramite_id'))
        batch_op.drop_index(batch_op.f('ix_respuestatramite_tramite_id'))
    op.drop_table('respuestatramite')

    with op.batch_alter_table('tramite', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tramite_cuil'))
        batch_op.drop_index(batch_op.f('ix_tramite_numero_expediente'))
        batch_op.drop_index(batch_op.f('ix_tramite_tipo_tramite_id'))
        batch_op.drop_index(batch_op.f('ix_tramite_sindicato_id'))
    op.drop_table('tramite')

    with op.batch_alter_table('campotramite', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_campotramite_tipo_tramite_id'))
    op.drop_table('campotramite')

    with op.batch_alter_table('tipotramite', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tipotramite_sindicato_id'))
    op.drop_table('tipotramite')
