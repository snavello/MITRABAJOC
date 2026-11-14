"""mesa de implementacion

Revision ID: 3be99db601b1
Revises: e8b2d4f6a1c3
Create Date: 2026-11-14 13:13:55.640951

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '3be99db601b1'
down_revision: Union[str, None] = 'e8b2d4f6a1c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotente: una tabla que ya existe no se vuelve a crear. Pasa cuando
    # `clonar_demo_a_pruebas.py` restaura un dump de la demo (que no trae las
    # tablas `impl*`, excluidas a propósito) sobre Pruebas: `alembic_version`
    # vuelve a una revisión vieja con las tablas de la mesa ya creadas.
    existentes = set(sa.inspect(op.get_bind()).get_table_names())

    
    if 'implarchivo' not in existentes:
        op.create_table('implarchivo',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('proyecto_id', sa.Integer(), nullable=False),
        sa.Column('tarjeta_id', sa.Integer(), nullable=False),
        sa.Column('mensaje_id', sa.Integer(), nullable=True),
        sa.Column('nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('mime', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('tamano', sa.Integer(), nullable=False),
        sa.Column('datos', sa.LargeBinary(), nullable=True),
        sa.Column('datos_personales', sa.Boolean(), nullable=False),
        sa.Column('subido_por_lado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('subido_por_id', sa.Integer(), nullable=False),
        sa.Column('subido_por_nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('subido_en', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('borrado_en', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('borrado_por_lado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('borrado_por_id', sa.Integer(), nullable=False),
        sa.Column('borrado_por_nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_implarchivo_mensaje_id'), 'implarchivo', ['mensaje_id'], unique=False)
        op.create_index('ix_implarchivo_proyecto_tarjeta', 'implarchivo', ['proyecto_id', 'tarjeta_id'], unique=False)
    if 'impldescarga' not in existentes:
        op.create_table('impldescarga',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('proyecto_id', sa.Integer(), nullable=False),
        sa.Column('archivo_id', sa.Integer(), nullable=False),
        sa.Column('tarjeta_id', sa.Integer(), nullable=False),
        sa.Column('lado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('cuando', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_impldescarga_proyecto_archivo', 'impldescarga', ['proyecto_id', 'archivo_id'], unique=False)
    if 'impletapa' not in existentes:
        op.create_table('impletapa',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('proyecto_id', sa.Integer(), nullable=False),
        sa.Column('nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('descripcion', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('orden', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_impletapa_proyecto_id'), 'impletapa', ['proyecto_id'], unique=False)
        op.create_index('ix_impletapa_proyecto_orden', 'impletapa', ['proyecto_id', 'orden'], unique=False)
    if 'implevento' not in existentes:
        op.create_table('implevento',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('proyecto_id', sa.Integer(), nullable=False),
        sa.Column('tarjeta_id', sa.Integer(), nullable=True),
        sa.Column('actor_lado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=False),
        sa.Column('actor_nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('cuando', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('accion', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('solo_equipo', sa.Boolean(), nullable=False),
        sa.Column('detalle', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_implevento_proyecto_tarjeta', 'implevento', ['proyecto_id', 'tarjeta_id'], unique=False)
    if 'implhito' not in existentes:
        op.create_table('implhito',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('proyecto_id', sa.Integer(), nullable=False),
        sa.Column('etapa_id', sa.Integer(), nullable=False),
        sa.Column('texto', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('orden', sa.Integer(), nullable=False),
        sa.Column('hecho', sa.Boolean(), nullable=False),
        sa.Column('hecho_por', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('hecho_en', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_implhito_etapa_id'), 'implhito', ['etapa_id'], unique=False)
        op.create_index('ix_implhito_proyecto_etapa', 'implhito', ['proyecto_id', 'etapa_id', 'orden'], unique=False)
        op.create_index(op.f('ix_implhito_proyecto_id'), 'implhito', ['proyecto_id'], unique=False)
    if 'impllecturaaviso' not in existentes:
        op.create_table('impllecturaaviso',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('proyecto_id', sa.Integer(), nullable=False),
        sa.Column('tarjeta_id', sa.Integer(), nullable=False),
        sa.Column('lado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('cuando', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tarjeta_id', 'lado', 'usuario_id', name='uq_impllecturaaviso_persona')
        )
        op.create_index('ix_impllecturaaviso_proyecto_tarjeta', 'impllecturaaviso', ['proyecto_id', 'tarjeta_id'], unique=False)
    if 'implmensaje' not in existentes:
        op.create_table('implmensaje',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('proyecto_id', sa.Integer(), nullable=False),
        sa.Column('tarjeta_id', sa.Integer(), nullable=False),
        sa.Column('autor_lado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('autor_id', sa.Integer(), nullable=False),
        sa.Column('autor_nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('texto', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('solo_equipo', sa.Boolean(), nullable=False),
        sa.Column('creado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_implmensaje_proyecto_tarjeta', 'implmensaje', ['proyecto_id', 'tarjeta_id'], unique=False)
    if 'implproyecto' not in existentes:
        op.create_table('implproyecto',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('sindicato_id', sa.Integer(), nullable=True),
        sa.Column('activo', sa.Boolean(), nullable=False),
        sa.Column('ultimo_numero', sa.Integer(), nullable=False),
        sa.Column('creado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_implproyecto_activo'), 'implproyecto', ['activo'], unique=False)
        op.create_index(op.f('ix_implproyecto_sindicato_id'), 'implproyecto', ['sindicato_id'], unique=False)
    if 'impltarjeta' not in existentes:
        op.create_table('impltarjeta',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('proyecto_id', sa.Integer(), nullable=False),
        sa.Column('numero', sa.Integer(), nullable=False),
        sa.Column('tipo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('titulo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('estado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('lado_que_espera', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('etapa_id', sa.Integer(), nullable=True),
        sa.Column('hito_id', sa.Integer(), nullable=True),
        sa.Column('responsable_lado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('responsable', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('fecha_limite', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('autor_lado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('autor_id', sa.Integer(), nullable=False),
        sa.Column('autor_nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('creada', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('actualizada', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('resuelta_por_lado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('resuelta_por_id', sa.Integer(), nullable=False),
        sa.Column('resuelta_por_nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('resuelta_en', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('proyecto_id', 'numero', name='uq_impltarjeta_proyecto_numero')
        )
        op.create_index(op.f('ix_impltarjeta_etapa_id'), 'impltarjeta', ['etapa_id'], unique=False)
        op.create_index(op.f('ix_impltarjeta_hito_id'), 'impltarjeta', ['hito_id'], unique=False)
        op.create_index('ix_impltarjeta_proyecto_espera', 'impltarjeta', ['proyecto_id', 'lado_que_espera'], unique=False)
        op.create_index('ix_impltarjeta_proyecto_estado', 'impltarjeta', ['proyecto_id', 'estado'], unique=False)
    if 'implusuario' not in existentes:
        op.create_table('implusuario',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('proyecto_id', sa.Integer(), nullable=False),
        sa.Column('nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('mail', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('clave_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('debe_cambiar_clave', sa.Boolean(), nullable=False),
        sa.Column('activo', sa.Boolean(), nullable=False),
        sa.Column('creado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('proyecto_id', 'mail', name='uq_implusuario_proyecto_mail')
        )
        op.create_index(op.f('ix_implusuario_proyecto_id'), 'implusuario', ['proyecto_id'], unique=False)


def downgrade() -> None:
    
    op.drop_index(op.f('ix_implusuario_proyecto_id'), table_name='implusuario')
    op.drop_table('implusuario')
    op.drop_index('ix_impltarjeta_proyecto_estado', table_name='impltarjeta')
    op.drop_index('ix_impltarjeta_proyecto_espera', table_name='impltarjeta')
    op.drop_index(op.f('ix_impltarjeta_hito_id'), table_name='impltarjeta')
    op.drop_index(op.f('ix_impltarjeta_etapa_id'), table_name='impltarjeta')
    op.drop_table('impltarjeta')
    op.drop_index(op.f('ix_implproyecto_sindicato_id'), table_name='implproyecto')
    op.drop_index(op.f('ix_implproyecto_activo'), table_name='implproyecto')
    op.drop_table('implproyecto')
    op.drop_index('ix_implmensaje_proyecto_tarjeta', table_name='implmensaje')
    op.drop_table('implmensaje')
    op.drop_index('ix_impllecturaaviso_proyecto_tarjeta', table_name='impllecturaaviso')
    op.drop_table('impllecturaaviso')
    op.drop_index(op.f('ix_implhito_proyecto_id'), table_name='implhito')
    op.drop_index('ix_implhito_proyecto_etapa', table_name='implhito')
    op.drop_index(op.f('ix_implhito_etapa_id'), table_name='implhito')
    op.drop_table('implhito')
    op.drop_index('ix_implevento_proyecto_tarjeta', table_name='implevento')
    op.drop_table('implevento')
    op.drop_index('ix_impletapa_proyecto_orden', table_name='impletapa')
    op.drop_index(op.f('ix_impletapa_proyecto_id'), table_name='impletapa')
    op.drop_table('impletapa')
    op.drop_index('ix_impldescarga_proyecto_archivo', table_name='impldescarga')
    op.drop_table('impldescarga')
    op.drop_index('ix_implarchivo_proyecto_tarjeta', table_name='implarchivo')
    op.drop_index(op.f('ix_implarchivo_mensaje_id'), table_name='implarchivo')
    op.drop_table('implarchivo')
