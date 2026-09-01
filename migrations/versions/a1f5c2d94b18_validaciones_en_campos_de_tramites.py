"""Validaciones en campos de trámites (Fase 1: fija + consistencia)

- CampoTramite/CampoTramiteEmpleador.validaciones: lista de validaciones
  por campo ({fuente, operador, valor, mensaje, bloquea}).
- TipoTramite/TipoTramiteEmpleador.reglas_consistencia: reglas entre dos
  campos, referenciadas por orden (no por id: editar reemplaza los campos).
- Tramite/TramiteEmpleador.advertencias: mensajes de validaciones "avisa"
  que el envío disparó, para el operador del sindicato.

Revision ID: a1f5c2d94b18
Revises: d4a78e3fc144
Create Date: 2026-09-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a1f5c2d94b18'
down_revision: Union[str, None] = 'd4a78e3fc144'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# JSONB en Postgres, JSON común en SQLite -- mismo patrón que Concepto.alias.
JSON_TIPO = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    for tabla in ("campotramite", "campotramiteempleador"):
        with op.batch_alter_table(tabla, schema=None) as batch_op:
            batch_op.add_column(sa.Column('validaciones', JSON_TIPO, nullable=True))
    for tabla in ("tipotramite", "tipotramiteempleador"):
        with op.batch_alter_table(tabla, schema=None) as batch_op:
            batch_op.add_column(sa.Column('reglas_consistencia', JSON_TIPO, nullable=True))
    for tabla in ("tramite", "tramiteempleador"):
        with op.batch_alter_table(tabla, schema=None) as batch_op:
            batch_op.add_column(sa.Column('advertencias', JSON_TIPO, nullable=True))


def downgrade() -> None:
    for tabla in ("tramite", "tramiteempleador"):
        with op.batch_alter_table(tabla, schema=None) as batch_op:
            batch_op.drop_column('advertencias')
    for tabla in ("tipotramite", "tipotramiteempleador"):
        with op.batch_alter_table(tabla, schema=None) as batch_op:
            batch_op.drop_column('reglas_consistencia')
    for tabla in ("campotramite", "campotramiteempleador"):
        with op.batch_alter_table(tabla, schema=None) as batch_op:
            batch_op.drop_column('validaciones')
