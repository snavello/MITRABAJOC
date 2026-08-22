"""tramites de empresa por area receptora

Revision ID: e3c9f620ab17
Revises: d2b8e51cf024
Create Date: 2026-08-22 22:40:19.551204

Fase 5 de SPRINT_AREAS.md: el espejo de la migración anterior sobre las
tablas de trámites de empleador. Mismo movimiento de datos -- los tipos que
ya existen se rutean a "Mesa de Entradas" de su propio sindicato.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'e3c9f620ab17'
down_revision: Union[str, None] = 'd2b8e51cf024'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

AREA_INICIAL = "Mesa de Entradas"


def upgrade() -> None:
    op.create_table('areatipotramiteempleador',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tipo_tramite_id', sa.Integer(), nullable=False),
        sa.Column('area_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['tipo_tramite_id'], ['tipotramiteempleador.id'], ),
        sa.ForeignKeyConstraint(['area_id'], ['area.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('areatipotramiteempleador', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_areatipotramiteempleador_tipo_tramite_id'),
                              ['tipo_tramite_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_areatipotramiteempleador_area_id'),
                              ['area_id'], unique=False)

    with op.batch_alter_table('tramiteempleador', schema=None) as batch_op:
        batch_op.add_column(sa.Column('area_a_cargo_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_tramiteempleador_area_a_cargo_id'),
                              ['area_a_cargo_id'], unique=False)
        batch_op.create_foreign_key('fk_tramiteempleador_area_a_cargo_id_area',
                                    'area', ['area_a_cargo_id'], ['id'])

    with op.batch_alter_table('notatramiteempleador', schema=None) as batch_op:
        batch_op.add_column(sa.Column('usuario_sindicato_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_notatramiteempleador_usuario_sindicato_id_usuariosindicato',
                                    'usuariosindicato', ['usuario_sindicato_id'], ['id'])

    op.execute(f"""
        INSERT INTO areatipotramiteempleador (tipo_tramite_id, area_id)
        SELECT t.id, a.id
        FROM tipotramiteempleador t
        JOIN area a ON a.sindicato_id = t.sindicato_id AND a.nombre = '{AREA_INICIAL}'
        WHERE NOT EXISTS (
            SELECT 1 FROM areatipotramiteempleador x WHERE x.tipo_tramite_id = t.id)
    """)


def downgrade() -> None:
    with op.batch_alter_table('notatramiteempleador', schema=None) as batch_op:
        batch_op.drop_constraint('fk_notatramiteempleador_usuario_sindicato_id_usuariosindicato',
                                 type_='foreignkey')
        batch_op.drop_column('usuario_sindicato_id')

    with op.batch_alter_table('tramiteempleador', schema=None) as batch_op:
        batch_op.drop_constraint('fk_tramiteempleador_area_a_cargo_id_area', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_tramiteempleador_area_a_cargo_id'))
        batch_op.drop_column('area_a_cargo_id')

    with op.batch_alter_table('areatipotramiteempleador', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_areatipotramiteempleador_area_id'))
        batch_op.drop_index(batch_op.f('ix_areatipotramiteempleador_tipo_tramite_id'))
    op.drop_table('areatipotramiteempleador')
