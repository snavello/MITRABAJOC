"""usuarios de plataforma nominales

Tablas UsuarioPlataforma y LogPlataforma (db.py, SPRINT_R1.md): reemplazan la
cuenta compartida por variable de entorno (XSK H-0002/H-0016). Siembra los dos
superadmin iniciales (snavello, arsantagati) con clave transitoria de un solo
uso, usando la MISMA definición de db.SUPERADMINS_INICIALES y el mismo hasheo
de auth, sobre la conexión de la propia migración.

Revision ID: f4a2b7c19d05
Revises: e7b3c9a15f28
Create Date: 2026-09-20 21:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'f4a2b7c19d05'
down_revision: Union[str, None] = 'e7b3c9a15f28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'usuarioplataforma',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('usuario', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('clave_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('rol', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('activo', sa.Boolean(), nullable=False),
        sa.Column('debe_cambiar_clave', sa.Boolean(), nullable=False),
        sa.Column('clave_vence', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('debe_completar_datos', sa.Boolean(), nullable=False),
        sa.Column('cuil', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('dni', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('email', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('direccion', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('telefono', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('creado_en', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('creado_por', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_usuarioplataforma_usuario'), 'usuarioplataforma', ['usuario'])
    op.create_index(op.f('ix_usuarioplataforma_cuil'), 'usuarioplataforma', ['cuil'])
    op.create_index(op.f('ix_usuarioplataforma_email'), 'usuarioplataforma', ['email'])

    op.create_table(
        'logplataforma',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cuando', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('accion', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('usuario', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('objetivo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('ip', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('detalle', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_logplataforma_cuando'), 'logplataforma', ['cuando'])
    op.create_index(op.f('ix_logplataforma_usuario'), 'logplataforma', ['usuario'])

    # Siembra de los dos superadmin, sobre la conexión de la migración (misma
    # transacción que el CREATE TABLE). Usa la definición y el hasheo únicos.
    import auth
    import db as _db
    import fechas
    ahora = fechas.ahora_texto()
    filas = [{
        "usuario": sa_["usuario"], "nombre": sa_["nombre"],
        "clave_hash": auth.hashear_clave(sa_["clave"]),
        "rol": "superadmin", "activo": True,
        "debe_cambiar_clave": True, "clave_vence": None,
        "debe_completar_datos": True,
        "cuil": "", "dni": "", "email": "", "direccion": "", "telefono": "",
        "creado_en": ahora, "creado_por": "semilla",
    } for sa_ in _db.SUPERADMINS_INICIALES]
    tabla = sa.table(
        'usuarioplataforma',
        sa.column('usuario', sqlmodel.sql.sqltypes.AutoString()),
        sa.column('nombre', sqlmodel.sql.sqltypes.AutoString()),
        sa.column('clave_hash', sqlmodel.sql.sqltypes.AutoString()),
        sa.column('rol', sqlmodel.sql.sqltypes.AutoString()),
        sa.column('activo', sa.Boolean()),
        sa.column('debe_cambiar_clave', sa.Boolean()),
        sa.column('clave_vence', sqlmodel.sql.sqltypes.AutoString()),
        sa.column('debe_completar_datos', sa.Boolean()),
        sa.column('cuil', sqlmodel.sql.sqltypes.AutoString()),
        sa.column('dni', sqlmodel.sql.sqltypes.AutoString()),
        sa.column('email', sqlmodel.sql.sqltypes.AutoString()),
        sa.column('direccion', sqlmodel.sql.sqltypes.AutoString()),
        sa.column('telefono', sqlmodel.sql.sqltypes.AutoString()),
        sa.column('creado_en', sqlmodel.sql.sqltypes.AutoString()),
        sa.column('creado_por', sqlmodel.sql.sqltypes.AutoString()),
    )
    op.bulk_insert(tabla, filas)


def downgrade() -> None:
    op.drop_index(op.f('ix_logplataforma_usuario'), table_name='logplataforma')
    op.drop_index(op.f('ix_logplataforma_cuando'), table_name='logplataforma')
    op.drop_table('logplataforma')
    op.drop_index(op.f('ix_usuarioplataforma_email'), table_name='usuarioplataforma')
    op.drop_index(op.f('ix_usuarioplataforma_cuil'), table_name='usuarioplataforma')
    op.drop_index(op.f('ix_usuarioplataforma_usuario'), table_name='usuarioplataforma')
    op.drop_table('usuarioplataforma')
