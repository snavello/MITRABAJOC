"""areas y permisos del sindicato

Revision ID: c1a7d40be913
Revises: c5f1a2d70b39
Create Date: 2026-09-11 04:20:00.000000

Fase 1 de SPRINT_AREAS.md. Además del esquema, esta migración hace tres
movimientos de DATOS que no se pueden separar del esquema sin dejar la
base en un estado inconsistente:

1. Grandfathering: todo UsuarioSindicato que ya existía pasa a Super Admin.
   Sin esto, el día del deploy nadie podría entrar a administrar nada.
2. Cada sindicato estrena una seccional "Sede Central" (con ve_todas
   tildado) y un área "Mesa de Entradas".
3. Los trabajadores y usuarios sin seccional se pasan a Sede Central: desde
   ahora la seccional acota lo que se ve, así que dejar filas en NULL sería
   dejar trabajadores que ningún usuario de área alcanza.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'c1a7d40be913'
down_revision: Union[str, None] = 'c5f1a2d70b39'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SECCIONAL_CENTRAL = "Sede Central"
AREA_INICIAL = "Mesa de Entradas"


def upgrade() -> None:
    # ---------- Esquema ----------
    op.create_table('area',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sindicato_id', sa.Integer(), nullable=False),
        sa.Column('nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('activo', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.ForeignKeyConstraint(['sindicato_id'], ['sindicato.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('area', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_area_sindicato_id'), ['sindicato_id'], unique=False)

    op.create_table('permisoarea',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('area_id', sa.Integer(), nullable=False),
        sa.Column('seccion', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['area_id'], ['area.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('permisoarea', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_permisoarea_area_id'), ['area_id'], unique=False)

    op.create_table('permisousuario',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('seccion', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('tipo', sqlmodel.sql.sqltypes.AutoString(), nullable=False,
                  server_default='agregar'),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuariosindicato.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('permisousuario', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_permisousuario_usuario_id'), ['usuario_id'], unique=False)

    with op.batch_alter_table('seccional', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ve_todas', sa.Boolean(), nullable=False,
                                      server_default=sa.text('false')))

    with op.batch_alter_table('usuariosindicato', schema=None) as batch_op:
        batch_op.add_column(sa.Column('es_super_admin', sa.Boolean(), nullable=False,
                                      server_default=sa.text('false')))
        batch_op.add_column(sa.Column('area_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('seccional_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_usuariosindicato_area_id'), ['area_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_usuariosindicato_seccional_id'), ['seccional_id'], unique=False)
        batch_op.create_foreign_key('fk_usuariosindicato_area_id_area', 'area', ['area_id'], ['id'])
        batch_op.create_foreign_key('fk_usuariosindicato_seccional_id_seccional', 'seccional', ['seccional_id'], ['id'])

    # ---------- Datos ----------
    # 1. Los usuarios que ya existían eran omnipotentes: siguen siéndolo.
    op.execute("UPDATE usuariosindicato SET es_super_admin = true")

    # 2. Sede Central y Mesa de Entradas, una por sindicato. El NOT EXISTS
    #    evita duplicar si algún sindicato ya tenía una seccional con ese
    #    nombre cargada a mano.
    op.execute(f"""
        INSERT INTO seccional (sindicato_id, nombre, direccion, ve_todas)
        SELECT s.id, '{SECCIONAL_CENTRAL}', '', true FROM sindicato s
        WHERE NOT EXISTS (
            SELECT 1 FROM seccional x
            WHERE x.sindicato_id = s.id AND x.nombre = '{SECCIONAL_CENTRAL}')
    """)
    # El INSERT de arriba no corre para un sindicato que YA tenía una
    # seccional llamada "Sede Central" (cargada a mano, o dejada por un
    # downgrade previo de esta misma migración, que borra la columna pero
    # no las filas). En ese caso la columna recién creada le queda en el
    # default `false` y Sede Central se queda sin su poder de ver todas las
    # seccionales, en silencio. Este UPDATE lo garantiza en los dos caminos.
    op.execute(f"""
        UPDATE seccional SET ve_todas = true WHERE nombre = '{SECCIONAL_CENTRAL}'
    """)

    op.execute(f"""
        INSERT INTO area (sindicato_id, nombre, activo)
        SELECT s.id, '{AREA_INICIAL}', true FROM sindicato s
        WHERE NOT EXISTS (
            SELECT 1 FROM area x
            WHERE x.sindicato_id = s.id AND x.nombre = '{AREA_INICIAL}')
    """)
    # Mismo motivo que arriba: un área "Mesa de Entradas" preexistente y
    # desactivada dejaría los trámites migrados en un área muerta.
    op.execute(f"""
        UPDATE area SET activo = true WHERE nombre = '{AREA_INICIAL}'
    """)

    # 3. Nadie queda sin seccional. Si un sindicato ya tenía "Sede Central"
    #    duplicada, el MIN(id) elige siempre la misma y el resultado es
    #    determinístico.
    for tabla in ("trabajador", "usuariosindicato"):
        op.execute(f"""
            UPDATE {tabla} SET seccional_id = (
                SELECT MIN(x.id) FROM seccional x
                WHERE x.sindicato_id = {tabla}.sindicato_id
                  AND x.nombre = '{SECCIONAL_CENTRAL}')
            WHERE seccional_id IS NULL
        """)


def downgrade() -> None:
    # Las filas de Sede Central / Mesa de Entradas NO se borran: si el
    # downgrade se corre después de que alguien las usó, borrarlas se
    # llevaría puestos datos reales. Quedan como seccionales y áreas
    # comunes, que es lo que son.
    with op.batch_alter_table('usuariosindicato', schema=None) as batch_op:
        batch_op.drop_constraint('fk_usuariosindicato_seccional_id_seccional', type_='foreignkey')
        batch_op.drop_constraint('fk_usuariosindicato_area_id_area', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_usuariosindicato_seccional_id'))
        batch_op.drop_index(batch_op.f('ix_usuariosindicato_area_id'))
        batch_op.drop_column('seccional_id')
        batch_op.drop_column('area_id')
        batch_op.drop_column('es_super_admin')

    with op.batch_alter_table('seccional', schema=None) as batch_op:
        batch_op.drop_column('ve_todas')

    with op.batch_alter_table('permisousuario', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_permisousuario_usuario_id'))
    op.drop_table('permisousuario')

    with op.batch_alter_table('permisoarea', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_permisoarea_area_id'))
    op.drop_table('permisoarea')

    with op.batch_alter_table('area', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_area_sindicato_id'))
    op.drop_table('area')
