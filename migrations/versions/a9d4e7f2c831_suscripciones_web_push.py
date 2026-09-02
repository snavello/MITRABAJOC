"""Suscripciones Web Push del trabajador

Notificaciones push a la PWA instalada (novedades de trámites). Un CUIL
puede tener varias suscripciones (teléfono + compu); endpoint único.

Revision ID: a9d4e7f2c831
Revises: f2a7b9c4d156
Create Date: 2026-09-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a9d4e7f2c831'
down_revision: Union[str, None] = 'f2a7b9c4d156'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'suscripcionpush',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('cuil', sa.String(), nullable=False),
        sa.Column('endpoint', sa.String(), nullable=False),
        sa.Column('p256dh', sa.String(), nullable=False),
        sa.Column('auth', sa.String(), nullable=False),
        sa.Column('creado', sa.String(), nullable=False),
        sa.UniqueConstraint('endpoint'),
    )
    op.create_index('ix_suscripcionpush_cuil', 'suscripcionpush', ['cuil'])


def downgrade() -> None:
    op.drop_index('ix_suscripcionpush_cuil', table_name='suscripcionpush')
    op.drop_table('suscripcionpush')
