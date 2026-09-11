"""ruteo de tramites por area

Revision ID: f8a3d05e2c17
Revises: e7b2c9d41f85
Create Date: 2026-09-11 08:15:00.000000

Fase 3 de SPRINT_AREAS_V2.md (decisiones N6 y N7). El formulario declara a
qué área cae el trámite, seccional por seccional, con un destino por
defecto obligatorio; y puede ser global o de una seccional.

Tres movimientos de datos que no se pueden separar del esquema:

1. Los tipos que ya existían quedan con destino por defecto = "Mesa de
   Entradas" de su sindicato (el área que creó c1a7d40be913). Sin eso, el
   primer trámite presentado después del deploy no caería en ninguna
   bandeja y nadie lo vería -- en silencio.
2. Todos quedan GLOBALES (seccional_id NULL), que es lo que eran: hasta
   ahora un formulario lo veía todo el sindicato.
3. Los TRÁMITES ya presentados se rutean al mismo destino. Si quedaran con
   area_a_cargo_id NULL, ningún usuario de área los alcanzaría -- se
   volverían invisibles para todos menos los administradores.

`area_destino_default_id` queda NULLABLE en el esquema aunque la decisión
diga "obligatorio", y es deliberado: la obligatoriedad la imponen las rutas
(un formulario sin destino no se guarda), y un NOT NULL acá convertiría un
caso de datos raro -- un sindicato sin áreas, que no debería existir -- en
un deploy que falla entero. Se prefiere fallar en el alta, que es donde el
admin puede corregirlo.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f8a3d05e2c17'
down_revision: Union[str, None] = 'e7b2c9d41f85'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

AREA_INICIAL = "Mesa de Entradas"


def upgrade() -> None:
    op.create_table('destinotipotramite',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tipo_tramite_id', sa.Integer(), nullable=False),
        sa.Column('seccional_id', sa.Integer(), nullable=False),
        sa.Column('area_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['tipo_tramite_id'], ['tipotramite.id'], ),
        sa.ForeignKeyConstraint(['seccional_id'], ['seccional.id'], ),
        sa.ForeignKeyConstraint(['area_id'], ['area.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('destinotipotramite', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_destinotipotramite_tipo_tramite_id'),
                              ['tipo_tramite_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_destinotipotramite_seccional_id'),
                              ['seccional_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_destinotipotramite_area_id'),
                              ['area_id'], unique=False)

    with op.batch_alter_table('tipotramite', schema=None) as batch_op:
        batch_op.add_column(sa.Column('seccional_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('area_destino_default_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_tipotramite_seccional_id'),
                              ['seccional_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_tipotramite_area_destino_default_id'),
                              ['area_destino_default_id'], unique=False)
        batch_op.create_foreign_key('fk_tipotramite_seccional_id_seccional',
                                    'seccional', ['seccional_id'], ['id'])
        batch_op.create_foreign_key('fk_tipotramite_area_destino_default_id_area',
                                    'area', ['area_destino_default_id'], ['id'])

    with op.batch_alter_table('tramite', schema=None) as batch_op:
        batch_op.add_column(sa.Column('area_a_cargo_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_tramite_area_a_cargo_id'),
                              ['area_a_cargo_id'], unique=False)
        batch_op.create_foreign_key('fk_tramite_area_a_cargo_id_area',
                                    'area', ['area_a_cargo_id'], ['id'])

    # ---------- Datos ----------
    # MIN(id) para que el resultado sea reproducible si un sindicato tuviera
    # dos áreas con ese nombre (una cargada a mano antes de la migración).
    op.execute(f"""
        UPDATE tipotramite SET area_destino_default_id = (
            SELECT MIN(a.id) FROM area a
            WHERE a.sindicato_id = tipotramite.sindicato_id AND a.nombre = '{AREA_INICIAL}')
        WHERE area_destino_default_id IS NULL
    """)
    # Red de seguridad: un sindicato al que le renombraron "Mesa de Entradas"
    # cae a su área más vieja en vez de quedarse sin destino.
    op.execute("""
        UPDATE tipotramite SET area_destino_default_id = (
            SELECT MIN(a.id) FROM area a WHERE a.sindicato_id = tipotramite.sindicato_id)
        WHERE area_destino_default_id IS NULL
    """)

    # Los trámites ya presentados van al destino de su formulario.
    op.execute("""
        UPDATE tramite SET area_a_cargo_id = (
            SELECT t.area_destino_default_id FROM tipotramite t
            WHERE t.id = tramite.tipo_tramite_id)
        WHERE area_a_cargo_id IS NULL
    """)


def downgrade() -> None:
    with op.batch_alter_table('tramite', schema=None) as batch_op:
        batch_op.drop_constraint('fk_tramite_area_a_cargo_id_area', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_tramite_area_a_cargo_id'))
        batch_op.drop_column('area_a_cargo_id')

    with op.batch_alter_table('tipotramite', schema=None) as batch_op:
        batch_op.drop_constraint('fk_tipotramite_area_destino_default_id_area', type_='foreignkey')
        batch_op.drop_constraint('fk_tipotramite_seccional_id_seccional', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_tipotramite_area_destino_default_id'))
        batch_op.drop_index(batch_op.f('ix_tipotramite_seccional_id'))
        batch_op.drop_column('area_destino_default_id')
        batch_op.drop_column('seccional_id')

    with op.batch_alter_table('destinotipotramite', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_destinotipotramite_area_id'))
        batch_op.drop_index(batch_op.f('ix_destinotipotramite_seccional_id'))
        batch_op.drop_index(batch_op.f('ix_destinotipotramite_tipo_tramite_id'))
    op.drop_table('destinotipotramite')
