"""empleadores cuenta y crud

Revision ID: 826e9627293a
Revises: f774fd280364
Create Date: 2026-08-17 18:43:38.214948

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '826e9627293a'
down_revision: Union[str, None] = 'f774fd280364'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('cuentaempleador',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cuit', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('clave_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('cuentaempleador', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_cuentaempleador_cuit'), ['cuit'], unique=True)

    op.create_table('empleador',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sindicato_id', sa.Integer(), nullable=False),
        sa.Column('cuit', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('razon_social', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('domicilio', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('telefono', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('provincia', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('mail', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('registrado', sa.Boolean(), nullable=False),
        sa.Column('activo', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['sindicato_id'], ['sindicato.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('empleador', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_empleador_sindicato_id'), ['sindicato_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_empleador_cuit'), ['cuit'], unique=False)

    # Grandfathering: un Empleador mínimo (solo cuit) por cada CUIT que ya
    # aparece en Concepto.cuit_empleador de cada sindicato -- mismo idioma
    # SQL crudo que la migración de módulos, sin importar db.py acá.
    op.execute("""
        INSERT INTO empleador (sindicato_id, cuit, razon_social, domicilio,
                                telefono, provincia, mail, registrado, activo)
        SELECT DISTINCT sindicato_id, cuit_empleador, '', '', '', '', '', false, true
        FROM concepto
        WHERE cuit_empleador IS NOT NULL AND cuit_empleador <> ''
    """)


def downgrade() -> None:
    with op.batch_alter_table('empleador', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_empleador_cuit'))
        batch_op.drop_index(batch_op.f('ix_empleador_sindicato_id'))
    op.drop_table('empleador')

    with op.batch_alter_table('cuentaempleador', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_cuentaempleador_cuit'))
    op.drop_table('cuentaempleador')
