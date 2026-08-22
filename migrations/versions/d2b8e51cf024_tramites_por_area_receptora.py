"""tramites por area receptora

Revision ID: d2b8e51cf024
Revises: c1a7d40be913
Create Date: 2026-08-22 21:05:44.902118

Fase 4 de SPRINT_AREAS.md. Además del esquema mueve datos: los tipos de
trámite que ya existen no tienen área, y desde ahora el área es lo que
rutea el trámite -- un tipo sin área sería un formulario cuyos trámites no
ve NADIE salvo el Super Admin. Se los asigna al área "Mesa de Entradas"
que creó la migración anterior.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'd2b8e51cf024'
down_revision: Union[str, None] = 'c1a7d40be913'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

AREA_INICIAL = "Mesa de Entradas"


def upgrade() -> None:
    op.create_table('areatipotramite',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tipo_tramite_id', sa.Integer(), nullable=False),
        sa.Column('area_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['tipo_tramite_id'], ['tipotramite.id'], ),
        sa.ForeignKeyConstraint(['area_id'], ['area.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('areatipotramite', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_areatipotramite_tipo_tramite_id'), ['tipo_tramite_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_areatipotramite_area_id'), ['area_id'], unique=False)

    with op.batch_alter_table('tramite', schema=None) as batch_op:
        batch_op.add_column(sa.Column('area_a_cargo_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_tramite_area_a_cargo_id'), ['area_a_cargo_id'], unique=False)
        batch_op.create_foreign_key('fk_tramite_area_a_cargo_id_area', 'area', ['area_a_cargo_id'], ['id'])

    with op.batch_alter_table('notatramite', schema=None) as batch_op:
        batch_op.add_column(sa.Column('usuario_sindicato_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_notatramite_usuario_sindicato_id_usuariosindicato',
                                    'usuariosindicato', ['usuario_sindicato_id'], ['id'])

    # Todo tipo de trámite existente queda ruteado a "Mesa de Entradas" DE SU
    # PROPIO SINDICATO. El NOT EXISTS deja la migración repetible (mismo
    # criterio que la anterior: un downgrade borra la tabla pero re-aplicar
    # no tiene que duplicar).
    op.execute(f"""
        INSERT INTO areatipotramite (tipo_tramite_id, area_id)
        SELECT t.id, a.id
        FROM tipotramite t
        JOIN area a ON a.sindicato_id = t.sindicato_id AND a.nombre = '{AREA_INICIAL}'
        WHERE NOT EXISTS (
            SELECT 1 FROM areatipotramite x WHERE x.tipo_tramite_id = t.id)
    """)


def downgrade() -> None:
    with op.batch_alter_table('notatramite', schema=None) as batch_op:
        batch_op.drop_constraint('fk_notatramite_usuario_sindicato_id_usuariosindicato', type_='foreignkey')
        batch_op.drop_column('usuario_sindicato_id')

    with op.batch_alter_table('tramite', schema=None) as batch_op:
        batch_op.drop_constraint('fk_tramite_area_a_cargo_id_area', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_tramite_area_a_cargo_id'))
        batch_op.drop_column('area_a_cargo_id')

    with op.batch_alter_table('areatipotramite', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_areatipotramite_area_id'))
        batch_op.drop_index(batch_op.f('ix_areatipotramite_tipo_tramite_id'))
    op.drop_table('areatipotramite')
