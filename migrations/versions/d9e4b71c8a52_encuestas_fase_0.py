"""encuestas: modelo base (Fase 0)

Revision ID: d9e4b71c8a52
Revises: b5c8e30a91f6
Create Date: 2026-09-11 20:55:00.000000

Fase 0 de SPRINT_ENCUESTAS.md. Solo esquema: no hay ninguna ruta todavía y
el módulo nace apagado para todos (está fuera de MODULOS_INICIALES), así que
este deploy no cambia nada de lo que se ve.

Las cinco tablas y por qué están separadas así (decisión N2, el anonimato se
sostiene por la FORMA del modelo y no por un cartel):

- `encuesta` — la cabecera. El estado no se guarda: se deriva de `publicada`
  y las dos fechas (encuestas.estado).
- `preguntaencuesta` — las preguntas, con el vocabulario de CampoTramite más
  escala y ranking.
- `respuestaencuesta` — LA URNA. Una fila por opción elegida o valor libre,
  para agregar en SQL con GROUP BY. **Sin ninguna columna que lleve a una
  persona**, y con el DÍA en vez de la hora: sin timestamp fino no hay forma
  de ordenar las respuestas para alinearlas con nada.
- `encuestaparticipante` — EL PADRÓN. Sus filas se crean AL PUBLICAR, una
  por destinatario, y responder solo prende `respondio`: el orden de los id
  es el del padrón, no el de las respuestas. No guarda cuándo respondió cada
  uno, a propósito.
- `eventoencuesta` — el historial: erratas corregidas, prórrogas, cierres,
  recordatorios y descargas de resultados.

Y tres columnas sueltas:

- `noticia.encuesta_id` y `notificacion.encuesta_id`: la noticia y el aviso
  que anuncian una encuesta llevan el botón para responderla. De la segunda
  sale además el "leídas / no leídas" del dashboard. Sin FK, mismo criterio
  que `formulario_id`.
- `configuracionplataforma.encuestas_umbral_minimo`: el mínimo de respuestas
  para mostrar un grupo (5). Cada encuesta se lleva el valor vigente al
  publicarse.

No hay backfill: no existe ninguna encuesta todavía.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import sqlmodel


revision: str = 'd9e4b71c8a52'
down_revision: Union[str, None] = 'b5c8e30a91f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# JSONB en Postgres, JSON común en SQLite -- mismo patrón que Concepto.alias.
JSON_TIPO = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

TEXTO = sqlmodel.sql.sqltypes.AutoString


def upgrade() -> None:
    op.create_table('encuesta',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sindicato_id', sa.Integer(), nullable=False),
        sa.Column('titulo', TEXTO(), nullable=False),
        sa.Column('descripcion', TEXTO(), nullable=False, server_default=''),
        sa.Column('modo', TEXTO(), nullable=False, server_default='nominal'),
        sa.Column('cortes', JSON_TIPO, nullable=False, server_default='[]'),
        sa.Column('umbral_minimo', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('fecha_desde', TEXTO(), nullable=False, server_default=''),
        sa.Column('fecha_hasta', TEXTO(), nullable=False, server_default=''),
        sa.Column('publicada', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('publicada_en', TEXTO(), nullable=False, server_default=''),
        sa.Column('cerrada_en', TEXTO(), nullable=False, server_default=''),
        sa.Column('mostrar_resultados', sa.Boolean(), nullable=False,
                  server_default=sa.text('false')),
        sa.Column('criterio', TEXTO(), nullable=False, server_default=''),
        sa.Column('criterio_valores', JSON_TIPO, nullable=False, server_default='[]'),
        sa.Column('cantidad_destinatarios', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('usuario_id', sa.Integer(), nullable=True),
        sa.Column('seccional_id', sa.Integer(), nullable=True),
        sa.Column('origen_id', sa.Integer(), nullable=True),
        sa.Column('creada', TEXTO(), nullable=False, server_default=''),
        sa.ForeignKeyConstraint(['sindicato_id'], ['sindicato.id'], ),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuariosindicato.id'], ),
        sa.ForeignKeyConstraint(['seccional_id'], ['seccional.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('encuesta', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_encuesta_sindicato_id'),
                              ['sindicato_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_encuesta_seccional_id'),
                              ['seccional_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_encuesta_origen_id'),
                              ['origen_id'], unique=False)

    op.create_table('preguntaencuesta',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('encuesta_id', sa.Integer(), nullable=False),
        sa.Column('orden', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('etiqueta', TEXTO(), nullable=False, server_default=''),
        sa.Column('tipo_dato', TEXTO(), nullable=False),
        sa.Column('opciones', TEXTO(), nullable=False, server_default=''),
        sa.Column('escala_min', sa.Integer(), nullable=True),
        sa.Column('escala_max', sa.Integer(), nullable=True),
        sa.Column('etiqueta_min', TEXTO(), nullable=False, server_default=''),
        sa.Column('etiqueta_max', TEXTO(), nullable=False, server_default=''),
        sa.Column('ancho', TEXTO(), nullable=False, server_default='completo'),
        sa.Column('obligatorio', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.ForeignKeyConstraint(['encuesta_id'], ['encuesta.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('preguntaencuesta', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_preguntaencuesta_encuesta_id'),
                              ['encuesta_id'], unique=False)

    # LA URNA. Ninguna columna apunta a una persona, y guarda el día y no la
    # hora: las dos cosas son la garantía, no un detalle de implementación.
    op.create_table('respuestaencuesta',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('encuesta_id', sa.Integer(), nullable=False),
        sa.Column('pregunta_id', sa.Integer(), nullable=False),
        sa.Column('opcion_indice', sa.Integer(), nullable=True),
        sa.Column('posicion', sa.Integer(), nullable=True),
        sa.Column('valor_texto', TEXTO(), nullable=False, server_default=''),
        sa.Column('valor_numero', sa.Float(), nullable=True),
        sa.Column('valor_fecha', TEXTO(), nullable=False, server_default=''),
        sa.Column('dia', TEXTO(), nullable=False, server_default=''),
        sa.Column('seccional_id', sa.Integer(), nullable=True),
        sa.Column('provincia', TEXTO(), nullable=False, server_default=''),
        sa.Column('cuit_empleador', TEXTO(), nullable=False, server_default=''),
        sa.ForeignKeyConstraint(['encuesta_id'], ['encuesta.id'], ),
        sa.ForeignKeyConstraint(['pregunta_id'], ['preguntaencuesta.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('respuestaencuesta', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_respuestaencuesta_encuesta_id'),
                              ['encuesta_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_respuestaencuesta_pregunta_id'),
                              ['pregunta_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_respuestaencuesta_dia'), ['dia'], unique=False)
        batch_op.create_index(batch_op.f('ix_respuestaencuesta_seccional_id'),
                              ['seccional_id'], unique=False)

    # EL PADRÓN. Sus filas nacen al publicar; responder solo prende el
    # booleano, así el orden de los id no dice nada del orden de respuesta.
    op.create_table('encuestaparticipante',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('encuesta_id', sa.Integer(), nullable=False),
        sa.Column('cuil', TEXTO(), nullable=False),
        sa.Column('respondio', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.ForeignKeyConstraint(['encuesta_id'], ['encuesta.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('encuestaparticipante', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_encuestaparticipante_encuesta_id'),
                              ['encuesta_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_encuestaparticipante_cuil'),
                              ['cuil'], unique=False)

    op.create_table('eventoencuesta',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('encuesta_id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=True),
        sa.Column('evento', TEXTO(), nullable=False, server_default=''),
        sa.Column('detalle', TEXTO(), nullable=False, server_default=''),
        sa.Column('fecha', TEXTO(), nullable=False, server_default=''),
        sa.ForeignKeyConstraint(['encuesta_id'], ['encuesta.id'], ),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuariosindicato.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('eventoencuesta', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_eventoencuesta_encuesta_id'),
                              ['encuesta_id'], unique=False)

    with op.batch_alter_table('noticia', schema=None) as batch_op:
        batch_op.add_column(sa.Column('encuesta_id', sa.Integer(), nullable=True))

    with op.batch_alter_table('notificacion', schema=None) as batch_op:
        batch_op.add_column(sa.Column('encuesta_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_notificacion_encuesta_id'),
                              ['encuesta_id'], unique=False)

    with op.batch_alter_table('configuracionplataforma', schema=None) as batch_op:
        batch_op.add_column(sa.Column('encuestas_umbral_minimo', sa.Integer(),
                                      nullable=False, server_default='5'))


def downgrade() -> None:
    with op.batch_alter_table('configuracionplataforma', schema=None) as batch_op:
        batch_op.drop_column('encuestas_umbral_minimo')

    with op.batch_alter_table('notificacion', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notificacion_encuesta_id'))
        batch_op.drop_column('encuesta_id')

    with op.batch_alter_table('noticia', schema=None) as batch_op:
        batch_op.drop_column('encuesta_id')

    with op.batch_alter_table('eventoencuesta', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_eventoencuesta_encuesta_id'))
    op.drop_table('eventoencuesta')

    with op.batch_alter_table('encuestaparticipante', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_encuestaparticipante_cuil'))
        batch_op.drop_index(batch_op.f('ix_encuestaparticipante_encuesta_id'))
    op.drop_table('encuestaparticipante')

    with op.batch_alter_table('respuestaencuesta', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_respuestaencuesta_seccional_id'))
        batch_op.drop_index(batch_op.f('ix_respuestaencuesta_dia'))
        batch_op.drop_index(batch_op.f('ix_respuestaencuesta_pregunta_id'))
        batch_op.drop_index(batch_op.f('ix_respuestaencuesta_encuesta_id'))
    op.drop_table('respuestaencuesta')

    with op.batch_alter_table('preguntaencuesta', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_preguntaencuesta_encuesta_id'))
    op.drop_table('preguntaencuesta')

    with op.batch_alter_table('encuesta', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_encuesta_origen_id'))
        batch_op.drop_index(batch_op.f('ix_encuesta_seccional_id'))
        batch_op.drop_index(batch_op.f('ix_encuesta_sindicato_id'))
    op.drop_table('encuesta')
