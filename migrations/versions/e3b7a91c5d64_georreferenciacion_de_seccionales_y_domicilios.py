"""georreferenciacion de seccionales y domicilios

Revision ID: e3b7a91c5d64
Revises: f1a6c39d47b2
Create Date: 2026-09-12 18:20:00.000000

Le da ubicación geográfica a las Seccionales y al domicilio del afiliado,
con el MISMO bloque de campos en las dos tablas (ver geo.CAMPOS_DOMICILIO).

**`seccional.direccion` SE BORRA y su contenido no se migra.** Era una sola
columna de texto libre escrita a mano ("Av. Independencia 1200, CABA"), y
sobre una cadena libre no se puede buscar ni ubicar nada. El dato existente
era provisorio -- decisión explícita de Sd el 2026-09-12 -- así que en vez de
intentar partir ese texto en calle/número/localidad con heurísticas que
fallan en la mitad de los casos, las seccionales existentes quedan `sin_geo`
y el panel las marca como pendientes de georreferenciar. Es un estado
visible y accionable, no una pérdida silenciosa.

**En `trabajador` no se pierde nada: son dos renames.** `piso` -> `piso_depto`
y `ciudad` -> `localidad`, para que el domicilio de la persona y el de la
seccional se llamen igual. Dos nombres para lo mismo es lo que hacía que
cada pantalla armara la dirección a su manera. Un rename de columna conserva
los datos; los campos nuevos (CP, texto armado, coordenadas) nacen vacíos.

`direccion_texto` de trabajador SÍ se backfillea, porque los campos
estructurados ya estaban: el CONCAT_WS de abajo produce exactamente lo mismo
que `geo.armar_direccion_texto` para una fila sin código postal, que es el
caso de todas las filas existentes (la columna es nueva). La próxima vez que
alguien guarde esa fila, el texto lo vuelve a armar el servidor.

`precision_geo` nace en 'sin_geo' y no en '' a propósito: "no está ubicada"
es un estado válido del sistema y tiene que ser legible, no un campo vacío
que cada pantalla interprete como quiera.

Índice `(sindicato_id, localidad)` en seccional, que es el orden con el que
se listan en "cerca de mí" y en los filtros del panel. Va solo en la
migración, igual que `ix_reciboverificado_sind_procesado`: los índices
compuestos de este proyecto no viven en el modelo.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'e3b7a91c5d64'
down_revision: Union[str, None] = 'f1a6c39d47b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# El bloque de domicilio, igual para las dos tablas. Se escribe una vez acá
# para que no haya forma de que una tabla quede con un campo que la otra no
# tiene -- que es el defecto que esta migración viene a corregir.
TEXTOS_DOMICILIO = ("calle", "numero", "piso_depto", "localidad", "provincia",
                    "codigo_postal", "direccion_texto")
CONTACTO_SECCIONAL = ("telefono", "whatsapp", "mail", "horario_atencion")


def _agregar_domicilio(batch_op, textos) -> None:
    for campo in textos:
        batch_op.add_column(sa.Column(campo, sqlmodel.sql.sqltypes.AutoString(),
                                      nullable=False, server_default=''))
    batch_op.add_column(sa.Column('latitud', sa.Float(), nullable=True))
    batch_op.add_column(sa.Column('longitud', sa.Float(), nullable=True))
    batch_op.add_column(sa.Column('precision_geo', sqlmodel.sql.sqltypes.AutoString(),
                                  nullable=False, server_default='sin_geo'))
    batch_op.add_column(sa.Column('geo_actualizado', sqlmodel.sql.sqltypes.AutoString(),
                                  nullable=False, server_default=''))


def upgrade() -> None:
    # ---------- seccional: domicilio estructurado + contacto ----------
    with op.batch_alter_table('seccional', schema=None) as batch_op:
        _agregar_domicilio(batch_op, TEXTOS_DOMICILIO)
        for campo in CONTACTO_SECCIONAL:
            batch_op.add_column(sa.Column(campo, sqlmodel.sql.sqltypes.AutoString(),
                                          nullable=False, server_default=''))
        # El texto libre se va. Ver el encabezado: era provisorio y no se
        # puede partir en campos sin adivinar.
        batch_op.drop_column('direccion')

    op.create_index('ix_seccional_sind_localidad', 'seccional',
                    ['sindicato_id', 'localidad'])

    # ---------- trabajador: los dos renames + los campos nuevos ----------
    with op.batch_alter_table('trabajador', schema=None) as batch_op:
        batch_op.alter_column('piso', new_column_name='piso_depto')
        batch_op.alter_column('ciudad', new_column_name='localidad')
        batch_op.add_column(sa.Column('codigo_postal', sqlmodel.sql.sqltypes.AutoString(),
                                      nullable=False, server_default=''))
        batch_op.add_column(sa.Column('direccion_texto', sqlmodel.sql.sqltypes.AutoString(),
                                      nullable=False, server_default=''))
        batch_op.add_column(sa.Column('latitud', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('longitud', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('precision_geo', sqlmodel.sql.sqltypes.AutoString(),
                                      nullable=False, server_default='sin_geo'))
        batch_op.add_column(sa.Column('geo_actualizado', sqlmodel.sql.sqltypes.AutoString(),
                                      nullable=False, server_default=''))

    # Backfill del texto armado. CONCAT_WS ignora los NULL (no los vacíos),
    # de ahí el NULLIF en cada campo. El resultado es idéntico al de
    # geo.armar_direccion_texto para una fila sin CP: "calle numero, piso,
    # localidad, provincia".
    op.execute("""
        UPDATE trabajador SET direccion_texto = COALESCE(NULLIF(CONCAT_WS(', ',
            NULLIF(TRIM(CONCAT_WS(' ', NULLIF(TRIM(calle), ''),
                                       NULLIF(TRIM(numero), ''))), ''),
            NULLIF(TRIM(piso_depto), ''),
            NULLIF(TRIM(localidad), ''),
            NULLIF(TRIM(provincia), '')
        ), ''), '')
    """)

    # ---------- caché de geocodificación ----------
    # Sin sindicato_id a propósito: lo que guarda es la respuesta de una API
    # pública a una dirección normalizada, no un dato de un sindicato. Ver
    # el docstring de db.GeoCache.
    op.create_table('geocache',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('consulta_normalizada', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('respuesta_json', sa.JSON(), nullable=True),
        sa.Column('creado', sqlmodel.sql.sqltypes.AutoString(), nullable=False,
                  server_default=''),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('geocache', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_geocache_consulta_normalizada'),
                              ['consulta_normalizada'], unique=True)


def downgrade() -> None:
    with op.batch_alter_table('geocache', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_geocache_consulta_normalizada'))
    op.drop_table('geocache')

    with op.batch_alter_table('trabajador', schema=None) as batch_op:
        for campo in ('geo_actualizado', 'precision_geo', 'longitud', 'latitud',
                      'direccion_texto', 'codigo_postal'):
            batch_op.drop_column(campo)
        batch_op.alter_column('localidad', new_column_name='ciudad')
        batch_op.alter_column('piso_depto', new_column_name='piso')

    op.drop_index('ix_seccional_sind_localidad', table_name='seccional')

    with op.batch_alter_table('seccional', schema=None) as batch_op:
        # `direccion` vuelve a existir pero VACÍA: el texto viejo se borró en
        # el upgrade y no hay de dónde recuperarlo. El downgrade devuelve el
        # esquema, no los datos -- y eso es justamente lo que el upgrade dice
        # que se acepta perder.
        batch_op.add_column(sa.Column('direccion', sqlmodel.sql.sqltypes.AutoString(),
                                      nullable=False, server_default=''))
        for campo in CONTACTO_SECCIONAL:
            batch_op.drop_column(campo)
        for campo in ('geo_actualizado', 'precision_geo', 'longitud', 'latitud'):
            batch_op.drop_column(campo)
        for campo in reversed(TEXTOS_DOMICILIO):
            batch_op.drop_column(campo)
