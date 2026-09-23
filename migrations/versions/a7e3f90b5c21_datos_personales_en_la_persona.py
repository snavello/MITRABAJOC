"""los datos personales del afiliado pasan a la persona

Revision ID: a7e3f90b5c21
Revises: f4a2b7c19d05
Create Date: 2026-09-22 00:00:00.000000

El nombre, el domicilio, el teléfono y el mail de un afiliado dejan de vivir
en `trabajador` -- que es una fila POR SINDICATO -- y pasan a
`cuentatrabajador`, que es una fila por CUIL. Una persona vive en un solo
lugar y se llama de una sola manera.

**Por qué.** Con el dato en el empadronamiento, un CUIL en dos gremios tenía
dos copias, y las cuatro puertas por las que entra un domicilio no escribían
igual: `/trabajador/registro` lo copiaba a TODOS los empadronamientos y
`/api/perfil` solo al del sindicato activo. La misma persona editando en dos
pantallas dejaba dos direcciones distintas y nada decía cuál era la buena.
En Pruebas y en Demo había un CUIL así en cada base. Además `cuentatrabajador`
ya tenía una columna `nombre` que **no leía nadie** y que solo llenaba el
cargador de datos sintéticos: una tercera copia, siempre desactualizada.

**Qué pasa con los que todavía no se registraron.** Nada: a partir de acá la
fila de `cuentatrabajador` existe desde que el CUIL entra al PADRÓN, con
`clave_hash` vacío. Vacío significa "todavía no eligió clave", no "no
existe" -- `auth.verificar_clave` ya devuelve False con un hash vacío, así
que ninguna de esas filas puede usarse para entrar. Sin esto el alta del
admin necesitaría un segundo lugar donde escribir y volveríamos al problema.

**Cómo se consolida lo que ya diverge.** El DOMICILIO se copia entero desde
UN empadronamiento, no campo por campo: son seis campos que valen como un
solo dato, y fusionarlos produciría una dirección que no existe en ninguna
parte (la calle de una ciudad con la localidad de otra). Gana la fila más
completa -- primero la que tiene coordenadas, después la que tiene más
campos cargados y, empatando, la del sindicato más viejo.

El NOMBRE, el TELÉFONO y el MAIL se resuelven aparte, cada uno con el primer
valor no vacío por orden de sindicato. No son parte del bloque y atarlos a
él haría perder el teléfono que cargó un gremio solo porque la dirección
buena la tenía el otro. Salen del empadronamiento y no de
`cuentatrabajador.nombre` porque el del empadronamiento es el que la app
venía mostrando en todas las pantallas; el de la cuenta solo se usa si
ningún empadronamiento traía uno.

**Cuánto tarda.** A la escala de hoy, nada: Pruebas tiene 1.315
empadronamientos y 1.310 personas, Demo 313 y 309. Son cuatro ALTER TABLE y
cinco sentencias de datos sobre tablas de miles de filas, o sea segundos en
el Pre-Deploy. El `ADD COLUMN ... NOT NULL DEFAULT ''` no reescribe la tabla
(Postgres 11+) pero el `DROP COLUMN` sí toma un lock ACCESS EXCLUSIVE; si
estas tablas llegaran a millones de filas habría que repensarlo (columna
nueva, backfill por lotes y swap), igual que se anotó para la migración
`d2c8f04a6b31`.

**Es irreversible en los datos.** `downgrade` devuelve las columnas a
`trabajador` y copia de vuelta lo consolidado en todos los empadronamientos
del CUIL: el esquema vuelve, pero la divergencia que había antes no, porque
esa información se pierde acá a propósito. Es el punto del cambio.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'a7e3f90b5c21'
down_revision: Union[str, None] = 'f4a2b7c19d05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# El bloque que se muda, con el valor con el que nace cada columna. Se
# escribe una sola vez para que el alta, la copia y el downgrade no puedan
# quedar con listas distintas.
TEXTOS = ("calle", "numero", "piso_depto", "localidad", "provincia",
          "codigo_postal", "direccion_texto", "telefono", "mail")
DEFAULTS = {campo: '' for campo in TEXTOS}
DEFAULTS["precision_geo"] = 'sin_geo'
DEFAULTS["geo_actualizado"] = ''


def _agregar_bloque(batch_op) -> None:
    for campo in TEXTOS:
        batch_op.add_column(sa.Column(campo, sqlmodel.sql.sqltypes.AutoString(),
                                      nullable=False, server_default=''))
    batch_op.add_column(sa.Column('latitud', sa.Float(), nullable=True))
    batch_op.add_column(sa.Column('longitud', sa.Float(), nullable=True))
    batch_op.add_column(sa.Column('precision_geo', sqlmodel.sql.sqltypes.AutoString(),
                                  nullable=False, server_default='sin_geo'))
    batch_op.add_column(sa.Column('geo_actualizado', sqlmodel.sql.sqltypes.AutoString(),
                                  nullable=False, server_default=''))


def _quitar_bloque(batch_op) -> None:
    for campo in (*TEXTOS, 'latitud', 'longitud', 'precision_geo', 'geo_actualizado'):
        batch_op.drop_column(campo)


# Todo el bloque junto. Solo lo usa el `downgrade`, que copia de vuelta sin
# elegir nada: la divergencia ya se perdió y no hay entre qué decidir.
COPIADAS = (*TEXTOS, 'latitud', 'longitud', 'precision_geo', 'geo_actualizado')

# El domicilio propiamente dicho: los campos que se mueven JUNTOS, porque
# valen como un solo dato. El teléfono, el mail y el nombre quedan afuera a
# propósito -- se resuelven uno por uno (ver el encabezado).
DOMICILIO = ('calle', 'numero', 'piso_depto', 'localidad', 'provincia',
             'codigo_postal', 'direccion_texto', 'latitud', 'longitud',
             'precision_geo', 'geo_actualizado')
SUELTOS = ('nombre', 'telefono', 'mail')


def upgrade() -> None:
    # ---------- 1. la persona recibe el bloque ----------
    with op.batch_alter_table('cuentatrabajador', schema=None) as batch_op:
        _agregar_bloque(batch_op)

    # ---------- 2. toda persona del padrón tiene su fila ----------
    # `clave_hash` vacío = está en el padrón y todavía no eligió clave.
    op.execute("""
        INSERT INTO cuentatrabajador (cuil, clave_hash, nombre)
        SELECT DISTINCT t.cuil, '', ''
          FROM trabajador t
         WHERE NOT EXISTS (SELECT 1 FROM cuentatrabajador c WHERE c.cuil = t.cuil)
    """)

    # ---------- 3a. el domicilio, como bloque ----------
    # DISTINCT ON elige UNA fila por CUIL: la de mejor calidad, con la regla
    # del encabezado. El orden es explícito y determinista para que correr la
    # migración dos veces sobre la misma base dé el mismo resultado.
    asignaciones = ", ".join(f"{campo} = mejor.{campo}" for campo in DOMICILIO)
    campos = ", ".join(DOMICILIO)
    completos = " + ".join(
        f"(CASE WHEN TRIM({campo}) <> '' THEN 1 ELSE 0 END)"
        for campo in ('calle', 'numero', 'piso_depto', 'localidad',
                      'provincia', 'codigo_postal'))
    op.execute(f"""
        UPDATE cuentatrabajador c
           SET {asignaciones}
          FROM (
            SELECT DISTINCT ON (cuil) cuil, {campos}
              FROM trabajador
             ORDER BY cuil,
                      (latitud IS NOT NULL) DESC,
                      ({completos}) DESC,
                      sindicato_id ASC
          ) AS mejor
         WHERE mejor.cuil = c.cuil
    """)

    # ---------- 3b. nombre, teléfono y mail, uno por uno ----------
    # El primer valor NO VACÍO por orden de sindicato. Si ningún
    # empadronamiento traía nada, queda lo que ya tuviera la cuenta (que para
    # el nombre puede ser el que dejó el cargador de datos sintéticos).
    for campo in SUELTOS:
        op.execute(f"""
            UPDATE cuentatrabajador c
               SET {campo} = COALESCE(elegido.valor, c.{campo})
              FROM (
                SELECT DISTINCT ON (cuil) cuil, NULLIF(TRIM({campo}), '') AS valor
                  FROM trabajador
                 ORDER BY cuil, (NULLIF(TRIM({campo}), '') IS NULL), sindicato_id ASC
              ) AS elegido
             WHERE elegido.cuil = c.cuil
        """)

    # ---------- 4. el empadronamiento se queda sin copia ----------
    with op.batch_alter_table('trabajador', schema=None) as batch_op:
        _quitar_bloque(batch_op)
        batch_op.drop_column('nombre')


def downgrade() -> None:
    with op.batch_alter_table('trabajador', schema=None) as batch_op:
        batch_op.add_column(sa.Column('nombre', sqlmodel.sql.sqltypes.AutoString(),
                                      nullable=False, server_default=''))
        _agregar_bloque(batch_op)

    asignaciones = ", ".join(f"{campo} = c.{campo}" for campo in COPIADAS)
    op.execute(f"""
        UPDATE trabajador t
           SET nombre = c.nombre, {asignaciones}
          FROM cuentatrabajador c
         WHERE c.cuil = t.cuil
    """)

    # Y la persona vuelve a ser solo identidad + foto. Sin esto el downgrade
    # deja las columnas de los dos lados y el upgrade siguiente falla al
    # intentar crearlas de nuevo.
    with op.batch_alter_table('cuentatrabajador', schema=None) as batch_op:
        _quitar_bloque(batch_op)
