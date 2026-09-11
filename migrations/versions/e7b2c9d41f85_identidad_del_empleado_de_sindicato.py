"""identidad del empleado de sindicato

Revision ID: e7b2c9d41f85
Revises: d4f18a2c7b30
Create Date: 2026-09-11 07:05:00.000000

Fase 2 de SPRINT_AREAS_V2.md (decisión N1). El operador del panel y el
afiliado dejan de ser dos desconocidos: se vinculan POR CUIL.

- `usuariosindicato.cuil`: quién ES la persona, separado de `usuario`, que
  es con lo que ENTRA. Hoy coinciden porque el alta pide el CUIT/CUIL como
  nombre de usuario; guardarlos por separado es lo que permite que mañana
  se habilite el login por mail sin perder la identidad.
- `usuariosindicato.trabajador_id`: el vínculo, NULLABLE a propósito --
  trabajar en el gremio sin estar afiliado a él es un caso real.
- `trabajador.es_empleado_sindicato`: la marca en el padrón.

El backfill arma los vínculos que ya existían de hecho: los usuarios cuyo
`usuario` son 11 dígitos tienen ahí su CUIL, y los que además están
empadronados en su propio sindicato quedan vinculados y marcados.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'e7b2c9d41f85'
down_revision: Union[str, None] = 'd4f18a2c7b30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('trabajador', schema=None) as batch_op:
        batch_op.add_column(sa.Column('es_empleado_sindicato', sa.Boolean(), nullable=False,
                                      server_default=sa.text('false')))

    with op.batch_alter_table('usuariosindicato', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cuil', sqlmodel.sql.sqltypes.AutoString(),
                                      nullable=False, server_default=''))
        batch_op.add_column(sa.Column('trabajador_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_usuariosindicato_cuil'), ['cuil'], unique=False)
        batch_op.create_index(batch_op.f('ix_usuariosindicato_trabajador_id'),
                              ['trabajador_id'], unique=False)
        batch_op.create_foreign_key('fk_usuariosindicato_trabajador_id_trabajador',
                                    'trabajador', ['trabajador_id'], ['id'])

    # ---------- Datos ----------
    # 1. El CUIL sale de `usuario` cuando son 11 dígitos, que es lo que el
    #    alta viene exigiendo. Un `usuario` que no lo sea (un mail cargado a
    #    mano antes de esa validación) queda con cuil vacío: es correcto, no
    #    sabemos su CUIL y no hay que inventarlo.
    op.execute("""
        UPDATE usuariosindicato SET cuil = usuario
        WHERE usuario ~ '^[0-9]{11}$'
    """)

    # 2. El vínculo, solo dentro del PROPIO sindicato: el mismo CUIL puede
    #    estar empadronado en varios gremios y el empleado de uno no tiene
    #    nada que ver con su afiliación a otro.
    op.execute("""
        UPDATE usuariosindicato u SET trabajador_id = (
            SELECT MIN(t.id) FROM trabajador t
            WHERE t.sindicato_id = u.sindicato_id AND t.cuil = u.cuil)
        WHERE u.cuil <> ''
    """)

    # 3. La marca, solo para los que quedaron vinculados por un usuario ACTIVO.
    op.execute("""
        UPDATE trabajador SET es_empleado_sindicato = true
        WHERE id IN (SELECT trabajador_id FROM usuariosindicato
                     WHERE trabajador_id IS NOT NULL AND activo)
    """)


def downgrade() -> None:
    with op.batch_alter_table('usuariosindicato', schema=None) as batch_op:
        batch_op.drop_constraint('fk_usuariosindicato_trabajador_id_trabajador',
                                 type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_usuariosindicato_trabajador_id'))
        batch_op.drop_index(batch_op.f('ix_usuariosindicato_cuil'))
        batch_op.drop_column('trabajador_id')
        batch_op.drop_column('cuil')

    with op.batch_alter_table('trabajador', schema=None) as batch_op:
        batch_op.drop_column('es_empleado_sindicato')
