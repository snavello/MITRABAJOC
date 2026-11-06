"""clave transitoria solo para las altas nuevas

Desde Admin 0.79.01 el login del panel lee `cuentapanel.debe_cambiar_clave` y,
si está en True, obliga a elegir una clave antes de abrir la sesión. La bandera
quedaba en True desde CADA alta y nadie la leía, así que al desplegar TODAS las
cuentas ya existentes (Pruebas, Demo, La Bancaria) hubieran tenido que elegir
clave en su próximo ingreso sin aviso. Esta migración las deja como están
(False): la obligación corre solo para las altas y los reseteos de ahora en
adelante, que son los que escriben True a sabiendas.

Revision ID: b2d4f6a8c0e2
Revises: a9c2e4f6b8d1
Create Date: 2026-11-06 20:30:00

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'b2d4f6a8c0e2'
down_revision: Union[str, None] = 'a9c2e4f6b8d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE cuentapanel SET debe_cambiar_clave = false")


def downgrade() -> None:
    # Migración de datos: no se puede saber qué cuentas estaban en True.
    pass
