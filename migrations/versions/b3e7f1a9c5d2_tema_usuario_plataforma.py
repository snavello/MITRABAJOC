"""apariencia: el modelo de diseño de cada usuario de plataforma

PLAN_TEMAS.md, D2, llevado al panel de plataforma: cada usuario nominal elige
su modelo (`usuarioplataforma.tema`; vacío = el por defecto, laguna). La
paleta no se guarda: plataforma no tiene sindicato y va siempre con los
colores de Colm3na.

Revision ID: b3e7f1a9c5d2
Revises: a9d4e7c2f1b8
Create Date: 2026-10-25 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b3e7f1a9c5d2'
down_revision: Union[str, None] = 'a9d4e7c2f1b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("usuarioplataforma", sa.Column("tema", sa.String(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("usuarioplataforma", "tema")
