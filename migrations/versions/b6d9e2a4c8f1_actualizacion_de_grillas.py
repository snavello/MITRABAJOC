"""actualización automática de las grillas: modelo de IA y notas vistas

PLAN_CONVENIO_ESCALAS.md, bloque 5:
- configuracionplataforma.modelo_grilla_salarial: el quinto uso de IA elegible
  desde /plataforma → Uso de IA → Modelos (vacío = el default del módulo,
  escalas_lectura.MODELO).
- escalanovedad: las notas del sitio del sindicato que el proceso ya vio
  (comunicados y notas de grillas), con sus intentos de lectura.

Idempotente: la columna y la tabla se crean solo si faltan.

Revision ID: b6d9e2a4c8f1
Revises: a5c8e1f3b7d2
Create Date: 2026-11-16 19:10:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import postgresql

revision: str = 'b6d9e2a4c8f1'
down_revision: Union[str, None] = 'a5c8e1f3b7d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    columnas = {c["name"] for c in insp.get_columns("configuracionplataforma")}
    if "modelo_grilla_salarial" not in columnas:
        with op.batch_alter_table("configuracionplataforma") as batch_op:
            batch_op.add_column(sa.Column("modelo_grilla_salarial", sqlmodel.sql.sqltypes.AutoString(),
                                          nullable=False, server_default=""))
    if 'escalanovedad' in set(insp.get_table_names()):
        return
    op.create_table(
        'escalanovedad',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('convenio', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('tipo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('post_id', sa.Integer(), nullable=False),
        sa.Column('titulo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('url', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('publicada', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('periodo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('datos', _JSON, nullable=False),
        sa.Column('visto', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('intentos', sa.Integer(), nullable=False),
        sa.Column('resultado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('ultimo_error', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('grilla_id', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('convenio', 'tipo', 'post_id', name='uq_escalanovedad_post'),
    )
    op.create_index(op.f('ix_escalanovedad_convenio'), 'escalanovedad', ['convenio'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_escalanovedad_convenio'), table_name='escalanovedad')
    op.drop_table('escalanovedad')
    with op.batch_alter_table("configuracionplataforma") as batch_op:
        batch_op.drop_column("modelo_grilla_salarial")
