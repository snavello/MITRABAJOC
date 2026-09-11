"""areas por seccional y admin de seccional

Revision ID: d4f18a2c7b30
Revises: c1a7d40be913
Create Date: 2026-09-11 06:10:00.000000

Fase 1 de SPRINT_AREAS_V2.md. Dos cambios de esquema y un movimiento de
datos que no se pueden separar:

1. `area.seccional_id`: el área deja de colgar del sindicato y pasa a vivir
   dentro de una seccional (decisión N2). La columna nace NULLABLE, se
   rellena, y recién entonces se le pone NOT NULL -- en ese orden, porque
   agregar una columna NOT NULL sin default sobre una tabla con filas
   falla, y un default inventado dejaría áreas apuntando a cualquier lado.
2. `usuariosindicato.es_admin_seccional`: el rol intermedio. Arranca en
   false para TODOS -- es opt-in, un sindicato centralizado no se entera.

Las áreas que ya existían se mueven a "Sede Central", que es la seccional
que creó la migración anterior. Es la única asignación posible que no
inventa nada: hasta ahora el área no tenía seccional, así que pertenecía al
sindicato entero, y la sede central es la que representa eso.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4f18a2c7b30'
down_revision: Union[str, None] = 'c1a7d40be913'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SECCIONAL_CENTRAL = "Sede Central"


def upgrade() -> None:
    with op.batch_alter_table('usuariosindicato', schema=None) as batch_op:
        batch_op.add_column(sa.Column('es_admin_seccional', sa.Boolean(), nullable=False,
                                      server_default=sa.text('false')))

    # ---------- area.seccional_id, en tres pasos ----------
    with op.batch_alter_table('area', schema=None) as batch_op:
        batch_op.add_column(sa.Column('seccional_id', sa.Integer(), nullable=True))

    # MIN(id) y no un id cualquiera: si un sindicato tuviera dos seccionales
    # llamadas "Sede Central" (la suya de antes más la que creó la migración
    # anterior), esto elige siempre la misma y el resultado es reproducible.
    op.execute(f"""
        UPDATE area SET seccional_id = (
            SELECT MIN(x.id) FROM seccional x
            WHERE x.sindicato_id = area.sindicato_id
              AND x.nombre = '{SECCIONAL_CENTRAL}')
        WHERE seccional_id IS NULL
    """)
    # Red de seguridad: un sindicato SIN "Sede Central" (alguien la renombró
    # entre una migración y otra) dejaría áreas en NULL y el NOT NULL de
    # abajo reventaría el deploy entero. En ese caso se cae a la seccional
    # más vieja del sindicato, que es lo más parecido a "la central".
    op.execute("""
        UPDATE area SET seccional_id = (
            SELECT MIN(x.id) FROM seccional x
            WHERE x.sindicato_id = area.sindicato_id)
        WHERE seccional_id IS NULL
    """)
    # Un área de un sindicato sin NINGUNA seccional no puede existir: la
    # migración anterior le creó una a cada sindicato, así que esto no
    # debería borrar nada. Está para que el NOT NULL no falle en silencio.
    op.execute("DELETE FROM permisoarea WHERE area_id IN (SELECT id FROM area WHERE seccional_id IS NULL)")
    op.execute("UPDATE usuariosindicato SET area_id = NULL WHERE area_id IN (SELECT id FROM area WHERE seccional_id IS NULL)")
    op.execute("DELETE FROM area WHERE seccional_id IS NULL")

    with op.batch_alter_table('area', schema=None) as batch_op:
        batch_op.alter_column('seccional_id', existing_type=sa.Integer(), nullable=False)
        batch_op.create_index(batch_op.f('ix_area_seccional_id'), ['seccional_id'], unique=False)
        batch_op.create_foreign_key('fk_area_seccional_id_seccional', 'seccional',
                                    ['seccional_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('area', schema=None) as batch_op:
        batch_op.drop_constraint('fk_area_seccional_id_seccional', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_area_seccional_id'))
        batch_op.drop_column('seccional_id')

    with op.batch_alter_table('usuariosindicato', schema=None) as batch_op:
        batch_op.drop_column('es_admin_seccional')
