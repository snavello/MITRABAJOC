"""pase de tramites entre areas

Revision ID: a2e6f1b83d40
Revises: f8a3d05e2c17
Create Date: 2026-09-11 09:30:00.000000

Fase 4 de SPRINT_AREAS_V2.md (decisión N8). El área que recibe un trámite
puede derivarlo a otra, si el formulario lo habilita.

- `tipotramite.permite_pase`: arranca en false para TODOS. Es opt-in por
  formulario: los que ya existen siguen funcionando igual, el área que los
  recibe solo le contesta al trabajador.
- `pasetipotramite`: la lista CERRADA de áreas a las que ese formulario
  puede derivar. Vacía para los existentes, que es coherente con
  permite_pase=false.
- `pasetramite`: el registro de cada movimiento. Es lo que hace posible que
  el área que derivó conserve LECTURA -- sin esta tabla, derivar sería
  perder de vista para siempre lo que uno pasó.

No hay backfill: un trámite que nunca se derivó no tiene pases, y su área a
cargo ya la puso la migración anterior.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'a2e6f1b83d40'
down_revision: Union[str, None] = 'f8a3d05e2c17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('tipotramite', schema=None) as batch_op:
        batch_op.add_column(sa.Column('permite_pase', sa.Boolean(), nullable=False,
                                      server_default=sa.text('false')))

    op.create_table('pasetipotramite',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tipo_tramite_id', sa.Integer(), nullable=False),
        sa.Column('area_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['tipo_tramite_id'], ['tipotramite.id'], ),
        sa.ForeignKeyConstraint(['area_id'], ['area.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('pasetipotramite', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_pasetipotramite_tipo_tramite_id'),
                              ['tipo_tramite_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_pasetipotramite_area_id'),
                              ['area_id'], unique=False)

    op.create_table('pasetramite',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tramite_id', sa.Integer(), nullable=False),
        sa.Column('area_origen_id', sa.Integer(), nullable=True),
        sa.Column('area_destino_id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=True),
        sa.Column('motivo', sqlmodel.sql.sqltypes.AutoString(), nullable=False,
                  server_default=''),
        sa.Column('creado', sqlmodel.sql.sqltypes.AutoString(), nullable=False,
                  server_default=''),
        sa.ForeignKeyConstraint(['tramite_id'], ['tramite.id'], ),
        sa.ForeignKeyConstraint(['area_origen_id'], ['area.id'], ),
        sa.ForeignKeyConstraint(['area_destino_id'], ['area.id'], ),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuariosindicato.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('pasetramite', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_pasetramite_tramite_id'),
                              ['tramite_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_pasetramite_area_origen_id'),
                              ['area_origen_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_pasetramite_area_destino_id'),
                              ['area_destino_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('pasetramite', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_pasetramite_area_destino_id'))
        batch_op.drop_index(batch_op.f('ix_pasetramite_area_origen_id'))
        batch_op.drop_index(batch_op.f('ix_pasetramite_tramite_id'))
    op.drop_table('pasetramite')

    with op.batch_alter_table('pasetipotramite', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_pasetipotramite_area_id'))
        batch_op.drop_index(batch_op.f('ix_pasetipotramite_tipo_tramite_id'))
    op.drop_table('pasetipotramite')

    with op.batch_alter_table('tipotramite', schema=None) as batch_op:
        batch_op.drop_column('permite_pase')
