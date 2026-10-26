"""noticias: la marca «On top»

Una noticia marcada `on_top` va primera mientras esté vigente; las demás
siguen en orden cronológico. Sin ninguna marcada, todas en orden como antes.

Revision ID: c4f8a2d6e1b9
Revises: b3e7f1a9c5d2
Create Date: 2026-10-26 14:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c4f8a2d6e1b9'
down_revision: Union[str, None] = 'b3e7f1a9c5d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("noticia", sa.Column("on_top", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("noticia", "on_top")
