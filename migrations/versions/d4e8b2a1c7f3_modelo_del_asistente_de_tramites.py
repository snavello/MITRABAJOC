"""modelo de IA del Asistente de trámites

configuracionplataforma.modelo_asistente_tramites: el cuarto uso de IA
elegible desde /plataforma → Uso de IA → Modelos (PLAN_ASISTENTE_TRAMITES.md,
D3). Vacío = el default del módulo (asistente_tramites_ia.MODELO), igual que
los otros tres.

Revision ID: d4e8b2a1c7f3
Revises: a3c7e91d4b26
Create Date: 2026-10-16 18:10:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = 'd4e8b2a1c7f3'
down_revision: Union[str, None] = 'a3c7e91d4b26'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("configuracionplataforma") as batch_op:
        batch_op.add_column(sa.Column("modelo_asistente_tramites", sqlmodel.sql.sqltypes.AutoString(),
                                      nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("configuracionplataforma") as batch_op:
        batch_op.drop_column("modelo_asistente_tramites")
