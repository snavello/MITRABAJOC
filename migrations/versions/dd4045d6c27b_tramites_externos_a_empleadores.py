"""tramites externos a empleadores

Revision ID: dd4045d6c27b
Revises: bb24421c03e3
Create Date: 2026-08-17 23:04:12.190199

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'dd4045d6c27b'
down_revision: Union[str, None] = 'bb24421c03e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('tipotramiteempleador',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sindicato_id', sa.Integer(), nullable=False),
        sa.Column('titulo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('codigo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('activo', sa.Boolean(), nullable=False),
        sa.Column('creado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['sindicato_id'], ['sindicato.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('tipotramiteempleador', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tipotramiteempleador_sindicato_id'), ['sindicato_id'], unique=False)

    op.create_table('campotramiteempleador',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tipo_tramite_id', sa.Integer(), nullable=False),
        sa.Column('orden', sa.Integer(), nullable=False),
        sa.Column('etiqueta', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('tipo_dato', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('longitud_maxima', sa.Integer(), nullable=True),
        sa.Column('longitud_exacta', sa.Integer(), nullable=True),
        sa.Column('decimales', sa.Integer(), nullable=True),
        sa.Column('tipos_archivo_permitidos', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('opciones', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('ancho', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('obligatorio', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['tipo_tramite_id'], ['tipotramiteempleador.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('campotramiteempleador', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_campotramiteempleador_tipo_tramite_id'), ['tipo_tramite_id'], unique=False)

    op.create_table('tramiteempleador',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sindicato_id', sa.Integer(), nullable=False),
        sa.Column('tipo_tramite_id', sa.Integer(), nullable=False),
        sa.Column('numero_expediente', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('cuit', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('estado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('creado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('actualizado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['sindicato_id'], ['sindicato.id'], ),
        sa.ForeignKeyConstraint(['tipo_tramite_id'], ['tipotramiteempleador.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('tramiteempleador', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tramiteempleador_sindicato_id'), ['sindicato_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_tramiteempleador_tipo_tramite_id'), ['tipo_tramite_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_tramiteempleador_numero_expediente'), ['numero_expediente'], unique=True)
        batch_op.create_index(batch_op.f('ix_tramiteempleador_cuit'), ['cuit'], unique=False)

    op.create_table('respuestatramiteempleador',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tramite_id', sa.Integer(), nullable=False),
        sa.Column('campo_tramite_id', sa.Integer(), nullable=False),
        sa.Column('valor_texto', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('archivo_datos', sa.LargeBinary(), nullable=True),
        sa.Column('archivo_mime', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('archivo_nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['tramite_id'], ['tramiteempleador.id'], ),
        sa.ForeignKeyConstraint(['campo_tramite_id'], ['campotramiteempleador.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('respuestatramiteempleador', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_respuestatramiteempleador_tramite_id'), ['tramite_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_respuestatramiteempleador_campo_tramite_id'), ['campo_tramite_id'], unique=False)

    op.create_table('notatramiteempleador',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tramite_id', sa.Integer(), nullable=False),
        sa.Column('autor', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('texto', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('adjunto_datos', sa.LargeBinary(), nullable=True),
        sa.Column('adjunto_mime', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('adjunto_nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('creado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['tramite_id'], ['tramiteempleador.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('notatramiteempleador', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_notatramiteempleador_tramite_id'), ['tramite_id'], unique=False)

    op.create_table('tramiteempleadorlog',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tramite_id', sa.Integer(), nullable=False),
        sa.Column('evento', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('detalle', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('creado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['tramite_id'], ['tramiteempleador.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('tramiteempleadorlog', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tramiteempleadorlog_tramite_id'), ['tramite_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('tramiteempleadorlog', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tramiteempleadorlog_tramite_id'))
    op.drop_table('tramiteempleadorlog')

    with op.batch_alter_table('notatramiteempleador', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notatramiteempleador_tramite_id'))
    op.drop_table('notatramiteempleador')

    with op.batch_alter_table('respuestatramiteempleador', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_respuestatramiteempleador_campo_tramite_id'))
        batch_op.drop_index(batch_op.f('ix_respuestatramiteempleador_tramite_id'))
    op.drop_table('respuestatramiteempleador')

    with op.batch_alter_table('tramiteempleador', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tramiteempleador_cuit'))
        batch_op.drop_index(batch_op.f('ix_tramiteempleador_numero_expediente'))
        batch_op.drop_index(batch_op.f('ix_tramiteempleador_tipo_tramite_id'))
        batch_op.drop_index(batch_op.f('ix_tramiteempleador_sindicato_id'))
    op.drop_table('tramiteempleador')

    with op.batch_alter_table('campotramiteempleador', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_campotramiteempleador_tipo_tramite_id'))
    op.drop_table('campotramiteempleador')

    with op.batch_alter_table('tipotramiteempleador', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tipotramiteempleador_sindicato_id'))
    op.drop_table('tipotramiteempleador')
