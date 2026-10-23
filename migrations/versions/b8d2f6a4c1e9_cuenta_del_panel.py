"""cuenta del panel: una clave por CUIL para todos los sindicatos

Hasta acá la clave del panel vivía en cada `usuariosindicato`, una por
sindicato, y el login probaba la clave contra la primera fila que encontraba
con ese CUIL: quien trabajaba en dos sindicatos solo entraba a uno. La clave
pasa a `cuentapanel`, una fila por CUIL, como `cuentatrabajador`.

El pase de las claves que ya existen: por cada CUIL se toma la de su fila
ACTIVA más vieja (la del primer sindicato que lo dio de alta, que es la que
la regla nueva hubiera conservado: los sindicatos que lo suman después no
fijan la clave). Si una persona tenía claves distintas en dos sindicatos,
la del más nuevo deja de valer; plataforma se la puede restablecer. Después
de copiarlas, las filas quedan con la clave vacía.

Revision ID: b8d2f6a4c1e9
Revises: a9c4e7f2d1b6
Create Date: 2026-10-17 10:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = 'b8d2f6a4c1e9'
down_revision: Union[str, None] = 'a9c4e7f2d1b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cuentapanel",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cuil", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("clave_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("debe_cambiar_clave", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("cuentapanel") as batch_op:
        batch_op.create_index(batch_op.f("ix_cuentapanel_cuil"), ["cuil"], unique=True)

    # Filas viejas sin `cuil`: el login siempre fue el CUIL.
    op.execute("UPDATE usuariosindicato SET cuil = usuario "
               "WHERE (cuil IS NULL OR cuil = '') AND usuario ~ '^[0-9]{11}$'")
    op.execute("""
        INSERT INTO cuentapanel (cuil, clave_hash, debe_cambiar_clave)
        SELECT DISTINCT ON (cuil) cuil, clave_hash, debe_cambiar_clave
        FROM usuariosindicato
        WHERE cuil <> '' AND clave_hash <> ''
        ORDER BY cuil, activo DESC, id ASC
    """)
    op.execute("UPDATE usuariosindicato SET clave_hash = ''")


def downgrade() -> None:
    # Cada fila recupera la clave de la cuenta de su persona: vuelve a haber
    # una por sindicato, pero todas iguales.
    op.execute("""
        UPDATE usuariosindicato u SET clave_hash = c.clave_hash,
               debe_cambiar_clave = c.debe_cambiar_clave
        FROM cuentapanel c WHERE c.cuil = u.cuil
    """)
    with op.batch_alter_table("cuentapanel") as batch_op:
        batch_op.drop_index(batch_op.f("ix_cuentapanel_cuil"))
    op.drop_table("cuentapanel")
