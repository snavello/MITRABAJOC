"""tope de base imponible de septiembre de 2014 (Res. ANSES 449/2014)

Revision ID: e28e33b0aec5
Revises: b6d3f1a8c902
Create Date: 2026-10-11 16:22:00.000000

La semilla de topes (data/topes_ss.csv) arrancaba con una fila "2015-01" de
$37.191,95, marcada por_verificar. Esa vigencia no existe: el tope cambia en
marzo y septiembre, con la movilidad. El que regía de septiembre de 2014 a
febrero de 2015 es el de la Res. ANSES 449/2014, art. 7: mínima $1.124,06 y
máxima $36.531,48. Lo confirmó un recibo real de AEFIP de febrero de 2015
(el empleador es el propio organismo recaudador): jubilación $4.018,46 y PAMI
$1.095,94, exactos sobre $36.531,48; con el valor viejo la app le marcaba una
diferencia de $72,65 que no existía.

Solo toca la fila si sigue como la dejó la semilla (mismo importe): si
alguien ya la corrigió a mano desde /plataforma, no se pisa. Con la tabla
vacía no hace nada: la semilla, ya corregida, se carga al arrancar la app.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e28e33b0aec5'
down_revision: Union[str, None] = 'b6d3f1a8c902'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TOPES = sa.table(
    'topebaseimponible',
    sa.column('id', sa.Integer), sa.column('vigencia_desde', sa.String),
    sa.column('tope_maximo', sa.Float), sa.column('base_minima', sa.Float),
    sa.column('estado', sa.String), sa.column('fuente', sa.String),
)

VIEJA = {"vigencia_desde": "2015-01", "tope_maximo": 37191.95, "base_minima": 1144.38,
         "estado": "por_verificar", "fuente": "CSV aportado, sin contrastar con fuente oficial"}
NUEVA = {"vigencia_desde": "2014-09", "tope_maximo": 36531.48, "base_minima": 1124.06,
         "estado": "verificado", "fuente": "Res. ANSES 449/2014"}


def _fila(conn, datos):
    """id de la fila con esa vigencia y ese importe, o None."""
    return conn.execute(sa.select(TOPES.c.id).where(
        TOPES.c.vigencia_desde == datos["vigencia_desde"],
        sa.func.abs(TOPES.c.tope_maximo - datos["tope_maximo"]) < 0.005,
    )).scalar()


def _hay_vigencia(conn, vigencia):
    return conn.execute(sa.select(TOPES.c.id).where(
        TOPES.c.vigencia_desde == vigencia)).first() is not None


def _reemplazar(desde, hacia):
    conn = op.get_bind()
    fila = _fila(conn, desde)
    if fila is None:
        return
    if _hay_vigencia(conn, hacia["vigencia_desde"]):
        # La vigencia correcta ya está cargada (a mano): sobra la otra.
        conn.execute(TOPES.delete().where(TOPES.c.id == fila))
    else:
        conn.execute(TOPES.update().where(TOPES.c.id == fila).values(**hacia))


def upgrade() -> None:
    _reemplazar(VIEJA, NUEVA)


def downgrade() -> None:
    _reemplazar(NUEVA, VIEJA)
