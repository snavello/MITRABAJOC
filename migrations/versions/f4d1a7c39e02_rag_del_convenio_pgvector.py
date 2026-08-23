"""rag del convenio con pgvector

Revision ID: f4d1a7c39e02
Revises: bd0236c61d6c
Create Date: 2026-08-23 01:05:33.418927

Bloque 1 de PLAN_RAG_CONVENIO.md. Crea la extensión pgvector y las 4 tablas
del piloto de consultas sobre el convenio.

La dimensión del vector (1024) NO es arbitraria: sale de medir tres modelos
contra el convenio real de AEFIP con 18 preguntas (ver medicion_rag/).
multilingual-e5-large ganó con 94% de recall@8 contra 76% y 47%. Cambiarla
después es esta migración otra vez MÁS reindexar todo lo cargado.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = 'f4d1a7c39e02'
down_revision: Union[str, None] = 'bd0236c61d6c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DIM = 1024


def upgrade() -> None:
    # La extensión primero: sin esto el tipo `vector` no existe. La imagen
    # `postgres:16` pelada NO la trae -- docker-compose.yml usa
    # pgvector/pgvector:pg16 justamente por esto.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table('convenio',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sindicato_id', sa.Integer(), nullable=False),
        sa.Column('nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('codigo', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
        sa.Column('activo', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('creado', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
        sa.ForeignKeyConstraint(['sindicato_id'], ['sindicato.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('convenio', schema=None) as b:
        b.create_index(b.f('ix_convenio_sindicato_id'), ['sindicato_id'], unique=False)

    op.create_table('documentoconvenio',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('convenio_id', sa.Integer(), nullable=False),
        sa.Column('sindicato_id', sa.Integer(), nullable=False),
        sa.Column('tipo', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default='convenio'),
        sa.Column('titulo', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
        sa.Column('fecha_documento', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
        sa.Column('archivo_datos', sa.LargeBinary(), nullable=True),
        sa.Column('archivo_mime', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
        sa.Column('archivo_nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
        sa.Column('observaciones', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
        sa.Column('observaciones_fecha', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
        sa.Column('vigente', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('vigencia_desde', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
        sa.Column('vigencia_hasta', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
        sa.Column('origen_texto', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
        sa.Column('caracteres_extraidos', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('paginas', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('creado', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
        sa.ForeignKeyConstraint(['convenio_id'], ['convenio.id'], ),
        sa.ForeignKeyConstraint(['sindicato_id'], ['sindicato.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('documentoconvenio', schema=None) as b:
        b.create_index(b.f('ix_documentoconvenio_convenio_id'), ['convenio_id'], unique=False)
        b.create_index(b.f('ix_documentoconvenio_sindicato_id'), ['sindicato_id'], unique=False)

    op.create_table('fragmentoconvenio',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('documento_id', sa.Integer(), nullable=False),
        sa.Column('convenio_id', sa.Integer(), nullable=False),
        sa.Column('sindicato_id', sa.Integer(), nullable=False),
        sa.Column('orden', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('texto', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
        sa.Column('referencia', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
        sa.Column('seccion', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
        sa.Column('tipo_fuente', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default='convenio'),
        sa.Column('notas_acta', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
        sa.Column('embedding', Vector(DIM), nullable=True),
        sa.Column('modelo_embedding', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
        sa.Column('creado', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
        sa.ForeignKeyConstraint(['documento_id'], ['documentoconvenio.id'], ),
        sa.ForeignKeyConstraint(['convenio_id'], ['convenio.id'], ),
        sa.ForeignKeyConstraint(['sindicato_id'], ['sindicato.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('fragmentoconvenio', schema=None) as b:
        b.create_index(b.f('ix_fragmentoconvenio_documento_id'), ['documento_id'], unique=False)
        b.create_index(b.f('ix_fragmentoconvenio_convenio_id'), ['convenio_id'], unique=False)
        b.create_index(b.f('ix_fragmentoconvenio_sindicato_id'), ['sindicato_id'], unique=False)

    # Índice vectorial. HNSW con distancia coseno, que es la que usa el
    # modelo. NO se crea todavía: con pocos miles de fragmentos el escaneo
    # secuencial es más rápido que el índice, y HNSW construido sobre una
    # tabla vacía hay que reconstruirlo igual. Se agrega cuando el volumen lo
    # justifique, en su propia migración.
    #   op.execute("CREATE INDEX ... USING hnsw (embedding vector_cosine_ops)")

    op.create_table('consultaconvenio',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sindicato_id', sa.Integer(), nullable=False),
        sa.Column('convenio_id', sa.Integer(), nullable=True),
        sa.Column('cuil', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
        sa.Column('pregunta', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
        sa.Column('hubo_respuesta', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('fragmentos_usados', sa.JSON(), nullable=True),
        sa.Column('creado', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
        sa.ForeignKeyConstraint(['sindicato_id'], ['sindicato.id'], ),
        sa.ForeignKeyConstraint(['convenio_id'], ['convenio.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('consultaconvenio', schema=None) as b:
        b.create_index(b.f('ix_consultaconvenio_sindicato_id'), ['sindicato_id'], unique=False)
        b.create_index(b.f('ix_consultaconvenio_convenio_id'), ['convenio_id'], unique=False)
        b.create_index(b.f('ix_consultaconvenio_cuil'), ['cuil'], unique=False)


def downgrade() -> None:
    # La extensión NO se borra: puede estar en uso por otra cosa, y dejarla
    # instalada no molesta.
    for tabla, indices in [
        ('consultaconvenio', ['cuil', 'convenio_id', 'sindicato_id']),
        ('fragmentoconvenio', ['sindicato_id', 'convenio_id', 'documento_id']),
        ('documentoconvenio', ['sindicato_id', 'convenio_id']),
        ('convenio', ['sindicato_id']),
    ]:
        with op.batch_alter_table(tabla, schema=None) as b:
            for col in indices:
                b.drop_index(b.f(f'ix_{tabla}_{col}'))
        op.drop_table(tabla)
