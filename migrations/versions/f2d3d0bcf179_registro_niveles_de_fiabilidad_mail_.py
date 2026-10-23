"""registro: niveles de fiabilidad, mail declarado, codigos de verificacion, politica por sindicato

Revision ID: f2d3d0bcf179
Revises: e28e33b0aec5
Create Date: 2026-10-11 22:14:32.229849

PLAN_REGISTRO.md, modelo de datos (§3). Cuatro cosas del mismo bloque:

1. `cuentatrabajador` y `cuentaempleador`: nivel de fiabilidad (1 a 4), qué
   lo justificó y cuándo, el mail declarado (aparte del del padrón, que
   nunca se pisa), cuándo se confirmó y la marca de clave temporal.
2. `sindicato.acepta_mail_declarado` (D5): nace en verdadero, que es lo que
   había de hecho (nadie pedía mail para registrarse).
3. Tabla `codigoverificacion`: los códigos de 6 dígitos del registro y la
   recuperación de clave, con su hash y su traza.
4. `mail_padron` (Q-6 de la QA): el mail que cargó EL SINDICATO, aparte del
   `mail` de contacto que la persona (o la empresa) edita desde su perfil.
   `cuentatrabajador.mail_padron` y `empleador.mail_padron`, con
   `server_default ''`. Backfill conservador: si la persona nunca eligió clave
   (`clave_hash = ''`) ese `mail` lo cargó el sindicato y se copia; las cuentas
   ya registradas quedan con `mail_padron` vacío (no se sabe de dónde salió su
   `mail`: pudo cambiarlo ella) y el gremio lo recarga por alta masiva. En
   `empleador` se copia cuando el CUIT no tiene `cuentaempleador` (nadie pudo
   editar ese mail todavía).
5. Backfill (D10): las cuentas YA registradas (con clave) quedan en nivel 1
   con origen "cuil_padron" (CUIL en el padrón, anterior a este plan); las de
   trabajador que además tienen al menos un recibo verificado propio suben a
   nivel 3 ("recibo_propio"; el CUIL del recibo se compara solo con sus
   dígitos de los dos lados, porque `reciboverificado.cuil` puede haberse
   guardado con guiones: Q-7). Las empresas quedan en 1: no suben recibos.
   Las filas del padrón que todavía no eligieron clave (clave_hash vacío)
   quedan sin origen: no tienen nivel que justificar.

Las columnas nuevas llevan `server_default`: las filas existentes quedan
válidas sin tocarlas una por una y el INSERT de cualquier código viejo sigue
andando.

Lo que `--autogenerate` propuso de más (borrar siete índices compuestos que el
modelo no declara pero esta cadena de migraciones sí crea) NO se aplica: no
tiene nada que ver con este bloque.
"""
from datetime import datetime
from typing import Sequence, Union
from zoneinfo import ZoneInfo

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'f2d3d0bcf179'
down_revision: Union[str, None] = 'e28e33b0aec5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CUENTAS = ('cuentatrabajador', 'cuentaempleador')


def upgrade() -> None:
    op.create_table('codigoverificacion',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tipo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('identificador', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('proposito', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('destino', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('origen_destino', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('codigo_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('creado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('vence', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('intentos', sa.Integer(), nullable=False),
    sa.Column('usado_en', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('ip', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_codigoverificacion_identificador'), 'codigoverificacion', ['identificador'], unique=False)

    for tabla in CUENTAS:
        op.add_column(tabla, sa.Column('nivel_fiabilidad', sa.Integer(), nullable=False, server_default='1'))
        op.add_column(tabla, sa.Column('nivel_origen', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''))
        op.add_column(tabla, sa.Column('nivel_actualizado', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''))
        op.add_column(tabla, sa.Column('mail_declarado', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''))
        op.add_column(tabla, sa.Column('mail_declarado_confirmado', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''))
        op.add_column(tabla, sa.Column('clave_temporal', sa.Boolean(), nullable=False, server_default=sa.false()))

    op.add_column('sindicato', sa.Column('acepta_mail_declarado', sa.Boolean(), nullable=False, server_default=sa.true()))

    # El mail que cargó el sindicato, aparte del de contacto (Q-6).
    op.add_column('cuentatrabajador', sa.Column('mail_padron', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''))
    op.add_column('empleador', sa.Column('mail_padron', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''))

    # ---- Backfill (D10) ----
    # La hora de Buenos Aires, en el formato de todo el proyecto. Se calcula acá
    # y no importando fechas.py: una migración tiene que seguir andando aunque
    # el código de la app cambie.
    ahora = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).strftime("%Y-%m-%d %H:%M")
    for tabla in CUENTAS:
        op.execute(sa.text(
            f"UPDATE {tabla} SET nivel_origen = 'cuil_padron', nivel_actualizado = :ahora "
            "WHERE clave_hash <> ''").bindparams(ahora=ahora))
    # Q-7: se comparan solo los dígitos de los dos lados (un recibo puede
    # estar guardado como '20-11111111-6'). Con IN sobre una subconsulta
    # Postgres arma una tabla hash de los CUIL de recibos y no cruza cuentas
    # por recibos.
    op.execute(sa.text(
        "UPDATE cuentatrabajador SET nivel_fiabilidad = 3, nivel_origen = 'recibo_propio', "
        "nivel_actualizado = :ahora "
        "WHERE clave_hash <> '' AND regexp_replace(cuil, '[^0-9]', '', 'g') IN ("
        "SELECT regexp_replace(r.cuil, '[^0-9]', '', 'g') FROM reciboverificado r)"
    ).bindparams(ahora=ahora))
    # Q-6: mail del padrón. Ver el docstring: solo donde se sabe que lo cargó el sindicato.
    op.execute(sa.text(
        "UPDATE cuentatrabajador SET mail_padron = mail WHERE clave_hash = ''"))
    op.execute(sa.text(
        "UPDATE empleador SET mail_padron = mail WHERE NOT EXISTS ("
        "SELECT 1 FROM cuentaempleador c WHERE c.cuit = empleador.cuit)"))


def downgrade() -> None:
    op.drop_column('empleador', 'mail_padron')
    op.drop_column('cuentatrabajador', 'mail_padron')
    op.drop_column('sindicato', 'acepta_mail_declarado')
    for tabla in CUENTAS:
        op.drop_column(tabla, 'clave_temporal')
        op.drop_column(tabla, 'mail_declarado_confirmado')
        op.drop_column(tabla, 'mail_declarado')
        op.drop_column(tabla, 'nivel_actualizado')
        op.drop_column(tabla, 'nivel_origen')
        op.drop_column(tabla, 'nivel_fiabilidad')
    op.drop_index(op.f('ix_codigoverificacion_identificador'), table_name='codigoverificacion')
    op.drop_table('codigoverificacion')
