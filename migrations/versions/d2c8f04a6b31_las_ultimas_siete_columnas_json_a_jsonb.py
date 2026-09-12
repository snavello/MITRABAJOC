"""las ultimas siete columnas json a jsonb

Revision ID: d2c8f04a6b31
Revises: e3b7a91c5d64
Create Date: 2026-09-12 20:05:00.000000

Deja TODAS las columnas JSON del proyecto en `jsonb`, que es lo que CLAUDE.md
viene diciendo desde hace meses y lo que las migraciones hacen desde la del
alta de módulos. Estas siete quedaron en `json` solo porque sus migraciones
son anteriores a que se adoptara `sa.JSON().with_variant(JSONB, "postgresql")`:

    concepto.alias                     reciboverificado.detalle
    reporte.detalle                    enviosindicato.detalle
    consultaconvenio.fragmentos_usados testcarga.parametros / .resumen

**Qué gana.** `jsonb` es binario y normalizado: tiene operador de igualdad,
contención (`@>`), y se puede indexar con GIN. `json` guarda el texto tal cual
y no permite nada de eso -- una consulta que filtre por dentro de `detalle`
hoy tiene que castear en cada fila. No hay ninguna consulta así todavía, y
justamente por eso conviene hacerlo ahora, cuando las tablas son chicas.

**Qué NO cambia.** Leer y escribir un dict o una lista entera se comporta
igual, que es todo lo que la app hace hoy con estas columnas. `jsonb` reordena
las claves de los OBJETOS pero **conserva el orden de los ARRAYS**, y todo lo
que el código recorre en orden son arrays (`discrepancias`, `alertas`, `log`,
`respuestas`, `alias`): se revisó uno por uno antes de escribir esto.

**Riesgo medido, no supuesto.** Sobre una copia de la base de demo con 15.000
recibos (25 MB en `reciboverificado`), las siete conversiones juntas tardaron
1,5 segundos; a las 50.000 filas del banco de pruebas del panel serían unos 5.
`ALTER COLUMN ... TYPE` toma un lock ACCESS EXCLUSIVE y reescribe la tabla,
así que durante esos segundos las consultas a esas tablas esperan. En Render
esto corre en el Pre-Deploy, con la versión anterior todavía sirviendo: son
unos segundos de espera en un momento en el que igual va a haber un reinicio.
A esta escala es benigno; si algún día estas tablas tienen millones de filas,
hay que repensarlo (crear columna nueva, backfill por lotes y swap).

**El único caso en que esto falla**: `jsonb` rechaza `\\u0000` dentro de una
cadena y `json` lo acepta. Si alguna fila lo tuviera, el cast aborta, la
migración revierte entera y el deploy se corta con la versión vieja intacta
-- falla del lado seguro, no corrompe nada. No hay ninguna en la demo (se
buscó en las 21.000 filas de las tres tablas). Si llegara a aparecer en
producción, el síntoma es "unsupported Unicode escape sequence" y se
encuentran con:

    SELECT id FROM reciboverificado WHERE detalle::text LIKE '%\\u0000%';

El `USING` va explícito aunque Postgres sepa castear json a jsonb solo:
decirlo deja el asiento de qué conversión se pidió.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'd2c8f04a6b31'
down_revision: Union[str, None] = 'e3b7a91c5d64'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (tabla, columna) de las siete rezagadas.
COLUMNAS = [
    ("concepto", "alias"),
    ("reporte", "detalle"),
    ("reciboverificado", "detalle"),
    ("enviosindicato", "detalle"),
    ("consultaconvenio", "fragmentos_usados"),
    ("testcarga", "parametros"),
    ("testcarga", "resumen"),
]


def upgrade() -> None:
    for tabla, columna in COLUMNAS:
        op.alter_column(tabla, columna, type_=postgresql.JSONB(),
                        postgresql_using=f"{columna}::jsonb")


def downgrade() -> None:
    # jsonb -> json siempre castea (jsonb es un subconjunto: todo lo que
    # entró ya es JSON válido). Lo que NO vuelve es el texto original: el
    # orden de las claves de los objetos y los espacios quedan normalizados
    # por jsonb, y eso es irreversible. El dato es el mismo; su
    # representación textual, no necesariamente.
    for tabla, columna in reversed(COLUMNAS):
        op.alter_column(tabla, columna, type_=sa.JSON(),
                        postgresql_using=f"{columna}::json")
