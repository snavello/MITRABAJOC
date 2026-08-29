"""configuracion del Panel Sindical

- sindicato.color_destacado: marca selecciones/filtros activos del dashboard
  (default fucsia #E5188F), editable solo por el admin de plataforma.
- configuracionplataforma: umbrales del semáforo de aportes (verde hasta 35
  días, amarillo hasta 60, rojo después) y feature flag del carril de
  consultas al bot (apagado hasta que el RAG clasifique por tema).
- consultaconvenio.tema: la tabla del piloto RAG se reutiliza como fuente
  del carril de consultas (decisión de Sd, 2026-08-29) -- tema NULL en todo
  lo ya registrado.

Revision ID: c3f67d2eb033
Revises: b2e56c1daf22
Create Date: 2026-08-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = 'c3f67d2eb033'
down_revision: Union[str, None] = 'b2e56c1daf22'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('sindicato', schema=None) as batch_op:
        batch_op.add_column(sa.Column('color_destacado', sqlmodel.sql.sqltypes.AutoString(),
                                      nullable=False, server_default='#E5188F'))
    with op.batch_alter_table('configuracionplataforma', schema=None) as batch_op:
        batch_op.add_column(sa.Column('semaforo_verde_hasta_dias', sa.Integer(),
                                      nullable=False, server_default='35'))
        batch_op.add_column(sa.Column('semaforo_amarillo_hasta_dias', sa.Integer(),
                                      nullable=False, server_default='60'))
        batch_op.add_column(sa.Column('dashboard_consultas_bot_habilitado', sa.Boolean(),
                                      nullable=False, server_default='false'))
    with op.batch_alter_table('consultaconvenio', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tema', sqlmodel.sql.sqltypes.AutoString(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('consultaconvenio', schema=None) as batch_op:
        batch_op.drop_column('tema')
    with op.batch_alter_table('configuracionplataforma', schema=None) as batch_op:
        batch_op.drop_column('dashboard_consultas_bot_habilitado')
        batch_op.drop_column('semaforo_amarillo_hasta_dias')
        batch_op.drop_column('semaforo_verde_hasta_dias')
    with op.batch_alter_table('sindicato', schema=None) as batch_op:
        batch_op.drop_column('color_destacado')
