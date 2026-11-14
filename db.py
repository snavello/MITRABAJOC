"""Capa de datos: modelos SQLModel, motor y acceso a datos.

Motor: **Postgres, siempre**. DATABASE_URL es obligatoria y sin ella la app
no arranca -- no hay fallback a SQLite (lo hubo hasta el 2026-09-11; ver
HISTORIAL.md, "Afuera SQLite"). El esquema lo administra Alembic
(`migrations/`): se aplica con `alembic upgrade head` y NUNCA con
create_all. `crear_tablas()` existe solo para que la suite arme el esquema
de su base descartable (ver conftest.py).

Acá viven todas las tablas de la plataforma, por área: sindicatos,
seccionales y administradores; trabajadores y sus cuentas; empleadores y
sus cuentas; catálogo (conceptos, fórmulas, topes de base imponible);
recibos verificados, reportes, envíos al sindicato y recibos con alerta;
noticias y beneficios; notificaciones y trámites, duplicados para
trabajador y para empresa (aislamiento explícito, no un descuido);
convenio y RAG (documentos, fragmentos con vector, consultas); consultas
del Asistente y uso de IA; suscripciones push; configuración y marca de
plataforma; recursos de la landing.

Convenciones: todo binario (logos, fotos, adjuntos, PDF) va en columnas de
bytes de la base, nunca a disco; JSON como JSONB en Postgres; cada consulta
filtra por sindicato_id (aislamiento total entre sindicatos). `init_db()`
ya NO siembra AEFIP: una base nueva queda vacía hasta `cargar_demo.py` o un
alta desde /plataforma (`cargar_seed_si_vacio()` solo a pedido explícito).
"""

import os
import re
import csv
import json
import hashlib
import hmac
import secrets
from pathlib import Path
from typing import Optional
from datetime import date, datetime, timedelta

from dotenv import load_dotenv
from typing import Any
from sqlmodel import SQLModel, Field, create_engine, Session, select, Column, JSON, text
from sqlalchemy import or_, bindparam, UniqueConstraint, Index, delete as sa_delete, event
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

# El tipo de las columnas JSON del proyecto. **En Postgres es JSONB**, que es
# lo que las migraciones vienen creando desde el principio con esta misma
# expresión.
#
# Estaba solo en las migraciones y no en los modelos, así que el esquema que
# arma `create_all` -- el de la base descartable de la SUITE -- tenía `json`
# donde producción tiene `jsonb`: quince columnas probándose contra un tipo
# distinto del que corre. Es el mismo defecto que motivó sacar SQLite el
# 2026-09-11, solo que adentro del mismo motor y por eso más difícil de ver.
# `test_migraciones.py` compara los dos esquemas para que no vuelva a pasar.
#
# `json` guarda el texto tal cual (conserva orden de claves y espacios) y no
# tiene operador de igualdad; `jsonb` es binario, normalizado, comparable e
# indexable. Para leer y escribir un dict entero dan lo mismo, que es por lo
# que la diferencia pasó desapercibida.
#
# **Toda columna JSON del proyecto usa esto**: desde la migración
# d2c8f04a6b31 no queda ninguna en `json` pelado. Una columna nueva que use
# `Column(JSON)` en vez de `Column(JSON_TIPO)` rompe esa uniformidad y
# `test_migraciones.py` la marca.
JSON_TIPO = JSON().with_variant(postgresql.JSONB(), "postgresql")

import cuit
import encuestas
import errores
import fechas
import precios_ia
# geo.py importa db DENTRO de sus funciones, no en el encabezado, así que
# esto no es un ciclo: la mitad pura de geo (armar el texto, haversine) se
# puede probar sin base, y db puede usar su contrato de campos.
import geo
from pgvector.sqlalchemy import Vector

# En Render, DATABASE_URL es una variable de entorno real (no hace falta
# .env). Localmente vive en .env -- sin este load_dotenv() acá, cualquier
# entrypoint que importe db.py ANTES de que algo más cargue el .env (ej.
# `python -m alembic`, que importa db.py directo desde migrations/env.py,
# sin pasar por main.py/auth.py) ve DATABASE_URL vacío y cae a SQLite en
# silencio -- exactamente el bug que motivó pasar el desarrollo local a
# Postgres (ver CLAUDE.md "Desarrollo local con Postgres").
load_dotenv()


# ---------- Ubicación de la base ----------
# Postgres o nada. Hasta el 2026-09-11 había un fallback a SQLite y fue peor
# el remedio: la suite entera validaba contra un motor que el proyecto no
# usa, y daba por buenos defectos que SQLite perdona y Postgres no (claves
# foráneas sin validar, sobre todo). Un fallback silencioso a otro motor es
# la clase de red que hace caer más fuerte.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError(
        "Falta DATABASE_URL: esta app corre sobre Postgres y no tiene otro "
        "motor.\n"
        "  - Desarrollo local: `docker compose up -d` y DATABASE_URL en el "
        ".env (ver .env.example).\n"
        "  - Render: la variable ya existe en el servicio.\n"
        "SQLite dejó de usarse el 2026-09-11.")

# Render entrega la URL como postgres://; SQLAlchemy/psycopg3 espera
# postgresql+psycopg://
url = DATABASE_URL
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql+psycopg://", 1)
elif url.startswith("postgresql://") and "+psycopg" not in url:
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)


def _env_entero(nombre: str, defecto: int) -> int:
    """Entero de una variable de entorno; vacía o mal escrita = el default."""
    try:
        return int(os.getenv(nombre, "").strip() or defecto)
    except ValueError:
        return defecto


# Techos del engine (cuelgue de Pruebas del 2026-09-18, ver
# docs/chat/2026-09-19-cuelgue-dashboard-conexiones.md). Sin ellos, nada tenía
# límite: un request esperaba 30 s una conexión que nunca llegaba, y una
# consulta lenta o una transacción abierta quedaban vivas en Postgres aunque
# el web service ya no existiera. Todo se puede mover por variable de entorno
# sin tocar código; 0 apaga el techo de Postgres (statement / idle).
POOL_SIZE = _env_entero("DB_POOL_SIZE", 5)
MAX_OVERFLOW = _env_entero("DB_MAX_OVERFLOW", 5)
# Segundos que un request espera una conexión libre. Corto a propósito: si el
# pool está agotado, es mejor un 503 en 5 s (main.pool_agotado) que un hilo del
# threadpool atado 30 s, que es lo que termina tumbando a TODA la app.
POOL_TIMEOUT = _env_entero("DB_POOL_TIMEOUT", 5)
# Techo de UNA consulta. La más pesada del panel (percentile_cont sobre 50.000
# recibos) tarda ~30 ms con CPU completa, así que 15 s deja más de 100 veces de
# margen incluso en la base de 0,1 vCPU.
STATEMENT_TIMEOUT_MS = _env_entero("DB_STATEMENT_TIMEOUT_MS", 15000)
# Una transacción abierta sin hacer nada retiene su conexión y sus locks.
IDLE_TX_TIMEOUT_MS = _env_entero("DB_IDLE_TX_TIMEOUT_MS", 30000)

_KEEPALIVES = {
    # TCP keepalives agresivos: sin esto, si un proxy/NAT intermedio
    # corta una conexión ociosa en silencio (sin avisarle a Postgres
    # ni a la app), el propio pool_pre_ping puede quedar COLGADO
    # hasta 15-20 min (el timeout de TCP por defecto del SO) en vez
    # de fallar rápido y reconectar -- bug conocido de SQLAlchemy +
    # psycopg contra Postgres gestionado (ver
    # github.com/sqlalchemy/sqlalchemy/discussions/13032). Con esto,
    # una conexión muerta se detecta en ~60s (30 + 10*3) en vez de
    # minutos: sospecha fundada para el "se corta a los 2-3 minutos,
    # específicamente al guardar" reportado (ver CLAUDE.md
    # "Pendientes" -- sigue sin confirmarse con un traceback real).
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 3,
}


def _opciones_postgres(**parametros) -> str:
    """El string `options` de libpq: `-c parametro=valor` por cada uno."""
    return " ".join(f"-c {k}={v}" for k, v in parametros.items())


engine = create_engine(
    url,
    pool_pre_ping=True,   # descarta conexiones muertas antes de usarlas (clave con base remota)
    pool_recycle=300,     # recicla conexiones cada 5 min (Render duerme el servicio en plan free)
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_timeout=POOL_TIMEOUT,
    connect_args={
        **_KEEPALIVES,
        "options": _opciones_postgres(
            statement_timeout=STATEMENT_TIMEOUT_MS,
            idle_in_transaction_session_timeout=IDLE_TX_TIMEOUT_MS),
    },
)


def engine_para_migraciones():
    """Engine de Alembic (migrations/env.py): una sola conexión, sin pool.

    Las migraciones no pueden llevar los techos del engine de la app: un
    ALTER COLUMN TYPE sobre una tabla grande reescribe la tabla y pasa de los
    15 s de statement_timeout, y una conversión hecha en Python deja la
    transacción "idle" más de 30 s. Al revés, sí llevan `lock_timeout`: una
    migración que espera un lock más de 5 s (porque el web service viejo está
    tocando esa tabla) tiene que fallar en el Pre-Deploy y no quedarse
    haciendo cola detrás de una consulta larga, bloqueando además a todas las
    que vengan después de ella."""
    return create_engine(
        url, poolclass=NullPool,
        connect_args={**_KEEPALIVES, "options": _opciones_postgres(
            statement_timeout=0, idle_in_transaction_session_timeout=0,
            lock_timeout=5000)})



# ---------- Modelos ----------
class Sindicato(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nombre: str
    descripcion: str = ""
    slug: str = Field(default="", index=True)   # identificador corto para URLs y logos
    # Contacto / institucional
    cuit: str = ""
    direccion: str = ""
    mail: str = ""
    telefonos: str = ""
    autoridad: str = ""
    cargo_autoridad: str = ""
    # Marca
    logo: str = ""                              # nombre/flag: no vacío = tiene logo cargado
    logo_datos: Optional[bytes] = Field(default=None)   # binario del logo (Opción B: en la base)
    logo_mime: str = ""                         # tipo MIME para servirlo (image/png, etc.)
    color_primario: str = "#152238"
    color_secundario: str = "#1a7a6b"
    color_acento: str = "#b23a2e"
    color_base: str = "#0f1b2d"  # fondo oscuro de la portada del trabajador; debe ser oscuro
    # Color "destacado" del Panel Sindical (docs/DASHBOARD.md §4.1): marca
    # EXCLUSIVAMENTE selecciones y filtros activos del dashboard ("destacado
    # = seleccionado" como regla visual absoluta). Lo edita SOLO el admin de
    # plataforma, no el del sindicato.
    color_destacado: str = "#E5188F"
    # Firma digitalizada de la autoridad, para la credencial sindical del
    # trabajador. Misma estrategia que el logo: el binario va en la base y se
    # sirve por /firma/{id}; `firma` es el flag "tiene firma cargada".
    firma: str = ""
    firma_datos: Optional[bytes] = Field(default=None)
    firma_mime: str = ""
    activo: bool = True
    # Qué módulos tiene disponibles este sindicato (ver modulos.py). Controla
    # qué tarjetas ve el trabajador y qué pestañas ve el admin del sindicato
    # -- pensado para distintos modelos comerciales, no todos adoptan todo.
    modulos_habilitados: list = Field(default=[], sa_column=Column(JSON_TIPO, nullable=False))
    # «Portada clara» del trabajador y del admin: SIN USO desde 2026-10-25
    # (auditoría R2-03). Con los dos modelos de diseño (PLAN_TEMAS.md) la
    # portada la define el modelo que elige cada persona; plataforma ya no
    # ofrece las casillas, ninguna ruta las escribe y marca_sindicato() no
    # las expone. Las columnas quedan en la base para no migrar.
    portada_clara: bool = Field(default=False)
    admin_portada_clara: bool = Field(default=False)
    # ---- Cláusula de confidencialidad (Reportes, 2026-09-24) ----
    # Los recibos que el afiliado verificó pero NO envió le llegan al
    # sindicato anonimizados (sin nombre, CUIL, legajo ni empresa) en la
    # lista de Reportes y en el explorador del Panel. Aun anonimizados, solo
    # le llegan si el sindicato aceptó por contrato la responsabilidad de
    # tratarlos como confidenciales: sin la cláusula ve solo lo enviado. Lo
    # marca SOLO plataforma, con quién y cuándo (hechos, no un tilde suelto).
    # Los números agregados del Panel cuentan todo con o sin cláusula.
    clausula_confidencialidad: bool = Field(default=False)
    clausula_aceptada_en: str = ""     # "AAAA-MM-DD HH:MM", hora de Buenos Aires
    clausula_aceptada_por: str = ""    # usuario de plataforma que la cargó
    # El contrato/convenio firmado con el sindicato: bytes en la base, mismo
    # patrón que el logo (no hay disco persistente en Render).
    contrato_datos: Optional[bytes] = Field(default=None)
    contrato_mime: str = ""
    contrato_nombre: str = ""          # nombre del archivo tal como se subió
    # ---- Política de registro (PLAN_REGISTRO.md, D5) ----
    # True (default): quien no tiene mail en el padrón puede registrarse
    # DECLARANDO uno y confirmándolo con un código. False: "solo mail del
    # padrón" -- para gremios que cargaron los mails y no quieren que nadie
    # entre con uno que se inventó. El default es True porque bloquear el
    # registro a quien no tiene mail cargado mata la adopción. Lo edita
    # plataforma, como la cláusula de confidencialidad.
    acepta_mail_declarado: bool = Field(default=True)
    # ---- Apariencia (PLAN_TEMAS.md, D3) ----
    # El modelo de diseño con el que arrancan sus afiliados y sus operadores
    # (cada persona puede cambiarlo a gusto: CuentaTrabajador/CuentaPanel.tema)
    # y la paleta: "colm3na" (la del modelo) o "sindicato" (sus colores de
    # marca). La paleta no la elige cada persona: es identidad del gremio.
    tema_afiliados: str = "laguna"
    tema_panel: str = "laguna"
    paleta_tema: str = "colm3na"
    # La foto de portada que eligió de la biblioteca de cada modelo:
    # {"laguna": id de FotoTema, "noticiero": id}. Sin elegir = la primera
    # publicada que tenga disponible.
    fotos_portada: dict = Field(default={}, sa_column=Column(JSON_TIPO, nullable=False))
    # Cuánto color muestra la foto de portada de cada modelo
    # (`fotos_tema.SATURACIONES`): {"laguna": 0, "noticiero": 50}. 0 o sin
    # elegir = la normalizada sola, como siempre; 100 = la original a todo
    # color; en el medio, la de color fundida sobre la normalizada. Vale
    # para la foto que tenga de portada; si esa foto no tiene versión en
    # color (se subió antes del 2026-10-29), se muestra normalizada.
    saturacion_fotos: dict = Field(default={}, sa_column=Column(JSON_TIPO, nullable=False))
    # Lo mismo para las fotos de Noticias y Beneficios en la portada (la
    # nota de tapa y el carrusel), por modelo: {"laguna": 0, "noticiero": 50}.
    saturacion_publicaciones: dict = Field(default={}, sa_column=Column(JSON_TIPO, nullable=False))
    # "Tu día" en la portada del afiliado (módulo opt-in `tu_dia`): qué rubros
    # rotan, cada cuánto y sus opciones. NULL = los valores por defecto de
    # tu_dia.py. Lo escribe solo `db.set_tu_dia`, que descarta lo que no está
    # en el catálogo.
    tu_dia: Optional[dict] = Field(default=None, sa_column=Column(JSON_TIPO, nullable=True))


class Seccional(SQLModel, table=True):
    """Delegación/seccional de un sindicato (ej. por zona geográfica). El
    admin las da de alta y las asigna a trabajadores en el alta/edición.

    Desde el sistema de Áreas dejó de ser un dato meramente descriptivo:
    ACOTA lo que ve un usuario de área (sus trámites y a quién puede
    notificar). Sigue sin afectar la validación de recibos ni el
    aislamiento entre sindicatos.

    `ve_todas` es la excepción a ese recorte: los usuarios de una seccional
    tildada alcanzan TODAS las seccionales del sindicato. Nace tildada en
    "Sede Central"; el Super Admin la puede tildar en otra (ej. una regional
    que supervisa varias). Ver SPRINT_AREAS.md, decisión 5.

    **El domicilio es estructurado, no un texto libre.** Hasta el 2026-09-12
    había una sola columna `direccion` con la dirección escrita a mano; se
    reemplazó por los campos separados + `direccion_texto` (el armado, para
    mostrar) + coordenadas. El texto viejo no se migró: era provisorio y
    buscar o ubicar sobre una cadena libre no se puede.

    El MISMO bloque de campos lo tiene `Trabajador`, con idénticos nombres y
    tipos, y `test_seccional_geo.py` lo verifica: si los dos domicilios de la
    app se escriben igual, se cargan igual (una sola pantalla guiada) y se
    geocodifican con la misma función."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(foreign_key="sindicato.id", index=True)
    nombre: str
    ve_todas: bool = False
    # ---- Domicilio (bloque compartido con Trabajador, ver geo.CAMPOS_DOMICILIO)
    calle: str = ""
    numero: str = ""
    piso_depto: str = ""
    localidad: str = ""
    provincia: str = ""
    codigo_postal: str = ""
    # La dirección tal como se muestra. La arma el SERVIDOR al guardar
    # (geo.armar_direccion_texto), nunca el cliente: es lo que se ve en la
    # tabla del panel, en la ficha y en la app del trabajador, y si cada
    # pantalla la compusiera a su manera habría tres direcciones distintas
    # para la misma seccional.
    direccion_texto: str = ""
    latitud: Optional[float] = Field(default=None)
    longitud: Optional[float] = Field(default=None)
    # exacta | aproximada | manual | sin_geo (geo.PRECISIONES). Nace en
    # "sin_geo" y no en "" para que el estado sea siempre legible: una
    # seccional sin ubicar es un estado válido del sistema, no un dato que
    # falta.
    precision_geo: str = "sin_geo"
    # Texto "AAAA-MM-DD HH:MM" en hora de Buenos Aires, como TODOS los sellos
    # de tiempo del proyecto (fechas.ahora_texto()). Un datetime acá sería la
    # única columna de tiempo con otro criterio.
    geo_actualizado: str = ""
    # ---- Contacto de la seccional (esto NO lo tiene Trabajador: es la
    # puerta de atención al afiliado, no el domicilio de una persona)
    telefono: str = ""
    whatsapp: str = ""
    mail: str = ""
    horario_atencion: str = ""


class Area(SQLModel, table=True):
    """Área organizativa DE UNA SECCIONAL (Secretaría Legal de Rosario,
    Tesorería de Sede Central...).

    El área dice QUÉ hace un usuario; la seccional a la que pertenece dice
    SOBRE QUIÉNES. En la primera tanda el área colgaba del sindicato y los
    dos ejes eran independientes; ahora el área vive DENTRO de una seccional
    (decisión N2 de SPRINT_AREAS_V2.md), que es lo que permite que cada
    delegación arme su propia estructura sin pisarle el nombre a otra: puede
    haber una "Legales" por seccional y son áreas distintas.

    De ahí sale la regla de coherencia que fuerzan las rutas: un usuario y
    su área tienen que ser de la MISMA seccional. Si no, "Legales de
    Rosario" con alcance Córdoba sería un usuario que nadie sabe qué ve.

    Los permisos se asignan al área (PermisoArea) y los heredan todos sus
    usuarios; el ajuste fino por persona va en PermisoUsuario.

    Un área NO se borra, se desactiva: los usuarios seguirían apuntando a un
    área inexistente, y desactivarla es además la forma de cortarle el
    acceso a todo un equipo sin tocar usuario por usuario."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(foreign_key="sindicato.id", index=True)
    seccional_id: int = Field(foreign_key="seccional.id", index=True)
    nombre: str
    activo: bool = True


class PermisoArea(SQLModel, table=True):
    """Una sección del panel habilitada para un área -- una fila por sección
    (ver permisos.py). Lo que heredan todos los usuarios del área."""
    id: Optional[int] = Field(default=None, primary_key=True)
    area_id: int = Field(foreign_key="area.id", index=True)
    seccion: str


class PermisoUsuario(SQLModel, table=True):
    """Ajuste individual sobre lo que hereda del área.

    `tipo` es "agregar" o "bloquear", y el bloqueo le gana al área Y al
    agregado (ver permisos.calcular_efectivos). Sin el bloqueo no habría
    forma de decir "es de Legales pero a él no le doy Notificaciones" sin
    inventarle un área propia."""
    id: Optional[int] = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key="usuariosindicato.id", index=True)
    seccion: str
    tipo: str = "agregar"   # agregar | bloquear


class UsuarioSindicato(SQLModel, table=True):
    """Usuario del panel de un sindicato.

    Tres clases:
    - Super Admin (`es_super_admin`), el administrador de Sede Central: todo
      el panel sobre TODAS las seccionales, incluida la gestión de áreas y
      usuarios y el alta de seccionales. Es lo que era TODO usuario antes
      del sistema de Áreas (los que ya existían quedaron con la bandera
      prendida en la migración).
    - Admin de Seccional (`es_admin_seccional`): las mismas atribuciones
      sobre SU seccional y nada más -- "el admin grande en chiquito". Arma
      las áreas de su delegación y les asigna gente sin depender de central.
      No puede crear seccionales, ni otorgar Super Admin, ni tocar nada de
      otra seccional (ver `_exigir_alcance_*` en main.py).
    - Usuario de área: ve solo las secciones que le den su área y sus
      permisos individuales, y solo sobre su alcance de seccional.

    Las dos banderas arrancan en False: un usuario que se dé de alta sin
    declarar rol nace SIN poder, no con todo. Y `es_admin_seccional` es
    opt-in por diseño -- un sindicato centralizado ni se entera del rol.

    El primer Super Admin de cada sindicato lo sigue dando de alta el admin
    de plataforma; de ahí en más los crea el propio sindicato."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(foreign_key="sindicato.id", index=True)
    usuario: str = Field(index=True)            # con lo que INICIA SESIÓN
    # CUIL de la persona, normalizado a 11 dígitos. Hoy coincide con
    # `usuario` porque el alta pide el CUIT/CUIL como nombre de usuario,
    # pero son dos cosas distintas y conviene tenerlas separadas: `usuario`
    # es con lo que entra (mañana podría ser un mail) y `cuil` es QUIÉN ES.
    # Si se guardara uno solo, habilitar el login por mail borraría la
    # identidad de la persona.
    cuil: str = Field(default="", index=True)
    # Vínculo OPCIONAL con su fila del padrón, cuando el empleado del
    # sindicato es además afiliado. Se resuelve por CUIL en el alta; queda
    # en NULL para quien trabaja en el gremio sin estar afiliado a él, que
    # es un caso real y no un error.
    trabajador_id: Optional[int] = Field(default=None, foreign_key="trabajador.id", index=True)
    nombre: str = ""
    # La clave NO vive acá (2026-10-17): vive en `CuentaPanel`, una por CUIL.
    # Estas dos columnas quedan solo como la puerta de entrada de un alta: lo
    # que traiga `clave_hash` al insertar lo mueve a la cuenta el enganche
    # `_mover_clave_a_la_cuenta` (si la persona todavía no tenía), y la fila
    # queda SIEMPRE con la clave vacía. Ver CuentaPanel.
    clave_hash: str = ""
    debe_cambiar_clave: bool = True
    activo: bool = True
    # Default False a propósito: si alguna alta se olvida de setearlo, el
    # usuario nace SIN poder, no con todo. Los tres lugares que crean Super
    # Admins de verdad (alta desde plataforma, alta desde el propio
    # sindicato, cargar_demo) lo pasan explícito.
    es_super_admin: bool = False
    es_admin_seccional: bool = False
    area_id: Optional[int] = Field(default=None, foreign_key="area.id", index=True)
    seccional_id: Optional[int] = Field(default=None, foreign_key="seccional.id", index=True)


class CuentaPanel(SQLModel, table=True):
    """**La credencial del operador**: una fila por CUIL para el panel de
    TODOS los sindicatos (2026-10-17). Es a `UsuarioSindicato` lo que
    `CuentaTrabajador` es a `Trabajador`: el usuario dice en qué sindicato
    trabaja la persona y con qué rol; la cuenta dice con qué clave entra.

    Hasta esta fecha la clave estaba en cada `UsuarioSindicato`, una por
    sindicato, y el login buscaba el CUIL en todos y probaba la clave contra
    la PRIMERA fila que encontraba: quien trabajaba en dos sindicatos solo
    podía entrar a uno, y a cuál dependía del orden de la base.

    Reglas:
    - Una persona, una clave. Entra con ella y, si trabaja en más de un
      sindicato, elige a cuál después del login (como el afiliado con
      pluriempleo).
    - La clave la fija el PRIMER sindicato que da de alta a la persona. Los
      que la suman después no la pisan: si pudieran, el admin de un gremio
      entraría al panel de otro con la clave que él mismo eligió.
    - Es una credencial aparte de la del afiliado (`CuentaTrabajador`):
      distinto rol, distinta cookie, distinto nivel de confianza.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    cuil: str = Field(index=True, unique=True)
    clave_hash: str = ""
    # La clave la puso otra persona (el alta, o un reseteo de plataforma o del
    # Super Admin del sindicato): es transitoria y `POST /admin/login` no abre
    # la sesión hasta que la persona elija la suya (2026-11-06). La bandera
    # vive ACÁ y no en `UsuarioSindicato.debe_cambiar_clave`, que solo es la
    # puerta de entrada de un alta (`_mover_clave_a_la_cuenta`): la clave es
    # una por persona y su estado también.
    debe_cambiar_clave: bool = True
    # El modelo de diseño que eligió para el panel (PLAN_TEMAS.md, D2).
    # "" = no eligió: vale el de su sindicato (Sindicato.tema_panel).
    tema: str = ""
    # Ingreso con Google al panel (google_auth.py). El mail es de la PERSONA, como
    # la clave: lo carga quien da el alta (solo si la cuenta no tenía uno) o la
    # propia persona en «Tu cuenta», y Google lo verifica. `google_sub` es la
    # cuenta de Google con que ingresó la primera vez; restablecer la clave lo
    # borra. Vacíos = sin mail / nunca ingresó con Google.
    mail: str = Field(default="", index=True)
    google_sub: str = Field(default="", index=True)


@event.listens_for(UsuarioSindicato, "before_insert")
def _mover_clave_a_la_cuenta(mapper, connection, target):
    """La clave que trae un alta va a la CUENTA de la persona, nunca a la fila.

    Vive en el modelo y no en las rutas a propósito: hay cinco lugares que
    dan de alta usuarios del panel (el panel del sindicato, plataforma,
    `cargar_demo`, `cargar_bancaria` y los robots) y todos escriben
    `clave_hash` en la fila. Con esto ninguno puede crear una segunda clave
    para el mismo CUIL, ni pisar la que la persona ya tiene: si la cuenta
    existe, la clave del alta se descarta. La fila queda siempre vacía."""
    # El login siempre fue el CUIL: si la fila no trae `cuil` y el usuario
    # es uno, se toma de ahí. Un login que no es un CUIL no se copia (no
    # puede entrar: el login normaliza a dígitos) y no tiene cuenta.
    if not target.cuil and (target.usuario or "").isdigit() and len(target.usuario) == 11:
        target.cuil = target.usuario
    if target.clave_hash and target.cuil:
        tabla = CuentaPanel.__table__
        existe = connection.execute(
            select(tabla.c.id).where(tabla.c.cuil == target.cuil)).first()
        if not existe:
            connection.execute(postgresql.insert(tabla).values(
                cuil=target.cuil, clave_hash=target.clave_hash,
                debe_cambiar_clave=bool(target.debe_cambiar_clave),
            ).on_conflict_do_nothing(index_elements=["cuil"]))
    target.clave_hash = ""


class UsuarioPlataforma(SQLModel, table=True):
    """Usuario NOMINAL del panel de plataforma (SPRINT_R1.md). Reemplaza a la
    cuenta compartida por variable de entorno (XSK H-0002/H-0016). La misma
    credencial entra a /plataforma y a /entornos.

    - `usuario` es la llave de login (texto, p. ej. "snavello"), no el CUIT.
      El CUIL es un dato del perfil (obligatorio, pero no la llave).
    - `rol`: "superadmin" (gestiona usuarios, con log) o "admin".
    - Primer ingreso forzado: mientras `debe_cambiar_clave` o
      `debe_completar_datos` estén en True, la persona solo ve la pantalla de
      completar la cuenta. La clave inicial es transitoria; `clave_vence`
      (texto AAAA-MM-DD HH:MM, hora de Buenos Aires) la caduca a los 7 días
      para los usuarios que crea un superadmin. Las dos semillas iniciales
      van con `clave_vence=None`: valen hasta que la persona entre."""
    id: Optional[int] = Field(default=None, primary_key=True)
    usuario: str = Field(index=True)            # con lo que INICIA SESIÓN
    nombre: str = ""
    clave_hash: str = ""
    rol: str = "admin"                          # "superadmin" | "admin"
    activo: bool = True
    debe_cambiar_clave: bool = True             # la primera clave es transitoria
    clave_vence: Optional[str] = None           # AAAA-MM-DD HH:MM (BA) o None = no vence
    debe_completar_datos: bool = True
    # Datos obligatorios que la persona carga en el primer ingreso.
    cuil: str = Field(default="", index=True)
    dni: str = ""
    email: str = Field(default="", index=True)
    direccion: str = ""
    telefono: str = ""
    creado_en: str = ""                         # AAAA-MM-DD HH:MM (BA)
    creado_por: str = ""                        # usuario del superadmin, o "semilla"
    # El modelo de diseño que eligió para el panel de plataforma (PLAN_TEMAS.md,
    # D2). "" = no eligió: vale el por defecto (laguna). Plataforma no tiene
    # sindicato, así que no hay un default intermedio ni paleta propia.
    tema: str = ""


class LogPlataforma(SQLModel, table=True):
    """Bitácora de acciones del panel de plataforma (SPRINT_R1.md, XSK
    H-0016): el "quién tocó qué" que la cuenta compartida no dejaba. Guarda
    login y la gestión de usuarios (alta/edición/desactivación/reseteo)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    cuando: str = Field(default="", index=True)  # AAAA-MM-DD HH:MM (BA)
    accion: str = ""                             # login | alta | edicion | desactivacion | reseteo | ...
    usuario: str = Field(default="", index=True)  # QUIÉN hizo la acción
    objetivo: str = ""                           # sobre qué usuario recae (si aplica)
    ip: str = ""
    detalle: str = ""


class CambioIdentificador(SQLModel, table=True):
    """Traza de la regularización de un CUIL/CUIT (PLAN_CUIT_MOD11.md, D5):
    una fila por número que `regularizar_cuit.py aplicar --si` convirtió.

    Existe porque la HISTORIA no se reescribe: las bitácoras (`logplataforma`,
    `tramitelog`, ...), los textos libres y los archivos siguen diciendo el
    número que tenían. Una entrada vieja de la bitácora con el número anterior
    se sigue hasta la persona o la empresa buscándolo acá. Se guardan hechos,
    no derivados: el número anterior y el nuevo, quién lo decidió y cuántas
    filas de cada tabla se tocaron.

    Los números van como DÍGITOS (11, sin guiones) aunque en alguna columna
    estuvieran con guiones: es lo que se compara. `detalle` es el conteo de
    filas por `tabla.columna`. Es de solo agregar: nada de la app la lee ni la
    modifica, solo la herramienta la escribe."""
    id: Optional[int] = Field(default=None, primary_key=True)
    anterior: str = Field(index=True)
    nuevo: str = Field(index=True)
    tipo: str = ""                 # "persona" | "empresa"
    origen: str = ""               # "manual" | "demo" | "lote" | ...
    entorno: str = ""              # local | pruebas | demo | prod
    fecha: str = ""                # "AAAA-MM-DD HH:MM", hora de Buenos Aires
    quien: str = ""                # quien corrió la herramienta
    filas: int = 0                 # total de filas tocadas
    detalle: dict = Field(default={}, sa_column=Column(JSON_TIPO, nullable=False))


class CuentaTrabajador(SQLModel, table=True):
    """**La PERSONA**: una fila por CUIL en toda la plataforma, y la única
    dueña de sus datos personales -- nombre, domicilio, teléfono, mail y
    foto.

    Hasta el 2026-09-22 esto era solo "CUIL + clave" y los datos personales
    vivían en `Trabajador`, que es una fila POR SINDICATO. Una persona en dos
    gremios tenía entonces dos copias de su nombre y su domicilio, y las
    cuatro puertas por las que entra un domicilio no escribían igual: el
    registro lo copiaba a TODOS los empadronamientos y el perfil solo al del
    sindicato activo. El resultado, encontrado en Pruebas, era el mismo CUIL
    con dos nombres y dos direcciones distintas, y nada que dijera cuál era
    la buena. Una persona vive en un solo lugar: ahora hay un solo renglón
    donde eso se escribe (decisión de Sd, 2026-09-22).

    **La fila existe desde que el CUIL entra al PADRÓN, no desde que se
    registra.** Es lo que hace que "un solo lugar" sea cierto también para
    los afiliados que el sindicato cargó y que todavía no crearon su cuenta
    -- si no, el alta del admin necesitaría un segundo lugar donde escribir y
    volveríamos al problema. Por eso `clave_hash` puede estar vacío: vacío
    significa "todavía no eligió clave", no "no existe". Quien decide si una
    persona ya se registró sigue siendo `Trabajador.registrado`, que es por
    sindicato y alimenta el KPI del panel.

    **Los TRES mails** (PLAN_REGISTRO.md, Q-6). Parecen uno y no lo son:

    1. `mail` es el mail de CONTACTO de la persona. Lo escribe ella desde
       `/api/perfil` y el admin desde el alta; es un dato personal como el
       teléfono y se puede cambiar cuando quiera. NO prueba nada.
    2. `mail_padron` es el mail que cargó EL SINDICATO (alta individual y
       alta masiva del panel, nunca el perfil ni el registro). Que lo haya
       puesto un tercero con acceso al padrón es lo que lo hace una prueba:
       un código mandado ahí llega a quien el gremio conoce, no a quien
       llegó primero con un CUIL público.
    3. `mail_declarado` es el que dio la persona al registrarse, sin que el
       sindicato lo conozca, y vale recién cuando `mail_declarado_confirmado`
       tiene fecha (confirmó un código ahí).

    Por eso los códigos de verificación solo van al 2.º o al 3.º confirmado:
    si fueran al 1.º, quien se registra primero (el impostor) lo cambia desde
    el perfil y recibe en su casilla el código para recuperar la cuenta de
    otro. `mail_padron_de` lee el 2.º y nada más.

    El domicilio usa el MISMO bloque de campos que `Seccional` (ver
    `geo.CAMPOS_DOMICILIO`), con la misma carga guiada y la misma función de
    guardado; `test_seccional_geo.py` verifica que las dos tablas no se
    separen. Las coordenadas son dato sensible del padrón: no salen nunca en
    un endpoint que no sea del propio afiliado o del padrón de su sindicato,
    y en particular NO van al Panel Sindical."""
    id: Optional[int] = Field(default=None, primary_key=True)
    cuil: str = Field(index=True, unique=True)
    clave_hash: str = ""                   # "" = está en el padrón pero todavía no eligió clave
    nombre: str = ""
    # ---- Domicilio (bloque compartido con Seccional, ver geo.CAMPOS_DOMICILIO)
    calle: str = ""
    numero: str = ""
    piso_depto: str = ""
    localidad: str = ""
    provincia: str = ""
    codigo_postal: str = ""
    direccion_texto: str = ""
    latitud: Optional[float] = Field(default=None)
    longitud: Optional[float] = Field(default=None)
    precision_geo: str = "sin_geo"
    geo_actualizado: str = ""
    # ---- Contacto
    telefono: str = ""
    mail: str = ""                         # CONTACTO: lo escribe la persona (ver "Los TRES mails")
    # El mail que cargó EL SINDICATO (alta individual y masiva). Solo
    # `guardar_datos_personales(mail_padron=...)` desde esas dos rutas lo
    # escribe; ni el perfil ni el registro. Es al que van los códigos.
    mail_padron: str = ""
    # ---- Fecha de nacimiento (PLAN_LISTAS_VALIDACIONES.md, D4): de la
    # PERSONA, la carga el afiliado en el registro o el perfil y el sindicato
    # en Trabajadores. Texto ISO "AAAA-MM-DD" como todas las fechas del
    # proyecto; NULL = no se cargó. Hechos, no derivados: la edad se calcula
    # donde se necesita (una validación de trámite), nunca se guarda.
    fecha_nacimiento: Optional[str] = Field(default=None)
    # ---- Foto de perfil (bytes en la base, mismo patrón que el logo del sindicato)
    foto_datos: Optional[bytes] = Field(default=None)
    foto_mime: str = ""
    # El modelo de diseño que eligió para la app (PLAN_TEMAS.md, D2). Vive en
    # la cuenta y no en el navegador para que se respete en cualquier aparato.
    # "" = no eligió: vale el de su sindicato (Sindicato.tema_afiliados).
    tema: str = ""
    # El año en que ya vio el saludo de cumpleaños de "Tu día" ("2026"): se
    # muestra una sola vez, ocho segundos, el día de su cumpleaños.
    cumple_visto: str = ""
    # ---- Registro confirmado y niveles de fiabilidad (PLAN_REGISTRO.md) ----
    # Nivel 1 a 4 (R2). SUBE y no baja: `subir_nivel` es la única escritura.
    nivel_fiabilidad: int = Field(default=1)
    # Qué justificó el nivel actual: cuil_padron | mail_padron |
    # mail_declarado | recibo_propio | presencial (ver ORIGENES_NIVEL).
    nivel_origen: str = ""
    nivel_actualizado: str = ""            # "AAAA-MM-DD HH:MM", hora de Buenos Aires
    # El mail que dio la persona al registrarse. NUNCA pisa `mail_padron` (el
    # que cargó el sindicato): si quien se registra es un impostor, el mail
    # de la persona real tiene que quedar intacto.
    mail_declarado: str = ""
    mail_declarado_confirmado: str = ""    # cuándo se confirmó con un código; vacío = no
    # Ingreso con Google (google_auth.py): el `sub` de la cuenta de Google con
    # que se ingresó la primera vez, para que las próximas veces la cuenta se
    # reconozca por él aunque el mail cambie. "" = nunca ingresó con Google.
    # Google solo identifica: no crea cuentas ni reemplaza la clave.
    google_sub: str = Field(default="", index=True)
    # La puso el admin del sindicato al restablecer la clave: el primer
    # ingreso obliga a cambiarla.
    clave_temporal: bool = Field(default=False)


class Trabajador(SQLModel, table=True):
    """Empadronamiento de un CUIL en un sindicato: el VÍNCULO con ese gremio.
    El mismo CUIL puede tener varias filas (una por sindicato donde está
    afiliado).

    **Acá NO viven los datos personales.** El nombre, el domicilio, el
    teléfono y el mail son de la PERSONA y viven en `CuentaTrabajador`, una
    sola fila por CUIL (ver su docstring: hasta el 2026-09-22 estaban acá y
    una persona en dos gremios terminaba con dos nombres y dos direcciones
    distintas). Lo que queda acá es lo que de verdad cambia de un sindicato
    a otro: a qué seccional pertenece, qué credencial le dieron, con qué
    empleador figura, si está activo y si ya se registró.

    Una consulta que necesite el nombre o la zona de un afiliado hace JOIN
    con `cuentatrabajador` por CUIL; no hay copia local que se pueda quedar
    vieja."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(foreign_key="sindicato.id", index=True)
    cuil: str = Field(index=True)          # obligatorio
    # Estado
    registrado: bool = False               # True cuando el CUIL ya eligió su clave
    activo: bool = True                    # baja lógica: False = dado de baja (recuperable)
    # Token opaco para el QR de la credencial (/v/{token}). Optional/NULL para
    # las filas ya cargadas: se genera solo, la primera vez que hace falta
    # (ver db.token_credencial), así no hace falta una migración de datos.
    token: Optional[str] = Field(default=None, unique=True, index=True)
    # Código de credencial VISIBLE (distinto del token): lo genera a mano el
    # admin del sindicato con el botón "Generar credencial", no se inventa
    # solo. NULL hasta que se genera. Formato: 5 letras del sindicato + 8
    # alfanuméricos al azar (ver db.generar_codigo_credencial).
    codigo_credencial: Optional[str] = Field(default=None, unique=True, index=True)
    # Vigencia de la credencial, la carga el admin en el alta o la edición
    # del trabajador. Fecha como string "AAAA-MM-DD" (formato de <input
    # type=date>), igual que se recibe del formulario.
    vigencia_credencial: Optional[str] = Field(default=None)
    # Fecha de afiliación a ESTE sindicato (PLAN_LISTAS_VALIDACIONES.md, D4):
    # es del empadronamiento, no de la persona (una misma persona se afilió a
    # cada gremio en una fecha distinta), y la carga solo el sindicato (alta,
    # edición y carga masiva). ISO "AAAA-MM-DD"; NULL = no se cargó. La
    # antigüedad se calcula en la validación que la necesite, no se guarda.
    fecha_afiliacion: Optional[str] = Field(default=None)
    # Seccional del sindicato a la que pertenece (opcional -- no todos los
    # sindicatos cargan seccionales, y un trabajador puede quedar sin asignar).
    seccional_id: Optional[int] = Field(default=None, foreign_key="seccional.id", index=True)
    # Marca de EMPLEADO DEL SINDICATO: este afiliado además trabaja en el
    # gremio y opera el panel (decisión N1 de SPRINT_AREAS_V2.md). No la
    # pone el admin a mano: se prende sola cuando se le da de alta un
    # usuario del panel con este mismo CUIL, y se apaga cuando ese usuario
    # deja de existir. Guardarla acá y no deducirla en cada consulta es lo
    # que permite filtrar el padrón por "empleados" sin un JOIN en cada
    # pantalla -- y lo que hace que la marca siga estando aunque mañana el
    # vínculo se rompa por una baja.
    es_empleado_sindicato: bool = False
    # CUIT del empleador (opcional, lo carga el admin en el alta/edición
    # manual -- NO está en el alta masiva, mismo criterio que seccional_id).
    # Permite dirigir una Notificacion "por empresa" (ver Notificacion).
    cuit_empleador: Optional[str] = Field(default=None, index=True)
    # Último semáforo de ARCA calculado (POST /api/aportes) -- antes se
    # perdía apenas se navegaba o se recargaba la página, porque nunca se
    # guardaba. Es el mismo dict que devuelve semaforo.calcular_semaforo().
    semaforo_datos: dict = Field(default={}, sa_column=Column(JSON_TIPO))
    semaforo_actualizado: Optional[str] = Field(default=None)  # fecha ISO del último cálculo


class CuentaEmpleador(SQLModel, table=True):
    """La identidad única del empleador en toda la plataforma: CUIT + clave.
    Mismo patrón que CuentaTrabajador -- con esto entra sin importar en
    cuántos sindicatos esté dado de alta como Empleador ("multisindicato").
    La foto de perfil vive acá (no en Empleador, que es por sindicato) --
    una sola por CUIT, se ve igual sin importar el sindicato activo, mismo
    patrón que CuentaTrabajador.foto_datos."""
    id: Optional[int] = Field(default=None, primary_key=True)
    cuit: str = Field(index=True, unique=True)
    clave_hash: str = ""
    foto_datos: Optional[bytes] = Field(default=None)
    foto_mime: str = ""
    # ---- Registro confirmado y niveles de fiabilidad (PLAN_REGISTRO.md) ----
    # Nivel 1 a 4 (R2), mismo criterio que CuentaTrabajador. SUBE y no baja: `subir_nivel` es la única escritura.
    nivel_fiabilidad: int = Field(default=1)
    # Qué justificó el nivel actual: cuil_padron | mail_padron |
    # mail_declarado | recibo_propio | presencial (ver ORIGENES_NIVEL).
    nivel_origen: str = ""
    nivel_actualizado: str = ""            # "AAAA-MM-DD HH:MM", hora de Buenos Aires
    # El mail que dio la persona al registrarse. NUNCA pisa
    # `Empleador.mail_padron` (el que cargó el sindicato): si quien se registra
    # es un impostor, el mail de la empresa real tiene que quedar intacto.
    mail_declarado: str = ""
    mail_declarado_confirmado: str = ""    # cuándo se confirmó con un código; vacío = no
    # Ingreso con Google (google_auth.py): el `sub` de la cuenta de Google con
    # que se ingresó la primera vez, para que las próximas veces la cuenta se
    # reconozca por él aunque el mail cambie. "" = nunca ingresó con Google.
    # Google solo identifica: no crea cuentas ni reemplaza la clave.
    google_sub: str = Field(default="", index=True)
    # La puso el admin del sindicato al restablecer la clave: el primer
    # ingreso obliga a cambiarla.
    clave_temporal: bool = Field(default=False)
    # El modelo de diseño que eligió para su app (PLAN_TEMAS.md, D2), como el
    # afiliado: vive en la cuenta y no en el navegador. "" = no eligió: vale
    # el que el sindicato eligió para sus afiliados (Sindicato.tema_afiliados).
    tema: str = ""


class Empleador(SQLModel, table=True):
    """Alta de un CUIT como empleador en un sindicato -- el CRUD real que
    administra el admin del sindicato (a mano, o precargado desde
    Concepto.cuit_empleador, ver importar_cuits_de_conceptos). Mismo
    patrón que Trabajador: un mismo CUIT puede tener varias filas (una
    por sindicato donde está dado de alta)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(foreign_key="sindicato.id", index=True)
    cuit: str = Field(index=True)          # obligatorio
    razon_social: str = ""
    domicilio: str = ""
    telefono: str = ""
    provincia: str = ""
    mail: str = ""                         # CONTACTO: lo edita la empresa desde su perfil
    # El mail que cargó EL SINDICATO (solo `POST /admin/empleador`). Es al que
    # van los códigos; `actualizar_perfil_empleador` NO lo toca. Por sindicato,
    # como `mail` (el empleador no está unificado). Mismo criterio que
    # `CuentaTrabajador.mail_padron`.
    mail_padron: str = ""
    registrado: bool = False               # True cuando el CUIT ya creó su CuentaEmpleador
    activo: bool = True                    # baja lógica: False = dado de baja (recuperable)


# ---- Registro confirmado por mail (PLAN_REGISTRO.md) ----
CODIGO_VIGENCIA_MINUTOS = 15      # D2: cuánto vive un código
CODIGO_MAX_INTENTOS = 5           # D2: intentos erróneos antes de quedar agotado
CODIGOS_POR_HORA = 3              # D2: cupo por persona y propósito, para no bombardear un mail
CODIGOS_POR_HORA_DESTINO = 5       # QA-REG-03: cupo por MAIL de destino, sea de quien sea el CUIL
# Niveles de fiabilidad de una cuenta (R2). Sube y no baja.
NIVELES_FIABILIDAD = {1: "CUIL en el padrón", 2: "mail confirmado",
                      3: "recibo propio verificado", 4: "confirmado por el sindicato"}
# Qué nivel acredita cada origen (columna `nivel_origen` de las cuentas).
ORIGENES_NIVEL = {"cuil_padron": 1, "mail_padron": 2, "mail_declarado": 2,
                  "recibo_propio": 3, "presencial": 4}


class CodigoVerificacion(SQLModel, table=True):
    """Un código de 6 dígitos mandado por mail para confirmar un registro o
    recuperar una clave (PLAN_REGISTRO.md, D2 y D6).

    Existe porque el CUIL/CUIT es dato público: quien llega primero con el
    número de un afiliado se queda con su cuenta (H-0017). Con el código, la
    cuenta solo nace para quien controla el mail -- el que cargó el sindicato
    en el padrón (`origen_destino = "padron"`) o uno que la persona declaró y
    confirmó (`"declarado"`).

    **Se guarda el hash, nunca el código**: HMAC-SHA256 con el secreto del
    servidor (`auth.SECRETO`) sobre `codigo:identificador:creado`. Seis
    dígitos son un millón de combinaciones; con un sha256 simple, quien leyera
    la base las probaba todas en segundos, porque el resto de los datos está
    en la misma fila. Con la clave del servidor el hash no sirve fuera de él.
    Lo que frena la fuerza bruta DENTRO de la app son los 5 intentos y los 15
    minutos de vigencia (`CODIGO_MAX_INTENTOS`, `CODIGO_VIGENCIA_MINUTOS`). Hay un solo código
    vivo por persona y propósito: pedir otro vence el anterior.

    **Un código usado o vencido NO se borra**: es la traza de quién pidió qué
    y a qué mail (mismo criterio que `CambioIdentificador`). Sirve para
    contar cuántos pidió una persona en la última hora y poner el cupo
    (`CODIGOS_POR_HORA`), para que el registro no se use para bombardear el
    mail de un afiliado.

    `identificador` es un CUIL o un CUIT según `tipo`; entra al inventario de
    `regularizar_cuit.py`. Los sellos de tiempo son texto "AAAA-MM-DD HH:MM"
    en hora de Buenos Aires, como todo el proyecto."""
    id: Optional[int] = Field(default=None, primary_key=True)
    tipo: str = ""                       # "trabajador" | "empleador"
    identificador: str = Field(default="", index=True)   # CUIL o CUIT
    proposito: str = ""                  # "registro" | "recuperacion"
    destino: str = ""                    # el mail al que se mandó
    origen_destino: str = ""             # "padron" | "declarado"
    codigo_hash: str = ""
    creado: str = ""
    vence: str = ""
    intentos: int = 0
    usado_en: str = ""                   # vacío = no se usó
    ip: str = ""


class Concepto(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(default=1, foreign_key="sindicato.id", index=True)
    codigo: str = Field(index=True)
    nombre: str
    tipo: str                      # "ingreso" | "descuento"
    remunerativo: bool = True
    alias: list = Field(default=[], sa_column=Column(JSON_TIPO))
    pendiente_revision: bool = False
    # Ley 27.802 / Dto 407/2026: categoría sindical de un descuento.
    # "convenio"   = cuota solidaria / fondos convencionales -> cuenta para el tope
    #                global del 2% (art. 133).
    # "afiliacion" = cuota de afiliación -> NO cuenta para el tope, pero SÍ se
    #                reporta al sindicato al enviar el recibo (art. 21 bis).
    # ""           = no aplica (cualquier otro descuento).
    categoria_sindical: str = ""
    # Escalado a muchos empleadores por sindicato: un concepto puede ser
    # específico de un empleador (código tal cual lo trae SU recibo, sin
    # normalizar) o genérico (NULL = como hasta ahora, visible para cualquier
    # recibo del sindicato). El matching en validador.py prioriza el concepto
    # específico del CUIT del recibo y cae al genérico si no hay uno.
    cuit_empleador: Optional[str] = Field(default=None, index=True)
    # Para un concepto específico de un empleador: el código del concepto
    # genérico que realmente controla la Formula (Formula.target siempre
    # apunta a un código genérico). NULL = el propio `codigo` ya es el
    # genérico (caso de hoy, sin cambios). Ver indexar_conceptos().
    codigo_generico: Optional[str] = Field(default=None)


class Formula(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(default=1, foreign_key="sindicato.id", index=True)
    target: str                    # código del concepto que controla
    descripcion: str
    expr: str                      # ej: "0.015 * base_remunerativa"
    tolerancia: float = 1.0
    activa: bool = True
    # Vigencia por período del recibo (recibo["periodo"] = "AAAA-MM"). Un
    # recibo viejo se valida con la fórmula que regía en SU período, no con la
    # fórmula actual. NULL en ambas = sin límite de ese lado (una fórmula
    # cargada sin fechas sigue vigente siempre, como antes de este cambio).
    # fecha_hasta NULL = todavía vigente (sin fecha de baja). No puede haber
    # dos fórmulas del mismo target con rangos de vigencia superpuestos — se
    # valida en el alta/edición (ver validador.rangos_se_superponen).
    fecha_desde: Optional[str] = Field(default=None)
    fecha_hasta: Optional[str] = Field(default=None)
    # Base imponible de la seguridad social (art. 9 Ley 24.241): si está en
    # True, el motor de validación (validador.tope_vigente_en) recorta la
    # base_remunerativa al tope máximo y la eleva al piso mínimo vigentes en
    # el período del recibo antes de evaluar esta fórmula. Por defecto True
    # solo en jubilación/INSSJP/obra social (ver crear_conceptos_universales);
    # el admin del sindicato lo puede cambiar libremente.
    sujeto_a_tope: bool = False


class TopeBaseImponible(SQLModel, table=True):
    """Tope máximo y piso mínimo de la base imponible de la seguridad
    social, por vigencia mensual (art. 9 Ley 24.241, actualizado todos los
    meses por IPC/movilidad desde el Decreto 274/2024). Tabla NACIONAL, sin
    sindicato_id -- un solo valor rige para todos los sindicatos, se
    administra desde /plataforma. No tiene fecha_hasta: cada fila rige
    hasta que empieza la siguiente (ver validador.tope_vigente_en)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    vigencia_desde: str = Field(index=True)   # "AAAA-MM", único
    tope_maximo: float
    base_minima: float
    # Cuánto se puede confiar en este valor: "verificado" (contrastado
    # contra resolución oficial), "derivado" (calculado por movilidad, con
    # control cruzado), "por_verificar" (cargado sin contrastar) o
    # "SOSPECHOSO" (inconsistente con valores verificados -- se muestra
    # igual pero el validador avisa que el resultado puede no ser confiable).
    estado: str = "por_verificar"
    fuente: str = ""


class Noticia(SQLModel, table=True):
    """Novedad del sindicato para sus trabajadores (portada + pestaña
    Novedades). Vigente cuando fecha_desde <= hoy <= fecha_hasta -- a
    diferencia de la vigencia de Formula, acá las dos fechas son obligatorias
    (es un período cerrado, no una entrada en vigencia indefinida)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(foreign_key="sindicato.id", index=True)
    titulo: str
    bajada: str = ""
    texto_completo: str = ""
    fecha_desde: str  # AAAA-MM-DD
    fecha_hasta: str  # AAAA-MM-DD
    creada: str = ""  # fecha y hora de alta ("AAAA-MM-DD HH:MM"), para ordenar y mostrar
    # «On top»: mientras esté vigente va primera, antes que las más nuevas
    # (ver noticias_vigentes). Varias marcadas: entre ellas, más nueva primero.
    on_top: bool = False
    # Hasta 2 imágenes, mismo patrón que el logo del sindicato (bytes en la
    # base, Opción B -- ver Sindicato.logo_datos).
    imagen1_datos: Optional[bytes] = Field(default=None)
    imagen1_mime: str = ""
    imagen2_datos: Optional[bytes] = Field(default=None)
    imagen2_mime: str = ""
    # La versión NORMALIZADA de cada imagen (gris, niveles y brillo parejos,
    # webp; `fotos_tema.normalizar_imagen`), para que el sindicato elija
    # cuánto color mostrar (`Sindicato.saturacion_publicaciones`,
    # 2026-10-29). Se calcula al subir y, en las de antes, la primera vez
    # que se pide (`db.imagen_normalizada`). NULL = todavía no se calculó.
    imagen1_norm: Optional[bytes] = Field(default=None)
    imagen2_norm: Optional[bytes] = Field(default=None)
    # Formulario "para iniciar" (TipoTramite) asociado: el trabajador ve un
    # ícono que abre ese formulario ("completá los datos haciendo click
    # acá" lo escribe el admin en el texto). Int SIN FK, mismo criterio que
    # NotaTramite.formulario_id: un tipo borrado/inactivo esconde el ícono.
    formulario_id: Optional[int] = None
    # Encuesta asociada: la noticia que anuncia una encuesta lleva el botón
    # para responderla. Int SIN FK, mismo criterio que formulario_id.
    encuesta_id: Optional[int] = None
    # Destino: lista de Seccional.id a la(s) que se dirige. Lista vacía (el
    # default) = todas las seccionales, incluidos los trabajadores sin
    # seccional asignada.
    destino_seccionales: list = Field(default=[], sa_column=Column(JSON_TIPO, nullable=False))


class Beneficio(SQLModel, table=True):
    """Descuento/beneficio del sindicato para sus afiliados, mostrado como
    carrusel en la portada. Mismo patrón de vigencia cerrada que Noticia
    (fecha_desde/fecha_hasta obligatorias). A diferencia de Noticia, tiene
    una sola imagen (es la que se expone en el carrusel) y un `rubro` corto
    (categoría/título breve que se superpone a la imagen)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(foreign_key="sindicato.id", index=True)
    rubro: str
    descripcion: str = ""
    link: str = ""
    fecha_desde: str  # AAAA-MM-DD
    fecha_hasta: str  # AAAA-MM-DD
    creada: str = ""  # fecha y hora de alta ("AAAA-MM-DD HH:MM")
    imagen_datos: Optional[bytes] = Field(default=None)
    imagen_mime: str = ""
    # La versión normalizada (como en Noticia.imagen1_norm).
    imagen_norm: Optional[bytes] = Field(default=None)
    formulario_id: Optional[int] = None  # mismo criterio que Noticia.formulario_id
    # Destino: lista de Seccional.id a la(s) que se dirige. Lista vacía (el
    # default) = todas las seccionales, mismo criterio que Noticia.
    destino_seccionales: list = Field(default=[], sa_column=Column(JSON_TIPO, nullable=False))


class Reporte(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(default=1, foreign_key="sindicato.id", index=True)
    fecha: str
    cuil: str = ""
    periodo: str = ""
    estado: str = "nuevo"          # "nuevo" | "en_revision" | "resuelto"
    detalle: dict = Field(default={}, sa_column=Column(JSON_TIPO))


class UsoIA(SQLModel, table=True):
    """Consumo de la API de Anthropic, una fila por llamada -- sindicato_id
    NULL cuando no se puede resolver (no debería pasar en los puntos donde se
    registra hoy, pero no se descarta la fila por eso). Mide el costo real por
    sindicato y por tipo de llamada en el panel de plataforma."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: Optional[int] = Field(default=None, foreign_key="sindicato.id", index=True)
    cuil: str = ""  # vacío en "aprendizaje", "prueba" y "herramienta": no son de un trabajador puntual
    tipo: str = ""  # "recibo" | "aportes" | "aprendizaje" | "prueba" | "herramienta"
    modelo: str = ""
    tokens_entrada: int = 0
    tokens_salida: int = 0
    fecha: str = ""  # "AAAA-MM-DD HH:MM"
    # Cuánto tardó la llamada a la API, medida alrededor del pedido y no del
    # request entero: es el número que cambia al probar otro modelo.
    duracion_ms: int = 0
    # Los dólares por millón de tokens que regían en ESE momento. Se guarda el
    # precio y no el costo ya multiplicado, por lo mismo que se guarda la fecha
    # de afiliación y no la antigüedad: el precio es el hecho, el costo se
    # deriva (precios_ia.py). Así cambiar la lista de precios no reescribe el
    # gasto de los meses anteriores.
    # 0 en todo lo anterior a esta columna: esas filas muestran el costo
    # estimado con los precios de hoy, y la pantalla lo dice.
    precio_entrada: float = 0.0
    precio_salida: float = 0.0
    # Caché de prompt (EXTRACTOR_CACHE=1). `tokens_entrada` es lo que la API
    # llama input_tokens y NO incluye estos dos: la entrada total de la
    # llamada es entrada + cache_lectura + cache_escritura. 0 en todo lo
    # anterior y en lo que corre sin caché (la pantalla lo lee como «—»).
    tokens_cache_lectura: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    tokens_cache_escritura: int = Field(default=0, sa_column_kwargs={"server_default": "0"})


class FotoTema(SQLModel, table=True):
    """Una foto de la biblioteca de un modelo de diseño (PLAN_TEMAS.md, D5).

    La carga plataforma (biblioteca global) o el Super Admin del sindicato
    (fotos propias, ver `sindicato_id`) y se guarda en dos versiones del mismo tamaño
    (`fotos_tema.normalizar`): `datos` es la NORMALIZADA (gris, niveles y
    brillo parejos, webp), a la que el modelo le pone el color al mostrarla;
    `datos_color` es la ORIGINAL en color (solo orientada y acotada), que el
    sindicato puede fundir encima según `Sindicato.saturacion_fotos`. NULL
    en `datos_color` = foto subida antes del 2026-10-29, solo en gris, hasta
    que plataforma la vuelva a subir. Bytes en la base, como el logo.
    `foco_x`/`foco_y` (0 a 1) es el punto de interés: el recorte de cada
    pantalla se centra ahí. Un borrador no lo ve ningún sindicato;
    publicada, la ven todos o solo los de `sindicatos`.

    `sindicato_id` (2026-11-06, pedido de SDN): NULL = foto de la biblioteca
    GLOBAL de plataforma (todas las de antes); con valor = foto PROPIA de ese
    sindicato, que solo él lista, edita, borra y puede elegir de portada. La
    sube el Super Admin en Apariencia y está disponible desde el primer
    momento: se guarda `publicada=True` y `sindicatos=[sindicato_id]` por
    coherencia, pero nada de eso se edita (no hay borrador ni alcance)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    tema: str = Field(index=True)
    sindicato_id: Optional[int] = Field(default=None, foreign_key="sindicato.id", index=True)
    datos: bytes
    mime: str = "image/webp"
    datos_color: Optional[bytes] = None
    mime_color: str = "image/webp"
    ancho: int = 0
    alto: int = 0
    foco_x: float = 0.5
    foco_y: float = 0.5
    descripcion: str = ""              # texto alternativo para lectores de pantalla
    publicada: bool = False
    todos_los_sindicatos: bool = True
    sindicatos: list = Field(default=[], sa_column=Column(JSON_TIPO, nullable=False))
    creada: str = ""                   # "AAAA-MM-DD HH:MM", hora de Buenos Aires
    subida_por: str = ""               # usuario de plataforma


class ConfiguracionPlataforma(SQLModel, table=True):
    """Parámetros globales de plataforma (no por sindicato). Fila única, id=1."""
    id: Optional[int] = Field(default=None, primary_key=True)
    # Ley 27.802 art. 133 / Dto 407/2026: tope global a las cargas sindicales de
    # convenio, en % de la remuneración. Editable SOLO por el admin de plataforma.
    tope_sindical_pct: float = 2.0
    # Panel Sindical (docs/DASHBOARD.md §2.3), mismo patrón que el tope:
    # parámetros a nivel plataforma, iguales para todos los sindicatos.
    # Umbrales del semáforo de aportes por empresa, en días desde el último
    # depósito informado: verde hasta N días, amarillo hasta M, rojo después.
    semaforo_verde_hasta_dias: int = 35
    semaforo_amarillo_hasta_dias: int = 60
    # Feature flag del carril "Consultas al asistente" del dashboard: apagado
    # hasta que el bot (RAG) clasifique por tema. Con False, el endpoint de
    # consultas devuelve 404 y la UI no muestra nada de ese carril.
    dashboard_consultas_bot_habilitado: bool = False
    # Encuestas (SPRINT_ENCUESTAS.md, N1): por debajo de esta cantidad de
    # respuestas, un grupo no se muestra ni se exporta. Cada encuesta se
    # lleva el valor vigente al publicarse, así cambiarlo no altera lo que
    # una encuesta ya cerrada venía mostrando.
    encuestas_umbral_minimo: int = 5
    # Qué modelo de Anthropic usa cada parte de la app (los tres usos de
    # precios_ia.USOS). VACÍO significa "el que está escrito en el módulo"
    # (extractor.MODELO, rag.MODELO_RESPUESTA, asistente.MODELO), no "ninguno":
    # así el default sigue viviendo en el código, en un solo lugar, y la
    # configuración solo existe cuando alguien eligió apartarse de él.
    # Editable SOLO desde /plataforma, igual que el tope sindical.
    modelo_recibos: str = ""
    modelo_convenio: str = ""
    modelo_asistente: str = ""
    modelo_asistente_tramites: str = ""   # Asistente de trámites (Herramientas de /entornos)
    # Claves de los OTROS proveedores del Laboratorio de modelos (Kimi, Qwen),
    # {variable: clave}, pegadas desde la propia pantalla (2026-10-29): es un
    # módulo de evaluación y SDN pidió no tener que ir a Render por cada una.
    # Una variable de entorno con el mismo nombre manda sobre lo guardado acá.
    claves_laboratorio: Optional[dict] = Field(default=None, sa_column=Column(JSON_TIPO, nullable=True))
    # Marca de la plataforma "Mi Trabajo" (pantallas de login y panel de
    # plataforma, antes de entrar a un sindicato en particular). Mismo patrón
    # que Sindicato: logo en la base (Opción B), colores editables. Si no se
    # cargó nada, se usan los valores de siempre (ver marca_plataforma()).
    color_primario: str = "#152238"
    color_secundario: str = "#1a7a6b"
    color_acento: str = "#b23a2e"
    # "logo" (sin sufijo) es la variante para FONDO CLARO (texto oscuro) --
    # nombre heredado de cuando solo había un logo. "logo_oscuro" es la
    # variante para FONDO OSCURO (texto blanco), sumada después para poder
    # usar el logo correcto en encabezados oscuros (admin/trabajador/
    # empresa/plataforma) vs. los logins (fondo gris claro). Si
    # "logo_oscuro" no se cargó, las templates caen al logo claro (mismo
    # criterio que ya usaban antes de esta feature).
    logo: str = ""
    logo_datos: Optional[bytes] = Field(default=None)
    logo_mime: str = ""
    logo_oscuro: str = ""
    logo_datos_oscuro: Optional[bytes] = Field(default=None)
    logo_mime_oscuro: str = ""
    # «Portada clara» de /plataforma: SIN USO desde 2026-10-25 (auditoría
    # R2-03), igual que Sindicato.portada_clara. La portada la pinta el
    # modelo de diseño del usuario; la columna queda en la base sin migrar.
    portada_clara: bool = Field(default=False)


class EnvioSindicato(SQLModel, table=True):
    """Envío voluntario del trabajador de los datos de su recibo al sindicato,
    para acreditar afiliado cotizante ante la autoridad (art. 21 bis, Dto 407/2026).
    NO se anonimiza: el dato identificado es lo que da valor a la acreditación."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(foreign_key="sindicato.id", index=True)
    cuil: str = Field(index=True)
    periodo: str = ""
    monto_cuota: float = 0.0
    fecha: str = ""
    # {"recibo": {...}, "resultado": {...}} — lo que el sindicato puede consultar
    # del recibo que el trabajador envió (Punto 3).
    detalle: dict = Field(default={}, sa_column=Column(JSON_TIPO))


class ReciboVerificado(SQLModel, table=True):
    """Historial privado del trabajador: cada recibo que verifica queda acá,
    esté todo en orden o no, lo haya enviado al sindicato o no."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(foreign_key="sindicato.id", index=True)
    cuil: str = Field(index=True)
    periodo: str = ""
    fecha: str = ""
    estado: str = ""    # "OK" | "CON_DISCREPANCIAS"
    # Marca el intento EXACTO que se envió (no todos los intentos del mismo
    # período): lo actualiza /api/enviar-sindicato por id, no por matching.
    enviado_sindicato: bool = False
    fecha_envio: str = ""
    detalle: dict = Field(default={}, sa_column=Column(JSON_TIPO))
    # ---- Columnas analíticas para el Panel Sindical (docs/DASHBOARD.md) ----
    # Todo esto ya existía ADENTRO de `detalle` (JSON), pero los agregados del
    # dashboard se calculan en SQL con índices y ahí un JSON no sirve. Se
    # persisten al crear el registro (main.api_validar) y las filas viejas se
    # backfillearon parseando `detalle` en la migración. `fecha` quedó como
    # estaba ("dd/mm/AAAA HH:MM", NO ordenable) para no romper lo que la
    # muestra; `procesado_en` es la MISMA fecha en formato ordenable.
    procesado_en: Optional[str] = Field(default=None)   # "AAAA-MM-DD HH:MM"
    cuit_empleador: str = ""                            # solo dígitos (cuit.normalizar)
    categoria: str = ""                                 # texto libre leído del recibo (no hay catálogo CCT)
    formato: str = ""                                   # "clasico" | "nuevo" (Ley 27.802)
    bruto: Optional[float] = Field(default=None)        # resultado.totales.ingresos
    monto_diferencia: float = 0.0                       # suma de |diferencia| de las fórmulas que no dieron
    fecha_ultimo_deposito: Optional[str] = Field(default=None)  # "AAAA-MM-DD", del recibo (semáforo por empresa)


class ReciboSospechoso(SQLModel, table=True):
    """Recibo que la IA marcó con alto grado de certeza de datos posiblemente
    adulterados (en totales, CUIL del trabajador, CUIT del empleador o
    fechas) al leerlo en /api/leer. Se guarda el archivo original (imagen o
    PDF, mismo patrón bytes-en-la-base que el logo del sindicato) para que
    la plataforma lo pueda revisar -- a modo de prueba, todavía no se envía
    al sindicato (eso queda para una etapa siguiente, por voluntad del
    trabajador)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: Optional[int] = Field(default=None, foreign_key="sindicato.id", index=True)
    cuil: str = Field(index=True)
    periodo: str = ""
    fecha: str = ""       # fecha/hora de la detección ("AAAA-MM-DD HH:MM")
    motivo: str = ""      # explicación corta que dio la IA
    archivo_datos: bytes
    archivo_mime: str = ""
    archivo_nombre: str = ""


class Notificacion(SQLModel, table=True):
    """Mensaje dirigido del sindicato a un grupo de trabajadores (Fase 2 de
    Módulos + Notificaciones + Trámites). La lista de destinatarios se
    resuelve y se FIJA al momento de enviar (snapshot en
    NotificacionDestinatario) -- no se recalcula después, así un trabajador
    que cambia de seccional o CUIT no pierde ni gana mensajes ya enviados."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(foreign_key="sindicato.id", index=True)
    remitente: str = ""            # texto libre, ej. "Comisión Directiva"
    # Quién la generó, auditoría real -- NULL en origen="sistema" (Fase 3:
    # la dispara un cambio de trámite, no una persona).
    usuario_id: Optional[int] = Field(default=None, foreign_key="usuariosindicato.id")
    texto: str = ""
    adjunto_datos: Optional[bytes] = Field(default=None)
    adjunto_mime: str = ""
    adjunto_nombre: str = ""
    criterio: str = ""             # "cuil" | "cuit_empleador" | "seccional" | "provincia"
    criterio_valores: list = Field(default=[], sa_column=Column(JSON_TIPO, nullable=False))
    # "manual" = la compuso el admin desde /admin. "sistema" = la disparó
    # automáticamente un cambio de trámite (Fase 3, main._notificar_cambio_tramite).
    origen: str = "manual"
    enviado_en: str = ""           # fecha/hora de envío ("AAAA-MM-DD HH:MM")
    cantidad_destinatarios: int = 0  # snapshot: cuántos matchearon al enviar
    formulario_id: Optional[int] = None  # mismo criterio que Noticia.formulario_id
    # Encuesta que la generó: el aviso de lanzamiento y cada recordatorio.
    # Una encuesta puede tener varias (N15), y de acá sale el "leídas / no
    # leídas" del dashboard. Int SIN FK, mismo criterio que formulario_id.
    encuesta_id: Optional[int] = Field(default=None, index=True)


class NotificacionDestinatario(SQLModel, table=True):
    """Una fila por CUIL que recibió una Notificacion puntual -- separado de
    Notificacion para poder marcar la lectura de cada destinatario por su
    lado (leida_en NULL = todavía no la abrió)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    notificacion_id: int = Field(foreign_key="notificacion.id", index=True)
    cuil: str = Field(index=True)
    leida_en: Optional[str] = Field(default=None)


class NotificacionEmpleador(SQLModel, table=True):
    """Mensaje dirigido del sindicato a un grupo de empleadores -- mismo
    patrón que Notificacion (Fase 2), pero completamente separada por
    decisión explícita: no mezclar identidades CUIL/CUIT en la misma tabla,
    ni tocar el sistema de notificaciones al trabajador que ya funciona."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(foreign_key="sindicato.id", index=True)
    remitente: str = ""
    usuario_id: Optional[int] = Field(default=None, foreign_key="usuariosindicato.id")
    texto: str = ""
    adjunto_datos: Optional[bytes] = Field(default=None)
    adjunto_mime: str = ""
    adjunto_nombre: str = ""
    criterio: str = ""             # "cuit" | "todos" | "provincia"
    criterio_valores: list = Field(default=[], sa_column=Column(JSON_TIPO, nullable=False))
    origen: str = "manual"          # "manual" | "sistema" (Fase 5: cambio de trámite externo)
    enviado_en: str = ""
    cantidad_destinatarios: int = 0
    formulario_id: Optional[int] = None  # referencia TipoTramiteEmpleador (formularios de empresa)


class NotificacionEmpleadorDestinatario(SQLModel, table=True):
    """Una fila por CUIT que recibió una NotificacionEmpleador puntual --
    separado de NotificacionEmpleador para marcar la lectura de cada
    destinatario por su lado."""
    id: Optional[int] = Field(default=None, primary_key=True)
    notificacion_empleador_id: int = Field(foreign_key="notificacionempleador.id", index=True)
    cuit: str = Field(index=True)
    leida_en: Optional[str] = Field(default=None)


class TipoTramite(SQLModel, table=True):
    """Tipo de trámite/formulario que el sindicato pone a disposición del
    trabajador (Fase 3 de Módulos + Notificaciones + Trámites), ej. "F01
    AEFIP - Solicitud de Reintegro". Sus campos van en CampoTramite."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(foreign_key="sindicato.id", index=True)
    titulo: str
    codigo: str  # ej. "F01 AEFIP" -- prefijo del número de expediente
    activo: bool = True
    creado: str = ""
    # Reglas de consistencia entre dos campos ({campo_a, operador, campo_b,
    # mensaje, bloquea}), referenciando campos POR ORDEN y no por id porque
    # editar el tipo REEMPLAZA los campos (ids nuevos en cada edición). Se
    # sanean en validaciones_tramite.reglas_saneadas antes de llegar acá.
    reglas_consistencia: list = Field(default=[], sa_column=Column(JSON_TIPO))
    # Requisitos para INICIAR el trámite (PLAN_LISTAS_VALIDACIONES.md, bloque
    # 3): validaciones de fuente `funcion`, todas bloqueantes, que se evalúan
    # contra el padrón y las listas antes de mostrar el formulario y otra
    # vez al enviar. Saneadas en validaciones_tramite.requisitos_saneados.
    requisitos: list = Field(default=[], sa_column=Column(JSON_TIPO))
    # NULL = formulario GLOBAL, lo ve todo el sindicato. Con seccional, solo
    # lo ven los trabajadores de esa seccional y solo su admin local lo
    # edita (decisión N7 de SPRINT_AREAS_V2.md).
    seccional_id: Optional[int] = Field(default=None, foreign_key="seccional.id", index=True)
    # Si este formulario habilita el PASE entre áreas (decisión N8). Sin el
    # tilde, el área que lo recibe solo puede contestarle al trabajador.
    # Default False: un formulario que no diga nada no habilita circuitos.
    permite_pase: bool = False
    # A qué ÁREA cae el trámite cuando la seccional del trabajador no está
    # mapeada en DestinoTipoTramite. Es OBLIGATORIO: sin él, una seccional
    # nueva dejaría trámites sin dueño, y el error sería silencioso -- nadie
    # los vería en ninguna bandeja (decisión N6, "destino por defecto").
    area_destino_default_id: Optional[int] = Field(
        default=None, foreign_key="area.id", index=True)
    # BORRADOR (SDN, 2026-10-19): un formulario guardado a medias, para
    # seguirlo otro día. Nace inactivo y sin exigir campos ni área; el
    # afiliado nunca lo ve. Publicarlo es guardarlo sin esta marca, y ahí
    # rigen todas las exigencias del alta. Aparte de `activo`, porque un
    # formulario publicado y apagado a propósito no es un borrador.
    borrador: bool = False


class PaseTipoTramite(SQLModel, table=True):
    """Un área a la que ESTE formulario se puede derivar.

    La lista es CERRADA y se declara al armar el formulario (decisión N8):
    el circuito queda diseñado de antemano y es auditable. Sin filas, el
    área que recibe el trámite solo puede contestarle al trabajador.

    No incluye al área destino: derivar al que ya lo tiene no es un pase."""
    id: Optional[int] = Field(default=None, primary_key=True)
    tipo_tramite_id: int = Field(foreign_key="tipotramite.id", index=True)
    area_id: int = Field(foreign_key="area.id", index=True)


class PaseTramite(SQLModel, table=True):
    """Un movimiento de un trámite entre áreas.

    Es lo que hace posible que el área que derivó CONSERVE LECTURA: el
    permiso de ver no sale solo de area_a_cargo_id sino también de haber
    sido origen de algún pase (ver puede_ver_tramite). Sin este registro,
    derivar sería perder de vista para siempre lo que uno pasó.

    Guarda además quién lo hizo, que el panel muestra y el trabajador no
    (misma regla que las notas: al afiliado se le dice el ÁREA, nunca la
    persona)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    tramite_id: int = Field(foreign_key="tramite.id", index=True)
    area_origen_id: Optional[int] = Field(default=None, foreign_key="area.id", index=True)
    area_destino_id: int = Field(foreign_key="area.id", index=True)
    usuario_id: Optional[int] = Field(default=None, foreign_key="usuariosindicato.id")
    motivo: str = ""
    creado: str = ""


class DestinoTipoTramite(SQLModel, table=True):
    """El mapa "esta seccional -> esta área" de un formulario.

    Es la decisión N6: el destino se declara seccional por seccional en vez
    de derivarse de una jerarquía de áreas. Gana precisión (cada delegación
    decide quién atiende qué) a costa de mantener el mapa; el destino por
    defecto de TipoTramite es lo que evita que ese mantenimiento se vuelva
    obligatorio -- una seccional que nadie mapeó funciona igual.

    Una fila por seccional mapeada. Las que no están, caen al default."""
    id: Optional[int] = Field(default=None, primary_key=True)
    tipo_tramite_id: int = Field(foreign_key="tipotramite.id", index=True)
    seccional_id: int = Field(foreign_key="seccional.id", index=True)
    area_id: int = Field(foreign_key="area.id", index=True)


class CampoTramite(SQLModel, table=True):
    """Un campo del formulario dinámico de un TipoTramite. El orden decide
    cómo se renderiza; longitud/decimales/tipos de archivo solo aplican
    según tipo_dato (ver validación server-side en main.api_enviar_tramite).

    "separador" es un pseudo-campo (una raya horizontal): no junta
    respuesta, existe solo para dividir visualmente el formulario -- se
    valida y se salta explícitamente en main.api_enviar_tramite."""
    id: Optional[int] = Field(default=None, primary_key=True)
    tipo_tramite_id: int = Field(foreign_key="tipotramite.id", index=True)
    orden: int = 0
    etiqueta: str = ""  # obligatoria salvo para tipo_dato="separador"
    tipo_dato: str  # texto|numero|fecha|archivo|seleccion|opcion_unica|multiple|booleano|separador
    longitud_maxima: Optional[int] = Field(default=None)
    longitud_exacta: Optional[int] = Field(default=None)  # ej. CVU = 22
    decimales: Optional[int] = Field(default=None)        # solo si tipo_dato="numero"
    tipos_archivo_permitidos: str = ""                     # solo si tipo_dato="archivo"
    opciones: str = ""       # separadas por coma -- seleccion/opcion_unica/multiple
    ancho: str = "completo"  # completo | mitad | tercio -- cuánto ocupa en el formulario
    obligatorio: bool = True
    # Validaciones del campo ({fuente, operador, valor, mensaje, bloquea}),
    # saneadas en validaciones_tramite.validaciones_saneadas. Fase 1: solo
    # fuente "fija"; la forma ya contempla lista/sistema/externa.
    validaciones: list = Field(default=[], sa_column=Column(JSON_TIPO))
    # True = el admin lo quitó del formulario pero ya tenía respuestas: no
    # se puede borrar (FK desde RespuestaTramite) y los trámites viejos
    # necesitan su etiqueta. Sale de la búsqueda del formulario, nada más.
    retirado: bool = False


class Tramite(SQLModel, table=True):
    """Un trámite presentado por un trabajador contra un TipoTramite. El
    número de expediente es correlativo por (sindicato_id, tipo_tramite_id),
    NO se reinicia por año aunque el año quede impreso en el número."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(foreign_key="sindicato.id", index=True)
    tipo_tramite_id: int = Field(foreign_key="tipotramite.id", index=True)
    numero_expediente: str = Field(index=True, unique=True)  # "F01AEFIP-2026-000123"
    cuil: str = Field(index=True)
    estado: str = "iniciado"  # iniciado | en_tratamiento | respondido | espera_info | terminado
    # El área que lo tiene. Se resuelve AL CREARLO (ver area_destino_para) y
    # queda escrito en la fila: si se recalculara en cada consulta, cambiar
    # el mapa del formulario movería de bandeja trámites ya presentados, y
    # el que lo venía trabajando lo perdería de vista sin enterarse.
    area_a_cargo_id: Optional[int] = Field(default=None, foreign_key="area.id", index=True)
    creado: str = ""
    actualizado: str = ""
    # Cuándo pasó a "terminado" (NULL si sigue abierto). Lo setea
    # cambiar_estado_tramite; para el dashboard (días de resolución). Las
    # filas viejas ya terminadas se backfillearon desde `actualizado`, que es
    # exacto: un trámite terminado queda bloqueado y no se actualiza más.
    resuelto_en: Optional[str] = Field(default=None)  # "AAAA-MM-DD HH:MM"
    # Mensajes de validaciones con bloquea=False ("avisa") que el envío
    # disparó: no frenan al trabajador, quedan para el operador del
    # sindicato en el detalle del trámite.
    advertencias: list = Field(default=[], sa_column=Column(JSON_TIPO))
    # Trámite desde cuyo CHAT se inició este (el admin adjuntó un
    # formulario y el trabajador lo abrió desde ahí): los dos chats se
    # muestran vinculados. Un formulario abierto desde una noticia/
    # beneficio/notificación NO vincula (decisión de Sd 2026-09-01).
    origen_tramite_id: Optional[int] = None
    # NULL = hay novedad para el TRABAJADOR (globo en Trámites). Un cambio
    # del sindicato (estado o nota) lo pone en NULL; abrir el detalle o
    # escribir una nota propia lo sella con la hora. Deliberadamente NO se
    # comparan timestamps: el minuto de granularidad de `actualizado` no
    # distingue dos eventos del mismo minuto. (Decisión de Sd 2026-09-02:
    # las novedades de un trámite ya no generan Notificacion.)
    visto_trabajador_en: Optional[str] = None


class RespuestaTramite(SQLModel, table=True):
    """Lo que cargó el trabajador para cada campo del formulario, al enviar
    el trámite -- un CampoTramite, una fila."""
    id: Optional[int] = Field(default=None, primary_key=True)
    tramite_id: int = Field(foreign_key="tramite.id", index=True)
    campo_tramite_id: int = Field(foreign_key="campotramite.id", index=True)
    valor_texto: str = ""
    archivo_datos: Optional[bytes] = Field(default=None)
    archivo_mime: str = ""
    archivo_nombre: str = ""


class NotaTramite(SQLModel, table=True):
    """Ida y vuelta admin <-> trabajador sobre un trámite puntual, con
    adjunto opcional de cada lado."""
    id: Optional[int] = Field(default=None, primary_key=True)
    tramite_id: int = Field(foreign_key="tramite.id", index=True)
    autor: str  # "admin" | "trabajador"
    texto: str = ""
    # El estado que fijó ESTE mensaje (decisión N9). Vacío = el mensaje no
    # movió el estado, que es siempre el caso del trabajador.
    #
    # Vive ACÁ y no en una tabla aparte a propósito: responder y cambiar el
    # estado son UN SOLO ACTO, y guardarlos separados es lo que hacía que el
    # chat mostrara dos movimientos por una sola cosa. Con el estado dentro
    # del mensaje no hay forma de que se desincronicen -- no existe un
    # cambio de estado sin su mensaje ni un mensaje cuyo estado se perdió.
    estado_nuevo: str = ""
    adjunto_datos: Optional[bytes] = Field(default=None)
    adjunto_mime: str = ""
    adjunto_nombre: str = ""
    creado: str = ""
    # Formulario adjuntado por el ADMIN en el mensaje: el trabajador ve una
    # tarjeta "Iniciar este trámite" que abre ese formulario directo (ej.:
    # aprueban la reserva de turismo y le mandan "Registro de pasajeros").
    # Int pelado a propósito, sin FK: un tipo se puede borrar y el chat
    # muestra "ya no disponible" en vez de impedir el borrado.
    formulario_id: Optional[int] = None


class SuscripcionPush(SQLModel, table=True):
    """Suscripción Web Push de un TRABAJADOR (la PWA instalada o el
    navegador). Un CUIL puede tener varias (un teléfono y una compu); el
    endpoint es único globalmente. Se borra sola cuando el servicio de push
    responde 404/410 (suscripción muerta) -- ver push.py."""
    id: Optional[int] = Field(default=None, primary_key=True)
    cuil: str = Field(index=True)
    endpoint: str = Field(unique=True)
    p256dh: str = ""
    auth: str = ""
    creado: str = ""


class TramiteLog(SQLModel, table=True):
    """Tabla de log explícita -- un evento por fila (decisión tomada sobre
    el plan: no una vista derivada). db._log_tramite() es el único punto que
    escribe acá, así el formato del detalle queda en un solo lugar."""
    id: Optional[int] = Field(default=None, primary_key=True)
    tramite_id: int = Field(foreign_key="tramite.id", index=True)
    evento: str  # "creado" | "cambio_estado" | "nota_admin" | "nota_trabajador"
    detalle: str = ""
    creado: str = ""


class DescargaListado(SQLModel, table=True):
    """Cada descarga del listado de trámites con sus respuestas (CSV desde
    la pestaña Trámites, 2026-10-28). Está acá y no en un log del servidor
    por lo mismo que EventoEncuesta: los nombres y documentos de familiares
    son dato sensible, y si alguna vez circula una planilla que no debía,
    hay a quién preguntarle. `filtros` es el texto de lo que se pidió.
    `tipo_tramite_id` en NULL = se bajó sin elegir formulario (2026-10-29:
    el formulario es un filtro más de la bandeja)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(foreign_key="sindicato.id", index=True)
    tipo_tramite_id: Optional[int] = Field(default=None, foreign_key="tipotramite.id", index=True)
    usuario_id: Optional[int] = Field(default=None, foreign_key="usuariosindicato.id")
    filtros: str = ""
    filas: int = 0
    fecha: str = ""     # "AAAA-MM-DD HH:MM"


class TipoTramiteEmpleador(SQLModel, table=True):
    """Mirror de TipoTramite, para formularios "externos" que el sindicato
    pone a disposición de las empresas (Fase 5 del plan de Empleadores) --
    tablas completamente separadas de las de trabajador, a propósito."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(foreign_key="sindicato.id", index=True)
    titulo: str
    codigo: str
    activo: bool = True
    creado: str = ""
    reglas_consistencia: list = Field(default=[], sa_column=Column(JSON_TIPO))  # mirror de TipoTramite


class CampoTramiteEmpleador(SQLModel, table=True):
    """Mirror de CampoTramite."""
    id: Optional[int] = Field(default=None, primary_key=True)
    tipo_tramite_id: int = Field(foreign_key="tipotramiteempleador.id", index=True)
    orden: int = 0
    etiqueta: str = ""
    tipo_dato: str
    longitud_maxima: Optional[int] = Field(default=None)
    longitud_exacta: Optional[int] = Field(default=None)
    decimales: Optional[int] = Field(default=None)
    tipos_archivo_permitidos: str = ""
    opciones: str = ""
    ancho: str = "completo"
    obligatorio: bool = True
    validaciones: list = Field(default=[], sa_column=Column(JSON_TIPO))  # mirror de CampoTramite
    retirado: bool = False                                           # mirror de CampoTramite


class TramiteEmpleador(SQLModel, table=True):
    """Mirror de Tramite, con `cuit` en vez de `cuil`. Numeración de
    expediente correlativa por tipo, mismo criterio que Tramite."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(foreign_key="sindicato.id", index=True)
    tipo_tramite_id: int = Field(foreign_key="tipotramiteempleador.id", index=True)
    numero_expediente: str = Field(index=True, unique=True)
    cuit: str = Field(index=True)
    estado: str = "iniciado"
    creado: str = ""
    actualizado: str = ""
    advertencias: list = Field(default=[], sa_column=Column(JSON_TIPO))  # mirror de Tramite
    origen_tramite_id: Optional[int] = None                          # mirror de Tramite
    visto_empresa_en: Optional[str] = None                           # mirror de visto_trabajador_en


class RespuestaTramiteEmpleador(SQLModel, table=True):
    """Mirror de RespuestaTramite."""
    id: Optional[int] = Field(default=None, primary_key=True)
    tramite_id: int = Field(foreign_key="tramiteempleador.id", index=True)
    campo_tramite_id: int = Field(foreign_key="campotramiteempleador.id", index=True)
    valor_texto: str = ""
    archivo_datos: Optional[bytes] = Field(default=None)
    archivo_mime: str = ""
    archivo_nombre: str = ""


class NotaTramiteEmpleador(SQLModel, table=True):
    """Mirror de NotaTramite -- `autor` es "admin" | "empresa"."""
    id: Optional[int] = Field(default=None, primary_key=True)
    tramite_id: int = Field(foreign_key="tramiteempleador.id", index=True)
    autor: str
    texto: str = ""
    adjunto_datos: Optional[bytes] = Field(default=None)
    adjunto_mime: str = ""
    adjunto_nombre: str = ""
    creado: str = ""
    formulario_id: Optional[int] = None  # mirror de NotaTramite (referencia TipoTramiteEmpleador)


class TramiteEmpleadorLog(SQLModel, table=True):
    """Mirror de TramiteLog."""
    id: Optional[int] = Field(default=None, primary_key=True)
    tramite_id: int = Field(foreign_key="tramiteempleador.id", index=True)
    evento: str
    detalle: str = ""
    creado: str = ""


class Recurso(SQLModel, table=True):
    """Documentación del proyecto subida desde la landing /entornos (ver
    recursos.py, que también lista los recursos versionados en recursos/).
    Los bytes van en la base, como los logos y los adjuntos: en Render no
    hay disco persistente. Un recurso es un archivo O un enlace (url); la
    miniatura es opcional y, si falta, la landing dibuja una portada con el
    título. `fecha` es la del documento (el orden de la landing), `creado`
    cuándo se subió."""
    id: Optional[int] = Field(default=None, primary_key=True)
    titulo: str
    descripcion: str = ""            # una línea
    fecha: date
    tipo: str = "archivo"            # recursos.TIPOS: html/pdf/imagen/video/audio/enlace/archivo
    url: str = ""                    # enlace externo, cuando no hay archivo
    nombre_archivo: str = ""
    mime: str = ""
    tamanio: int = 0
    archivo_datos: Optional[bytes] = Field(default=None)
    miniatura_datos: Optional[bytes] = Field(default=None)
    miniatura_mime: str = ""
    fragmento: str = ""              # "#estrategia": ancla o pestaña con la que se abre
    creado: str = ""                 # ISO


# ---------- Recursos de la landing (recursos.py) ----------
def listar_recursos() -> list[dict]:
    """Metadatos de los recursos subidos, SIN los bytes: un video pesa
    decenas de MB y la landing solo necesita título, fecha y si hay
    miniatura. Del más nuevo al más viejo."""
    with Session(engine) as s:
        filas = s.exec(
            select(Recurso.id, Recurso.titulo, Recurso.descripcion, Recurso.fecha, Recurso.tipo,
                   Recurso.url, Recurso.nombre_archivo, Recurso.mime, Recurso.tamanio,
                   Recurso.fragmento, Recurso.miniatura_mime)
            .order_by(Recurso.fecha.desc(), Recurso.id.desc())
        ).all()
        claves = ("id", "titulo", "descripcion", "fecha", "tipo", "url", "nombre_archivo",
                  "mime", "tamanio", "fragmento", "miniatura_mime")
        return [dict(zip(claves, fila)) for fila in filas]


def guardar_recurso(titulo: str, descripcion: str, fecha: date, tipo: str, url: str = "",
                    nombre_archivo: str = "", mime: str = "", archivo_datos: bytes = None,
                    miniatura_datos: bytes = None, miniatura_mime: str = "",
                    fragmento: str = "") -> int:
    with Session(engine) as s:
        r = Recurso(
            titulo=titulo, descripcion=descripcion, fecha=fecha, tipo=tipo, url=url,
            nombre_archivo=nombre_archivo, mime=mime, tamanio=len(archivo_datos or b""),
            archivo_datos=archivo_datos, miniatura_datos=miniatura_datos,
            miniatura_mime=miniatura_mime, fragmento=fragmento,
            creado=fechas.ahora().isoformat(timespec="seconds"),
        )
        s.add(r)
        s.commit()
        return r.id


def recurso(recurso_id: int) -> Optional[Recurso]:
    """El recurso con el ARCHIVO (los bytes quedan diferidos por defecto):
    solo para servirlo. La miniatura, aparte: `recurso_miniatura`."""
    from sqlalchemy.orm import undefer
    with Session(engine) as s:
        return s.get(Recurso, recurso_id, options=[undefer(Recurso.archivo_datos)])


def recurso_miniatura(recurso_id: int) -> Optional[Recurso]:
    """El recurso con SOLO la miniatura (sin el archivo, que puede pesar MB)."""
    from sqlalchemy.orm import undefer
    with Session(engine) as s:
        return s.get(Recurso, recurso_id, options=[undefer(Recurso.miniatura_datos)])


def borrar_recurso(recurso_id: int) -> bool:
    with Session(engine) as s:
        r = s.get(Recurso, recurso_id)
        if not r:
            return False
        s.delete(r)
        s.commit()
        return True


# ---------- Inicialización ----------
# ---------- Consultas sobre el convenio (RAG) -- ver PLAN_RAG_CONVENIO.md ----------
# Módulo "convenio", opt-in por sindicato. Piloto: NO toca la validación de
# recibos. Todo el aislamiento sigue el criterio del resto de la app.

# Dimensión del vector. Sale de una medición con material real (convenio de
# AEFIP, 18 preguntas): multilingual-e5-large ganó con 94% de recall@8 contra
# 76% y 47% de los otros dos. Cambiar de modelo a uno de otra dimensión es
# migración + reindexado completo -- ver medicion_rag/.
DIM_EMBEDDING = 1024

# Identidad COMPLETA del embedding: librería + modelo. La librería va incluida
# a propósito -- fastembed cambió el pooling de este mismo modelo entre
# versiones, y con solo el nombre del modelo el cambio pasaría inadvertido y
# la búsqueda devolvería basura en silencio.
MODELO_EMBEDDING = "fastembed-0.8.0/intfloat/multilingual-e5-large"


class Convenio(SQLModel, table=True):
    """Un convenio colectivo del sindicato. Un sindicato puede tener VARIOS
    (uno general, otros por empresa o rama) y es el TRABAJADOR quien elige
    cuál consultar: inferirlo del empleador o la categoría sería frágil, y
    contestar con el convenio equivocado es peor que no contestar.

    `nombre` es lo único que va a guiar al trabajador en el selector, así que
    tiene que ser entendible ("Metalúrgicos - rama automotriz"), no el código
    legal."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(foreign_key="sindicato.id", index=True)
    nombre: str
    codigo: str = ""              # "CCT 260/75", referencia formal
    activo: bool = True
    creado: str = ""


class DocumentoConvenio(SQLModel, table=True):
    """El PDF del convenio o de un acta, con lo que el admin declara sobre él.

    LA VIGENCIA LA DECLARA EL ADMIN, no se calcula: un acta no dice de forma
    confiable qué artículo modifica. `vigente` responde "¿entra en la búsqueda
    hoy?" -- es lo que el admin marca cuando un texto ordenado absorbe actas
    viejas. Las fechas responden "¿en qué período rigió?", que hace falta para
    una consulta retroactiva y es imposible de reconstruir después."""
    id: Optional[int] = Field(default=None, primary_key=True)
    convenio_id: int = Field(foreign_key="convenio.id", index=True)
    sindicato_id: int = Field(foreign_key="sindicato.id", index=True)
    tipo: str = "convenio"        # convenio | acta
    titulo: str = ""
    fecha_documento: str = ""
    archivo_datos: Optional[bytes] = Field(default=None)
    archivo_mime: str = ""
    archivo_nombre: str = ""
    # "Datos asociados": lo que el admin adjunta como relevante. SE INDEXA
    # como fuente distinta (tipo_fuente="observacion") porque suele estar en
    # lenguaje llano, más parecido a cómo pregunta un trabajador que el
    # articulado formal.
    observaciones: str = ""
    observaciones_fecha: str = ""
    vigente: bool = True
    vigencia_desde: str = ""
    vigencia_hasta: str = ""
    origen_texto: str = ""        # nativo | ocr
    caracteres_extraidos: int = 0
    paginas: int = 0
    # Indexar un convenio tarda ~9 minutos (medido: 246 fragmentos a 2,3 s
    # cada uno). Ningún request HTTP sobrevive eso, así que corre en segundo
    # plano y el documento lleva su propio estado para que el panel pueda
    # mostrar en qué anda.
    estado: str = "pendiente"     # pendiente | procesando | listo | error
    fragmentos_generados: int = 0
    error_detalle: str = ""
    creado: str = ""


class FragmentoConvenio(SQLModel, table=True):
    """Un trozo indexado, con su vector. Hereda la vigencia de su documento.

    `sindicato_id` está desnormalizado a propósito: la búsqueda vectorial
    filtra por él en el camino caliente y no queremos un join ahí.

    `referencia` es texto libre ("Artículo 47", "Acta 2024-03") y no un número
    estructurado: con actas que no siguen un formato fijo, forzar estructura
    garantiza perderla. Lo que importa es que sea legible en la cita."""
    id: Optional[int] = Field(default=None, primary_key=True)
    documento_id: int = Field(foreign_key="documentoconvenio.id", index=True)
    convenio_id: int = Field(foreign_key="convenio.id", index=True)
    sindicato_id: int = Field(foreign_key="sindicato.id", index=True)
    orden: int = 0
    texto: str = ""
    referencia: str = ""
    seccion: str = ""             # el TÍTULO del convenio donde cae
    tipo_fuente: str = "convenio"  # convenio | acta | observacion
    # Las notas "(Ex - Artículo N modificado por Acta...)" viven ACÁ y no en
    # `texto`: son ~116 con redacción casi idéntica y dentro del embedding
    # harían que el 60% de los artículos se parezcan por su boilerplate.
    notas_acta: str = ""
    embedding: Any = Field(default=None, sa_column=Column(Vector(DIM_EMBEDDING)))
    modelo_embedding: str = ""
    creado: str = ""


class ConsultaConvenio(SQLModel, table=True):
    """Cada pregunta que hizo un trabajador. Es el único dato que dice si el
    troceo funciona y dónde están los huecos de lo indexado -- por eso se
    registra desde el principio y no al final."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(foreign_key="sindicato.id", index=True)
    convenio_id: Optional[int] = Field(default=None, foreign_key="convenio.id", index=True)
    cuil: str = Field(default="", index=True)
    pregunta: str = ""
    hubo_respuesta: bool = False   # False = se contestó "no lo encontré"
    fragmentos_usados: list = Field(default=[], sa_column=Column(JSON_TIPO))
    creado: str = ""
    # Tema de la consulta, para el gráfico "Consultas por tema" del Panel
    # Sindical (docs/DASHBOARD.md). NULL en todo lo registrado hasta ahora:
    # el piloto RAG todavía no clasifica por tema -- cuando lo haga, lo llena
    # acá y el dashboard lo muestra (detrás del feature flag
    # dashboard_consultas_bot_habilitado).
    tema: Optional[str] = Field(default=None)


class ConsultaAsistente(SQLModel, table=True):
    """Cada pregunta al Asistente del Panel Sindical (docs/ASISTENTE_PANEL.md
    §3): qué preguntó el admin, qué contestó el modelo, qué filtros quedaron
    y cuánto costó. Sirve para el tope diario, para auditar y para armar el
    set de frases de prueba con preguntas reales. Distinta de
    ConsultaConvenio (el bot del convenio del trabajador) a propósito: no
    comparten tabla ni código."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(foreign_key="sindicato.id", index=True)
    usuario_id: Optional[int] = Field(default=None, foreign_key="usuariosindicato.id")
    pregunta: str = ""
    respuesta: str = ""
    filtros: Optional[dict] = Field(default=None, sa_column=Column(JSON_TIPO))   # None = no aplicó
    tab: str = ""
    aplicado: bool = False
    modelo: str = ""
    tokens_entrada: int = 0
    tokens_salida: int = 0
    llamadas: int = 0
    creado: str = ""               # "AAAA-MM-DD HH:MM", como el resto de la base


def registrar_consulta_asistente(sindicato_id: int, usuario_id: Optional[int], pregunta: str,
                                 respuesta: str, filtros: Optional[dict], aplicado: bool,
                                 uso: dict) -> int:
    with Session(engine) as s:
        fila = ConsultaAsistente(
            sindicato_id=sindicato_id, usuario_id=usuario_id,
            pregunta=pregunta[:500], respuesta=respuesta[:2000],
            filtros=filtros, tab=(filtros or {}).get("tab", ""), aplicado=aplicado,
            modelo=uso.get("modelo", ""), tokens_entrada=uso.get("tokens_entrada", 0),
            tokens_salida=uso.get("tokens_salida", 0), llamadas=uso.get("llamadas", 0),
            creado=fechas.ahora_texto())
        s.add(fila); s.commit(); s.refresh(fila)
        return fila.id


def usuarios_carga_estres() -> list:
    """CUIL + clave fija ("1234") de los 1.000 trabajadores sintéticos que
    siembra carga/preparar_datos.py, leídos de la base -- no de
    carga/usuarios.csv. Los Jobs de Render (carga/correr_job.py) son
    contenedores efímeros que no comparten filesystem entre sí ni con el
    servicio web, así que un CSV generado por otro Job ya no está ahí; la
    base sí es compartida y es la fuente de verdad."""
    with Session(engine) as s:
        sind = s.exec(select(Sindicato).where(Sindicato.slug == "carga-estres")).first()
        if not sind:
            return []
        cuils = s.exec(select(Trabajador.cuil).where(Trabajador.sindicato_id == sind.id)).all()
        return [(c, "1234") for c in cuils]


class TestCarga(SQLModel, table=True):
    """Una corrida del test de estrés (carga/, ver carga/README.md),
    disparada desde la pestaña "Tests" de /entornos. El generador corre en
    un Job de Render aparte (no en este proceso -- si compitiera por CPU/red
    con el propio servidor que está testeando, los números saldrían
    falsos), así que esta tabla es el ÚNICO canal entre ese Job y la página
    que lo muestra: el Job escribe acá su avance y su resultado final."""
    id: Optional[int] = Field(default=None, primary_key=True)
    entorno: str = "pruebas"                 # "pruebas" únicamente por ahora (demo: no disponible)
    tipo: str = "lecturas"                    # "lecturas" | "recibos"
    estado: str = "pendiente"                 # pendiente -> corriendo -> listo | error
    parametros: dict = Field(default={}, sa_column=Column(JSON_TIPO, nullable=False))
    resumen: Optional[list] = Field(default=None, sa_column=Column(JSON_TIPO))  # filas tipo resumen.csv
    avance: str = ""                          # último progreso corto ("escalón 200, 00m30s")
    error_detalle: str = ""
    render_job_id: str = ""
    creado_en: str = Field(default_factory=fechas.ahora_con_segundos)
    terminado_en: str = ""


def crear_test_carga(tipo: str, parametros: dict) -> int:
    with Session(engine) as s:
        t = TestCarga(tipo=tipo, parametros=parametros)
        s.add(t); s.commit(); s.refresh(t)
        return t.id


def fijar_job_test_carga(test_id: int, render_job_id: str) -> None:
    with Session(engine) as s:
        t = s.get(TestCarga, test_id)
        if t:
            t.render_job_id = render_job_id
            t.estado = "corriendo"
            s.add(t); s.commit()


def actualizar_test_carga(test_id: int, **campos) -> None:
    """Lo llama el Job (proceso aparte, misma base) para dejar avance,
    resumen final, error o estado. Solo pisa los campos que le pasan."""
    with Session(engine) as s:
        t = s.get(TestCarga, test_id)
        if not t:
            return
        for k, v in campos.items():
            setattr(t, k, v)
        s.add(t); s.commit()


def tests_carga_recientes(limite: int = 20) -> list:
    with Session(engine) as s:
        filas = s.exec(select(TestCarga).order_by(TestCarga.id.desc()).limit(limite)).all()
        return [f.model_dump() for f in filas]


def test_carga_por_id(test_id: int) -> Optional[dict]:
    with Session(engine) as s:
        t = s.get(TestCarga, test_id)
        return t.model_dump() if t else None


def borrar_todos_los_tests_carga() -> int:
    """Vacía la tabla y reinicia el contador de id, para que la próxima
    publicación arranque otra vez en 1. Hace falta porque la lista de
    /entornos se rearmó desde cero -- una entrada por experimento real, no
    una por tipo de test -- y los números tienen que coincidir con los del
    informe: test 1 = primer experimento, y así.

    Es destructivo a propósito. Los datos de origen viven en carga/log/ y
    carga/experimentos.json, así que la lista siempre se puede regenerar
    con carga/publicar_experimentos.py."""
    with Session(engine) as s:
        n = len(s.exec(select(TestCarga)).all())
        s.execute(text("DELETE FROM testcarga"))
        try:
            s.execute(text("ALTER SEQUENCE testcarga_id_seq RESTART WITH 1"))
        except Exception:
            # Si el contador no se pudo reiniciar, el borrado igual vale.
            pass
        s.commit()
        return n


class AccesoLog(SQLModel, table=True):
    """Un login exitoso de cualquiera de los 4 roles -- para el dashboard
    de Actividad de /entornos ("cantidad de accesos por app"). Nada de esto
    existía antes: se registra desde main.py, en cada ruta de login, justo
    después de validar la clave. `sindicato_id` queda NULL cuando el rol no
    tiene uno resuelto en ese momento (plataforma; trabajador con
    pluriempleo, antes de elegir) -- el resumen los cuenta aparte, no los
    descarta."""
    id: Optional[int] = Field(default=None, primary_key=True)
    rol: str                                   # trabajador | admin | empresa | plataforma
    sindicato_id: Optional[int] = Field(default=None, foreign_key="sindicato.id", index=True)
    fecha: str = Field(default="", index=True)  # "AAAA-MM-DD HH:MM"


def registrar_acceso(rol: str, sindicato_id: Optional[int] = None) -> None:
    with Session(engine) as s:
        s.add(AccesoLog(rol=rol, sindicato_id=sindicato_id,
                         fecha=fechas.ahora_texto()))
        s.commit()


# ---- Usuarios de plataforma nominales (SPRINT_R1.md) ----

def usuario_plataforma_por_usuario(usuario: str):
    """La fila del usuario de plataforma por su nombre de login, o None.
    No filtra por activo: quien llama decide qué hacer con uno inactivo."""
    u = (usuario or "").strip().lower()
    if not u:
        return None
    with Session(engine) as s:
        return s.exec(select(UsuarioPlataforma).where(
            UsuarioPlataforma.usuario == u)).first()


def registrar_log_plataforma(accion: str, usuario: str, objetivo: str = "",
                             ip: str = "", detalle: str = "") -> None:
    """Deja un evento en la bitácora de plataforma (XSK H-0016)."""
    with Session(engine) as s:
        s.add(LogPlataforma(cuando=fechas.ahora_texto(), accion=accion,
                            usuario=usuario or "", objetivo=objetivo or "",
                            ip=ip or "", detalle=detalle or ""))
        s.commit()


def hay_usuarios_plataforma() -> bool:
    """¿Ya existe al menos un usuario de plataforma nominal? Sirve para saber
    si la transición (login genérico + PIN) todavía hace falta."""
    with Session(engine) as s:
        return s.exec(select(UsuarioPlataforma.id)).first() is not None


def superadmins_activos() -> int:
    """Cuántos superadmin activos hay (para la guarda del último)."""
    with Session(engine) as s:
        return len(s.exec(select(UsuarioPlataforma).where(
            UsuarioPlataforma.rol == "superadmin",
            UsuarioPlataforma.activo == True)).all())


# Los dos superadmin iniciales (SPRINT_R1.md). Clave de un solo uso, sin
# vencimiento: valen hasta que la persona entre la primera vez y cambie la
# clave + cargue sus datos. La siembra es la ÚNICA fuente de estos datos: la
# usan la migración (al crear la tabla) y el test.
SUPERADMINS_INICIALES = [
    {"usuario": "snavello", "nombre": "Sandro Navello", "clave": "snaSandro"},
    {"usuario": "arsantagati", "nombre": "Alejandro Santagati", "clave": "arsAlejandro"},
]


def listar_usuarios_plataforma() -> list:
    """Todos los usuarios de plataforma, superadmin primero y luego por usuario."""
    with Session(engine) as s:
        return s.exec(select(UsuarioPlataforma).order_by(
            UsuarioPlataforma.rol, UsuarioPlataforma.usuario)).all()


def _vencimiento_transitoria(dias: int = 7) -> str:
    """Fecha/hora (texto, hora de Buenos Aires) a los `dias` días desde ahora,
    para la clave transitoria (SPRINT_R1.md: máximo 7 días)."""
    from datetime import timedelta
    return (fechas.ahora() + timedelta(days=dias)).strftime("%Y-%m-%d %H:%M")


def crear_usuario_plataforma(usuario: str, nombre: str, rol: str, clave_hash: str,
                             creado_por: str, dias_vencimiento: int = 7):
    """Alta de un usuario de plataforma con clave transitoria (la crea un
    superadmin). Devuelve (usuario, None) si se creó, o (None, motivo) si el
    nombre de usuario ya existe."""
    u = (usuario or "").strip().lower()
    if not u:
        return None, "El usuario es obligatorio."
    with Session(engine) as s:
        if s.exec(select(UsuarioPlataforma).where(UsuarioPlataforma.usuario == u)).first():
            return None, "Ya existe un usuario con ese nombre."
        fila = UsuarioPlataforma(
            usuario=u, nombre=(nombre or "").strip(),
            rol="superadmin" if rol == "superadmin" else "admin",
            clave_hash=clave_hash, activo=True,
            debe_cambiar_clave=True, clave_vence=_vencimiento_transitoria(dias_vencimiento),
            debe_completar_datos=True,
            creado_en=fechas.ahora_texto(), creado_por=creado_por)
        s.add(fila)
        s.commit()
        s.refresh(fila)
        return fila, None


def editar_usuario_plataforma(uid: int, nombre: str, rol: str) -> None:
    with Session(engine) as s:
        u = s.get(UsuarioPlataforma, uid)
        if not u:
            return
        u.nombre = (nombre or "").strip()
        u.rol = "superadmin" if rol == "superadmin" else "admin"
        s.add(u)
        s.commit()


def set_activo_usuario_plataforma(uid: int, activo: bool) -> None:
    with Session(engine) as s:
        u = s.get(UsuarioPlataforma, uid)
        if not u:
            return
        u.activo = activo
        s.add(u)
        s.commit()


def resetear_clave_plataforma(uid: int, clave_hash: str, dias_vencimiento: int = 7) -> None:
    """Un superadmin le pone al usuario una clave transitoria nueva: vuelve a
    forzar el cambio en el próximo ingreso, con vencimiento a 7 días."""
    with Session(engine) as s:
        u = s.get(UsuarioPlataforma, uid)
        if not u:
            return
        u.clave_hash = clave_hash
        u.debe_cambiar_clave = True
        u.clave_vence = _vencimiento_transitoria(dias_vencimiento)
        s.add(u)
        s.commit()


def usuario_plataforma_por_id(uid: int):
    with Session(engine) as s:
        return s.get(UsuarioPlataforma, uid)


def email_plataforma_en_uso(email: str, excepto_id: Optional[int] = None) -> bool:
    """¿Ya hay otro usuario de plataforma con ese mail? (único, sirve a futuro
    para recuperación de clave). Compara normalizado en minúsculas."""
    e = (email or "").strip().lower()
    if not e:
        return False
    with Session(engine) as s:
        q = select(UsuarioPlataforma).where(UsuarioPlataforma.email == e)
        return any(u.id != excepto_id for u in s.exec(q).all())


def completar_usuario_plataforma(uid: int, clave_hash: str, cuil: str, dni: str,
                                 email: str, direccion: str, telefono: str) -> None:
    """Primer ingreso: fija la clave definitiva, marca la cuenta como completa
    y guarda los datos obligatorios (SPRINT_R1.md)."""
    with Session(engine) as s:
        u = s.get(UsuarioPlataforma, uid)
        if not u:
            return
        u.clave_hash = clave_hash
        u.debe_cambiar_clave = False
        u.clave_vence = None
        u.debe_completar_datos = False
        u.cuil = (cuil or "").strip()
        u.dni = (dni or "").strip()
        u.email = (email or "").strip().lower()
        u.direccion = (direccion or "").strip()
        u.telefono = (telefono or "").strip()
        s.add(u)
        s.commit()


def sembrar_superadmins_iniciales() -> int:
    """Crea los superadmin iniciales que falten (idempotente). Devuelve
    cuántos creó. La clave inicial es transitoria (debe_cambiar_clave) y sin
    vencimiento (clave_vence=None); los datos quedan por completar."""
    import auth
    creados = 0
    with Session(engine) as s:
        for sa_ in SUPERADMINS_INICIALES:
            existe = s.exec(select(UsuarioPlataforma).where(
                UsuarioPlataforma.usuario == sa_["usuario"])).first()
            if existe:
                continue
            s.add(UsuarioPlataforma(
                usuario=sa_["usuario"], nombre=sa_["nombre"],
                clave_hash=auth.hashear_clave(sa_["clave"]),
                rol="superadmin", activo=True,
                debe_cambiar_clave=True, clave_vence=None,
                debe_completar_datos=True,
                creado_en=fechas.ahora_texto(), creado_por="semilla"))
            creados += 1
        s.commit()
    return creados


class GeoCache(SQLModel, table=True):
    """Respuestas ya pedidas a Georef y Nominatim, para no repetir el pedido.

    **No tiene `sindicato_id`, y es a propósito** -- la única excepción
    consciente al aislamiento total del proyecto. Lo que se guarda acá es la
    respuesta de una API PÚBLICA a una dirección normalizada: "santa fe|
    rosario|san martin|850" no es un dato de nadie, es una calle. Ponerle
    `sindicato_id` mataría el reuso (dos gremios con seccional en la misma
    cuadra pedirían dos veces, gastando el presupuesto de 1 pedido/segundo
    que comparten) y no protegería nada, porque ninguna pantalla de la app
    lee esta tabla: solo la lee `geo.py` antes de salir a la red.

    El TTL son 90 días. No hay proceso que limpie lo vencido: una fila
    vencida se reescribe la próxima vez que alguien pregunte por esa misma
    dirección, y la tabla crece con el padrón, no con el uso."""
    id: Optional[int] = Field(default=None, primary_key=True)
    # La clave de búsqueda, ya normalizada por geo._clave_cache (minúsculas,
    # sin tildes, campos separados por "|"). Única: una dirección, una fila.
    consulta_normalizada: str = Field(index=True, unique=True)
    respuesta_json: list = Field(default=[], sa_column=Column(JSON_TIPO))
    # "AAAA-MM-DD HH:MM" de Buenos Aires, igual que el resto del proyecto.
    creado: str = ""


class CacheExterna(SQLModel, table=True):
    """Respuestas de servicios públicos de afuera (clima, dólar oficial,
    centroides de localidad) para "Tu día". En la base y no en memoria:
    Render corre un proceso por núcleo y cada uno pediría lo suyo.

    Como `GeoCache`, **no tiene `sindicato_id` a propósito**: lo que se guarda
    es el clima de una celda de ~1 km o la cotización del día, que no son de
    nadie. La clave dice qué es ("clima|-33.13|-64.35", "dolar|2026-10-24").
    `vence` es una marca de tiempo (segundos de época): una fila vencida se
    reescribe la próxima vez que alguien la pide."""
    clave: str = Field(primary_key=True)
    valor: Optional[dict] = Field(default=None, sa_column=Column(JSON_TIPO, nullable=True))
    vence: float = 0


def cache_externa_leer(clave: str, ahora: float):
    """(True, valor) si hay una fila vigente; (False, None) si no."""
    with Session(engine) as s:
        fila = s.get(CacheExterna, clave)
        if fila and fila.vence > ahora:
            return True, fila.valor
    return False, None


def cache_externa_guardar(clave: str, valor, vence: float) -> None:
    with Session(engine) as s:
        fila = s.get(CacheExterna, clave)
        if fila:
            fila.valor, fila.vence = valor, vence
        else:
            fila = CacheExterna(clave=clave, valor=valor, vence=vence)
        s.add(fila)
        try:
            s.commit()
        except Exception:
            s.rollback()      # dos procesos guardando lo mismo a la vez: gana uno, da igual


def tu_dia_de(sindicato_id: int) -> Optional[dict]:
    with Session(engine) as s:
        sind = s.get(Sindicato, sindicato_id)
        return dict(sind.tu_dia) if sind and sind.tu_dia else None


def set_tu_dia(sindicato_id: int, config: dict) -> bool:
    """Guarda la configuración de "Tu día" ya normalizada por
    `tu_dia.normalizar_config` (lo que no está en el catálogo no entra)."""
    import tu_dia
    with Session(engine) as s:
        sind = s.get(Sindicato, sindicato_id)
        if not sind:
            return False
        sind.tu_dia = tu_dia.normalizar_config(config)
        s.add(sind)
        s.commit()
        return True


def cumple_de(cuil: str) -> dict:
    """{"fecha_nacimiento", "cumple_visto", "nombre"} de la persona."""
    with Session(engine) as s:
        c = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first()
        if not c:
            return {}
        return {"fecha_nacimiento": c.fecha_nacimiento, "cumple_visto": c.cumple_visto or "",
                "nombre": c.nombre or ""}


def marcar_cumple_visto(cuil: str, anio: str) -> None:
    with Session(engine) as s:
        c = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first()
        if c:
            c.cumple_visto = anio
            s.add(c)
            s.commit()


def geocache_leer(clave: str) -> Optional[dict]:
    """La fila de caché de esa consulta, o None. El TTL lo evalúa geo.py."""
    with Session(engine) as s:
        fila = s.exec(select(GeoCache).where(
            GeoCache.consulta_normalizada == clave)).first()
        if not fila:
            return None
        return {"respuesta_json": fila.respuesta_json, "creado": fila.creado}


def geocache_guardar(clave: str, respuesta: list) -> None:
    """Guarda o refresca la respuesta de esa consulta.

    Es un upsert a mano porque la fila vencida se REESCRIBE en lugar de
    sumar otra: la clave es única, y dejar histórico de una caché sería
    juntar basura para siempre. Si dos pedidos simultáneos intentan crear la
    misma clave, el UNIQUE frena al segundo y se ignora -- la caché ya
    quedó escrita por el primero, que era todo el objetivo.
    """
    with Session(engine) as s:
        fila = s.exec(select(GeoCache).where(
            GeoCache.consulta_normalizada == clave)).first()
        if fila:
            fila.respuesta_json = respuesta
            fila.creado = fechas.ahora_texto()
            s.add(fila)
        else:
            s.add(GeoCache(consulta_normalizada=clave, respuesta_json=respuesta,
                           creado=fechas.ahora_texto()))
        try:
            s.commit()
        except IntegrityError:
            s.rollback()


def actividad_resumen(dias: int = 30) -> dict:
    """Agregados de actividad de ESTE entorno para el dashboard de
    Actividad (/entornos): trámites, notificaciones enviadas/leídas,
    recibos verificados, tokens de IA y accesos, por sindicato y totales.
    Todo en SQL agrupado (mismo criterio que dashboard.py) -- nunca se
    traen filas crudas para sumar en Python. `dias` acota accesos y tokens
    de IA a una ventana reciente (por defecto 30 días); trámites/recibos/
    notificaciones son acumulados históricos, como el resto de la
    plataforma los muestra."""
    desde = (fechas.ahora() - timedelta(days=dias)).strftime("%Y-%m-%d %H:%M")
    with Session(engine) as s:
        sindicatos = {sd.id: sd.nombre for sd in
                      s.exec(select(Sindicato).where(Sindicato.activo == True)).all()}
        por_sind = {sid: {"id": sid, "nombre": nombre, "tramites": 0, "recibos": 0,
                           "notificaciones_enviadas": 0, "notificaciones_leidas": 0,
                           "tokens_ia": 0, "llamadas_ia": 0, "accesos": 0}
                    for sid, nombre in sindicatos.items()}

        def volcar(filas, campo):
            for sid, valor in filas:
                if sid in por_sind:
                    por_sind[sid][campo] = valor or 0

        volcar(s.execute(text(
            "SELECT sindicato_id, COUNT(*) FROM tramite GROUP BY sindicato_id")).all(), "tramites")
        volcar(s.execute(text(
            "SELECT sindicato_id, COUNT(*) FROM reciboverificado GROUP BY sindicato_id")).all(), "recibos")
        volcar(s.execute(text(
            "SELECT sindicato_id, COUNT(*) FROM notificacion GROUP BY sindicato_id"
        )).all(), "notificaciones_enviadas")
        volcar(s.execute(text(
            "SELECT n.sindicato_id, COUNT(*) FROM notificaciondestinatario nd "
            "JOIN notificacion n ON n.id = nd.notificacion_id "
            "WHERE nd.leida_en IS NOT NULL GROUP BY n.sindicato_id"
        )).all(), "notificaciones_leidas")
        volcar(s.execute(text(
            "SELECT sindicato_id, SUM(tokens_entrada + tokens_salida) FROM usoia "
            "WHERE fecha >= :desde GROUP BY sindicato_id"), {"desde": desde}).all(), "tokens_ia")
        volcar(s.execute(text(
            "SELECT sindicato_id, COUNT(*) FROM usoia WHERE fecha >= :desde GROUP BY sindicato_id"
        ), {"desde": desde}).all(), "llamadas_ia")
        volcar(s.execute(text(
            "SELECT sindicato_id, COUNT(*) FROM accesolog "
            "WHERE fecha >= :desde AND sindicato_id IS NOT NULL GROUP BY sindicato_id"
        ), {"desde": desde}).all(), "accesos")

        accesos_por_rol = dict(s.execute(text(
            "SELECT rol, COUNT(*) FROM accesolog WHERE fecha >= :desde GROUP BY rol"
        ), {"desde": desde}).all())
        accesos_sin_sindicato = s.execute(text(
            "SELECT COUNT(*) FROM accesolog WHERE fecha >= :desde AND sindicato_id IS NULL"
        ), {"desde": desde}).one()[0] or 0

        totales = {"tramites": 0, "recibos": 0, "notificaciones_enviadas": 0,
                   "notificaciones_leidas": 0, "tokens_ia": 0, "llamadas_ia": 0, "accesos": 0}
        for fila in por_sind.values():
            for k in totales:
                totales[k] += fila[k]
        totales["accesos"] += accesos_sin_sindicato
        totales["accesos_por_rol"] = accesos_por_rol
        totales["sindicatos_activos"] = len(sindicatos)

        return {"sindicatos": sorted(por_sind.values(), key=lambda f: f["nombre"]),
                "totales": totales, "dias": dias, "actualizado": fechas.ahora_con_segundos()}


def consultas_asistente_hoy(sindicato_id: int) -> int:
    """Para el tope diario del Asistente. `creado` es string ordenable, así
    que "hoy" es todo lo que empieza con la fecha de hoy."""
    hoy = fechas.hoy_texto()
    with Session(engine) as s:
        return len(s.exec(select(ConsultaAsistente.id).where(
            ConsultaAsistente.sindicato_id == sindicato_id,
            ConsultaAsistente.creado >= hoy)).all())


# ---------- Consultas sobre el convenio: acceso a datos ----------

def convenios_del_sindicato(sindicato_id: int, solo_activos: bool = False) -> list:
    """Convenios del sindicato, con el resumen de lo que tienen indexado.

    El conteo de fragmentos VIGENTES es lo que le importa al admin: un
    convenio con documentos cargados pero todos marcados como no vigentes no
    va a contestar nada, y eso tiene que verse."""
    with Session(engine) as s:
        q = select(Convenio).where(Convenio.sindicato_id == sindicato_id)
        if solo_activos:
            q = q.where(Convenio.activo == True)
        convenios = s.exec(q.order_by(Convenio.nombre)).all()
        salida = []
        for c in convenios:
            docs = s.exec(select(DocumentoConvenio).where(
                DocumentoConvenio.convenio_id == c.id)).all()
            ids_vigentes = [d.id for d in docs if d.vigente]
            frags = 0
            if ids_vigentes:
                frags = len(s.exec(select(FragmentoConvenio).where(
                    FragmentoConvenio.documento_id.in_(ids_vigentes))).all())
            salida.append({
                "id": c.id, "nombre": c.nombre, "codigo": c.codigo,
                "activo": c.activo, "creado": c.creado,
                "documentos": len(docs),
                "documentos_vigentes": len(ids_vigentes),
                "fragmentos_vigentes": frags,
                "indexando": any(d.estado == "procesando" for d in docs),
            })
        return salida


def documentos_del_convenio(convenio_id: int) -> list:
    with Session(engine) as s:
        docs = s.exec(select(DocumentoConvenio).where(
            DocumentoConvenio.convenio_id == convenio_id)
            .order_by(DocumentoConvenio.fecha_documento.desc(),
                      DocumentoConvenio.id.desc())).all()
        return [{
            "id": d.id, "tipo": d.tipo, "titulo": d.titulo,
            "fecha_documento": d.fecha_documento, "vigente": d.vigente,
            "vigencia_desde": d.vigencia_desde, "vigencia_hasta": d.vigencia_hasta,
            "observaciones": d.observaciones, "observaciones_fecha": d.observaciones_fecha,
            "origen_texto": d.origen_texto, "paginas": d.paginas,
            "caracteres_extraidos": d.caracteres_extraidos,
            "estado": d.estado, "fragmentos_generados": d.fragmentos_generados,
            "error_detalle": d.error_detalle, "creado": d.creado,
            "archivo_nombre": d.archivo_nombre,
        } for d in docs]


def documentos_anteriores_a(convenio_id: int, fecha: str, excluir_id: int = 0) -> list:
    """Documentos VIGENTES del convenio con fecha anterior a `fecha`.

    Se usa para avisar al admin, en el momento de subir uno nuevo, que hay
    documentos viejos que quizá quedaron absorbidos. Es cuando tiene el
    contexto fresco -- mucho más barato que un recordatorio a 30 días."""
    if not fecha:
        return []
    with Session(engine) as s:
        docs = s.exec(select(DocumentoConvenio).where(
            DocumentoConvenio.convenio_id == convenio_id,
            DocumentoConvenio.vigente == True)).all()
        return [{"id": d.id, "titulo": d.titulo or d.archivo_nombre,
                 "fecha_documento": d.fecha_documento, "tipo": d.tipo}
                for d in docs
                if d.id != excluir_id and d.fecha_documento and d.fecha_documento < fecha]


def fragmentos_de_documento(documento_id: int, limite: int = 0) -> list:
    """Los fragmentos de un documento, para la vista previa del admin.

    La vista previa muestra TEXTO y no solo el conteo a propósito: un troceo
    malo pasa el "se detectaron N fragmentos" sin problema y arruina todo lo
    que viene después."""
    with Session(engine) as s:
        q = select(FragmentoConvenio).where(
            FragmentoConvenio.documento_id == documento_id).order_by(FragmentoConvenio.orden)
        if limite:
            q = q.limit(limite)
        return [{"id": f.id, "orden": f.orden, "referencia": f.referencia,
                 "seccion": f.seccion, "tipo_fuente": f.tipo_fuente,
                 "texto": f.texto, "notas_acta": f.notas_acta,
                 "modelo_embedding": f.modelo_embedding} for f in s.exec(q).all()]


def crear_convenio(sindicato_id: int, nombre: str, codigo: str) -> int:
    with Session(engine) as s:
        c = Convenio(sindicato_id=sindicato_id, nombre=nombre.strip(),
                     codigo=(codigo or "").strip(),
                     creado=fechas.ahora_texto())
        s.add(c); s.commit(); s.refresh(c)
        return c.id


def editar_convenio(convenio_id: int, sindicato_id: int, nombre: str,
                    codigo: str, activo: bool) -> bool:
    with Session(engine) as s:
        c = s.get(Convenio, convenio_id)
        if not c or c.sindicato_id != sindicato_id:
            return False
        c.nombre, c.codigo, c.activo = nombre.strip(), (codigo or "").strip(), activo
        s.add(c); s.commit()
        return True


def crear_documento_convenio(convenio_id: int, sindicato_id: int, tipo: str, titulo: str,
                              fecha_documento: str, archivo_datos: bytes, archivo_mime: str,
                              archivo_nombre: str, observaciones: str = "",
                              observaciones_fecha: str = "", vigencia_desde: str = "",
                              vigencia_hasta: str = "") -> Optional[int]:
    """Guarda el documento en estado "pendiente". NO indexa: eso tarda ~9
    minutos y corre aparte."""
    with Session(engine) as s:
        conv = s.get(Convenio, convenio_id)
        if not conv or conv.sindicato_id != sindicato_id:
            return None
        d = DocumentoConvenio(
            convenio_id=convenio_id, sindicato_id=sindicato_id, tipo=tipo,
            titulo=titulo, fecha_documento=fecha_documento,
            archivo_datos=archivo_datos, archivo_mime=archivo_mime,
            archivo_nombre=archivo_nombre, observaciones=observaciones,
            observaciones_fecha=observaciones_fecha, vigencia_desde=vigencia_desde,
            vigencia_hasta=vigencia_hasta, estado="pendiente",
            creado=fechas.ahora_texto())
        s.add(d); s.commit(); s.refresh(d)
        return d.id


def set_vigencia_documento(documento_id: int, sindicato_id: int, vigente: bool) -> bool:
    """Marca un documento como vigente o no. Es lo que el admin usa cuando un
    texto ordenado absorbe actas viejas: quedan guardadas pero salen de la
    búsqueda."""
    with Session(engine) as s:
        d = s.get(DocumentoConvenio, documento_id)
        if not d or d.sindicato_id != sindicato_id:
            return False
        d.vigente = vigente
        s.add(d); s.commit()
        return True


def borrar_documento_convenio(documento_id: int, sindicato_id: int) -> bool:
    """Borra el documento y sus fragmentos. Los fragmentos primero: los
    modelos declaran la FK como columna pero no como relationship(), así que
    SQLAlchemy no conoce el orden de dependencia y Postgres rechazaría."""
    with Session(engine) as s:
        d = s.get(DocumentoConvenio, documento_id)
        if not d or d.sindicato_id != sindicato_id:
            return False
        for f in s.exec(select(FragmentoConvenio).where(
                FragmentoConvenio.documento_id == documento_id)).all():
            s.delete(f)
        s.commit()
        s.delete(d); s.commit()
        return True


def set_estado_documento(documento_id: int, estado: str, fragmentos: int = None,
                          error: str = None, origen_texto: str = None,
                          paginas: int = None, caracteres: int = None) -> None:
    """Actualiza el progreso de la indexación. La llama el hilo de fondo."""
    with Session(engine) as s:
        d = s.get(DocumentoConvenio, documento_id)
        if not d:
            return
        d.estado = estado
        if fragmentos is not None:
            d.fragmentos_generados = fragmentos
        if error is not None:
            d.error_detalle = error[:500]
        if origen_texto is not None:
            d.origen_texto = origen_texto
        if paginas is not None:
            d.paginas = paginas
        if caracteres is not None:
            d.caracteres_extraidos = caracteres
        s.add(d); s.commit()


def guardar_fragmentos(documento_id: int, convenio_id: int, sindicato_id: int,
                        fragmentos: list, vectores: list, tipo_fuente: str = "convenio",
                        desde_orden: int = 0) -> int:
    """Guarda un lote de fragmentos ya vectorizados."""
    ahora = fechas.ahora_texto()
    with Session(engine) as s:
        for i, (f, v) in enumerate(zip(fragmentos, vectores)):
            s.add(FragmentoConvenio(
                documento_id=documento_id, convenio_id=convenio_id,
                sindicato_id=sindicato_id, orden=desde_orden + i,
                texto=f["texto"], referencia=f["referencia"], seccion=f.get("seccion", ""),
                tipo_fuente=tipo_fuente, notas_acta=f.get("notas_acta", ""),
                embedding=v, modelo_embedding=MODELO_EMBEDDING, creado=ahora))
        s.commit()
    return len(fragmentos)


def borrar_fragmentos_de_documento(documento_id: int) -> None:
    with Session(engine) as s:
        for f in s.exec(select(FragmentoConvenio).where(
                FragmentoConvenio.documento_id == documento_id)).all():
            s.delete(f)
        s.commit()



def buscar_fragmentos(sindicato_id: int, convenio_id: int, vector: list,
                       k: int = 8) -> list:
    """Los k fragmentos más parecidos a la pregunta, con su similitud.

    El filtro por sindicato_id y convenio_id NO es opcional ni una
    optimización: es el aislamiento. Va en el WHERE y no en un filtro
    posterior, para que sea imposible que un fragmento ajeno llegue a
    Claude aunque se equivoque el código de arriba.

    Solo documentos VIGENTES: el admin marca como no vigente lo que un texto
    ordenado nuevo ya absorbió, y esas cláusulas viejas no tienen que
    contestarle a nadie.

    k=8 sale de la medición: con el convenio real, recall@8 fue 94% y
    recall@3 82%. Los artículos que hacen falta suelen estar entre los 8,
    no entre los 3."""
    with Session(engine) as s:
        filas = s.exec(text("""
            SELECT f.id, f.referencia, f.seccion, f.texto, f.tipo_fuente,
                   f.notas_acta, d.titulo AS documento, d.fecha_documento,
                   1 - (f.embedding <=> CAST(:v AS vector)) AS similitud
            FROM fragmentoconvenio f
            JOIN documentoconvenio d ON d.id = f.documento_id
            WHERE f.sindicato_id = :sid
              AND f.convenio_id = :cid
              AND d.vigente = true
              AND f.embedding IS NOT NULL
            ORDER BY f.embedding <=> CAST(:v AS vector)
            LIMIT :k
        """).bindparams(v=str(vector), sid=sindicato_id, cid=convenio_id, k=k)).all()
        return [{"id": r[0], "referencia": r[1], "seccion": r[2], "texto": r[3],
                 "tipo_fuente": r[4], "notas_acta": r[5], "documento": r[6],
                 "fecha_documento": r[7], "similitud": float(r[8])} for r in filas]


def registrar_consulta(sindicato_id: int, convenio_id: int, cuil: str, pregunta: str,
                        hubo_respuesta: bool, fragmentos_usados: list) -> None:
    """Guarda cada pregunta. Es el único dato que dice si el troceo funciona
    y dónde están los huecos de lo indexado -- por eso se registra desde el
    principio, no al final del piloto."""
    with Session(engine) as s:
        s.add(ConsultaConvenio(
            sindicato_id=sindicato_id, convenio_id=convenio_id, cuil=cuil or "",
            pregunta=(pregunta or "")[:2000], hubo_respuesta=hubo_respuesta,
            fragmentos_usados=list(fragmentos_usados or []),
            creado=fechas.ahora_texto()))
        s.commit()


def consultas_del_sindicato(sindicato_id: int, limite: int = 200) -> list:
    """Para que el admin vea qué preguntó la gente y dónde no hubo respuesta."""
    with Session(engine) as s:
        filas = s.exec(select(ConsultaConvenio).where(
            ConsultaConvenio.sindicato_id == sindicato_id)
            .order_by(ConsultaConvenio.id.desc()).limit(limite)).all()
        return [{"id": c.id, "pregunta": c.pregunta, "cuil": c.cuil,
                 "hubo_respuesta": c.hubo_respuesta, "creado": c.creado,
                 "fragmentos_usados": c.fragmentos_usados or []} for c in filas]

def rescatar_indexaciones_colgadas() -> int:
    """Marca como error los documentos que quedaron en "procesando".

    La indexación corre en un hilo del proceso web: si el proceso muere a
    mitad -- un deploy, un reinicio, un OOM -- el hilo se va con él y el
    documento queda en "procesando" PARA SIEMPRE, sin nada que lo destrabe.
    El manejo de excepciones no cubre esto: no hay excepción, hay muerte.

    Como ninguna indexación sobrevive a un reinicio, al arrancar se puede
    afirmar con certeza que todo lo que esté en "procesando" está muerto."""
    with Session(engine) as s:
        colgados = s.exec(select(DocumentoConvenio).where(
            DocumentoConvenio.estado == "procesando")).all()
        for d in colgados:
            d.estado = "error"
            d.error_detalle = ("La indexación se interrumpió (el servidor se reinició "
                               "mientras corría). Volvé a indexar el documento.")
            s.add(d)
        s.commit()
        return len(colgados)


def documento_para_indexar(documento_id: int) -> Optional[dict]:
    """Lo que el hilo de fondo necesita, en un dict: no se puede pasar un
    objeto de SQLModel entre hilos con la sesión ya cerrada."""
    with Session(engine) as s:
        d = s.get(DocumentoConvenio, documento_id)
        if not d:
            return None
        return {"id": d.id, "convenio_id": d.convenio_id, "sindicato_id": d.sindicato_id,
                "archivo_datos": d.archivo_datos, "observaciones": d.observaciones,
                "tipo": d.tipo, "titulo": d.titulo, "fecha_documento": d.fecha_documento}

def crear_tablas():
    """Arma el esquema con create_all.

    NO se usa ni en producción ni en desarrollo: ahí el esquema lo
    administra Alembic. Existe para la suite, que levanta una base
    descartable por proceso y necesita el esquema sin correr 59 migraciones
    (ver conftest.py)."""
    SQLModel.metadata.create_all(engine)


def cargar_seed_si_vacio():
    """Carga el seed histórico de AEFIP (data/seed_aefip.json) si no hay
    conceptos. YA NO corre en el arranque (init_db): la demo arranca sin
    AEFIP (CLAUDE.md, "Datos desde cero") y sembrarlo solo hacía aparecer
    un sindicato fantasma con id=1 en toda base creada desde cero sin
    cargar_demo.py antes -- exactamente el caso del entorno de Pruebas.
    Queda disponible solo a pedido:
        python -c "import db; db.cargar_seed_si_vacio()"
    """
    seed_path = Path("data/seed_aefip.json")
    if not seed_path.exists():
        return
    try:
        with Session(engine) as s:
            if s.exec(select(Concepto)).first():
                return  # ya hay datos, no tocar
    except Exception:
        # En Postgres el esquema puede no existir aún (Alembic todavía no corrió).
        # No es un error: simplemente todavía no hay nada que sembrar.
        return
    with Session(engine) as s:
        seed = json.loads(seed_path.read_text(encoding="utf-8"))
        sind_data = seed.get("sindicato", {"nombre": "Sindicato"})
        sind = s.exec(select(Sindicato)).first()
        if not sind:
            sind = Sindicato(id=1, **sind_data)
            s.add(sind)
            # Postgres SÍ hace cumplir las FK: el sindicato padre debe existir
            # dentro de la transacción antes de insertar conceptos/fórmulas hijos.
            # SQLite lo perdonaba; este flush lo hace explícito para ambos motores.
            s.flush()
        for c in seed.get("conceptos", []):
            s.add(Concepto(sindicato_id=1, **c))
        for f in seed.get("formulas", []):
            s.add(Formula(sindicato_id=1, **f))
        s.commit()
        # Tras insertar filas con id explícito, Postgres NO avanza su secuencia
        # interna, así que el próximo alta chocaría con "clave duplicada".
        # Resincronizamos la secuencia de cada tabla con id explícito.
        _sincronizar_secuencias(s, [Sindicato])


def _sincronizar_secuencias(s, modelos):
    """Pone el contador de autoincremento por encima del id máximo."""
    from sqlalchemy import text
    for modelo in modelos:
        tabla = modelo.__tablename__
        s.exec(text(
            f"SELECT setval(pg_get_serial_sequence('{tabla}', 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {tabla}), 1))"
        ))
    s.commit()


def init_db():
    """Inicialización en el arranque.

    NO crea tablas: el esquema lo administra Alembic (`alembic upgrade head`
    corre en el Pre-Deploy). Y NO siembra AEFIP: una base vacía queda vacía
    hasta que se corre cargar_demo.py o se da de alta un sindicato desde
    /plataforma. Solo se siembran los topes de la seguridad social
    (data/topes_ss.csv), que son datos de ley y no de ningún sindicato.
    """
    sembrar_topes_si_vacio()


# ---------- Accesos de conveniencia ----------
# --- Los bytes no viajan si nadie los pide --------------------------------
# Todas las columnas de bytes de todos los modelos (logos, firmas, contratos,
# fotos de perfil, imágenes de noticias y beneficios, fotos de los modelos de
# diseño, adjuntos) quedan DIFERIDAS: un `s.get(Sindicato, id)` o un
# `select(Noticia)` traen la fila sin ellas, y recién se piden a la base si
# el código lee el atributo (adentro de la sesión, como hacen las rutas que
# sirven cada imagen). Antes, la fila del sindicato de La Bancaria (logo de
# 1 MB + firma + contrato) se leía entera en cada pantalla, varias veces por
# portada: con 200 personas navegando, la base se pasaba el tiempo mandando
# bytes que nadie usaba (medido el 2026-11-05, PLAN_PRUEBAS_BANCARIA.md).
# `test_paginas_sin_bytes.py` vigila que ninguna pantalla los traiga.
# Para saber si hay imagen sin traerla: octet_length en SQL (ver
# `marca_sindicato`, `tiene_foto_trabajador`, `_hay_bytes`).
from sqlalchemy import LargeBinary as _LargeBinary
from sqlalchemy.orm import Mapper as _Mapper


@event.listens_for(_Mapper, "before_configured", once=True)
def _diferir_columnas_de_bytes() -> None:
    for mapper in list(SQLModel._sa_registry.mappers):
        for prop in mapper.column_attrs:
            if isinstance(prop.columns[0].type, _LargeBinary) and not prop.deferred:
                prop.deferred = True
                prop.strategy_key = (("deferred", True), ("instrument", True))


def get_session() -> Session:
    return Session(engine)


def nombre_sindicato() -> str:
    with Session(engine) as s:
        sind = s.exec(select(Sindicato)).first()
        return sind.nombre if sind else ""


def conceptos_como_dicts(sindicato_id: int = None) -> list:
    """Devuelve los conceptos en el formato que espera el validador.
    Si se pasa sindicato_id, filtra solo los de ese sindicato."""
    with Session(engine) as s:
        q = select(Concepto)
        if sindicato_id is not None:
            q = q.where(Concepto.sindicato_id == sindicato_id)
        return [
            {
                "codigo": c.codigo, "nombre": c.nombre, "tipo": c.tipo,
                "remunerativo": c.remunerativo, "alias": c.alias or [],
                "pendiente_revision": c.pendiente_revision,
                "categoria_sindical": c.categoria_sindical,
                "cuit_empleador": c.cuit_empleador,
                "codigo_generico": c.codigo_generico,
            }
            for c in s.exec(q).all()
        ]


def formulas_como_dicts(sindicato_id: int = None) -> list:
    with Session(engine) as s:
        q = select(Formula)
        if sindicato_id is not None:
            q = q.where(Formula.sindicato_id == sindicato_id)
        return [
            {"target": f.target, "descripcion": f.descripcion,
             "expr": f.expr, "tolerancia": f.tolerancia,
             "fecha_desde": f.fecha_desde, "fecha_hasta": f.fecha_hasta,
             "sujeto_a_tope": f.sujeto_a_tope}
            for f in s.exec(q).all() if f.activa
        ]


def crear_conceptos_universales(sindicato_id: int) -> list:
    """Da de alta los 3 conceptos + fórmulas de aportes de ley (jubilación,
    PAMI, obra social) — el % es prácticamente igual en cualquier recibo
    argentino en blanco, así que el chequeo funciona desde el primer recibo
    aunque el sindicato todavía no haya cargado ningún empleador. Son
    conceptos y fórmulas comunes y corrientes: el admin los puede editar o
    borrar como a cualquier otro. La cuota sindical NO se autogenera acá
    porque el % varía por sindicato.

    IDEMPOTENTE: no duplica lo que ya exista (por código). Se usa tanto al
    dar de alta un sindicato nuevo como desde el botón manual en /admin, para
    completar sindicatos que ya existían antes de esta función. Devuelve la
    lista de códigos que efectivamente agregó algo (concepto y/o fórmula)."""
    from validador import CONCEPTOS_UNIVERSALES
    with Session(engine) as s:
        codigos_concepto = {c.codigo for c in s.exec(select(Concepto).where(
            Concepto.sindicato_id == sindicato_id)).all()}
        codigos_formula = {f.target for f in s.exec(select(Formula).where(
            Formula.sindicato_id == sindicato_id)).all()}
        agregados = []
        for c in CONCEPTOS_UNIVERSALES:
            algo_nuevo = False
            if c["codigo"] not in codigos_concepto:
                s.add(Concepto(
                    sindicato_id=sindicato_id, codigo=c["codigo"], nombre=c["nombre"],
                    tipo="descuento", remunerativo=True, alias=[c["nombre"]],
                    pendiente_revision=False,
                ))
                algo_nuevo = True
            if c["codigo"] not in codigos_formula:
                s.add(Formula(
                    sindicato_id=sindicato_id, target=c["codigo"],
                    descripcion=c["descripcion_formula"],
                    expr=f"{c['pct']} * base_remunerativa", tolerancia=1.0,
                    sujeto_a_tope=True,
                ))
                algo_nuevo = True
            if algo_nuevo:
                agregados.append(c["codigo"])
        s.commit()
    return agregados


# ---------- Topes de base imponible (jubilación, INSSJP, obra social) ----------
def secciones_vistas(s: Session, sindicato_id: int, ultimos: int = 500) -> dict:
    """{(codigo, cuit_empleador): {"haberes": n, "no_remunerativos": n,
    "descuentos": n}} -- en qué sección del recibo leyó la IA cada código,
    contado sobre los últimos `ultimos` recibos verificados del sindicato.

    Es lo que dice el recibo de cada concepto, para contrastarlo con su
    rubro en el catálogo (validador.clasificacion_vista): una devolución de
    Ganancias confirmada como haber se ve acá como "leído 4 veces entre los
    descuentos". Recibe la sesión del request (una conexión por request) y
    se acota a los últimos recibos: la evidencia que importa es la reciente,
    y la consulta abre el JSON de cada uno. Los recibos leídos antes de que
    el extractor dijera la sección (2026-10-11) no aportan nada.
    """
    from validador import seccion_de
    filas = s.execute(text("""
        WITH r AS (
            SELECT cuit_empleador, detalle->'recibo'->'lineas' AS lineas
            FROM reciboverificado
            WHERE sindicato_id = :sid
            ORDER BY id DESC
            LIMIT :n
        )
        SELECT l->>'codigo' AS codigo, r.cuit_empleador, l->>'seccion' AS seccion,
               count(*) AS veces
        FROM r, jsonb_array_elements(
                 CASE WHEN jsonb_typeof(r.lineas) = 'array' THEN r.lineas
                      ELSE '[]'::jsonb END) AS l
        WHERE jsonb_typeof(l) = 'object'
          AND jsonb_typeof(l->'seccion') = 'string'
          AND l->>'codigo' IS NOT NULL
        GROUP BY 1, 2, 3
    """), {"sid": sindicato_id, "n": ultimos}).all()
    vistas: dict = {}
    for codigo, cuit_empleador, seccion, veces in filas:
        seccion = seccion_de({"seccion": seccion})
        if seccion is None:
            continue
        clave = ((codigo or "").strip(), cuit_empleador or "")
        conteo = vistas.setdefault(clave, {})
        conteo[seccion] = conteo.get(seccion, 0) + veces
    return vistas


def secciones_del_concepto(vistas: dict, codigo: str, cuit_empleador: str | None,
                           especificos: set) -> dict:
    """Los conteos de secciones_vistas que le corresponden a UN concepto: el
    de un empleador, solo los recibos de ese CUIT; uno genérico, los de todos
    los empleadores salvo los que tienen su propio concepto con ese código
    (esos recibos matchean contra el específico, no contra este)."""
    codigo = (codigo or "").strip()
    total: dict = {}
    for (cod, cuit_r), conteo in vistas.items():
        if cod != codigo:
            continue
        if cuit_empleador:
            if cuit_r != cuit_empleador:
                continue
        elif (cod, cuit_r) in especificos:
            continue
        for seccion, n in conteo.items():
            total[seccion] = total.get(seccion, 0) + n
    return total


def topes_como_dicts() -> list:
    """Todos los topes, en el formato que espera el validador (sin filtro
    de sindicato: es una tabla nacional)."""
    with Session(engine) as s:
        return [
            {"vigencia_desde": t.vigencia_desde, "tope_maximo": t.tope_maximo,
             "base_minima": t.base_minima, "estado": t.estado, "fuente": t.fuente}
            for t in s.exec(select(TopeBaseImponible)).all()
        ]


def topes_listado() -> list:
    """Para la pantalla de /plataforma: todos los topes por vigencia
    descendente (el más nuevo primero) -- orden simple y predecible. Cuáles
    hay que revisar se ve por el chip de estado (SOSPECHOSO/por_verificar),
    no reordenando la tabla."""
    with Session(engine) as s:
        topes = s.exec(select(TopeBaseImponible)).all()
        return sorted(topes, key=lambda t: t.vigencia_desde, reverse=True)


def tope_anterior_a(vigencia_desde: str, excluir_id: int = None) -> Optional[dict]:
    """El tope con vigencia_desde más reciente ANTERIOR al dado (para la
    validación de "no debería bajar de un período al siguiente"). None si
    no hay ninguno anterior."""
    with Session(engine) as s:
        q = select(TopeBaseImponible).where(TopeBaseImponible.vigencia_desde < vigencia_desde)
        if excluir_id is not None:
            q = q.where(TopeBaseImponible.id != excluir_id)
        anteriores = s.exec(q).all()
        if not anteriores:
            return None
        t = max(anteriores, key=lambda x: x.vigencia_desde)
        return {"vigencia_desde": t.vigencia_desde, "tope_maximo": t.tope_maximo, "base_minima": t.base_minima}


def crear_tope(vigencia_desde: str, tope_maximo: float, base_minima: float, estado: str, fuente: str) -> bool:
    """False si ya existe un tope con esa vigencia (para cambiar un período
    existente se edita, no se agrega otro)."""
    with Session(engine) as s:
        if s.exec(select(TopeBaseImponible).where(TopeBaseImponible.vigencia_desde == vigencia_desde)).first():
            return False
        s.add(TopeBaseImponible(vigencia_desde=vigencia_desde, tope_maximo=tope_maximo,
                                 base_minima=base_minima, estado=estado, fuente=fuente))
        s.commit()
        return True


def editar_tope(tope_id: int, tope_maximo: float, base_minima: float, estado: str, fuente: str) -> bool:
    with Session(engine) as s:
        t = s.get(TopeBaseImponible, tope_id)
        if not t:
            return False
        t.tope_maximo, t.base_minima, t.estado, t.fuente = tope_maximo, base_minima, estado, fuente
        s.add(t)
        s.commit()
        return True


def borrar_tope(tope_id: int) -> None:
    with Session(engine) as s:
        t = s.get(TopeBaseImponible, tope_id)
        if t:
            s.delete(t)
            s.commit()


def sembrar_topes_si_vacio() -> None:
    """Si la tabla de topes está vacía, la carga desde data/topes_ss.csv
    (mismo criterio que cargar_seed_si_vacio con el seed de AEFIP) --
    corre en cada arranque, tanto en SQLite local como en Postgres/Render,
    así que no hace falta sembrar los datos desde la migración misma."""
    csv_path = Path("data/topes_ss.csv")
    if not csv_path.exists():
        return
    try:
        with Session(engine) as s:
            if s.exec(select(TopeBaseImponible)).first():
                return  # ya hay datos, no tocar
            with open(csv_path, newline="", encoding="utf-8") as f:
                for fila in csv.DictReader(f):
                    s.add(TopeBaseImponible(
                        vigencia_desde=fila["vigencia_desde"],
                        tope_maximo=float(fila["tope_maximo"]),
                        base_minima=float(fila["base_minima"]),
                        estado=fila["estado"], fuente=fila["fuente"],
                    ))
            s.commit()
    except Exception:
        pass  # semilla opcional, no debe romper el arranque de la app


# ---------- Trabajadores: cuenta única + empadronamiento por sindicato ----------
def sindicatos_de_cuil(cuil: str) -> list:
    """Devuelve los sindicatos donde este CUIL está empadronado (habilitado)."""
    with Session(engine) as s:
        empadronamientos = s.exec(select(Trabajador).where(Trabajador.cuil == cuil)).all()
        resultado = []
        for e in empadronamientos:
            sind = s.get(Sindicato, e.sindicato_id, options=_sin_bytes(Sindicato))
            if sind and sind.activo:
                resultado.append({"id": sind.id, "nombre": sind.nombre, "slug": sind.slug})
        return resultado


# ---------- Ingreso con Google: qué cuenta es la de este mail ----------
# Google solo IDENTIFICA (google_auth.py): nunca crea una cuenta. La verificación
# del mail la hace Google (`email_verified`); la app acepta ese mail contra
# CUALQUIERA de los mails que la cuenta ya tiene en su ficha -- el declarado
# (confirmado o no), el del padrón y el de contacto -- siempre que sea de UNA
# sola cuenta entre todas las del rol. Cambio del 2026-11-06 (Pruebas): con el
# canal de mail apagado nadie tiene `mail_declarado_confirmado`, y pedirlo dejaba
# a Google sin uso. Al entrar, el mail queda declarado y confirmado
# (`entrar_con_google`). El panel del sindicato queda afuera: CuentaPanel y
# UsuarioSindicato no tienen mail.
_CUENTA_GOOGLE = {"trabajador": ("CuentaTrabajador", "cuil"),
                  "empleador": ("CuentaEmpleador", "cuit"),
                  "panel": ("CuentaPanel", "cuil")}


# Una persona, una identidad (SSO del panel): la cuenta de afiliado del MISMO CUIL
# identifica a la operadora, pero solo si esa cuenta de afiliado está respaldada
# por algo más que lo que escribió quien se registró: el mail del padrón (lo cargó
# el sindicato), un recibo propio leído por la IA o la confirmación presencial.
# Un afiliado de nivel 1/2 por `mail_declarado` (un mail tipeado o un ingreso con
# Google con un mail de contacto) NO alcanza: el CUIL es público y, con el canal
# de mail apagado, cualquiera se registra como afiliado con el CUIL de un operador
# y le cuelga su Gmail. Si SDN decide aflojarlo, es esta tupla.
SSO_ORIGENES_VALIDOS = ("mail_padron", "recibo_propio", "presencial")


def _cuil_con_identidad_probada(c) -> bool:
    """¿La cuenta de afiliado `c` prueba quién es la persona (ver arriba)?"""
    return bool(c and c.clave_hash and (c.nivel_origen or "") in SSO_ORIGENES_VALIDOS)


def mail_sso_de(cuil: str) -> str:
    """El mail CONFIRMADO de la cuenta de afiliado de ese CUIL, si esa cuenta
    prueba la identidad: es el que el panel reconoce sin que la persona lo cargue
    de nuevo. "" si no hay."""
    with Session(engine) as s:
        c = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first()
        if _cuil_con_identidad_probada(c) and (c.mail_declarado_confirmado or ""):
            return (c.mail_declarado or "").strip()
    return ""


def _cuentas_panel_con_mail(s, mail: str, sub: str = "") -> list:
    """Las cuentas del PANEL (con clave y con algún usuario activo en un
    sindicato activo) a las que corresponde `mail`: el de la propia cuenta
    (`CuentaPanel.mail`), el que cargó el sindicato en el padrón
    (`CuentaTrabajador.mail_padron`) de esa persona, SOLO si está empadronada en
    alguno de los sindicatos donde ella es operadora, o -- una persona, una
    identidad -- la cuenta de AFILIADO del mismo CUIL cuando ya ingresó con ese
    mismo `sub` de Google o tiene ese mail declarado y confirmado, siempre que esa
    cuenta de afiliado pruebe la identidad (`SSO_ORIGENES_VALIDOS`).

    Deliberadamente NO cuenta el mail de contacto (`CuentaTrabajador.mail`) ni
    el declarado sin confirmar: los escribe quien se registre primero como
    afiliado con ese CUIL (que es público), y con ellos cualquiera entraría al
    panel de otro."""
    from sqlalchemy import func as _func
    activos: dict = {}
    for cuil, sid in s.exec(select(UsuarioSindicato.cuil, UsuarioSindicato.sindicato_id).join(
            Sindicato, Sindicato.id == UsuarioSindicato.sindicato_id).where(
            UsuarioSindicato.activo == True, Sindicato.activo == True,  # noqa: E712
            UsuarioSindicato.cuil != "")).all():
        activos.setdefault(cuil, set()).add(sid)
    propias = {c.cuil for c in s.exec(select(CuentaPanel).where(
        CuentaPanel.clave_hash != "", _func.lower(_func.trim(CuentaPanel.mail)) == mail)).all()}
    del_padron = set()
    for cuil in s.exec(select(CuentaTrabajador.cuil).where(
            _func.lower(_func.trim(CuentaTrabajador.mail_padron)) == mail,
            CuentaTrabajador.cuil.in_(list(activos) or [""]))).all():
        if s.exec(select(Trabajador.id).where(
                Trabajador.cuil == cuil, Trabajador.sindicato_id.in_(list(activos[cuil])))).first():
            del_padron.add(cuil)
    del_afiliado = set()
    if sub:
        del_afiliado |= {c for c in s.exec(select(CuentaTrabajador.cuil).where(
            CuentaTrabajador.google_sub == sub, CuentaTrabajador.clave_hash != "",
            CuentaTrabajador.nivel_origen.in_(SSO_ORIGENES_VALIDOS))).all()}
    del_afiliado |= {c for c in s.exec(select(CuentaTrabajador.cuil).where(
        _func.lower(_func.trim(CuentaTrabajador.mail_declarado)) == mail,
        CuentaTrabajador.mail_declarado_confirmado != "", CuentaTrabajador.clave_hash != "",
        CuentaTrabajador.nivel_origen.in_(SSO_ORIGENES_VALIDOS))).all()}
    cuils = [c for c in (propias | del_padron | del_afiliado) if c in activos]
    if not cuils:
        return []
    return s.exec(select(CuentaPanel).where(
        CuentaPanel.cuil.in_(cuils), CuentaPanel.clave_hash != "")).all()


def _cuentas_con_mail(s, rol: str, mail: str, sub: str = "") -> list:
    """Todas las cuentas REGISTRADAS (con clave) del rol que tienen `mail` en
    alguno de sus campos de mail, normalizado (minúsculas, sin espacios). Una
    fila del padrón sin clave todavía no es una cuenta: Google no la abre."""
    from sqlalchemy import func as _func

    def igual(col):
        return _func.lower(_func.trim(col)) == mail
    if rol == "panel":
        return _cuentas_panel_con_mail(s, mail, sub)
    if rol == "trabajador":
        return s.exec(select(CuentaTrabajador).where(
            CuentaTrabajador.clave_hash != "",
            or_(igual(CuentaTrabajador.mail_declarado), igual(CuentaTrabajador.mail_padron),
                igual(CuentaTrabajador.mail)))).all()
    # Empresa: el declarado vive en la cuenta; el del padrón y el de contacto, en
    # sus altas por sindicato (`Empleador`, unidas por CUIT).
    cuits = {e for e in s.exec(select(Empleador.cuit).where(
        or_(igual(Empleador.mail_padron), igual(Empleador.mail)))).all()}
    return s.exec(select(CuentaEmpleador).where(
        CuentaEmpleador.clave_hash != "",
        or_(igual(CuentaEmpleador.mail_declarado), CuentaEmpleador.cuit.in_(cuits)))).all()


def cuenta_para_google(rol: str, mail: str, sub: str) -> tuple[str, int, str]:
    """(estado, cuenta_id, identificador) de la cuenta que le corresponde a una
    identidad de Google. `estado`:
    - "ok": una y una sola cuenta;
    - "ninguna": no hay ninguna con ese mail, o su cuenta ya está atada a OTRA
      cuenta de Google (no se reasigna sola: el mail pudo cambiar de manos);
    - "varias": el mail está en más de una cuenta del rol, en cualquiera de sus
      campos (no se adivina);
    - "temporal": la cuenta tiene clave temporal (el sindicato la restableció y
      el primer ingreso obliga a elegir clave): por Google no se saltea eso.
    Primero se busca por `google_sub` (sobrevive a un cambio de mail) y recién
    después por el mail, en minúsculas y sin espacios."""
    nombre_modelo, campo = _CUENTA_GOOGLE[rol]
    modelo = globals()[nombre_modelo]
    mail = (mail or "").strip().lower()
    sub = (sub or "").strip()
    if not mail or not sub:
        return "ninguna", 0, ""
    with Session(engine) as s:
        cuentas = s.exec(select(modelo).where(
            modelo.google_sub == sub, modelo.clave_hash != "")).all()
        if rol == "panel" and cuentas:
            # Una cuenta del panel sin ningún usuario activo no entra a nada.
            cuentas = [c for c in cuentas if sindicatos_del_operador(c.cuil)]
        if not cuentas:
            cuentas = _cuentas_con_mail(s, rol, mail, sub)
            # La unicidad se cuenta sobre TODAS las cuentas; recién después se
            # descarta la que ya tiene otro `sub`.
            if len(cuentas) == 1 and (cuentas[0].google_sub or ""):
                return "ninguna", 0, ""
        if not cuentas:
            return "ninguna", 0, ""
        if len(cuentas) > 1:
            return "varias", 0, ""
        c = cuentas[0]
        # La clave transitoria (la puso otra persona) obliga a elegir la propia
        # antes de abrir nada: por Google no se saltea.
        if getattr(c, "clave_temporal", False) or getattr(c, "debe_cambiar_clave", False):
            return "temporal", 0, ""
        return "ok", c.id, getattr(c, campo)


def entrar_con_google(rol: str, cuenta_id: int, sub: str, mail: str) -> None:
    """Deja asentado el ingreso con Google en la cuenta: el `sub` la primera vez
    (nunca lo pisa) y el mail, verificado por Google, como declarado y
    confirmado -- solo si `mail_declarado` está vacío o ya es ese mail; un
    declarado confirmado DISTINTO no se pisa. El nivel sube por el origen que
    corresponde: `mail_padron` si Google probó el mail que cargó el sindicato,
    y `mail_declarado` solo si la política de los sindicatos de la persona
    acepta mails declarados (misma regla que el registro)."""
    nombre_modelo, campo = _CUENTA_GOOGLE[rol]
    modelo = globals()[nombre_modelo]
    mail = (mail or "").strip().lower()
    with Session(engine) as s:
        c = s.get(modelo, cuenta_id)
        if not c:
            return
        if sub and not (c.google_sub or ""):
            c.google_sub = sub
        if rol == "panel":
            # El operador no tiene niveles ni mail declarado: si la cuenta no
            # tenía mail, queda el que Google verificó.
            if mail and not (c.mail or "").strip():
                c.mail = mail
            s.add(c)
            s.commit()
            return
        declarado = (c.mail_declarado or "").strip().lower()
        if mail and declarado in ("", mail):
            c.mail_declarado = mail
            if not (c.mail_declarado_confirmado or ""):
                c.mail_declarado_confirmado = fechas.ahora_texto()
            numero = getattr(c, campo)
            if rol == "trabajador":
                del_padron = (c.mail_padron or "").strip().lower() == mail
                acepta = acepta_mail_declarado(s, numero)
            else:
                del_padron = any((e.mail_padron or "").strip().lower() == mail for e in s.exec(
                    select(Empleador).where(Empleador.cuit == numero)).all())
                acepta = acepta_mail_declarado_empresa(s, numero)
            if del_padron:
                subir_nivel(s, c, "mail_padron")
            elif acepta:
                subir_nivel(s, c, "mail_declarado")
        s.add(c)
        if rol == "trabajador" and sub and _cuil_con_identidad_probada(c):
            # Una persona, una identidad de Google: si la misma persona tiene
            # cuenta del panel sin vincular, queda atada al mismo `sub`. Solo si
            # esta cuenta de afiliado PRUEBA quién es (ver SSO_ORIGENES_VALIDOS):
            # si no, un afiliado registrado con el CUIL ajeno se ataría el panel.
            cp = s.exec(select(CuentaPanel).where(CuentaPanel.cuil == c.cuil)).first()
            if cp and cp.clave_hash and not (cp.google_sub or ""):
                cp.google_sub = c.google_sub or sub
                s.add(cp)
        s.commit()


def importar_cuits_de_conceptos(sindicato_id: int, invalidos: Optional[list] = None) -> int:
    """CUITs distintos de Concepto.cuit_empleador de ESTE sindicato que
    todavía no tienen fila en Empleador -- crea una fila mínima (solo
    cuit) por cada uno, registrado=False, activo=True. Idempotente: se
    puede volver a correr cuando aparezcan CUITs nuevos en Conceptos
    (botón "Importar CUITs de conceptos" en el CRUD). Devuelve cuántos
    se agregaron.

    Acá NACE un empleador, así que su CUIT tiene que cumplir el módulo 11
    (PLAN_CUIT_MOD11.md, D2): los de un concepto que no lo cumplen (un
    dígito mal leído por la IA, casi siempre) no se importan, y si se pasa
    `invalidos` se agregan ahí para que la pantalla los muestre. Se compara
    normalizado: un concepto con '30-11122233-5' es el mismo empleador que
    '30111222335'."""
    with Session(engine) as s:
        conceptos = s.exec(select(Concepto).where(
            Concepto.sindicato_id == sindicato_id)).all()
        cuits_concepto = {
            cuit.normalizar(c.cuit_empleador) for c in conceptos
            if cuit.normalizar(c.cuit_empleador)
        }
        malos = sorted(n for n in cuits_concepto if not cuit.es_valido(n))
        if invalidos is not None:
            invalidos.extend(malos)
        existentes = {cuit.normalizar(e.cuit) for e in s.exec(select(Empleador).where(
            Empleador.sindicato_id == sindicato_id)).all()}
        nuevos = cuits_concepto - existentes - set(malos)
        for numero in nuevos:     # no `cuit`: taparía al módulo en toda la función
            s.add(Empleador(sindicato_id=sindicato_id, cuit=numero))
        s.commit()
        return len(nuevos)


def sindicatos_de_cuit_empleador(cuit: str) -> list:
    """Sindicatos donde este CUIT está dado de alta como Empleador activo --
    mismo patrón que sindicatos_de_cuil, para la resolución de sesión y el
    selector multisindicato del empleador."""
    with Session(engine) as s:
        altas = s.exec(select(Empleador).where(
            Empleador.cuit == cuit, Empleador.activo == True)).all()
        resultado = []
        for e in altas:
            sind = s.get(Sindicato, e.sindicato_id)
            if sind and sind.activo:
                resultado.append({"id": sind.id, "nombre": sind.nombre, "slug": sind.slug})
        return resultado


# ---------- Registro confirmado por mail: niveles y códigos (PLAN_REGISTRO.md) ----------
# Todos reciben la sesión y NO abren la suya (regla "una sesión por request").
# Ninguno hace commit (lo hace quien los llama, junto con el resto del acto),
# con UNA excepción con motivo: `verificar_codigo` (ver su docstring).
def subir_nivel(s, cuenta, origen: str) -> bool:
    """Sube la cuenta (CuentaTrabajador o CuentaEmpleador) al nivel que
    acredita `origen`. Única escritura de `nivel_fiabilidad`: el nivel SUBE y
    no baja, así que un recibo propio (3) posterior a la confirmación del
    sindicato (4) no lo rebaja. Devuelve True si cambió algo, False si la
    cuenta ya tenía ese nivel o más (y entonces no toca nada). Un origen que
    no está en ORIGENES_NIVEL es un error de programación: ValueError.

    Excepción (Q-5): si el nivel pedido es IGUAL al actual y la cuenta no
    tiene `nivel_origen` (una cuenta nueva, que nace en 1 sin origen), se
    registran el origen y la fecha y devuelve True. Así "nivel 1, CUIL en el
    padrón" queda escrito también en las cuentas nuevas, por el mismo y único
    camino, y no hace falta escribirlo a mano desde la ruta."""
    if origen not in ORIGENES_NIVEL:
        raise ValueError(f"origen de nivel desconocido: {origen!r}")
    nivel = ORIGENES_NIVEL[origen]
    actual = cuenta.nivel_fiabilidad or 1
    if nivel < actual or (nivel == actual and (cuenta.nivel_origen or "")):
        return False
    cuenta.nivel_fiabilidad = nivel
    cuenta.nivel_origen = origen
    cuenta.nivel_actualizado = fechas.ahora_texto()
    s.add(cuenta)
    return True


def mail_padron_de(s, cuil: str) -> str:
    """El mail que el SINDICATO cargó para este CUIL ("" si no hay): lee
    `mail_padron`, nunca `mail` (el de contacto, que la persona cambia desde
    su perfil) ni `mail_declarado`. Ver "Los TRES mails" en CuentaTrabajador."""
    c = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first()
    return (c.mail_padron or "").strip() if c else ""


def mail_padron_de_empresa(s, cuit: str) -> str:
    """El mail del padrón de una empresa: el primer `Empleador.mail_padron` no
    vacío entre sus altas, las activas primero (el empleador no está
    unificado, el mail es por sindicato). "" si ninguna lo tiene. Lee
    `mail_padron` (lo que cargó el sindicato), no `mail` (el contacto que
    edita la empresa)."""
    filas = s.exec(select(Empleador).where(Empleador.cuit == cuit)
                   .order_by(Empleador.activo.desc(), Empleador.id)).all()
    for e in filas:
        if (e.mail_padron or "").strip():
            return e.mail_padron.strip()
    return ""


def acepta_mail_declarado(s, cuil: str) -> bool:
    """¿Puede este CUIL registrarse declarando un mail propio? Solo si TODOS
    los sindicatos activos donde está empadronado lo aceptan: manda el más
    estricto, porque basta un gremio que pida "solo mail del padrón" para que
    el camino flojo no valga. Sin empadronamientos en un sindicato activo,
    False (no hay política que lo habilite)."""
    sindicatos = s.exec(select(Sindicato).join(
        Trabajador, Trabajador.sindicato_id == Sindicato.id).where(
        Trabajador.cuil == cuil, Sindicato.activo == True)).all()  # noqa: E712
    return bool(sindicatos) and all(x.acepta_mail_declarado for x in sindicatos)


def acepta_mail_declarado_empresa(s, cuit: str) -> bool:
    """Lo mismo para un CUIT, sobre los sindicatos activos donde tiene un
    alta de Empleador activa (el mismo criterio que
    `sindicatos_de_cuit_empleador`)."""
    sindicatos = s.exec(select(Sindicato).join(
        Empleador, Empleador.sindicato_id == Sindicato.id).where(
        Empleador.cuit == cuit, Empleador.activo == True,  # noqa: E712
        Sindicato.activo == True)).all()  # noqa: E712
    return bool(sindicatos) and all(x.acepta_mail_declarado for x in sindicatos)


def codigos_recientes(s, tipo: str, identificador: str, proposito: str, horas: int = 1) -> int:
    """Cuántos códigos se pidieron para esta persona y propósito en las
    últimas `horas`, usados o no (el cupo cuenta pedidos, no aciertos)."""
    desde = fechas.a_texto(fechas.ahora() - timedelta(hours=horas))
    filas = s.exec(select(CodigoVerificacion.id).where(
        CodigoVerificacion.tipo == tipo,
        CodigoVerificacion.identificador == identificador,
        CodigoVerificacion.proposito == proposito,
        CodigoVerificacion.creado >= desde)).all()
    return len(filas)


def codigos_recientes_destino(s, destino: str, horas: int = 1) -> int:
    """Cuántos códigos se mandaron a este mail en las últimas `horas`, de
    cualquier persona, tipo o propósito (el cupo cuenta pedidos). El cupo por
    persona no alcanza: quien conoce N CUIL sin mail en el padrón declara el
    mismo mail ajeno en todos y le manda 3 códigos por CUIL, a nombre de
    Colm3na y gastando los mails del mes. Se compara sin distinguir
    mayúsculas: `A@x.com` y `a@x.com` son la misma casilla."""
    from sqlalchemy import func
    desde = fechas.a_texto(fechas.ahora() - timedelta(hours=horas))
    filas = s.exec(select(CodigoVerificacion.id).where(
        func.lower(CodigoVerificacion.destino) == (destino or "").strip().lower(),
        CodigoVerificacion.creado >= desde)).all()
    return len(filas)


def _hash_codigo(codigo: str, identificador: str, creado: str) -> str:
    """HMAC-SHA256 con `auth.SECRETO` como clave (Q-4): sin el secreto del
    servidor el hash no se puede probar contra el millón de códigos posibles."""
    import auth       # adentro de la función: así db no queda atado al orden de carga de auth
    return hmac.new(auth.SECRETO.encode(), f"{codigo}:{identificador}:{creado}".encode(),
                    hashlib.sha256).hexdigest()


def crear_codigo(s, tipo: str, identificador: str, proposito: str, destino: str,
                 origen_destino: str, ip: str):
    """Genera un código de 6 dígitos (con `secrets`, con ceros a la
    izquierda), guarda SOLO su hash y devuelve (fila, codigo_en_claro) para
    mandarlo por mail. Antes vence los pendientes de la misma persona y
    propósito: un solo código vivo a la vez, así el que se pidió primero no
    queda abierto para adivinarlo mientras llega el segundo.

    Aplica los cupos él mismo (Q-3): si ya hay `CODIGOS_POR_HORA` pedidos en
    la última hora para esa persona y propósito, o `CODIGOS_POR_HORA_DESTINO`
    para ese mail (QA-REG-03), levanta `ErrorApp("E-REGISTRO-03")` sin crear
    nada. Las rutas NO lo chequean antes: lo resuelve acá, en un solo lugar,
    así ninguna se olvida de ninguno de los dos cupos ni se puede ganar 5
    intentos por código nuevo."""
    if (codigos_recientes(s, tipo, identificador, proposito) >= CODIGOS_POR_HORA
            or codigos_recientes_destino(s, destino) >= CODIGOS_POR_HORA_DESTINO):
        raise errores.ErrorApp("E-REGISTRO-03")
    ahora = fechas.ahora()
    ahora_t = fechas.a_texto(ahora)
    pendientes = s.exec(select(CodigoVerificacion).where(
        CodigoVerificacion.tipo == tipo,
        CodigoVerificacion.identificador == identificador,
        CodigoVerificacion.proposito == proposito,
        CodigoVerificacion.usado_en == "",
        CodigoVerificacion.vence > ahora_t)).all()
    for viejo in pendientes:
        viejo.vence = ahora_t
        s.add(viejo)
    codigo = f"{secrets.randbelow(10 ** 6):06d}"
    fila = CodigoVerificacion(
        tipo=tipo, identificador=identificador, proposito=proposito,
        destino=destino, origen_destino=origen_destino,
        codigo_hash=_hash_codigo(codigo, identificador, ahora_t),
        creado=ahora_t,
        vence=fechas.a_texto(ahora + timedelta(minutes=CODIGO_VIGENCIA_MINUTOS)),
        ip=ip)
    s.add(fila)
    s.flush()
    return fila, codigo


def verificar_codigo(s, codigo_id: int, codigo: str) -> str:
    """Comprueba un código contra su fila. Devuelve "inexistente", "usado",
    "vencido", "agotado" (ya gastó sus 5 intentos: ni el código correcto
    sirve), "incorrecto" (suma un intento) u "ok" (lo marca usado). Se
    consulta en ese orden, así que un código usado o vencido no gasta
    intentos.

    **EXCEPCIÓN con motivo a "ningún helper hace commit" (Q-1)**: acá SÍ se
    hace commit, tras "incorrecto" y tras "ok" (y en las demás salidas, solo para
    soltar el bloqueo de la fila). El idioma de las rutas es
    `with db.get_session() as s:` + `raise ErrorApp(...)`, y al salir del with
    sin commit la sesión hace rollback: el intento fallido se perdía y el tope
    de 5 intentos no existía (el código se podía tantear durante los 15
    minutos). Un contador de seguridad no puede depender de que cada ruta se
    acuerde de confirmar. Efecto lateral aceptado: el commit confirma también
    lo que la sesión llevara pendiente; las rutas llaman a esto primero.

    **Lectura con bloqueo de fila (Q-2)**: `SELECT ... FOR UPDATE`, así dos
    requests simultáneos con el mismo código se serializan: los dos intentos
    erróneos cuentan dos (no uno) y un código correcto se consume UNA sola
    vez. El bloqueo se suelta con ese mismo commit."""
    fila = s.exec(select(CodigoVerificacion).where(
        CodigoVerificacion.id == codigo_id).with_for_update()).first()
    if not fila:
        return "inexistente"
    if fila.usado_en:
        s.commit()            # suelta el bloqueo de la fila
        return "usado"
    ahora_t = fechas.ahora_texto()
    if fila.vence <= ahora_t:
        s.commit()
        return "vencido"
    if fila.intentos >= CODIGO_MAX_INTENTOS:
        s.commit()
        return "agotado"
    esperado = _hash_codigo((codigo or "").strip(), fila.identificador, fila.creado)
    if not hmac.compare_digest(esperado, fila.codigo_hash):
        fila.intentos += 1
        s.add(fila)
        s.commit()
        return "incorrecto"
    fila.usado_en = ahora_t
    s.add(fila)
    s.commit()
    return "ok"


def perfil_empleador(cuit: str, sindicato_id: int) -> Optional[dict]:
    """Datos propios de la empresa para mostrarle su perfil -- mismo criterio
    que perfil_trabajador. Editable desde /api/empresa/perfil (ver
    actualizar_perfil_empleador) -- todo menos el CUIT."""
    with Session(engine) as s:
        e = s.exec(select(Empleador).where(
            Empleador.cuit == cuit, Empleador.sindicato_id == sindicato_id)).first()
        if not e:
            return None
        return {
            "razon_social": e.razon_social, "cuit": e.cuit, "domicilio": e.domicilio,
            "telefono": e.telefono, "provincia": e.provincia, "mail": e.mail,
        }


def actualizar_perfil_empleador(cuit: str, sindicato_id: int, razon_social: str, domicilio: str,
                                 telefono: str, provincia: str, mail: str) -> bool:
    """La empresa edita sus propios datos -- todo menos el CUIT (identidad,
    no se toca acá). Actualiza SOLO el alta del sindicato ACTIVO -- Empleador
    es por sindicato (multisindicato), mismo criterio que
    actualizar_perfil_trabajador."""
    with Session(engine) as s:
        e = s.exec(select(Empleador).where(
            Empleador.cuit == cuit, Empleador.sindicato_id == sindicato_id)).first()
        if not e:
            return False
        e.razon_social = (razon_social or "").strip()[:200] or e.razon_social
        e.domicilio = domicilio.strip()[:200]
        e.telefono, e.provincia, e.mail = telefono.strip()[:40], provincia.strip()[:60], mail.strip()[:200]
        s.add(e)
        s.commit()
        return True


def foto_empleador(cuit: str) -> Optional[dict]:
    """Foto de perfil (una por CUIT, no por sindicato -- ver CuentaEmpleador)."""
    with Session(engine) as s:
        c = s.exec(select(CuentaEmpleador).where(CuentaEmpleador.cuit == cuit)).first()
        if not c or not c.foto_datos:
            return None
        return {"datos": c.foto_datos, "mime": c.foto_mime or "image/jpeg"}


def guardar_foto_empleador(cuit: str, datos: bytes, mime: str) -> bool:
    with Session(engine) as s:
        c = s.exec(select(CuentaEmpleador).where(CuentaEmpleador.cuit == cuit)).first()
        if not c:
            return False
        c.foto_datos, c.foto_mime = datos, mime
        s.add(c)
        s.commit()
        return True


def marca_sindicato(sindicato_id: int) -> dict:
    """Devuelve la marca (nombre, logo, colores) de un sindicato para pintar la app."""
    from sqlalchemy import func
    with Session(engine) as s:
        # Sin el logo, la firma ni el contrato: esta función corre en cada
        # pantalla. El largo en bytes lo calcula la base.
        fila = s.exec(select(Sindicato,
                             func.coalesce(func.octet_length(Sindicato.logo_datos), 0),
                             func.coalesce(func.octet_length(Sindicato.firma_datos), 0))
                      .options(*_sin_bytes(Sindicato))
                      .where(Sindicato.id == sindicato_id)).first()
        if not fila:
            return {}
        sind, logo_v, firma_v = fila
        return {
            "id": sind.id, "nombre": sind.nombre, "logo": sind.logo,
            # Sello de versión (largo del binario) para romper el cache del
            # navegador cuando se reemplaza el logo/firma -- sin esto, /logo/{id}
            # y /firma/{id} son la MISMA url antes y después de subir uno nuevo,
            # y el Cache-Control:max-age=3600 de esas rutas seguía sirviendo la
            # imagen vieja hasta que expiraba solo.
            "logo_v": logo_v, "firma_v": firma_v,
            "color_primario": sind.color_primario,
            "color_secundario": sind.color_secundario,
            "color_acento": sind.color_acento,
            "color_base": sind.color_base,
            "color_destacado": sind.color_destacado or "#E5188F",
            # Para la credencial sindical del trabajador
            "autoridad": sind.autoridad, "cargo_autoridad": sind.cargo_autoridad,
            "firma": sind.firma,
            "direccion": sind.direccion, "telefonos": sind.telefonos,
        }


def _cuenta_con_tema(rol: str):
    """La tabla y la columna que identifican a la persona de cada rol con su
    modelo de diseño guardado: el afiliado y el operador por CUIL, la empresa
    por CUIT."""
    if rol == "panel":
        return CuentaPanel, CuentaPanel.cuil
    if rol == "empresa":
        return CuentaEmpleador, CuentaEmpleador.cuit
    return CuentaTrabajador, CuentaTrabajador.cuil


def apariencia_de(sindicato_id, cuil: str = "", rol: str = "afiliado", uid=None) -> dict:
    """El modelo de diseño y la paleta con que se pinta una página
    (PLAN_TEMAS.md). `rol` es "afiliado", "panel" o "empresa": cada uno tiene
    su propia elección guardada en su cuenta. El default del panel es
    `Sindicato.tema_panel`; el del afiliado y el de la empresa (un actor
    externo, con una app que se parece a la del afiliado) es
    `Sindicato.tema_afiliados`. Para la empresa, `cuil` es su CUIT. Abre su
    sesión: la llaman las rutas de página, que no tienen una abierta."""
    import temas
    with Session(engine) as s:
        sind = s.get(Sindicato, sindicato_id, options=_sin_bytes(Sindicato)) if sindicato_id else None
        defecto = (sind.tema_panel if rol == "panel" else sind.tema_afiliados) if sind else None
        propio = ""
        if not cuil and uid and rol == "panel":
            usuario = s.get(UsuarioSindicato, uid)
            cuil = usuario.cuil if usuario else ""
        if cuil:
            modelo, columna = _cuenta_con_tema(rol)
            cuenta = s.exec(select(modelo).options(*_sin_bytes(modelo)).where(columna == cuil)).first()
            propio = cuenta.tema if cuenta else ""
        return {
            "tema": temas.resolver_tema(propio, defecto),
            "paleta": temas.resolver_paleta(sind.paleta_tema if sind else None),
            "elegido": temas.tema_valido(propio) or "",
            "defecto": temas.resolver_tema(None, defecto),
        }


def guardar_tema_persona(cuil: str, tema: str, rol: str = "afiliado") -> bool:
    """Guarda en la CUENTA el modelo que eligió la persona (D2). "" vuelve al
    del sindicato. False si el modelo no existe o la persona no tiene cuenta:
    nunca se guarda un valor fuera del catálogo. Para `rol="empresa"`, `cuil`
    es el CUIT de la cuenta del empleador."""
    import temas
    valor = "" if tema in ("", None) else temas.tema_valido(tema)
    if valor is None:
        return False
    modelo, columna = _cuenta_con_tema(rol)
    with Session(engine) as s:
        cuenta = s.exec(select(modelo).where(columna == cuil)).first()
        if not cuenta:
            return False
        cuenta.tema = valor
        s.add(cuenta)
        s.commit()
        return True


def apariencia_plataforma(uid) -> dict:
    """El modelo y la paleta del panel de plataforma para el usuario `uid`
    (PLAN_TEMAS.md). La paleta es SIEMPRE la de Colm3na: plataforma no tiene
    sindicato. El genérico de transición (uid 0) no tiene cuenta propia y ve
    el modelo por defecto. Abre su sesión: la llaman las rutas de página
    después de cerrar la suya."""
    import temas
    propio = ""
    if uid:
        with Session(engine) as s:
            u = s.get(UsuarioPlataforma, uid)
            propio = u.tema if u else ""
    return {
        "tema": temas.resolver_tema(propio),
        "paleta": temas.PALETA_DEFECTO,
        "elegido": temas.tema_valido(propio) or "",
        "defecto": temas.TEMA_DEFECTO,
    }


def guardar_tema_plataforma(uid, tema: str) -> bool:
    """Guarda el modelo que eligió un usuario de plataforma. "" vuelve al por
    defecto. False si el modelo no existe o el usuario no está: nunca se
    guarda un valor fuera del catálogo."""
    import temas
    valor = "" if tema in ("", None) else temas.tema_valido(tema)
    if valor is None or not uid:
        return False
    with Session(engine) as s:
        u = s.get(UsuarioPlataforma, uid)
        if not u:
            return False
        u.tema = valor
        s.add(u)
        s.commit()
        return True


def set_apariencia_sindicato(sindicato_id: int, tema_afiliados=None, tema_panel=None, paleta=None) -> bool:
    """Los defaults de apariencia del sindicato (D3). Solo cambia lo que viene
    y valida contra el catálogo: un valor desconocido no se guarda."""
    import temas
    cambios = {}
    for campo, valor, validar in (("tema_afiliados", tema_afiliados, temas.tema_valido),
                                  ("tema_panel", tema_panel, temas.tema_valido),
                                  ("paleta_tema", paleta, temas.paleta_valida)):
        if valor is None:
            continue
        v = validar(valor)
        if v is None:
            return False
        cambios[campo] = v
    with Session(engine) as s:
        sind = s.get(Sindicato, sindicato_id)
        if not sind:
            return False
        for campo, v in cambios.items():
            setattr(sind, campo, v)
        s.add(sind)
        s.commit()
        return True


def crear_foto_tema(tema: str, normalizada: dict, descripcion: str = "", subida_por: str = "",
                    foco_x: float = 0.5, foco_y: float = 0.5, sindicato_id: Optional[int] = None) -> int:
    """Guarda una foto YA normalizada. Sin `sindicato_id` es de la biblioteca
    global de plataforma y queda como borrador del modelo; con `sindicato_id`
    es PROPIA de ese sindicato y queda disponible para él desde ya."""
    with Session(engine) as s:
        f = FotoTema(tema=tema, datos=normalizada["datos"], mime=normalizada["mime"],
                     datos_color=normalizada.get("datos_color"),
                     mime_color=normalizada.get("mime_color") or "image/webp",
                     ancho=normalizada["ancho"], alto=normalizada["alto"],
                     foco_x=_entre_0_y_1(foco_x), foco_y=_entre_0_y_1(foco_y),
                     descripcion=(descripcion or "").strip()[:300],
                     creada=fechas.ahora_texto(), subida_por=subida_por)
        if sindicato_id is not None:
            f.sindicato_id = sindicato_id
            f.publicada, f.todos_los_sindicatos, f.sindicatos = True, False, [sindicato_id]
        s.add(f)
        s.commit()
        s.refresh(f)
        return f.id


def _entre_0_y_1(v) -> float:
    try:
        return min(1.0, max(0.0, float(v)))
    except (TypeError, ValueError):
        return 0.5


def _foto_dict(f: "FotoTema", v: int, v_color: int) -> dict:
    """`v` y `v_color` son los largos en bytes calculados en SQL (sello de
    versión de la url y «¿tiene color?»): la lista no trae las fotos."""
    return {"id": f.id, "tema": f.tema, "ancho": f.ancho, "alto": f.alto,
            "foco_x": f.foco_x, "foco_y": f.foco_y, "descripcion": f.descripcion,
            "publicada": f.publicada, "todos_los_sindicatos": f.todos_los_sindicatos,
            "sindicatos": list(f.sindicatos or []), "creada": f.creada,
            "subida_por": f.subida_por, "v": v or 0,
            "color": bool(v_color), "v_color": v_color or 0,
            "propia": f.sindicato_id is not None}


def _foto_del_ambito(s, foto_id: int, sindicato_id: Optional[int]):
    """La fila `foto_id` SOLO si pertenece al ámbito pedido: `sindicato_id`
    None = la biblioteca global de plataforma; un id = las propias de ese
    sindicato. Una foto de otro ámbito es como si no existiera (None): así
    ni plataforma toca las propias de un sindicato por la ruta de la
    biblioteca, ni un sindicato toca las ajenas o las globales."""
    f = s.get(FotoTema, foto_id)
    if f is None or f.sindicato_id != sindicato_id:
        return None
    return f


def reemplazar_archivo_foto_tema(foto_id: int, normalizada: dict, sindicato_id: Optional[int] = None) -> bool:
    """Se vuelve a subir el archivo de una foto que ya existe (las
    de antes del 2026-10-29 no tienen versión en color): cambian las dos
    versiones y el tamaño; quedan el id, el foco, la descripción, la
    publicación y la disponibilidad, así los sindicatos que la eligieron
    no tienen que volver a elegirla. `sindicato_id`: el ámbito, ver
    `_foto_del_ambito`."""
    with Session(engine) as s:
        f = _foto_del_ambito(s, foto_id, sindicato_id)
        if not f:
            return False
        f.datos, f.mime = normalizada["datos"], normalizada["mime"]
        f.datos_color = normalizada.get("datos_color")
        f.mime_color = normalizada.get("mime_color") or "image/webp"
        f.ancho, f.alto = normalizada["ancho"], normalizada["alto"]
        s.add(f)
        s.commit()
        return True


def fotos_de_tema(tema: str, sindicato_id: Optional[int] = None) -> list:
    """Las fotos de un modelo, sin los bytes. Sin `sindicato_id`, la
    biblioteca global de plataforma (las propias de los sindicatos NO
    entran); con un id, solo las propias de ese sindicato."""
    from sqlalchemy import func
    with Session(engine) as s:
        consulta = select(FotoTema,
                          func.coalesce(func.octet_length(FotoTema.datos), 0),
                          func.coalesce(func.octet_length(FotoTema.datos_color), 0)).where(FotoTema.tema == tema)
        consulta = consulta.where(FotoTema.sindicato_id.is_(None) if sindicato_id is None
                                  else FotoTema.sindicato_id == sindicato_id)
        filas = s.exec(consulta.order_by(FotoTema.id.desc())).all()
        return [_foto_dict(f, v, v_color) for f, v, v_color in filas]


def fotos_disponibles(sindicato_id: int, tema: str) -> list:
    """Las fotos de un modelo que puede usar un sindicato: primero las
    PROPIAS (las más nuevas arriba) y después las de la biblioteca global
    que están publicadas para él."""
    globales = [f for f in fotos_de_tema(tema)
                if f["publicada"] and (f["todos_los_sindicatos"] or sindicato_id in f["sindicatos"])]
    return fotos_de_tema(tema, sindicato_id) + globales


def foto_tema(foto_id: int):
    """La fila completa (CON los bytes, que por defecto quedan diferidos) o
    None. Es la que usan las rutas que sirven la foto."""
    from sqlalchemy.orm import undefer
    with Session(engine) as s:
        return s.get(FotoTema, foto_id, options=[undefer(FotoTema.datos), undefer(FotoTema.datos_color)])


def editar_foto_tema(foto_id: int, sindicato_id: Optional[int] = None, **campos) -> bool:
    """Cambia descripción, foco, publicación y disponibilidad. Los ids de
    sindicatos que no existen se descartan. `sindicato_id`: el ámbito (ver
    `_foto_del_ambito`); en una foto propia solo valen descripción y foco:
    no hay borrador ni alcance que cambiar."""
    with Session(engine) as s:
        f = _foto_del_ambito(s, foto_id, sindicato_id)
        if not f:
            return False
        if "descripcion" in campos:
            f.descripcion = (campos["descripcion"] or "").strip()[:300]
        for eje in ("foco_x", "foco_y"):
            if eje in campos:
                setattr(f, eje, _entre_0_y_1(campos[eje]))
        if sindicato_id is None:
            if "publicada" in campos:
                f.publicada = bool(campos["publicada"])
            if "todos_los_sindicatos" in campos:
                f.todos_los_sindicatos = bool(campos["todos_los_sindicatos"])
            if "sindicatos" in campos:
                pedidos = {int(x) for x in (campos["sindicatos"] or []) if str(x).isdigit()}
                existentes = set(s.exec(select(Sindicato.id).where(Sindicato.id.in_(pedidos))).all()) if pedidos else set()
                f.sindicatos = sorted(existentes)
        s.add(f)
        s.commit()
        return True


def borrar_foto_tema(foto_id: int, sindicato_id: Optional[int] = None) -> bool:
    """Borra la foto y la saca de las portadas que la usaban. `sindicato_id`:
    el ámbito (ver `_foto_del_ambito`)."""
    with Session(engine) as s:
        f = _foto_del_ambito(s, foto_id, sindicato_id)
        if not f:
            return False
        for sind in s.exec(select(Sindicato)).all():
            portadas = dict(sind.fotos_portada or {})
            if foto_id in portadas.values():
                sind.fotos_portada = {k: v for k, v in portadas.items() if v != foto_id}
                s.add(sind)
        s.delete(f)
        s.commit()
        return True


def elegir_foto_portada(sindicato_id: int, tema: str, foto_id) -> bool:
    """El sindicato elige su foto de portada para un modelo. None la saca.
    Solo vale una foto publicada, de ese modelo y disponible para él."""
    import temas
    if temas.tema_valido(tema) is None:
        return False
    if foto_id is not None and foto_id not in {f["id"] for f in fotos_disponibles(sindicato_id, tema)}:
        return False
    with Session(engine) as s:
        sind = s.get(Sindicato, sindicato_id)
        if not sind:
            return False
        portadas = dict(sind.fotos_portada or {})
        if foto_id is None:
            portadas.pop(tema, None)
        else:
            portadas[tema] = foto_id
        sind.fotos_portada = portadas
        s.add(sind)
        s.commit()
        return True


def _elegir_nivel_color(sindicato_id: int, campo: str, tema: str, nivel) -> bool:
    import fotos_tema
    import temas
    n = fotos_tema.saturacion_valida(nivel)
    if temas.tema_valido(tema) is None or n is None:
        return False
    with Session(engine) as s:
        sind = s.get(Sindicato, sindicato_id)
        if not sind:
            return False
        niveles = dict(getattr(sind, campo) or {})
        niveles[tema] = n
        setattr(sind, campo, niveles)
        s.add(sind)
        s.commit()
        return True


def _nivel_color_de(sindicato_id: int, campo: str, tema: str) -> int:
    import fotos_tema
    with Session(engine) as s:
        sind = s.get(Sindicato, sindicato_id)
        guardado = (getattr(sind, campo) or {}).get(tema) if sind else None
    n = fotos_tema.saturacion_valida(guardado)
    return fotos_tema.SATURACION_DEFECTO if n is None else n


def elegir_saturacion_foto(sindicato_id: int, tema: str, nivel) -> bool:
    """El sindicato elige cuánto color muestra la foto de portada de un
    modelo (`fotos_tema.SATURACIONES`). Un nivel fuera del catálogo o un
    modelo que no existe no se guardan."""
    return _elegir_nivel_color(sindicato_id, "saturacion_fotos", tema, nivel)


def saturacion_foto_de(sindicato_id: int, tema: str) -> int:
    """El nivel de color elegido para un modelo; un valor que no está en el
    catálogo (o nada) vale el por defecto, la normalizada sola."""
    return _nivel_color_de(sindicato_id, "saturacion_fotos", tema)


def elegir_saturacion_publicaciones(sindicato_id: int, tema: str, nivel) -> bool:
    """Lo mismo para las fotos de Noticias y Beneficios en la portada."""
    return _elegir_nivel_color(sindicato_id, "saturacion_publicaciones", tema, nivel)


def saturacion_publicaciones_de(sindicato_id: int, tema: str) -> int:
    return _nivel_color_de(sindicato_id, "saturacion_publicaciones", tema)


def normalizada_o_none(datos) -> Optional[bytes]:
    """La versión normalizada de una imagen de noticia o beneficio, o None
    si no hay imagen o no se pudo leer (la pantalla cae a la de color)."""
    import fotos_tema
    if not datos:
        return None
    try:
        return fotos_tema.normalizar_imagen(datos)["datos"]
    except fotos_tema.FotoInvalida:
        return None


def imagen_normalizada(modelo, fila_id: int, campo: str):
    """Los bytes normalizados de `campo` (imagen1 / imagen2 / imagen) de una
    Noticia o un Beneficio. Las filas de antes del 2026-10-29 no los tienen:
    se calculan la primera vez que se piden y quedan guardados. Devuelve
    (datos, mime) o (None, "") sin imagen; si la imagen no se pudo leer,
    devuelve la de color tal cual (la hoja del modelo la pasa a gris)."""
    with Session(engine) as s:
        fila = s.get(modelo, fila_id)
        if not fila:
            return None, ""
        original = getattr(fila, f"{campo}_datos")
        if not original:
            return None, ""
        norm = getattr(fila, f"{campo}_norm")
        if not norm:
            norm = normalizada_o_none(original)
            if norm:
                setattr(fila, f"{campo}_norm", norm)
                s.add(fila)
                s.commit()
        if norm:
            return norm, "image/webp"
        return original, getattr(fila, f"{campo}_mime") or "application/octet-stream"


def foto_portada_de(sindicato_id: int, tema: str):
    """La foto de portada que se muestra: la elegida si sigue disponible; si
    no, la más nueva publicada para ese sindicato; None si no hay ninguna."""
    disponibles = fotos_disponibles(sindicato_id, tema)
    if not disponibles:
        return None
    with Session(engine) as s:
        sind = s.get(Sindicato, sindicato_id)
        elegida = (sind.fotos_portada or {}).get(tema) if sind else None
    for f in disponibles:
        if f["id"] == elegida:
            return f
    return disponibles[0]


def modulos_habilitados(sindicato_id: int) -> list:
    """Módulos que tiene disponibles este sindicato (ver modulos.py). Lista
    vacía si el sindicato no existe -- no rompe, simplemente no muestra nada."""
    with Session(engine) as s:
        sind = s.get(Sindicato, sindicato_id)
        return list(sind.modulos_habilitados or []) if sind else []


def modulo_habilitado(sindicato_id: int, modulo: str) -> bool:
    return modulo in modulos_habilitados(sindicato_id)


def set_modulos_sindicato(sindicato_id: int, modulos: list) -> None:
    """Persiste la lista de módulos habilitados, descartando cualquier valor
    que no esté en el catálogo (defensivo, mismo criterio que
    _destinos_validos en main.py para seccionales ajenas)."""
    from modulos import MODULOS
    validos = [m for m in (modulos or []) if m in MODULOS]
    with Session(engine) as s:
        sind = s.get(Sindicato, sindicato_id)
        if not sind:
            return
        sind.modulos_habilitados = validos
        s.add(sind)
        s.commit()


# ---------- Permisos del panel del sindicato (ver permisos.py) ----------

def permisos_efectivos(usuario_id: int) -> set:
    """Secciones del panel que este usuario puede tocar, ahora mismo.

    Se calcula CONTRA LA BASE en cada llamada y nunca se guarda en la
    cookie de sesión: si los permisos viajaran en el token firmado,
    quitarle un permiso a alguien no tendría efecto hasta que se le venciera
    la sesión. El middleware ya reemite la cookie en cada request, así que
    el costo real es una consulta más.

    Devuelve set() para un usuario inexistente o dado de baja -- sin
    excepción: quien llama decide si eso es un 403 o simplemente no mostrar
    nada."""
    from permisos import calcular_efectivos, secciones_de_modulos, SECCIONES_EMPLEADORES
    with Session(engine) as s:
        u = s.get(UsuarioSindicato, usuario_id)
        if not u or not u.activo:
            return set()
        # ¿Está ACOTADO a una seccional? (la misma regla que alcance_seccional,
        # resuelta con esta sesión para no abrir otra.) Quien lo está no ve
        # Empleadores: no tienen seccional (PLAN_ALCANCE_SECCIONAL.md, bloque 5).
        sec = s.get(Seccional, u.seccional_id) if u.seccional_id else None
        acotado = not u.es_super_admin and not (sec and sec.sindicato_id == u.sindicato_id
                                                 and sec.ve_todas)
        def _recortar(secciones: set) -> set:
            return secciones - SECCIONES_EMPLEADORES if acotado else secciones
        # Los módulos se leen con ESTA sesión. Llamar a modulos_habilitados()
        # abría una segunda conexión con la primera todavía tomada, y como
        # esto corre en cada ruta /admin/* (vía exigir_sindicato), cada request
        # del panel retenía dos conexiones del pool desde el primer instante:
        # con un pool de 10 alcanzaban cinco requests en vuelo para trabarlo.
        sind = s.get(Sindicato, u.sindicato_id)
        mods = list(sind.modulos_habilitados or []) if sind else []
        # El Super Admin tiene todo lo que el sindicato tenga contratado --
        # pero pasa por el mismo filtro de módulos que los demás, así un
        # módulo apagado no le deja secciones colgadas.
        #
        # El Admin de Seccional tiene EXACTAMENTE LAS MISMAS SECCIONES: es
        # "el admin grande en chiquito", y lo que lo achica no es la lista
        # de secciones sino el ALCANCE (alcance_seccional) y los chequeos de
        # las rutas que administran áreas y usuarios. Separar las dos cosas
        # es lo que hace que no haya dos catálogos que mantener.
        if u.es_super_admin or u.es_admin_seccional:
            return _recortar(set(secciones_de_modulos(mods)))
        del_area = []
        if u.area_id:
            area = s.get(Area, u.area_id)
            # Un área desactivada no da permisos: es la forma de cortarle el
            # acceso a todo un equipo de una, sin tocar usuario por usuario.
            if area and area.sindicato_id == u.sindicato_id and area.activo:
                del_area = [x.seccion for x in s.exec(
                    select(PermisoArea).where(PermisoArea.area_id == u.area_id)).all()]
        individuales = s.exec(select(PermisoUsuario).where(
            PermisoUsuario.usuario_id == usuario_id)).all()
        agregados = [x.seccion for x in individuales if x.tipo == "agregar"]
        bloqueados = [x.seccion for x in individuales if x.tipo == "bloquear"]
        return _recortar(calcular_efectivos(del_area, agregados, bloqueados, mods))


def es_acotado(usuario_id: int) -> bool:
    """¿Este usuario trabaja acotado a una seccional? (alcance_seccional
    distinto de None.) Lo usan las reglas de solo lectura del catálogo."""
    return alcance_seccional(usuario_id) is not None


def tiene_permiso(usuario_id: int, seccion: str) -> bool:
    return seccion in permisos_efectivos(usuario_id)


def es_super_admin(usuario_id: int) -> bool:
    """La llave de la gestión de áreas y usuarios. Se lee de la base en cada
    request por lo mismo que los permisos: degradar a alguien tiene que
    valer ya, no cuando se le venza la sesión."""
    with Session(engine) as s:
        u = s.get(UsuarioSindicato, usuario_id)
        return bool(u and u.activo and u.es_super_admin)


def es_admin_seccional(usuario_id: int) -> bool:
    """El rol intermedio: administra su seccional y nada más."""
    with Session(engine) as s:
        u = s.get(UsuarioSindicato, usuario_id)
        return bool(u and u.activo and u.es_admin_seccional and not u.es_super_admin)


def administra_areas_y_usuarios(usuario_id: int) -> bool:
    """Quién puede entrar a la pantalla de Áreas y Usuarios.

    Los dos roles de administrador, no solo el Super Admin. Lo que los
    distingue NO es el acceso a la pantalla sino el ALCANCE de lo que ven y
    pueden tocar ahí adentro, que lo imponen las rutas (ver
    _exigir_alcance_area / _exigir_alcance_usuario en main.py).

    Existe como función propia y no como `es_super_admin or
    es_admin_seccional` escrito en cada lado: cuando mañana haya que sumar
    o sacar un rol, se cambia acá y no en ocho rutas."""
    with Session(engine) as s:
        u = s.get(UsuarioSindicato, usuario_id)
        return bool(u and u.activo and (u.es_super_admin or u.es_admin_seccional))


def contar_super_admins(sindicato_id: int, excluyendo: int = 0) -> int:
    """Super Admins activos del sindicato, sin contar a `excluyendo`.

    Existe para el guard del último: antes del sistema de Áreas alcanzaba
    con contar usuarios activos, pero ahora un sindicato puede tener diez
    usuarios de área y un solo Super Admin -- y si se lo desactiva o se lo
    degrada, nadie puede volver a entrar a administrar."""
    with Session(engine) as s:
        filas = s.exec(select(UsuarioSindicato).where(
            UsuarioSindicato.sindicato_id == sindicato_id,
            UsuarioSindicato.activo == True,
            UsuarioSindicato.es_super_admin == True)).all()
        return len([u for u in filas if u.id != excluyendo])


def alcance_seccional(usuario_id: int):
    """Sobre qué seccionales trabaja este usuario.

    - `None`  = todas (Super Admin, o seccional con ve_todas tildado).
    - `{id}`  = solo esa seccional.
    - `set()` = ninguna.

    El set vacío es el caso defensivo del usuario de área al que le falta la
    seccional: desde el sistema de Áreas la seccional es obligatoria, así
    que si igual falta preferimos que no vea NADA antes que verlo todo --
    un dato incompleto no puede terminar en más permisos de los que
    corresponden. Devolver None ahí sería justamente eso.

    Se usa para recortar tanto los trámites que ve como los trabajadores a
    los que puede notificar: una sola regla de alcance para todo el panel."""
    with Session(engine) as s:
        u = s.get(UsuarioSindicato, usuario_id)
        if not u or not u.activo:
            return set()
        if u.es_super_admin:
            return None
        if not u.seccional_id:
            return set()
        sec = s.get(Seccional, u.seccional_id)
        if not sec or sec.sindicato_id != u.sindicato_id:
            return set()
        # Vale la MISMA regla para el admin de seccional que para un usuario
        # de área: su alcance es su seccional, salvo que esa seccional tenga
        # ve_todas. Un admin local de una regional que supervisa a otras
        # alcanza a todas, y eso es lo correcto -- una sola regla de alcance
        # para todo el panel, no una por rol.
        return None if sec.ve_todas else {u.seccional_id}


# ---------- Configuración de plataforma ----------
def obtener_tope_sindical() -> float:
    with Session(engine) as s:
        cfg = s.get(ConfiguracionPlataforma, 1)
        return cfg.tope_sindical_pct if cfg else 2.0


def set_tope_sindical(valor: float):
    with Session(engine) as s:
        cfg = s.get(ConfiguracionPlataforma, 1)
        if cfg:
            cfg.tope_sindical_pct = valor
        else:
            cfg = ConfiguracionPlataforma(id=1, tope_sindical_pct=valor)
        s.add(cfg)
        s.commit()


def config_dashboard() -> dict:
    """Parámetros de plataforma del Panel Sindical (docs/DASHBOARD.md §2.3):
    umbrales del semáforo de aportes y feature flag del carril de consultas.
    Defaults si la fila de configuración todavía no existe."""
    with Session(engine) as s:
        cfg = s.get(ConfiguracionPlataforma, 1)
        if not cfg:
            return {"semaforo_verde_hasta_dias": 35, "semaforo_amarillo_hasta_dias": 60,
                    "consultas_bot_habilitado": False}
        return {
            "semaforo_verde_hasta_dias": cfg.semaforo_verde_hasta_dias,
            "semaforo_amarillo_hasta_dias": cfg.semaforo_amarillo_hasta_dias,
            "consultas_bot_habilitado": cfg.dashboard_consultas_bot_habilitado,
        }


def set_config_dashboard(verde_hasta: int, amarillo_hasta: int, bot_habilitado: bool) -> None:
    """Editable SOLO desde el panel de plataforma (mismo criterio que el tope
    sindical). Se valida acá que verde < amarillo -- si no, se ignora el cambio."""
    if not (0 < verde_hasta < amarillo_hasta):
        return
    with Session(engine) as s:
        cfg = s.get(ConfiguracionPlataforma, 1) or ConfiguracionPlataforma(id=1)
        cfg.semaforo_verde_hasta_dias = verde_hasta
        cfg.semaforo_amarillo_hasta_dias = amarillo_hasta
        cfg.dashboard_consultas_bot_habilitado = bot_habilitado
        s.add(cfg)
        s.commit()


def modelos_ia() -> dict:
    """{uso: modelo_id} para los usos de precios_ia.USOS, ya resuelto:
    lo que eligió plataforma o, si no eligió nada, el default del módulo.
    Quien llama nunca tiene que preguntarse si hay configuración."""
    with Session(engine) as s:
        cfg = s.get(ConfiguracionPlataforma, 1)
        elegidos = {
            "recibos": (cfg.modelo_recibos if cfg else "") or "",
            "convenio": (cfg.modelo_convenio if cfg else "") or "",
            "asistente": (cfg.modelo_asistente if cfg else "") or "",
            "asistente_tramites": (cfg.modelo_asistente_tramites if cfg else "") or "",
        }
    return {uso: elegidos.get(uso) or precios_ia.default_de(uso) for uso in precios_ia.USOS}


def modelo_ia(uso: str) -> str:
    """El modelo vigente de UN uso. Se lee en cada llamada a propósito:
    cambiarlo desde el panel tiene que valer para el próximo recibo, no para
    el próximo reinicio del servidor (Render corre un worker por núcleo, así
    que una variable en memoria quedaría distinta en cada uno)."""
    return modelos_ia().get(uso, precios_ia.default_de(uso))


def set_modelos_ia(elegidos: dict) -> None:
    """Guarda los modelos elegidos. Un id que no está en el catálogo se
    IGNORA y el uso queda como estaba: un modelo mal escrito no falla acá,
    falla con un 400 de la API en la pantalla del trabajador que sube el
    recibo, que es el peor lugar posible para enterarse."""
    with Session(engine) as s:
        cfg = s.get(ConfiguracionPlataforma, 1) or ConfiguracionPlataforma(id=1)
        for uso, columna in (("recibos", "modelo_recibos"), ("convenio", "modelo_convenio"),
                             ("asistente", "modelo_asistente"),
                             ("asistente_tramites", "modelo_asistente_tramites")):
            valor = (elegidos.get(uso) or "").strip()
            if valor and precios_ia.modelo_valido(valor):
                setattr(cfg, columna, valor)
        s.add(cfg)
        s.commit()


def claves_laboratorio() -> dict:
    """{variable: clave} guardadas para el Laboratorio de modelos. Se lee en
    cada pedido (Render corre un worker por núcleo)."""
    with Session(engine) as s:
        cfg = s.get(ConfiguracionPlataforma, 1)
        return dict((cfg.claves_laboratorio if cfg else None) or {})


def set_clave_laboratorio(variable: str, clave: str) -> None:
    """Guarda (o borra, con clave vacía) la clave de un proveedor."""
    with Session(engine) as s:
        cfg = s.get(ConfiguracionPlataforma, 1) or ConfiguracionPlataforma(id=1)
        claves = dict(cfg.claves_laboratorio or {})
        if clave:
            claves[variable] = clave
        else:
            claves.pop(variable, None)
        cfg.claves_laboratorio = claves
        s.add(cfg)
        s.commit()


def set_color_destacado(sindicato_id: int, color: str) -> None:
    """Color destacado del dashboard de UN sindicato -- lo edita solo el
    admin de plataforma (docs/DASHBOARD.md §1.4)."""
    with Session(engine) as s:
        sind = s.get(Sindicato, sindicato_id)
        if not sind:
            return
        sind.color_destacado = color
        s.add(sind)
        s.commit()


def marca_plataforma() -> dict:
    """Marca de 'Mi Trabajo' para las pantallas sin sindicato (logins, panel de
    plataforma): degrada a los colores/logo de siempre si no se configuró nada."""
    with Session(engine) as s:
        cfg = s.get(ConfiguracionPlataforma, 1, options=_sin_bytes(ConfiguracionPlataforma))
        if not cfg:
            return {"logo": "", "logo_oscuro": "", "color_primario": "#152238",
                    "color_secundario": "#1a7a6b", "color_acento": "#b23a2e"}
        return {
            "logo": cfg.logo,
            "logo_oscuro": cfg.logo_oscuro,
            "color_primario": cfg.color_primario or "#152238",
            "color_secundario": cfg.color_secundario or "#1a7a6b",
            "color_acento": cfg.color_acento or "#b23a2e",
        }


def set_marca_plataforma(color_primario: str, color_secundario: str, color_acento: str,
                          logo_datos: bytes = None, logo_mime: str = "", logo_flag: str = "",
                          logo_datos_oscuro: bytes = None, logo_mime_oscuro: str = "",
                          logo_oscuro_flag: str = ""):
    with Session(engine) as s:
        cfg = s.get(ConfiguracionPlataforma, 1)
        if not cfg:
            cfg = ConfiguracionPlataforma(id=1)
        cfg.color_primario = color_primario or "#152238"
        cfg.color_secundario = color_secundario or "#1a7a6b"
        cfg.color_acento = color_acento or "#b23a2e"
        if logo_datos:
            cfg.logo_datos, cfg.logo_mime, cfg.logo = logo_datos, logo_mime, logo_flag
        if logo_datos_oscuro:
            cfg.logo_datos_oscuro, cfg.logo_mime_oscuro, cfg.logo_oscuro = (
                logo_datos_oscuro, logo_mime_oscuro, logo_oscuro_flag)
        s.add(cfg)
        s.commit()


# ---------- Provincias argentinas (para el ABM de trabajadores) ----------
PROVINCIAS_AR = [
    "Ciudad Autónoma de Buenos Aires", "Buenos Aires", "Catamarca", "Chaco",
    "Chubut", "Córdoba", "Corrientes", "Entre Ríos", "Formosa", "Jujuy",
    "La Pampa", "La Rioja", "Mendoza", "Misiones", "Neuquén", "Río Negro",
    "Salta", "San Juan", "San Luis", "Santa Cruz", "Santa Fe",
    "Santiago del Estero", "Tierra del Fuego", "Tucumán",
]


# ---------- Los datos personales de una persona: un solo dueño ----------
# Todo lo que sea nombre, domicilio, teléfono o mail de un afiliado entra y
# sale por acá. Las cuatro puertas de la app (alta manual del admin, alta
# masiva, registro del afiliado y su perfil) llaman a estas funciones y no
# escriben columnas a mano: es lo que impide que vuelvan a existir dos
# versiones del mismo domicilio (ver CuentaTrabajador).

def asegurar_cuenta(s: Session, cuil: str) -> CuentaTrabajador:
    """La fila de la PERSONA, creándola si el CUIL todavía no tenía ninguna.

    Recibe la sesión abierta y no abre la suya: un request nunca toma más de
    una conexión del pool a la vez (regla del 2026-09-19, ver "Una sesión de
    base por request" en CLAUDE.md). La crea sin `clave_hash`, que es el
    estado normal de alguien que el sindicato cargó en el padrón y todavía
    no se registró.

    Nace vacía a propósito: los datos se escriben con
    `guardar_datos_personales`, que es la única función que decide qué pisa y
    qué no."""
    c = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first()
    if not c:
        c = CuentaTrabajador(cuil=cuil)
        s.add(c)
        s.flush()          # que quede con id dentro de la misma transacción
    return c


def guardar_datos_personales(s: Session, cuil: str, nombre: str = None,
                             domicilio: dict = None, telefono: str = None,
                             mail: str = None,
                             mail_padron: str = None,
                             fecha_nacimiento: str = None) -> CuentaTrabajador:
    """Escribe el bloque personal de un CUIL. Lo que llega en `None` no se
    toca -- así una pantalla que edita solo el domicilio no borra el teléfono
    que cargó otra.

    `domicilio` llega ya armado por `geo.campos_para_guardar()`, que es la
    única función que decide qué se escribe en el bloque: antes esta firma
    tenía un parámetro por campo y sumarle el CP y las coordenadas la habría
    dejado en once posicionales, donde equivocarse de orden no da error, da
    datos mal.

    Un `nombre` vacío tampoco pisa al que había: es el caso del alta masiva y
    del registro, donde el campo puede venir en blanco y el padrón ya tenía
    el nombre bueno.

    `mail` es el mail de CONTACTO de la persona; `mail_padron` es el que
    cargó el SINDICATO (ver "Los TRES mails" en `CuentaTrabajador`). Solo el
    alta individual y el alta masiva del panel pasan `mail_padron`; el perfil
    y el registro NO (lo verifica `test_registro_modelo.py`). `None` = no
    tocar, como los demás.

    `fecha_nacimiento` llega ya normalizada a ISO (o "" para borrarla): quien
    la recibe de un formulario la pasa antes por `listas.normalizar_fecha`."""
    c = asegurar_cuenta(s, cuil)
    if nombre is not None and nombre.strip():
        c.nombre = nombre.strip()[:200]
    for campo, valor in (domicilio or {}).items():
        if campo in geo.CAMPOS_DOMICILIO:
            setattr(c, campo, valor)
    if telefono is not None:
        c.telefono = telefono.strip()[:40]
    if mail is not None:
        c.mail = mail.strip()[:200]
    if mail_padron is not None:
        c.mail_padron = mail_padron.strip()[:200]
    if fecha_nacimiento is not None:
        c.fecha_nacimiento = fecha_nacimiento.strip()[:10] or None
    s.add(c)
    return c


def publicacion_en_alcance(destino_seccionales, alcance) -> bool:
    """¿Quien tiene este alcance puede EDITAR o BORRAR una noticia o un
    beneficio con estos destinos? Solo si TODOS sus destinos caen en el
    alcance. Una publicación "a todas" (lista vacía) o dirigida a otra
    seccional la toca solo quien tiene alcance total: fail-closed, como
    `_en_alcance` (PLAN_ALCANCE_SECCIONAL.md, bloque 2)."""
    if alcance is None:
        return True
    return bool(destino_seccionales) and all(d in alcance for d in destino_seccionales)


def publicacion_visible(destino_seccionales, alcance) -> bool:
    """¿Quien tiene este alcance VE la publicación en el panel? Si va "a
    todas" o alguno de sus destinos cae en el alcance: la misma regla que el
    historial de Notificaciones (ve lo que le llega a su gente)."""
    if alcance is None:
        return True
    if not alcance:
        return False
    return not destino_seccionales or any(d in alcance for d in destino_seccionales)


def padron_del_sindicato(s: Session, sindicato_id: int, alcance=None) -> list:
    """El padrón completo de un sindicato, con los datos personales de cada
    afiliado ya unidos por CUIL.

    Recibe la sesión abierta y no abre la suya (regla del 2026-09-19: un
    request no toma dos conexiones del pool a la vez), porque las dos
    pantallas que lo piden ya están adentro de una.

    Devuelve DICTS y no filas de `Trabajador` porque lo que la pantalla del
    admin muestra no es una tabla sino dos: el vínculo con el gremio
    (seccional, credencial, empleador, estado) y la persona (nombre,
    domicilio, contacto). Que se arme acá y no en la plantilla es lo que
    permite que el resto de la app pida "el padrón" sin tener que acordarse
    del JOIN.

    `alcance` (ver alcance_seccional) recorta EN LA CONSULTA: None = todo,
    un set = solo esas seccionales (un afiliado sin seccional no lo alcanza
    nadie acotado), set() = nada. Es la única lectura del padrón del panel,
    así que lo que no entra acá no viaja a ninguna pantalla."""
    if alcance is not None and not alcance:
        return []
    filas = s.exec(_consulta_padron(sindicato_id, alcance)
                   .order_by(Trabajador.activo.desc(), CuentaTrabajador.nombre)).all()
    return [_fila_padron(t, c) for t, c in filas]


def _consulta_padron(sindicato_id: int, alcance=None):
    """El SELECT del padrón con la persona unida por CUIL y el recorte de
    seccional EN LA CONSULTA. Lo comparten el padrón entero y su página
    (`pagina_del_padron`): un solo lugar donde se recorta."""
    q = (select(Trabajador, CuentaTrabajador)
         .join(CuentaTrabajador, CuentaTrabajador.cuil == Trabajador.cuil, isouter=True)
         .where(Trabajador.sindicato_id == sindicato_id))
    if alcance is not None:
        q = q.where(Trabajador.seccional_id.in_(list(alcance) or [-1]))
    return q


# Tildes y eñes afuera para buscar por nombre en el SQL, como normTexto() del
# panel: "Pérez" se encuentra escribiendo "perez".
_CON_TILDE, _SIN_TILDE = "áéíóúüñàèìòù", "aeiouunaeiou"


def pagina_del_padron(s: Session, sindicato_id: int, alcance=None, cuil: str = "",
                      nombre: str = "", declarados: bool = False,
                      pagina: int = 1, por_pagina: int = 50) -> dict:
    """Una página del padrón para la pestaña Trabajadores (auditoría G4-19):
    el listado ya no dibuja los miles de un gremio real juntos. Busca en el
    servidor (CUIL por dígitos, nombre sin tildes ni mayúsculas palabra por
    palabra, y los "declarados sin recibo") y pagina con LIMIT/OFFSET.

    El recorte por seccional es el mismo de `padron_del_sindicato`
    (`_consulta_padron`). Devuelve además `activos` y `sin_registrar` del
    alcance entero, sin los filtros: son los números del título."""
    from sqlalchemy import func
    vacio = {"filas": [], "total": 0, "pagina": 1, "paginas": 1, "por_pagina": por_pagina,
             "activos": 0, "sin_registrar": 0}
    if alcance is not None and not alcance:
        return vacio
    base = _consulta_padron(sindicato_id, alcance)
    q = base
    digitos = "".join(ch for ch in (cuil or "") if ch.isdigit())
    if digitos:
        q = q.where(Trabajador.cuil.contains(digitos))
    for palabra in _sin_tildes(nombre).split():
        q = q.where(func.translate(func.lower(func.coalesce(CuentaTrabajador.nombre, "")),
                                   _CON_TILDE, _SIN_TILDE).contains(palabra, autoescape=True))
    if declarados:
        q = q.where(func.coalesce(CuentaTrabajador.clave_hash, "") != "",
                    CuentaTrabajador.nivel_fiabilidad == 2,
                    CuentaTrabajador.nivel_origen == "mail_declarado")
    total = s.exec(select(func.count()).select_from(q.subquery())).one()
    paginas = max(1, -(-total // por_pagina))
    pagina = min(max(1, pagina), paginas)
    filas = s.exec(q.order_by(Trabajador.activo.desc(), CuentaTrabajador.nombre, Trabajador.id)
                   .offset((pagina - 1) * por_pagina).limit(por_pagina)).all()
    sub = base.subquery()
    activos, sin_registrar = s.exec(select(
        func.count().filter(sub.c.activo),
        func.count().filter(sub.c.activo & ~sub.c.registrado))).one()
    return {"filas": [_fila_padron(t, c) for t, c in filas], "total": total,
            "pagina": pagina, "paginas": paginas, "por_pagina": por_pagina,
            "activos": activos or 0, "sin_registrar": sin_registrar or 0}


def _sin_tildes(texto: str) -> str:
    """Minúsculas y sin tildes, para comparar nombres (ver _CON_TILDE)."""
    t = (texto or "").lower()
    return t.translate(str.maketrans(_CON_TILDE, _SIN_TILDE))


def _fila_padron(t: "Trabajador", c: Optional["CuentaTrabajador"]) -> dict:
    """Una fila del padrón: el empadronamiento y la persona, en un dict."""
    vacios = {campo: "" for campo in ("nombre", *geo.CAMPOS_DOMICILIO)}
    vacios.update({"latitud": None, "longitud": None, "precision_geo": "sin_geo",
                   "telefono": "", "mail": "", "fecha_nacimiento": None})
    # Un afiliado sin fila de persona no debería existir (la crea el
    # alta), pero si alguna vez pasara la pantalla tiene que mostrar la
    # fila igual, vacía, y no romperse: un padrón que no se puede abrir
    # es peor que un renglón incompleto.
    fila = dict(_dict_personales(c) if c else vacios)
    fila.update({
        "id": t.id, "cuil": t.cuil, "sindicato_id": t.sindicato_id,
        "registrado": t.registrado, "activo": t.activo,
        "codigo_credencial": t.codigo_credencial,
        "vigencia_credencial": t.vigencia_credencial,
        "fecha_afiliacion": t.fecha_afiliacion,
        "seccional_id": t.seccional_id,
        "es_empleado_sindicato": t.es_empleado_sindicato,
        "cuit_empleador": t.cuit_empleador,
        # Nivel de fiabilidad de la cuenta (PLAN_REGISTRO.md): solo tiene
        # sentido si la persona ya eligió clave.
        "tiene_cuenta": bool(c and c.clave_hash),
        # ¿Este sindicato responde por esa cuenta? (ver `responde_por`).
        # Si no, la pantalla no muestra su nivel ni sus botones.
        "responde": responde_por(bool(c and c.clave_hash), t.registrado),
        "nivel_fiabilidad": (c.nivel_fiabilidad or 1) if c else 1,
        "nivel_origen": (c.nivel_origen or "") if c else "",
    })
    return fila


# ---------- ¿Este sindicato responde por la cuenta de esta persona? ----------
# Un admin puede cargar en SU padrón cualquier CUIL (es un dato público, y el
# alta solo exige el dígito verificador). Sin esta regla, cargar el CUIL de
# alguien que está en OTRO sindicato y apretar "Restablecer clave" le daría la
# cuenta entera -- y con ella sus recibos y su identidad en todos los gremios.
# La regla: un sindicato solo "responde" por una cuenta si la persona YA
# estaba en su padrón cuando la creó. `Trabajador.registrado` / `Empleador.
# registrado` se marcan en el registro sobre los empadronamientos que
# EXISTÍAN en ese momento (y en el reset de plataforma de una cuenta sin
# clave): un empadronamiento posterior a la cuenta queda en False.
def responde_por(tiene_clave: bool, registrado: bool) -> bool:
    """La regla, pura. Sin clave no hay cuenta que tomar (la persona todavía
    no se registró y el padrón la mandó a elegir una); con clave, solo
    responde el padrón que ya la tenía cargada al registrarse."""
    return (not tiene_clave) or bool(registrado)


def padron_responde_por(s, sindicato_id: int, cuil: str) -> bool:
    """True si `sindicato_id` puede tocar la cuenta de `cuil` (restablecerle
    la clave, confirmar su identidad, escribirle nombre o mails): la
    CuentaTrabajador no existe o todavía no tiene clave, o el empadronamiento
    de este sindicato es `registrado` (la persona ya estaba en este padrón
    cuando creó la cuenta). Un CUIL que ni siquiera está en el padrón de este
    sindicato con una cuenta ya hecha devuelve False: no hay de qué responder.
    Recibe la sesión, no abre la suya."""
    c = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first()
    if c is None or not c.clave_hash:
        return True
    t = s.exec(select(Trabajador).where(Trabajador.sindicato_id == sindicato_id,
                                        Trabajador.cuil == cuil)).first()
    return responde_por(True, bool(t and t.registrado))


def padron_responde_por_empresa(s, sindicato_id: int, cuit: str) -> bool:
    """Lo mismo que `padron_responde_por`, para la cuenta de una empresa
    (`CuentaEmpleador` y `Empleador.registrado`)."""
    c = s.exec(select(CuentaEmpleador).where(CuentaEmpleador.cuit == cuit)).first()
    if c is None or not c.clave_hash:
        return True
    e = s.exec(select(Empleador).where(Empleador.sindicato_id == sindicato_id,
                                       Empleador.cuit == cuit)).first()
    return responde_por(True, bool(e and e.registrado))


def cuiles_con_clave(s, cuiles) -> set:
    """De estos CUIL, los que ya tienen cuenta con clave (la persona ya se
    registró). Una sola consulta: lo usa la carga masiva, que no puede hacer
    una por línea."""
    cuiles = list(cuiles)
    if not cuiles:
        return set()
    return set(s.exec(select(CuentaTrabajador.cuil).where(
        CuentaTrabajador.cuil.in_(cuiles), CuentaTrabajador.clave_hash != "")).all())


def datos_personales(cuil: str) -> Optional[dict]:
    """El bloque personal de un CUIL, o None si ese CUIL no existe en la
    plataforma. No depende del sindicato: es una persona, no un afiliado."""
    with Session(engine) as s:
        c = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first()
        return _dict_personales(c) if c else None


def _dict_personales(c: CuentaTrabajador) -> dict:
    return {
        "nombre": c.nombre, "cuil": c.cuil,
        "calle": c.calle, "numero": c.numero, "piso_depto": c.piso_depto,
        "localidad": c.localidad, "provincia": c.provincia,
        "codigo_postal": c.codigo_postal, "direccion_texto": c.direccion_texto,
        "latitud": c.latitud, "longitud": c.longitud,
        "precision_geo": c.precision_geo, "geo_actualizado": c.geo_actualizado,
        "telefono": c.telefono, "mail": c.mail,
        "fecha_nacimiento": c.fecha_nacimiento,
    }


def nombre_trabajador(cuil: str, sindicato_id: int = None) -> str:
    """El nombre de la persona. `sindicato_id` ya no cambia nada -- el nombre
    es de la persona, no del empadronamiento -- pero se mantiene en la firma
    porque lo pasan una docena de llamadas y sacarlo de todas en el mismo
    cambio que mueve las columnas haría ilegible el diff."""
    with Session(engine) as s:
        c = s.exec(select(CuentaTrabajador).options(*_sin_bytes(CuentaTrabajador)).where(CuentaTrabajador.cuil == cuil)).first()
        return c.nombre if c else ""


def perfil_trabajador(cuil: str, sindicato_id: int) -> Optional[dict]:
    """Datos propios del trabajador para mostrarle su perfil. Devuelve None
    si ese CUIL no está empadronado en ese sindicato -- el perfil se abre
    desde la app de un gremio y no tiene sentido fuera de él, aunque los
    datos que muestre sean de la persona y no del empadronamiento."""
    with Session(engine) as s:
        t = s.exec(select(Trabajador).where(
            Trabajador.cuil == cuil, Trabajador.sindicato_id == sindicato_id)).first()
        if not t:
            return None
        c = s.exec(select(CuentaTrabajador).options(*_sin_bytes(CuentaTrabajador)).where(CuentaTrabajador.cuil == cuil)).first()
        return _dict_personales(c) if c else None


def actualizar_perfil_trabajador(cuil: str, sindicato_id: int, nombre: str,
                                  domicilio: dict, telefono: str, mail: str,
                                  fecha_nacimiento: str = None) -> bool:
    """El trabajador edita sus propios datos -- todo menos el CUIL (identidad,
    no se toca acá) y los campos de gestión del sindicato (seccional,
    vigencia de credencial, etc.), que siguen siendo resorte del admin.

    Escribe en la PERSONA, así que el cambio se ve en todos los sindicatos
    donde esté empadronado. Antes escribía solo el empadronamiento activo y
    el registro escribía todos: la misma persona editando en dos pantallas
    dejaba dos domicilios distintos."""
    with Session(engine) as s:
        t = s.exec(select(Trabajador).where(
            Trabajador.cuil == cuil, Trabajador.sindicato_id == sindicato_id)).first()
        if not t:
            return False
        guardar_datos_personales(s, cuil, nombre=nombre, domicilio=domicilio,
                                 telefono=telefono, mail=mail,
                                 fecha_nacimiento=fecha_nacimiento)
        s.commit()
        return True


def actualizar_dato_personal(cuil: str, dato: str, valor: str) -> bool:
    """Un dato PROPIO de la persona (validaciones_tramite.DATOS_PROPIOS) que
    el afiliado corrigió en un campo extraído de un trámite (2026-10-18):
    `fecha_nacimiento` (ya ISO) o `provincia` / `localidad`. El domicilio se
    escribe como un bloque (regla de 2026-09-22): se toma el que hay, se
    cambia ese dato y, como la localidad cambió, el globo del mapa deja de
    valer (`sin_geo`)."""
    valor = str(valor or "").strip()
    with Session(engine) as s:
        c = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first()
        if not c or not valor:
            return False
        if dato == "fecha_nacimiento":
            guardar_datos_personales(s, cuil, fecha_nacimiento=valor[:10])
        elif dato in ("provincia", "localidad"):
            bloque = {k: getattr(c, k, "") or "" for k in ("calle", "numero", "piso_depto", "localidad", "provincia", "codigo_postal")}
            bloque[dato] = valor
            guardar_datos_personales(s, cuil, domicilio=geo.campos_para_guardar(bloque, "sin_geo"))
        else:
            return False
        s.commit()
        return True


def tiene_foto_trabajador(cuil: str) -> bool:
    """Si la persona tiene foto de perfil, sin traerla (las portadas solo
    dibujan el círculo; la foto la sirve la ruta de la foto, aparte)."""
    from sqlalchemy import func
    with Session(engine) as s:
        largo = s.exec(select(func.coalesce(func.octet_length(CuentaTrabajador.foto_datos), 0))
                       .where(CuentaTrabajador.cuil == cuil)).first()
        return bool(largo)


def foto_trabajador(cuil: str) -> Optional[dict]:
    """Foto de perfil (una por CUIL, no por sindicato -- ver CuentaTrabajador)."""
    with Session(engine) as s:
        c = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first()
        if not c or not c.foto_datos:
            return None
        return {"datos": c.foto_datos, "mime": c.foto_mime or "image/jpeg"}


def guardar_foto_trabajador(cuil: str, datos: bytes, mime: str) -> bool:
    with Session(engine) as s:
        c = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first()
        if not c:
            return False
        c.foto_datos, c.foto_mime = datos, mime
        s.add(c)
        s.commit()
        return True


def token_credencial(cuil: str, sindicato_id: int) -> str:
    """Token opaco para el QR (/v/{token}). Se genera y se guarda la primera
    vez que hace falta, así las filas ya cargadas no necesitan una migración
    de datos aparte."""
    import secrets
    with Session(engine) as s:
        t = s.exec(select(Trabajador).where(
            Trabajador.cuil == cuil, Trabajador.sindicato_id == sindicato_id)).first()
        if not t:
            return ""
        if not t.token:
            t.token = secrets.token_urlsafe(16)
            s.add(t)
            s.commit()
        return t.token


def credencial_por_token(token: str) -> Optional[dict]:
    """Datos públicos de verificación para /v/{token}. A propósito NO incluye
    el DNI: la idea del QR es que una foto de la credencial no lo filtre."""
    if not token:
        return None
    with Session(engine) as s:
        t = s.exec(select(Trabajador).where(Trabajador.token == token)).first()
        if not t or not t.activo:
            return None
        sind = s.get(Sindicato, t.sindicato_id)
        if not sind or not sind.activo:
            return None
        persona = s.exec(select(CuentaTrabajador).where(
            CuentaTrabajador.cuil == t.cuil)).first()
        return {
            "sindicato": sind.nombre, "sindicato_id": sind.id,
            "logo": sind.logo, "color_primario": sind.color_primario,
            "nombre": persona.nombre if persona else "", "cuil": t.cuil,
            "codigo_credencial": t.codigo_credencial,
            "vigencia_credencial": t.vigencia_credencial,
        }


def credencial_de(cuil: str, sindicato_id: int) -> Optional[dict]:
    """Código y vigencia REALES (persistidos) de la credencial de un
    empadronamiento. None si el trabajador no existe; codigo=None si el admin
    todavía no la generó — eso es lo que decide si la app del trabajador
    muestra la credencial o un estado "pendiente"."""
    with Session(engine) as s:
        t = s.exec(select(Trabajador).where(
            Trabajador.cuil == cuil, Trabajador.sindicato_id == sindicato_id)).first()
        if not t:
            return None
        return {"codigo": t.codigo_credencial, "vigencia": t.vigencia_credencial}


def semaforo_guardado(cuil: str, sindicato_id: int) -> Optional[dict]:
    """Último semáforo calculado para ese empadronamiento, o None si
    todavía no subió ningún comprobante de ARCA. Incluye "actualizado" (fecha
    real del cálculo guardado) para que la pantalla no muestre "hoy" al
    repintar un dato viejo."""
    with Session(engine) as s:
        t = s.exec(select(Trabajador).where(
            Trabajador.cuil == cuil, Trabajador.sindicato_id == sindicato_id)).first()
        if not t or not t.semaforo_datos:
            return None
        return {**t.semaforo_datos, "actualizado": t.semaforo_actualizado}


def guardar_semaforo(cuil: str, sindicato_id: int, datos: dict) -> None:
    """Persiste el resultado de calcular_semaforo() para no perderlo al
    navegar o recargar. No hace nada si el trabajador no existe en ese
    sindicato (recibo/comprobante de una sesión ya inválida)."""
    with Session(engine) as s:
        t = s.exec(select(Trabajador).where(
            Trabajador.cuil == cuil, Trabajador.sindicato_id == sindicato_id)).first()
        if not t:
            return
        t.semaforo_datos = datos
        t.semaforo_actualizado = fechas.hoy_texto()
        s.add(t)
        s.commit()


def generar_codigo_credencial(trabajador_id: int, sindicato_id: int, nombre_sindicato: str) -> str:
    """Genera y persiste un código de credencial nuevo para ese empadronamiento
    (lo dispara el admin con el botón "Generar credencial", nunca es
    automático). Formato: 5 letras del sindicato + 8 alfanuméricos al azar.

    Los 8 caracteres salen de `secrets` (criptográficamente aleatorio), NO de
    una semilla reproducible: un código de credencial que se puede volver a
    generar sabiendo de qué sindicato es, no sirve como credencial. Reintenta
    si por casualidad ya existe (el índice único corta cualquier duda)."""
    import secrets
    import string
    letras = "".join(ch for ch in (nombre_sindicato or "").upper() if ch.isalnum())[:5]
    prefijo = (letras or "SIND").ljust(5, "X")
    alfabeto = string.ascii_uppercase + string.digits
    with Session(engine) as s:
        t = s.get(Trabajador, trabajador_id)
        if not t or t.sindicato_id != sindicato_id:
            return ""
        for _ in range(25):
            sufijo = "".join(secrets.choice(alfabeto) for _ in range(8))
            codigo = f"{prefijo}{sufijo}"
            if not s.exec(select(Trabajador).where(Trabajador.codigo_credencial == codigo)).first():
                t.codigo_credencial = codigo
                s.add(t)
                s.commit()
                return codigo
        raise RuntimeError("No se pudo generar un código de credencial único, reintentá.")


def noticia_vigente(n: "Noticia | dict", hoy: str) -> bool:
    """hoy en formato AAAA-MM-DD. Vigente = fecha_desde <= hoy <= fecha_hasta
    (comparación de strings ISO, funciona igual que comparar fechas reales)."""
    desde = n["fecha_desde"] if isinstance(n, dict) else n.fecha_desde
    hasta = n["fecha_hasta"] if isinstance(n, dict) else n.fecha_hasta
    return bool(desde) and bool(hasta) and desde <= hoy <= hasta


def _hay_bytes(columna):
    """Expresión SQL: la columna de bytes tiene contenido. Para preguntar por
    una imagen sin traerla."""
    from sqlalchemy import func
    return func.coalesce(func.octet_length(columna), 0) > 0


def _sin_bytes(modelo):
    """Opciones de carga que dejan AFUERA todas las columnas de bytes del
    modelo (logos, firmas, contratos, fotos, imágenes y sus copias
    normalizadas). Van en `s.get(Modelo, id, options=_sin_bytes(Modelo))` o
    en `select(Modelo).options(*_sin_bytes(Modelo))`. Un `s.get(Sindicato)`
    pelado trae el logo, la firma y el contrato (1,2 MB en La Bancaria), y
    la fila del sindicato se lee en CADA pantalla: medido el 2026-11-05 con
    200 personas navegando, la base se pasaba el tiempo mandando esos bytes
    (PLAN_PRUEBAS_BANCARIA.md). Si una función necesita los bytes, los pide
    aparte o accede al atributo adentro de la sesión (se cargan solos)."""
    from sqlalchemy import LargeBinary
    from sqlalchemy.orm import defer
    return [defer(getattr(modelo, c.key)) for c in modelo.__table__.columns
            if isinstance(c.type, LargeBinary)]


_sin_imagenes = _sin_bytes


def _ids_con_bytes(s, columna, ids) -> set:
    """Ids (de la tabla de `columna`) cuya columna de bytes tiene contenido,
    en UNA consulta y sin traer los bytes. Es la respuesta a «¿tiene
    adjunto?» de una lista: `bool(fila.adjunto_datos)` dispara un SELECT por
    fila con el adjunto entero (N+1 de blobs)."""
    ids = list(ids)
    if not ids:
        return set()
    tabla = columna.class_
    return set(s.exec(select(tabla.id).where(tabla.id.in_(ids), _hay_bytes(columna))).all())


def _noticia_a_dict(n: "Noticia", tiene_imagen1: bool = None, tiene_imagen2: bool = None) -> dict:
    """`tiene_imagen1/2` vienen calculados en SQL cuando la noticia se cargó
    sin las imágenes (las listas); si no se pasan, se miran los bytes."""
    return {
        "id": n.id, "sindicato_id": n.sindicato_id, "titulo": n.titulo,
        "bajada": n.bajada, "texto_completo": n.texto_completo,
        "fecha_desde": n.fecha_desde, "fecha_hasta": n.fecha_hasta, "creada": n.creada,
        "on_top": bool(n.on_top),
        "tiene_imagen1": bool(n.imagen1_datos) if tiene_imagen1 is None else bool(tiene_imagen1),
        "tiene_imagen2": bool(n.imagen2_datos) if tiene_imagen2 is None else bool(tiene_imagen2),
        "destino_seccionales": n.destino_seccionales or [],
        "formulario_id": n.formulario_id,
        "encuesta_id": n.encuesta_id,
    }


def formulario_activo_de(sindicato_id: int, formulario_id: Optional[int],
                          familia: str = "trabajador") -> Optional[int]:
    """Devuelve el formulario_id solo si sigue siendo un tipo ACTIVO del
    sindicato (de la familia correcta); None si fue borrado, desactivado o
    es ajeno. Es lo que decide si el ícono "completá los datos" se muestra."""
    if not formulario_id:
        return None
    with Session(engine) as s:
        modelo = TipoTramiteEmpleador if familia == "empresa" else TipoTramite
        t = s.get(modelo, formulario_id)
        return formulario_id if (t and t.sindicato_id == sindicato_id and t.activo) else None


def visible_para_seccional(destino_seccionales: list, seccional_id: Optional[int]) -> bool:
    """Lista vacía = todas las seccionales (incluye trabajadores sin
    seccional asignada). Si no está vacía, solo es visible para quien tenga
    esa seccional asignada -- un trabajador sin seccional NO ve contenido
    dirigido a seccionales específicas."""
    return not destino_seccionales or seccional_id in destino_seccionales


def noticias_del_sindicato(sindicato_id: int, alcance=None) -> list:
    """Las noticias del sindicato para el panel de admin, más recientes
    primero. Con `alcance`, solo las que le llegan a la gente de esas
    seccionales (`publicacion_visible`), y cada una dice si quien mira puede
    editarla o borrarla (`propia`, ver `publicacion_en_alcance`)."""
    # Las imágenes NO se traen: la lista solo necesita saber si existen
    # (`tiene_imagen1/2`), y la portada del afiliado lee esta lista en cada
    # pedido. Con las 37 noticias de La Bancaria eran 3 MB de la base por
    # pedido (el doble desde que existe la copia normalizada), y con 200
    # personas navegando la base se pasaba el tiempo mandando bytes que nadie
    # usaba (medido el 2026-11-05, PLAN_PRUEBAS_BANCARIA.md). Las fotos se
    # sirven por /noticia-imagen/{id}/{n}, de a una.
    with Session(engine) as s:
        filas = s.exec(select(Noticia, _hay_bytes(Noticia.imagen1_datos), _hay_bytes(Noticia.imagen2_datos))
                       .options(*_sin_imagenes(Noticia))
                       .where(Noticia.sindicato_id == sindicato_id)
                       .order_by(Noticia.creada.desc(), Noticia.id.desc())).all()
        salida = []
        for n, tiene1, tiene2 in filas:
            if not publicacion_visible(n.destino_seccionales or [], alcance):
                continue
            d = _noticia_a_dict(n, tiene1, tiene2)
            d["propia"] = publicacion_en_alcance(n.destino_seccionales or [], alcance)
            salida.append(d)
        return salida


def noticias_vigentes(sindicato_id: int, seccional_id: Optional[int] = None, limite: int = None) -> list:
    """Noticias vigentes HOY de un sindicato, dirigidas a la seccional del
    trabajador (o a todas): primero las marcadas «On top», después las demás,
    y dentro de cada grupo las más recientes primero."""
    hoy = fechas.hoy_texto()
    todas = noticias_del_sindicato(sindicato_id)
    vigentes = [n for n in todas if noticia_vigente(n, hoy)
                and visible_para_seccional(n["destino_seccionales"], seccional_id)]
    # sorted es estable: conserva el orden cronológico dentro de cada grupo.
    vigentes = sorted(vigentes, key=lambda n: not n["on_top"])
    return vigentes[:limite] if limite else vigentes


def noticia_por_id(noticia_id: int) -> Optional[dict]:
    with Session(engine) as s:
        fila = s.exec(select(Noticia, _hay_bytes(Noticia.imagen1_datos), _hay_bytes(Noticia.imagen2_datos))
                      .where(Noticia.id == noticia_id)).first()
        return _noticia_a_dict(fila[0], fila[1], fila[2]) if fila else None


def beneficio_vigente(b: "Beneficio | dict", hoy: str) -> bool:
    """Mismo criterio que noticia_vigente: hoy en AAAA-MM-DD, vigente =
    fecha_desde <= hoy <= fecha_hasta."""
    desde = b["fecha_desde"] if isinstance(b, dict) else b.fecha_desde
    hasta = b["fecha_hasta"] if isinstance(b, dict) else b.fecha_hasta
    return bool(desde) and bool(hasta) and desde <= hoy <= hasta


def _beneficio_a_dict(b: "Beneficio", tiene_imagen: bool = None) -> dict:
    return {
        "id": b.id, "sindicato_id": b.sindicato_id, "rubro": b.rubro,
        "descripcion": b.descripcion, "link": b.link,
        "fecha_desde": b.fecha_desde, "fecha_hasta": b.fecha_hasta, "creada": b.creada,
        "tiene_imagen": bool(b.imagen_datos) if tiene_imagen is None else bool(tiene_imagen),
        "destino_seccionales": b.destino_seccionales or [],
        "formulario_id": b.formulario_id,
    }


def beneficios_del_sindicato(sindicato_id: int, alcance=None) -> list:
    """Los beneficios del sindicato para el panel de admin, más recientes
    primero. Mismo recorte y misma marca `propia` que noticias_del_sindicato."""
    # Sin las imágenes, por lo mismo que noticias_del_sindicato.
    with Session(engine) as s:
        filas = s.exec(select(Beneficio, _hay_bytes(Beneficio.imagen_datos))
                       .options(*_sin_imagenes(Beneficio))
                       .where(Beneficio.sindicato_id == sindicato_id)
                       .order_by(Beneficio.creada.desc(), Beneficio.id.desc())).all()
        salida = []
        for b, tiene in filas:
            if not publicacion_visible(b.destino_seccionales or [], alcance):
                continue
            d = _beneficio_a_dict(b, tiene)
            d["propia"] = publicacion_en_alcance(b.destino_seccionales or [], alcance)
            salida.append(d)
        return salida


def beneficios_vigentes(sindicato_id: int, seccional_id: Optional[int] = None) -> list:
    """Beneficios vigentes HOY de un sindicato, dirigidos a la seccional del
    trabajador (o a todos), más recientes primero."""
    hoy = fechas.hoy_texto()
    todos = beneficios_del_sindicato(sindicato_id)
    return [b for b in todos if beneficio_vigente(b, hoy)
            and visible_para_seccional(b["destino_seccionales"], seccional_id)]


def beneficio_por_id(beneficio_id: int) -> Optional[dict]:
    with Session(engine) as s:
        fila = s.exec(select(Beneficio, _hay_bytes(Beneficio.imagen_datos))
                      .where(Beneficio.id == beneficio_id)).first()
        return _beneficio_a_dict(fila[0], fila[1]) if fila else None


def _seccional_a_dict(sec: "Seccional") -> dict:
    """La seccional como la consumen las pantallas. Un solo armado para
    todas: la tabla del panel, el <select> del alta de trabajador, los
    checkboxes de destino de Noticias/Beneficios/Notificaciones, el mapa por
    seccional de Trámites, los filtros del Panel Sindical y la ficha."""
    return {
        "id": sec.id, "nombre": sec.nombre, "ve_todas": sec.ve_todas,
        "calle": sec.calle, "numero": sec.numero, "piso_depto": sec.piso_depto,
        "localidad": sec.localidad, "provincia": sec.provincia,
        "codigo_postal": sec.codigo_postal, "direccion_texto": sec.direccion_texto,
        "latitud": sec.latitud, "longitud": sec.longitud,
        "precision_geo": sec.precision_geo, "geo_actualizado": sec.geo_actualizado,
        "telefono": sec.telefono, "whatsapp": sec.whatsapp, "mail": sec.mail,
        "horario_atencion": sec.horario_atencion,
    }


def seccionales_del_sindicato(sindicato_id: int) -> list:
    """Todas las seccionales del sindicato, para el CRUD de admin y el
    <select> del alta/edición de trabajador."""
    with Session(engine) as s:
        seccionales = s.exec(select(Seccional).where(
            Seccional.sindicato_id == sindicato_id).order_by(Seccional.nombre)).all()
        return [_seccional_a_dict(sec) for sec in seccionales]


def seccional_del_sindicato(sindicato_id: int, seccional_id: int) -> Optional[dict]:
    """UNA seccional, o None si no existe o es de otro sindicato.

    El `sindicato_id` va EN el WHERE y no en un chequeo posterior: es la
    misma regla que el resto del proyecto -- una seccional ajena no se
    encuentra, no es que se encuentre y después se descarte."""
    with Session(engine) as s:
        sec = s.exec(select(Seccional).where(
            Seccional.id == seccional_id,
            Seccional.sindicato_id == sindicato_id)).first()
        return _seccional_a_dict(sec) if sec else None


class GeoPadron(SQLModel, table=True):
    """Avance de la georreferenciación masiva del padrón de UN sindicato.

    Vive en la base y no en memoria del proceso porque Render corre un
    worker por núcleo: el hilo que trabaja está en uno y la pantalla que
    pregunta el avance puede caer en otro, y con un diccionario en memoria
    vería cero para siempre. Es el mismo motivo por el que los planes
    programados se coordinan con un UPDATE condicional y no con un flag.

    Una fila por sindicato, reutilizada en cada corrida."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(foreign_key="sindicato.id", index=True, unique=True)
    corriendo: bool = False
    total: int = 0
    hechos: int = 0
    ubicados: int = 0
    iniciado: str = ""
    actualizado: str = ""


# Si una corrida no dio señales en este tiempo, se la da por muerta. Sin
# esto, un proceso que se cae (o un redeploy en el medio) deja `corriendo`
# en true para siempre y nadie puede volver a lanzar la georreferenciación.
MINUTOS_GEO_MUERTA = 15


def _geo_padron(s: Session, sindicato_id: int) -> "GeoPadron":
    fila = s.exec(select(GeoPadron).where(GeoPadron.sindicato_id == sindicato_id)).first()
    if not fila:
        fila = GeoPadron(sindicato_id=sindicato_id)
        s.add(fila); s.commit(); s.refresh(fila)
    return fila


def iniciar_georreferenciacion(sindicato_id: int) -> bool:
    """Reclama la corrida. False si ya hay una viva: el segundo clic no
    arranca un segundo hilo pidiéndole a Nominatim al doble de velocidad."""
    ahora = fechas.ahora_texto()
    with Session(engine) as s:
        fila = _geo_padron(s, sindicato_id)
        if fila.corriendo and not _geo_esta_muerta(fila):
            return False
        pendientes = s.execute(text(
            "SELECT COUNT(*) FROM trabajador WHERE sindicato_id = :sid AND activo "
            "AND latitud IS NULL AND localidad != ''"), {"sid": sindicato_id}).one()[0]
        fila.corriendo, fila.total = True, pendientes
        fila.hechos, fila.ubicados = 0, 0
        fila.iniciado, fila.actualizado = ahora, ahora
        s.add(fila); s.commit()
        return True


def _geo_esta_muerta(fila: "GeoPadron") -> bool:
    try:
        ultimo = datetime.strptime((fila.actualizado or "")[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return True
    return ultimo < fechas.ahora() - timedelta(minutes=MINUTOS_GEO_MUERTA)


def avanzar_georreferenciacion(sindicato_id: int, ubicado: bool) -> None:
    with Session(engine) as s:
        fila = _geo_padron(s, sindicato_id)
        fila.hechos += 1
        fila.ubicados += 1 if ubicado else 0
        fila.actualizado = fechas.ahora_texto()
        s.add(fila); s.commit()


def terminar_georreferenciacion(sindicato_id: int) -> None:
    with Session(engine) as s:
        fila = _geo_padron(s, sindicato_id)
        fila.corriendo = False
        fila.actualizado = fechas.ahora_texto()
        s.add(fila); s.commit()


def estado_georreferenciacion(sindicato_id: int) -> dict:
    """Lo que lee la barra de progreso."""
    with Session(engine) as s:
        fila = _geo_padron(s, sindicato_id)
        corriendo = fila.corriendo and not _geo_esta_muerta(fila)
        return {"corriendo": corriendo, "total": fila.total, "hechos": fila.hechos,
                "ubicados": fila.ubicados, "iniciado": fila.iniciado,
                "actualizado": fila.actualizado}


def trabajadores_sin_geo(sindicato_id: int, alcance=None, limite: int = 2000) -> list:
    """(cuil, domicilio) de los afiliados activos sin coordenadas y CON
    localidad.

    Sin localidad no hay nada que preguntarle a Georef, así que esas filas
    no se cuentan ni se intentan: gastarían un pedido para devolver siempre
    lo mismo. El alcance de seccional se aplica EN la consulta.

    El domicilio sale de la PERSONA (`cuentatrabajador`) y el recorte, del
    empadronamiento: el admin georreferencia SU padrón, pero lo que ubica es
    la dirección de alguien, que es una sola. Devuelve el CUIL y no el id de
    la fila de padrón justamente por eso -- lo que se escribe después no es
    el empadronamiento."""
    conds = ["t.sindicato_id = :sid", "t.activo", "c.latitud IS NULL", "c.localidad != ''"]
    params = {"sid": sindicato_id, "limite": limite}
    if alcance is not None:
        if not alcance:
            return []
        conds.append("t.seccional_id IN :secs")
        params["secs"] = list(alcance)
    sql = (f"SELECT c.cuil, c.calle, c.numero, c.piso_depto, c.localidad, c.provincia, "
           f"c.codigo_postal FROM trabajador t "
           f"JOIN cuentatrabajador c ON c.cuil = t.cuil "
           f"WHERE {' AND '.join(conds)} ORDER BY t.id LIMIT :limite")
    stmt = text(sql)
    if alcance is not None:
        stmt = stmt.bindparams(bindparam("secs", expanding=True))
    with Session(engine) as s:
        filas = s.execute(stmt, params).all()
    return [(f[0], {"calle": f[1], "numero": f[2], "piso_depto": f[3],
                    "localidad": f[4], "provincia": f[5], "codigo_postal": f[6]})
            for f in filas]


def guardar_geo_trabajador(sindicato_id: int, cuil: str, domicilio: dict) -> None:
    """Escribe el bloque de domicilio de UNA persona, previa comprobación de
    que esté empadronada en ESE sindicato. La comprobación no sobra aunque el
    CUIL ya identifique la fila: es lo que impide que el proceso de un
    sindicato termine escribiendo el domicilio de alguien que no es suyo."""
    with Session(engine) as s:
        propio = s.exec(select(Trabajador).where(
            Trabajador.cuil == cuil,
            Trabajador.sindicato_id == sindicato_id)).first()
        if not propio:
            return
        guardar_datos_personales(s, cuil, domicilio=domicilio)
        s.commit()


def contar_afiliados_de_seccional(sindicato_id: int, seccional_id: int) -> int:
    """Cuántos afiliados activos tiene esa seccional. Para la ficha."""
    with Session(engine) as s:
        return s.execute(text(
            "SELECT COUNT(*) FROM trabajador WHERE sindicato_id = :sid "
            "AND seccional_id = :sec AND activo"
        ), {"sid": sindicato_id, "sec": seccional_id}).one()[0]


def seccionales_ubicadas(sindicato_id: int, limite: int = 500) -> list:
    """Las seccionales del sindicato que YA tienen coordenadas.

    Es lo que consume "Seccionales cerca de mí" del trabajador y el mapa del
    Panel Sindical. Devuelve solo datos de la institución (nombre,
    dirección, contacto, horario, coordenadas): ni un dato de una persona.
    El `limite` es una baranda, no una paginación -- el gremio más grande de
    Argentina no llega a 200 seccionales, y si algún día alguien carga un
    padrón raro, mejor cortar que mandar diez mil filas a un teléfono."""
    with Session(engine) as s:
        seccionales = s.exec(select(Seccional).where(
            Seccional.sindicato_id == sindicato_id,
            Seccional.latitud.is_not(None),
            Seccional.longitud.is_not(None),
        ).order_by(Seccional.provincia, Seccional.localidad,
                   Seccional.nombre).limit(limite)).all()
        return [_seccional_a_dict(sec) for sec in seccionales]


# ---------- Identidad del empleado del sindicato (decisión N1) ----------

def _trabajador_por_cuil(s: Session, sindicato_id: int, cuil: str):
    """La fila del padrón de ESE sindicato para ese CUIL, o None.

    Se busca solo dentro del sindicato a propósito: el mismo CUIL puede
    estar empadronado en varios gremios (ver Trabajador), y el empleado de
    uno no tiene nada que ver con su afiliación a otro."""
    if not cuil:
        return None
    return s.exec(select(Trabajador).where(
        Trabajador.sindicato_id == sindicato_id, Trabajador.cuil == cuil)).first()


def sincronizar_empleado(usuario_id: int) -> Optional[int]:
    """Rearma el vínculo usuario <-> padrón y deja la marca al día.

    Se llama después de cada alta, edición y baja de usuario, y hace las
    tres cosas de una porque separarlas es lo que las desincroniza:

    1. Busca en el padrón del sindicato el CUIL del usuario y lo vincula
       (o lo deja en NULL si no está: trabajar en el gremio sin estar
       afiliado a él es un caso real).
    2. Prende `es_empleado_sindicato` en esa fila del padrón.
    3. APAGA la marca de la fila que el usuario tenía antes, si ya no le
       corresponde -- pero solo si ningún OTRO usuario activo sigue
       apuntando a ese trabajador. Sin ese chequeo, dar de baja a uno de dos
       empleados con el mismo CUIL (que puede pasar: dos altas, un typo)
       apagaría la marca del que sigue trabajando.

    Devuelve el id del trabajador vinculado, o None.
    """
    with Session(engine) as s:
        u = s.get(UsuarioSindicato, usuario_id)
        if not u:
            return None
        anterior = u.trabajador_id
        nuevo = None
        if u.activo:
            t = _trabajador_por_cuil(s, u.sindicato_id, u.cuil)
            nuevo = t.id if t else None
        u.trabajador_id = nuevo
        s.add(u)
        if nuevo:
            t = s.get(Trabajador, nuevo)
            if t and not t.es_empleado_sindicato:
                t.es_empleado_sindicato = True
                s.add(t)
        if anterior and anterior != nuevo:
            quedan = s.exec(select(UsuarioSindicato).where(
                UsuarioSindicato.trabajador_id == anterior,
                UsuarioSindicato.activo == True,
                UsuarioSindicato.id != usuario_id)).first()
            if not quedan:
                viejo = s.get(Trabajador, anterior)
                if viejo:
                    viejo.es_empleado_sindicato = False
                    s.add(viejo)
        s.commit()
        return nuevo


def sincronizar_por_cuil(sindicato_id: int, cuil: str) -> None:
    """El camino INVERSO: se acaba de tocar una fila del padrón, hay que ver
    si ese CUIL tiene usuario del panel.

    Hace falta porque las dos altas pueden venir en cualquier orden. Lo
    normal es dar de alta al empleado en el padrón y después darle usuario,
    pero al revés pasa igual -- y sin esto, el que ya tenía usuario quedaría
    en el padrón sin la marca y sin vínculo, en silencio."""
    if not cuil:
        return
    with Session(engine) as s:
        usuarios = s.exec(select(UsuarioSindicato).where(
            UsuarioSindicato.sindicato_id == sindicato_id,
            UsuarioSindicato.cuil == cuil)).all()
        ids = [u.id for u in usuarios]
    for uid in ids:
        sincronizar_empleado(uid)


# ---------- Cuenta del panel: una clave por CUIL (2026-10-17) ----------

def cuenta_panel(cuil: str):
    """La cuenta del panel de ese CUIL, o None."""
    with Session(engine) as s:
        return s.exec(select(CuentaPanel).where(CuentaPanel.cuil == cuil)).first()


def fijar_clave_panel(cuil: str, clave_hash: str, debe_cambiar: bool) -> None:
    """Única escritura de la clave del panel: la crea si no existe. La
    llaman el reseteo de plataforma, el reseteo del Super Admin de un
    sindicato (los dos con `debe_cambiar=True`: la clave la puso otro) y el
    cambio de clave de la propia persona (`debe_cambiar=False`)."""
    with Session(engine) as s:
        c = s.exec(select(CuentaPanel).where(CuentaPanel.cuil == cuil)).first()
        if not c:
            c = CuentaPanel(cuil=cuil)
        c.clave_hash = clave_hash
        c.debe_cambiar_clave = debe_cambiar
        if debe_cambiar:
            # La clave la puso otro (alta o restablecimiento): se corta el
            # vínculo con Google. El mail de la cuenta se deja.
            c.google_sub = ""
        s.add(c)
        s.commit()


def guardar_mail_panel(cuil: str, mail: str, solo_si_vacio: bool) -> bool:
    """El mail de la CUENTA del operador (de la persona, como la clave). Con
    `solo_si_vacio` (altas y ediciones de un sindicato) no pisa uno ya cargado:
    un sindicato no le cambia a la persona el mail con que entra a otro panel.
    Sin él (la persona misma, en «Tu cuenta») lo reemplaza, y al cambiar se
    suelta el vínculo con Google. Devuelve si escribió. La validez del mail la
    mira quien llama (`correo.destino_valido`)."""
    mail = (mail or "").strip().lower()
    with Session(engine) as s:
        c = s.exec(select(CuentaPanel).where(CuentaPanel.cuil == cuil)).first()
        if not c:
            return False
        if solo_si_vacio and ((c.mail or "").strip() or not mail):
            return False
        if (c.mail or "").strip().lower() != mail:
            c.google_sub = ""
        c.mail = mail
        s.add(c)
        s.commit()
        return True


def mail_panel_de(cuil: str) -> str:
    c = cuenta_panel(cuil) if cuil else None
    return (c.mail or "") if c else ""


def trabaja_en_otro_sindicato(cuil: str, sindicato_id: int) -> bool:
    """¿Esa persona tiene un usuario del panel en algún sindicato que NO es
    este, activo o no? Si sí, su clave (una sola, `CuentaPanel`) también abre
    ese otro panel, y por eso un sindicato no puede restablecerla: quien la
    fijara entraría al otro gremio con ella. Cuenta también las filas dadas de
    baja, porque se pueden reactivar sin que nadie pase por acá."""
    with Session(engine) as s:
        return s.exec(select(UsuarioSindicato.id).where(
            UsuarioSindicato.cuil == cuil,
            UsuarioSindicato.sindicato_id != sindicato_id)).first() is not None


def sindicatos_del_operador(cuil: str) -> list:
    """Los usuarios ACTIVOS del panel de ese CUIL, uno por sindicato activo,
    con lo que el selector de después del login necesita mostrar. Ordenado
    por nombre del sindicato: el orden de la base no es un criterio."""
    with Session(engine) as s:
        filas = s.exec(select(UsuarioSindicato, Sindicato, _hay_bytes(Sindicato.logo_datos)).where(
            UsuarioSindicato.cuil == cuil, UsuarioSindicato.activo == True,
            Sindicato.id == UsuarioSindicato.sindicato_id,
            Sindicato.activo == True)).all()
        areas = {a.id: a.nombre for a in s.exec(select(Area).where(
            Area.id.in_([u.area_id for u, _, _ in filas if u.area_id] or [0]))).all()}
        secs = {x.id: x.nombre for x in s.exec(select(Seccional).where(
            Seccional.id.in_([u.seccional_id for u, _, _ in filas if u.seccional_id] or [0]))).all()}
        salida = [{
            "usuario_id": u.id, "sindicato_id": sind.id, "sindicato": sind.nombre,
            "logo": bool(logo),
            "rol": ("Super Admin" if u.es_super_admin else
                    "Admin de Seccional" if u.es_admin_seccional else "Usuario de área"),
            "area": areas.get(u.area_id, ""), "seccional": secs.get(u.seccional_id, ""),
        } for u, sind, logo in filas]
    return sorted(salida, key=lambda x: x["sindicato"].lower())


def operadores_de_todos_los_sindicatos() -> list:
    """Para plataforma: una fila por PERSONA (CUIL) con todos los sindicatos
    en los que tiene usuario del panel y el estado de su cuenta. Es la vista
    que permite ver de un vistazo quién trabaja en más de un gremio."""
    with Session(engine) as s:
        filas = s.exec(select(UsuarioSindicato, Sindicato).where(
            Sindicato.id == UsuarioSindicato.sindicato_id)).all()
        cuentas = {c.cuil: c for c in s.exec(select(CuentaPanel)).all()}
    personas: dict = {}
    for u, sind in filas:
        p = personas.setdefault(u.cuil, {"cuil": u.cuil, "nombre": "", "sindicatos": []})
        p["nombre"] = p["nombre"] or u.nombre
        p["sindicatos"].append({
            "sindicato": sind.nombre, "activo": bool(u.activo and sind.activo),
            "rol": ("Super Admin" if u.es_super_admin else
                    "Admin de Seccional" if u.es_admin_seccional else "Usuario de área")})
    for p in personas.values():
        c = cuentas.get(p["cuil"])
        p["cuenta"] = ("sin clave" if not c or not c.clave_hash else
                       "clave inicial" if c.debe_cambiar_clave else "clave propia")
        p["sindicatos"].sort(key=lambda x: x["sindicato"].lower())
    return sorted(personas.values(), key=lambda p: ((p["nombre"] or "").lower(), p["cuil"]))


def empleados_del_sindicato(sindicato_id: int) -> list:
    """CUILs del padrón marcados como empleados del sindicato. Lo usa la
    pantalla de Trabajadores para distinguirlos de un afiliado común."""
    with Session(engine) as s:
        return sorted({t.cuil for t in s.exec(select(Trabajador).where(
            Trabajador.sindicato_id == sindicato_id,
            Trabajador.es_empleado_sindicato == True)).all()})


# ---------- Áreas y permisos (CRUD del Super Admin) ----------

def areas_del_sindicato(sindicato_id: int, alcance=None) -> list:
    """Áreas del sindicato con su seccional y sus permisos, para el CRUD y
    los <select>.

    `alcance` es lo que devuelve alcance_seccional(): None = todas (Super
    Admin), un set = solo las áreas de esas seccionales. Filtrar ACÁ y no en
    la plantilla es a propósito -- si el recorte viviera en el HTML, las
    áreas de otras seccionales viajarían igual en la página.

    Trae los permisos en la misma pasada: la pantalla siempre los muestra
    junto al área, y son pocas filas."""
    with Session(engine) as s:
        consulta = select(Area).where(Area.sindicato_id == sindicato_id)
        if alcance is not None:
            if not alcance:
                return []
            consulta = consulta.where(Area.seccional_id.in_(list(alcance)))
        areas = s.exec(consulta.order_by(Area.nombre)).all()
        ids = [a.id for a in areas]
        por_area = {i: [] for i in ids}
        if ids:
            for x in s.exec(select(PermisoArea).where(PermisoArea.area_id.in_(ids))).all():
                por_area[x.area_id].append(x.seccion)
        secs = {x.id: x.nombre for x in s.exec(select(Seccional).where(
            Seccional.sindicato_id == sindicato_id)).all()}
        return [{"id": a.id, "nombre": a.nombre, "activo": a.activo,
                 "seccional_id": a.seccional_id,
                 "seccional": secs.get(a.seccional_id, ""),
                 "permisos": sorted(por_area.get(a.id, []))} for a in areas]


def set_permisos_area(area_id: int, secciones: list, sindicato_id: int) -> None:
    """Reemplaza los permisos del área. Descarta cualquier sección que no
    exista en el catálogo o que el sindicato no tenga contratada -- mismo
    criterio defensivo que set_modulos_sindicato: no se guarda basura que
    después haya que filtrar en cada lectura."""
    from permisos import secciones_de_modulos
    with Session(engine) as s:
        area = s.get(Area, area_id)
        if not area or area.sindicato_id != sindicato_id:
            return
        validas = set(secciones_de_modulos(modulos_habilitados(sindicato_id)))
        for x in s.exec(select(PermisoArea).where(PermisoArea.area_id == area_id)).all():
            s.delete(x)
        for seccion in dict.fromkeys(secciones or []):   # sin repetidos, sin perder el orden
            if seccion in validas:
                s.add(PermisoArea(area_id=area_id, seccion=seccion))
        s.commit()


def permisos_individuales(usuario_id: int) -> dict:
    """{"agregar": [...], "bloquear": [...]} del usuario, para pintar la
    pantalla en sus tres estados (hereda / agregado / bloqueado)."""
    with Session(engine) as s:
        filas = s.exec(select(PermisoUsuario).where(
            PermisoUsuario.usuario_id == usuario_id)).all()
        return {
            "agregar": sorted(x.seccion for x in filas if x.tipo == "agregar"),
            "bloquear": sorted(x.seccion for x in filas if x.tipo == "bloquear"),
        }


def set_permisos_usuario(usuario_id: int, agregar: list, bloquear: list,
                         sindicato_id: int) -> None:
    """Reemplaza los ajustes individuales del usuario.

    Si una sección viene en las dos listas gana BLOQUEAR, por lo mismo que
    el bloqueo le gana al área en el cálculo: es el único orden que hace
    que "bloqueado" signifique algo estable."""
    from permisos import secciones_de_modulos
    with Session(engine) as s:
        u = s.get(UsuarioSindicato, usuario_id)
        if not u or u.sindicato_id != sindicato_id:
            return
        validas = set(secciones_de_modulos(modulos_habilitados(sindicato_id)))
        for x in s.exec(select(PermisoUsuario).where(
                PermisoUsuario.usuario_id == usuario_id)).all():
            s.delete(x)
        bloqueadas = {x for x in (bloquear or []) if x in validas}
        for seccion in bloqueadas:
            s.add(PermisoUsuario(usuario_id=usuario_id, seccion=seccion, tipo="bloquear"))
        for seccion in {x for x in (agregar or []) if x in validas} - bloqueadas:
            s.add(PermisoUsuario(usuario_id=usuario_id, seccion=seccion, tipo="agregar"))
        s.commit()


def usuarios_del_sindicato(sindicato_id: int, alcance=None) -> list:
    """Usuarios del panel con su rol, área, seccional y ajustes individuales
    -- todo lo que la pantalla de "Áreas y Usuarios" necesita mostrar.

    `alcance` recorta igual que en areas_del_sindicato, y por el mismo
    motivo: un admin de seccional no tiene por qué recibir en el HTML los
    CUIT de los usuarios de otra delegación. Los Super Admin quedan SIEMPRE
    fuera del recorte -- no pertenecen a una sola seccional, y esconderlos
    haría que el admin local no entienda quién más administra el sindicato.
    """
    with Session(engine) as s:
        consulta = select(UsuarioSindicato).where(
            UsuarioSindicato.sindicato_id == sindicato_id)
        if alcance is not None:
            if not alcance:
                return []
            consulta = consulta.where(
                UsuarioSindicato.seccional_id.in_(list(alcance)))
        usuarios = s.exec(consulta.order_by(
            UsuarioSindicato.activo.desc(), UsuarioSindicato.nombre)).all()
        areas = {a.id: a.nombre for a in s.exec(select(Area).where(
            Area.sindicato_id == sindicato_id)).all()}
        secs = {x.id: x.nombre for x in s.exec(select(Seccional).where(
            Seccional.sindicato_id == sindicato_id)).all()}
        cuiles = [u.cuil for u in usuarios if u.cuil] or [""]
        cuentas = {c.cuil: c for c in s.exec(select(CuentaPanel).where(
            CuentaPanel.cuil.in_(cuiles))).all()}
        salida = []
        for u in usuarios:
            ind = permisos_individuales(u.id)
            salida.append({
                "id": u.id, "usuario": u.usuario, "nombre": u.nombre, "activo": u.activo,
                "cuil": u.cuil, "trabajador_id": u.trabajador_id,
                "es_afiliado": bool(u.trabajador_id),
                # De la CUENTA de la persona, no de la fila: la clave es una
                # sola para todos los sindicatos en los que trabaja.
                "debe_cambiar_clave": bool(cuentas.get(u.cuil) and cuentas[u.cuil].debe_cambiar_clave),
                "sin_clave": not (cuentas.get(u.cuil) and cuentas[u.cuil].clave_hash),
                "es_super_admin": u.es_super_admin,
                "es_admin_seccional": u.es_admin_seccional,
                "area_id": u.area_id, "area": areas.get(u.area_id, ""),
                "seccional_id": u.seccional_id, "seccional": secs.get(u.seccional_id, ""),
                "agregados": ind["agregar"], "bloqueados": ind["bloquear"],
                "efectivos": sorted(permisos_efectivos(u.id)),
            })
        return salida


def seccional_de_trabajador(cuil: str, sindicato_id: int) -> Optional[int]:
    """seccional_id del trabajador en ESE sindicato (None si no tiene
    asignada) -- para filtrar Noticias/Beneficios por destino."""
    with Session(engine) as s:
        t = s.exec(select(Trabajador).where(
            Trabajador.cuil == cuil, Trabajador.sindicato_id == sindicato_id)).first()
        return t.seccional_id if t else None


class RegistroEnmascarado(SQLModel, table=True):
    """Una fila por documento que pasó por el enmascarado en modo sombra o
    activo (preparacion.py): si se tapó, qué camino tomó y, si no se pudo,
    por qué. Es el "log para análisis posterior" de la decisión de mejor
    esfuerzo, y lo que dice en Pruebas cuántas fotos quedan sin tapar en una
    ráfaga.

    **Sin ningún dato personal a propósito**: ni CUIL, ni nombre, ni texto
    del documento -- la tabla existe para medir la protección de esos datos
    y no puede ser un lugar más donde queden."""
    id: Optional[int] = Field(default=None, primary_key=True)
    fecha: str = ""                  # "AAAA-MM-DD HH:MM", hora de Buenos Aires
    sindicato_id: Optional[int] = Field(default=None, foreign_key="sindicato.id", index=True)
    tipo: str = ""                   # "recibo" | "aportes" | "aprendizaje"
    modo: str = ""                   # "sombra" | "activo"
    camino: str = ""                 # "pdf_texto" | "pdf_imagen" | "foto" | "otro"
    motivo: str = ""                 # "ok" | "sin_ocr" | "sin_lugar" | "tiempo" | "sin_palabras" | "error:..."
    tapado: bool = False             # si lo que viajó iba tapado
    cajas: int = 0                   # zonas tapadas (o que se habrían tapado, en sombra)
    fugas: int = 0                   # lo que el control de fuga vio a la vista
    cuil_encontrado: Optional[bool] = None
    pertenece: Optional[bool] = None # None: no se pudo afirmar
    espera_ms: int = 0               # fila por un lector de OCR libre
    lectura_ms: int = 0              # OCR
    total_ms: int = 0                # todo el paso, de punta a punta


class ImagenEnmascarado(SQLModel, table=True):
    """DIAGNÓSTICO TRANSITORIO, solo Pruebas (pedido de SDN, 2026-09-24): la
    imagen original y la que se mandó a la IA de un documento del enmascarado,
    para ver en la pantalla qué se tapó de verdad.

    **La original tiene datos personales reales.** Por eso vive en una tabla
    aparte de `RegistroEnmascarado` (que sigue sin ninguno), solo se escribe
    donde `preparacion.guardar_imagenes_habilitado()` lo permite (entorno
    local o pruebas + ENMASCARADO_GUARDAR_IMAGENES=1), vence a los
    `preparacion.DIAS_IMAGENES` días y se vacía entera desde la pantalla."""
    id: Optional[int] = Field(default=None, primary_key=True)
    registro_id: int = Field(foreign_key="registroenmascarado.id", index=True)
    creado: str = ""                              # "AAAA-MM-DD HH:MM", Buenos Aires
    original: bytes = b""
    enviada: bytes = b""


def registrar_enmascarado(sindicato_id: Optional[int], tipo: str, registro: dict) -> Optional[int]:
    """Guarda el registro de `preparacion.preparar` y devuelve su id. NUNCA
    levanta: es un registro para mirar después y no puede tumbar la lectura de
    un recibo (mejor esfuerzo), ni siquiera si la tabla todavía no existe
    porque la migración no corrió."""
    if not registro:
        return None
    try:
        campos = {k: registro.get(k) for k in (
            "modo", "camino", "motivo", "tapado", "cajas", "fugas", "cuil_encontrado",
            "pertenece", "espera_ms", "lectura_ms", "total_ms") if registro.get(k) is not None}
        with Session(engine) as s:
            fila = RegistroEnmascarado(fecha=fechas.ahora_texto(), sindicato_id=sindicato_id,
                                       tipo=tipo, **campos)
            s.add(fila)
            s.commit()
            return fila.id
    except Exception as e:
        print(f"[enmascarado] no se pudo registrar ({type(e).__name__})")
        return None


def guardar_imagenes_enmascarado(registro_id: int, original: bytes, enviada: bytes,
                                 dias: int = 7) -> None:
    """Guarda el par de imágenes de diagnóstico y, de paso, borra las que ya
    vencieron. Nunca levanta. Quien llama decide si está habilitado."""
    try:
        limite = (fechas.ahora() - timedelta(days=dias)).strftime("%Y-%m-%d %H:%M")
        with Session(engine) as s:
            s.exec(sa_delete(ImagenEnmascarado).where(ImagenEnmascarado.creado < limite))
            s.add(ImagenEnmascarado(registro_id=registro_id, creado=fechas.ahora_texto(),
                                    original=original, enviada=enviada))
            s.commit()
    except Exception as e:
        print(f"[enmascarado] no se pudieron guardar las imágenes ({type(e).__name__})")


def imagen_enmascarado(registro_id: int, cual: str) -> Optional[bytes]:
    """Los bytes JPEG de la imagen "original" o "enviada" de un registro."""
    if cual not in ("original", "enviada"):
        return None
    with Session(engine) as s:
        f = s.exec(select(ImagenEnmascarado)
                   .where(ImagenEnmascarado.registro_id == registro_id)).first()
        return getattr(f, cual) if f else None


def borrar_imagenes_enmascarado() -> int:
    """Vacía la tabla de imágenes de diagnóstico. Devuelve cuántas borró."""
    with Session(engine) as s:
        n = len(s.exec(select(ImagenEnmascarado.id)).all())
        s.exec(sa_delete(ImagenEnmascarado))
        s.commit()
        return n


def registros_enmascarado(limite: int = 3000) -> list:
    """Los últimos registros del enmascarado, más reciente primero, para la
    sub-pestaña "Enmascarado" de Uso de IA en /plataforma. El `resultado` ya
    viene resuelto, porque en modo sombra nada viaja tapado y lo que importa
    es si SE HABRÍA tapado:

    - "tapado": viajó tapado (modo activo).
    - "se_habria_tapado": en sombra, se leyó bien y había qué tapar.
    - "sin_tapar": no se pudo (el motivo dice por qué) o no se encontró nada.

    Nunca levanta: sin la tabla (migración sin correr) devuelve lista vacía."""
    try:
        with Session(engine) as s:
            filas = s.exec(select(RegistroEnmascarado)
                           .order_by(RegistroEnmascarado.id.desc()).limit(limite)).all()
            nombres = {sind.id: sind.nombre for sind in s.exec(select(Sindicato)).all()}
            try:
                con_imagenes = set(s.exec(select(ImagenEnmascarado.registro_id)).all())
            except Exception:
                con_imagenes = set()
    except Exception:
        return []
    salida = []
    for f in filas:
        leido = f.motivo == "ok" and f.cajas > 0
        salida.append({
            "fecha": f.fecha, "sindicato": nombres.get(f.sindicato_id, "—"),
            "tipo": f.tipo, "modo": f.modo, "camino": f.camino or "—", "motivo": f.motivo,
            "tapado": f.tapado, "cajas": f.cajas, "fugas": f.fugas,
            "cuil_encontrado": f.cuil_encontrado, "pertenece": f.pertenece,
            "espera_ms": f.espera_ms, "lectura_ms": f.lectura_ms, "total_ms": f.total_ms,
            "resultado": ("tapado" if f.tapado else "se_habria_tapado") if leido else "sin_tapar",
            "id": f.id, "con_imagenes": f.id in con_imagenes,
        })
    return salida


def cuits_conocidos(cuil: str = "", sindicato_id: Optional[int] = None) -> tuple:
    """Los CUITs de empleador que la app ya conoce, para el enmascarado: con
    `cuil`, los de esa persona (su empadronamiento y sus recibos anteriores);
    con `sindicato_id`, los de ese sindicato (empleadores y conceptos). Un
    CUIT leído que coincide con uno de estos se tapa y se rearma con el
    conocido. Vacío si algo falla: el enmascarado es mejor esfuerzo."""
    def dig(x):
        return "".join(c for c in (x or "") if c.isdigit())
    cuil = dig(cuil)
    res = set()
    try:
        with Session(engine) as s:
            if cuil:
                res |= set(s.exec(select(Trabajador.cuit_empleador)
                                  .where(Trabajador.cuil == cuil)).all())
                res |= set(s.exec(select(ReciboVerificado.cuit_empleador)
                                  .where(ReciboVerificado.cuil == cuil).distinct()).all())
            if sindicato_id:
                res |= set(s.exec(select(Empleador.cuit)
                                  .where(Empleador.sindicato_id == sindicato_id)).all())
                res |= set(s.exec(select(Concepto.cuit_empleador)
                                  .where(Concepto.sindicato_id == sindicato_id).distinct()).all())
    except Exception:
        return ()
    return tuple(sorted(d for d in map(dig, res) if len(d) == 11))


def razon_social_de_cuit(sindicato_id: Optional[int], cuit: str) -> Optional[str]:
    """La razón social con que el sindicato tiene cargado a ese empleador,
    para rearmar el recibo cuando se le tapó a la IA. None si no está."""
    cuit = "".join(c for c in (cuit or "") if c.isdigit())
    if not cuit or not sindicato_id:
        return None
    try:
        with Session(engine) as s:
            e = s.exec(select(Empleador).where(Empleador.sindicato_id == sindicato_id,
                                               Empleador.cuit == cuit)).first()
            return (e.razon_social or None) if e else None
    except Exception:
        return None


def registrar_uso_ia(sindicato_id: Optional[int], cuil: str, tipo: str,
                      modelo: str, tokens_entrada: int, tokens_salida: int,
                      duracion_ms: int = 0, tokens_cache_lectura: int = 0,
                      tokens_cache_escritura: int = 0) -> None:
    """Guarda una fila de consumo de la API por cada llamada real -- se llama
    en el mismo request que hace la llamada (extraer/extraer_aportes), nunca
    se re-arma después, para que el conteo no dependa de que el trabajador
    confirme o reporte nada.

    El precio vigente se copia acá adentro y no lo pasa quien llama: es un
    dato del catálogo, no del request, y así ningún punto de registro puede
    olvidarse de congelarlo. Un modelo que no está en el catálogo queda en 0,
    que la pantalla lee como "no se puede saber" y no como "salió gratis"."""
    p = precios_ia.precios(modelo) or (0.0, 0.0)
    with Session(engine) as s:
        s.add(UsoIA(
            sindicato_id=sindicato_id, cuil=cuil, tipo=tipo, modelo=modelo,
            tokens_entrada=tokens_entrada, tokens_salida=tokens_salida,
            fecha=fechas.ahora_texto(), duracion_ms=duracion_ms or 0,
            precio_entrada=p[0], precio_salida=p[1],
            tokens_cache_lectura=tokens_cache_lectura or 0,
            tokens_cache_escritura=tokens_cache_escritura or 0,
        ))
        s.commit()


def uso_ia_listado() -> list:
    """Todo el consumo de IA de TODOS los sindicatos, más reciente primero,
    con el nombre del sindicato ya resuelto (para el panel de plataforma)."""
    with Session(engine) as s:
        filas = s.exec(select(UsoIA).order_by(UsoIA.id.desc())).all()
        nombres = {sind.id: sind.nombre for sind in s.exec(select(Sindicato)).all()}
        return [_uso_ia_fila(f, nombres) for f in filas]


def _uso_ia_fila(f: UsoIA, nombres: dict) -> dict:
    """Una fila del listado, con el costo YA calculado.

    Si la fila congeló su precio, el costo es exacto. Si no (todo lo
    registrado antes de que existiera la columna), se estima con los precios
    de hoy y se marca `costo_exacto=False` para que la pantalla lo diga: un
    número sin aclarar de dónde sale es peor que no tenerlo."""
    # Las filas de mock que ya están guardadas traen los 15 s del sleep de
    # MOCK_EXTRACTOR_LATENCIA. Nunca fueron una medición, así que se leen como
    # "no se sabe" -- si no, el tiempo mediano del panel en Pruebas lo decide
    # una variable de entorno.
    duracion = 0 if f.modelo == precios_ia.MOCK else f.duracion_ms
    if f.precio_entrada or f.precio_salida:
        costo = precios_ia.costo(f.tokens_entrada, f.tokens_salida,
                                 f.precio_entrada, f.precio_salida,
                                 f.tokens_cache_lectura, f.tokens_cache_escritura)
        exacto = True
    else:
        costo = precios_ia.costo_estimado(f.modelo, f.tokens_entrada, f.tokens_salida,
                                          f.tokens_cache_lectura, f.tokens_cache_escritura)
        exacto = False
    return {
        "id": f.id, "sindicato": nombres.get(f.sindicato_id, "—"),
        "sindicato_id": f.sindicato_id, "cuil": f.cuil, "tipo": f.tipo,
        "modelo": f.modelo, "modelo_nombre": precios_ia.nombre(f.modelo),
        "tokens_entrada": f.tokens_entrada,
        "tokens_salida": f.tokens_salida, "fecha": f.fecha,
        "tokens_cache_lectura": f.tokens_cache_lectura or 0,
        "tokens_cache_escritura": f.tokens_cache_escritura or 0,
        "duracion_ms": duracion, "duracion_txt": precios_ia.segundos(duracion),
        "costo": costo, "costo_exacto": exacto and costo is not None,
        "costo_txt": precios_ia.usd(costo),
    }


def registrar_recibo_sospechoso(sindicato_id: Optional[int], cuil: str, periodo: str,
                                 motivo: str, archivo_datos: bytes, archivo_mime: str,
                                 archivo_nombre: str) -> None:
    """Guarda el recibo (imagen o PDF) que la IA marcó con alto grado de
    certeza de datos posiblemente adulterados, para que la plataforma lo
    pueda revisar. sindicato_id puede ser None si todavía no se resolvió
    (no bloquea la detección)."""
    with Session(engine) as s:
        s.add(ReciboSospechoso(
            sindicato_id=sindicato_id or None, cuil=cuil, periodo=periodo or "", motivo=motivo or "",
            fecha=fechas.ahora_texto(),
            archivo_datos=archivo_datos, archivo_mime=archivo_mime or "",
            archivo_nombre=archivo_nombre or "",
        ))
        s.commit()


def recibos_sospechosos_listado() -> list:
    """Todos los recibos marcados como posiblemente adulterados, de TODOS
    los sindicatos, más reciente primero -- para el panel de plataforma."""
    with Session(engine) as s:
        filas = s.exec(select(ReciboSospechoso).order_by(ReciboSospechoso.id.desc())).all()
        nombres = {sind.id: sind.nombre for sind in s.exec(select(Sindicato)).all()}
        return [{
            "id": f.id, "sindicato": nombres.get(f.sindicato_id, "—"),
            "sindicato_id": f.sindicato_id, "cuil": f.cuil, "periodo": f.periodo,
            "motivo": f.motivo, "fecha": f.fecha, "archivo_nombre": f.archivo_nombre,
        } for f in filas]


# ---------- Notificaciones (Fase 2 de Módulos + Notificaciones + Trámites) ----------

def resolver_destinatarios(sindicato_id: int, criterio: str, valores: list,
                            usuario_id: Optional[int] = None) -> list:
    """CUILs de trabajadores ACTIVOS de este sindicato que matchean el
    criterio -- usado tanto por el preview (solo cuenta) como por el envío
    real (que además fija la lista, ver crear_notificacion). El sindicato
    solo puede targetear su propia gente: un valor que no matchea ningún
    trabajador de ESTE sindicato_id simplemente no suma destinatarios.

    Con `usuario_id` se recorta además por el ALCANCE DE SECCIONAL de quien
    envía (decisión N10): Prensa de Sede Central le escribe a todo el país,
    Prensa de Córdoba solo a Córdoba.

    El recorte vive ACÁ y no en la ruta a propósito: esta es la MISMA
    función que usan el preview y el envío real. Si el recorte estuviera en
    la ruta, el preview podría contar de más y el admin vería un número
    distinto del que sale -- y el error sería silencioso, porque nadie
    compara los dos.

    Se aplica a TODOS los criterios, no solo a "cuil": por provincia o
    pidiendo otra seccional se llegaría igual a gente de afuera."""
    valores = [str(v).strip() for v in (valores or []) if str(v).strip()]
    # "todos" es el único criterio sin valores: es el padrón entero, ya
    # recortado por el alcance de quien envía como todos los demás. Lo usan
    # las encuestas dirigidas a todo el gremio.
    if not valores and criterio != "todos":
        return []
    alcance = alcance_seccional(usuario_id) if usuario_id else None
    if alcance is not None and not alcance:
        return []
    with Session(engine) as s:
        # La provincia es de la PERSONA, así que el criterio "provincia" sale
        # del JOIN y no de una columna del empadronamiento. Se trae siempre
        # (no solo para ese criterio) para no tener dos consultas distintas
        # según el criterio, que es como se terminan aplicando dos recortes
        # de alcance distintos sin que nadie lo note.
        q = (select(Trabajador, CuentaTrabajador.provincia)
             .join(CuentaTrabajador, CuentaTrabajador.cuil == Trabajador.cuil, isouter=True)
             .where(Trabajador.sindicato_id == sindicato_id, Trabajador.activo == True))
        if alcance is not None:
            q = q.where(Trabajador.seccional_id.in_(list(alcance)))
        filas = s.exec(q).all()
    if criterio == "todos":
        return sorted({t.cuil for t, _prov in filas})
    # CUIL y CUIT se comparan NORMALIZADOS de los dos lados: el admin los tipea
    # con o sin guiones y las filas viejas pueden tenerlos guardados de las
    # dos formas (PLAN_CUIT_MOD11.md; antes "30-11122233-5" no encontraba a
    # quien tenía "30111222335").
    if criterio == "cuil":
        objetivo = {cuit.normalizar(v) for v in valores} - {""}
        return sorted({t.cuil for t, _prov in filas if cuit.normalizar(t.cuil) in objetivo})
    if criterio == "cuit_empleador":
        objetivo = {cuit.normalizar(v) for v in valores} - {""}
        return sorted({t.cuil for t, _prov in filas
                       if cuit.normalizar(t.cuit_empleador) in objetivo})
    if criterio == "seccional":
        objetivo = {int(v) for v in valores if v.isdigit()}
        return sorted({t.cuil for t, _prov in filas if t.seccional_id in objetivo})
    if criterio == "provincia":
        objetivo = set(valores)
        return sorted({t.cuil for t, prov in filas if prov in objetivo})
    return []


def crear_notificacion(sindicato_id: int, usuario_id: Optional[int], remitente: str, texto: str,
                        criterio: str, valores: list, adjunto_datos: Optional[bytes] = None,
                        adjunto_mime: str = "", adjunto_nombre: str = "",
                        origen: str = "manual", formulario_id: Optional[int] = None,
                        encuesta_id: Optional[int] = None) -> dict:
    """Resuelve los destinatarios y los FIJA en el momento de enviar (snapshot,
    ver Notificacion). Devuelve id y cantidad real, para la confirmación.

    `usuario_id` no es solo para registrar quién mandó: se le pasa a
    resolver_destinatarios para que el ALCANCE recorte a quién le llega
    (decisión N10). Es la misma función que usa el preview, así que el
    número que el admin confirmó es el que sale."""
    cuils = resolver_destinatarios(sindicato_id, criterio, valores, usuario_id=usuario_id)
    with Session(engine) as s:
        n = Notificacion(
            sindicato_id=sindicato_id, remitente=remitente or "", usuario_id=usuario_id,
            texto=texto or "", adjunto_datos=adjunto_datos, adjunto_mime=adjunto_mime or "",
            adjunto_nombre=adjunto_nombre or "", criterio=criterio, criterio_valores=list(valores or []),
            origen=origen, enviado_en=fechas.ahora_texto(),
            cantidad_destinatarios=len(cuils), formulario_id=formulario_id,
            encuesta_id=encuesta_id,
        )
        s.add(n); s.commit(); s.refresh(n)
        for cuil in cuils:
            s.add(NotificacionDestinatario(notificacion_id=n.id, cuil=cuil))
        s.commit()
        return {"id": n.id, "cantidad_destinatarios": len(cuils)}


def notificaciones_del_sindicato(sindicato_id: int, usuario_id: Optional[int] = None) -> list:
    """Notificaciones enviadas por este sindicato, con el resumen
    leídos/total, más recientes primero -- para el listado de admin.

    Con `usuario_id` se recorta a las que tienen AL MENOS UN destinatario
    dentro de su alcance: cada uno ve el historial de aquellos a quienes
    podría escribirle (decisión N10). Una notificación que salió a todo el
    país la ve también el admin de Córdoba, porque incluye a su gente -- lo
    que no ve son las que fueron solo a otras delegaciones.

    Y la lista de destinatarios se recorta también, en
    destinatarios_de_notificacion: sin eso, el resumen ocultaría lo ajeno
    pero el detalle lo mostraría igual."""
    alcance = alcance_seccional(usuario_id) if usuario_id else None
    if alcance is not None and not alcance:
        return []
    with Session(engine) as s:
        filas = s.exec(select(Notificacion).where(Notificacion.sindicato_id == sindicato_id)
                       .order_by(Notificacion.id.desc())).all()
        if alcance is not None:
            propios = {t.cuil for t in s.exec(select(Trabajador).where(
                Trabajador.sindicato_id == sindicato_id,
                Trabajador.seccional_id.in_(list(alcance)))).all()}
            visibles = {d.notificacion_id for d in s.exec(
                select(NotificacionDestinatario)).all() if d.cuil in propios}
            filas = [n for n in filas if n.id in visibles]
        resultado = []
        con_adjunto = _ids_con_bytes(s, Notificacion.adjunto_datos, [n.id for n in filas])
        for n in filas:
            dests = s.exec(select(NotificacionDestinatario).where(
                NotificacionDestinatario.notificacion_id == n.id)).all()
            leidos = sum(1 for d in dests if d.leida_en)
            resultado.append({
                "id": n.id, "remitente": n.remitente, "texto": n.texto,
                "tiene_adjunto": n.id in con_adjunto, "adjunto_nombre": n.adjunto_nombre,
                "criterio": n.criterio, "criterio_valores": n.criterio_valores or [],
                "origen": n.origen, "enviado_en": n.enviado_en,
                "cantidad_destinatarios": n.cantidad_destinatarios,
                "leidos": leidos,
            })
        return resultado


def notificacion_destinatarios(notificacion_id: int, usuario_id: Optional[int] = None) -> list:
    """Detalle fila por fila (CUIL + si leyó y cuándo) de una notificación.

    Con `usuario_id` se recorta a los destinatarios de SU alcance
    (decisión N10). Es la otra mitad del recorte del historial: sin esto,
    el listado escondería las notificaciones ajenas pero el detalle de una
    compartida entregaría igual los CUIL de todas las delegaciones."""
    alcance = alcance_seccional(usuario_id) if usuario_id else None
    if alcance is not None and not alcance:
        return []
    with Session(engine) as s:
        dests = s.exec(select(NotificacionDestinatario).where(
            NotificacionDestinatario.notificacion_id == notificacion_id).order_by(
            NotificacionDestinatario.cuil)).all()
        if alcance is not None:
            n = s.get(Notificacion, notificacion_id)
            propios = {t.cuil for t in s.exec(select(Trabajador).where(
                Trabajador.sindicato_id == (n.sindicato_id if n else 0),
                Trabajador.seccional_id.in_(list(alcance)))).all()}
            dests = [d for d in dests if d.cuil in propios]
        nombres = {c.cuil: c.nombre for c in s.exec(select(CuentaTrabajador)).all()}
        return [{
            "cuil": d.cuil, "nombre": nombres.get(d.cuil, ""), "leida_en": d.leida_en,
        } for d in dests]


def notificaciones_de_trabajador(cuil: str, sindicato_id: int) -> list:
    """Notificaciones que le llegaron a este CUIL en este sindicato, más
    nuevas primero -- para la portada y la bandeja del afiliado.

    "Más nueva" es por FECHA DE ENVÍO, no por id: un aviso programado o
    cargado con fecha tiene un id que no dice cuándo salió, y la bandeja es
    una línea de tiempo que muestra esa fecha -- ordenada por id saltaba
    para atrás y para adelante (29/09, 16/08, 06/08, 01/09...). El id
    desempata dos avisos del mismo minuto. `enviado_en` es texto
    "AAAA-MM-DD HH:MM", que ordena igual que la fecha."""
    with Session(engine) as s:
        dests = s.exec(select(NotificacionDestinatario).where(
            NotificacionDestinatario.cuil == cuil)).all()
        if not dests:
            return []
        por_id = {d.notificacion_id: d for d in dests}
        notifs = s.exec(select(Notificacion).where(
            Notificacion.id.in_(por_id.keys()), Notificacion.sindicato_id == sindicato_id)
            .order_by(Notificacion.enviado_en.desc(), Notificacion.id.desc())).all()
        # el ícono "completá los datos" solo se muestra si el formulario
        # referido sigue siendo un tipo activo del sindicato
        forms_ref = {n.formulario_id for n in notifs if n.formulario_id}
        activos = {t.id for t in s.exec(select(TipoTramite).where(
            TipoTramite.id.in_(forms_ref), TipoTramite.sindicato_id == sindicato_id,
            TipoTramite.activo == True)).all()} if forms_ref else set()  # noqa: E712
        # El botón "Responder la encuesta" solo si sigue abierta: un aviso
        # viejo de una encuesta cerrada llevaría a una pantalla que ya no
        # acepta nada.
        encuestas_ref = {n.encuesta_id for n in notifs if n.encuesta_id}
        hoy = fechas.hoy_texto()
        abiertas = {e.id for e in s.exec(select(Encuesta).where(
            Encuesta.id.in_(encuestas_ref),
            Encuesta.sindicato_id == sindicato_id)).all()
            if encuestas.acepta_respuestas(e.publicada, e.fecha_desde, e.fecha_hasta,
                                            hoy, e.cerrada_en)} if encuestas_ref else set()
        con_adjunto = _ids_con_bytes(s, Notificacion.adjunto_datos, [n.id for n in notifs])
        return [{
            "id": n.id, "remitente": n.remitente, "texto": n.texto,
            "tiene_adjunto": n.id in con_adjunto, "adjunto_nombre": n.adjunto_nombre,
            "enviado_en": n.enviado_en, "leida_en": por_id[n.id].leida_en,
            "formulario_id": n.formulario_id if n.formulario_id in activos else None,
            "encuesta_id": n.encuesta_id if n.encuesta_id in abiertas else None,
        } for n in notifs]


def marcar_todas_notificaciones_leidas(cuil: str, sindicato_id: int) -> int:
    """Marca leídas TODAS las copias de este cuil en este sindicato (botón
    "Marcar todas como leídas" de la bandeja). Devuelve cuántas cambió.
    Aislamiento: solo filas de este cuil, y solo notificaciones de este
    sindicato -- las de otro sindicato del mismo CUIL (pluriempleo) no se
    tocan."""
    ahora = fechas.ahora_texto()
    with Session(engine) as s:
        ids_sind = {n.id for n in s.exec(select(Notificacion).where(
            Notificacion.sindicato_id == sindicato_id)).all()}
        if not ids_sind:
            return 0
        pendientes = s.exec(select(NotificacionDestinatario).where(
            NotificacionDestinatario.cuil == cuil,
            NotificacionDestinatario.notificacion_id.in_(ids_sind),
            NotificacionDestinatario.leida_en == None)).all()  # noqa: E711
        for d in pendientes:
            d.leida_en = ahora
            s.add(d)
        s.commit()
        return len(pendientes)


def resumen_recibos_trabajador(cuil: str, sindicato_id: int) -> dict:
    """Lo que la portada del afiliado dice de SUS propios recibos: cuántos
    verificó en lo que va del año y cómo salió el último.

    Todo el filtro va adentro de la consulta. La portada la abre cada
    afiliado en cada entrada a la app, así que no puede traerse el
    historial entero para contarlo en Python.

    El año sale de `fechas.hoy_texto()` (hora de Buenos Aires) y no del
    reloj del servidor, que en Render corre en UTC -- entre las 21:00 y la
    medianoche del 31 de diciembre el contador diría el año que viene.

    El "último" se elige por PERÍODO, no por fecha de carga: alguien que
    sube en diciembre el recibo de marzo no cambia cuál es su último
    recibo. `procesado_en` desempata dos cargas del mismo período (se
    puede volver a subir un recibo corregido).
    """
    from sqlalchemy import func
    anio = fechas.hoy_texto()[:4]
    with Session(engine) as s:
        cantidad = s.execute(
            select(func.count(ReciboVerificado.id)).where(
                ReciboVerificado.cuil == cuil,
                ReciboVerificado.sindicato_id == sindicato_id,
                ReciboVerificado.periodo.like(anio + "-%"))).scalar()
        ultimo = s.exec(
            select(ReciboVerificado)
            .where(ReciboVerificado.cuil == cuil,
                   ReciboVerificado.sindicato_id == sindicato_id)
            .order_by(ReciboVerificado.periodo.desc(),
                      ReciboVerificado.procesado_en.desc())
            .limit(1)).first()
    return {
        "anio": int(cantidad or 0),
        "ultimo_periodo": (ultimo.periodo if ultimo else ""),
        # "OK" | "CON_DISCREPANCIAS" | "" (todavía no verificó ninguno)
        "ultimo_estado": (ultimo.estado if ultimo else ""),
    }


def contar_notificaciones_no_leidas(cuil: str, sindicato_id: int) -> int:
    return sum(1 for n in notificaciones_de_trabajador(cuil, sindicato_id) if not n["leida_en"])


def marcar_notificacion_leida(notificacion_id: int, cuil: str) -> bool:
    """Marca como leída la copia de ESTE cuil (aislamiento: no toca la fila
    de otro destinatario). Devuelve False si el cuil no era destinatario."""
    with Session(engine) as s:
        d = s.exec(select(NotificacionDestinatario).where(
            NotificacionDestinatario.notificacion_id == notificacion_id,
            NotificacionDestinatario.cuil == cuil)).first()
        if not d:
            return False
        if not d.leida_en:
            d.leida_en = fechas.ahora_texto()
            s.add(d); s.commit()
        return True


# ---------- Notificaciones a empleadores (Fase 4 del plan de Empleadores) ----------
# Mismo patrón que las notificaciones al trabajador, en tablas propias
# (NotificacionEmpleador/NotificacionEmpleadorDestinatario) -- ver esas
# clases más arriba para la razón de la separación.

def resolver_destinatarios_empleador(sindicato_id: int, criterio: str, valores: list) -> list:
    """CUITs de empleadores ACTIVOS de este sindicato que matchean el
    criterio. "todos" ignora `valores` (no hace falta elegir nada puntual)."""
    with Session(engine) as s:
        empleadores = s.exec(select(Empleador).where(
            Empleador.sindicato_id == sindicato_id, Empleador.activo == True)).all()
    if criterio == "todos":
        return sorted({e.cuit for e in empleadores})
    valores = [str(v).strip() for v in (valores or []) if str(v).strip()]
    if not valores:
        return []
    if criterio == "cuit":
        # Normalizado de los dos lados, como en resolver_destinatarios.
        objetivo = {cuit.normalizar(v) for v in valores} - {""}
        return sorted({e.cuit for e in empleadores if cuit.normalizar(e.cuit) in objetivo})
    if criterio == "provincia":
        objetivo = set(valores)
        return sorted({e.cuit for e in empleadores if e.provincia in objetivo})
    return []


def crear_notificacion_empleador(sindicato_id: int, usuario_id: Optional[int], remitente: str, texto: str,
                                  criterio: str, valores: list, adjunto_datos: Optional[bytes] = None,
                                  adjunto_mime: str = "", adjunto_nombre: str = "",
                                  origen: str = "manual", formulario_id: Optional[int] = None) -> dict:
    """Resuelve los destinatarios y los FIJA en el momento de enviar
    (snapshot, mismo criterio que crear_notificacion)."""
    cuits = resolver_destinatarios_empleador(sindicato_id, criterio, valores)
    with Session(engine) as s:
        n = NotificacionEmpleador(
            sindicato_id=sindicato_id, remitente=remitente or "", usuario_id=usuario_id,
            texto=texto or "", adjunto_datos=adjunto_datos, adjunto_mime=adjunto_mime or "",
            adjunto_nombre=adjunto_nombre or "", criterio=criterio, criterio_valores=list(valores or []),
            origen=origen, enviado_en=fechas.ahora_texto(),
            cantidad_destinatarios=len(cuits), formulario_id=formulario_id,
        )
        s.add(n); s.commit(); s.refresh(n)
        for cuit in cuits:
            s.add(NotificacionEmpleadorDestinatario(notificacion_empleador_id=n.id, cuit=cuit))
        s.commit()
        return {"id": n.id, "cantidad_destinatarios": len(cuits)}


def notificaciones_empleador_del_sindicato(sindicato_id: int) -> list:
    """Todas las notificaciones a empleadores de este sindicato, con el
    resumen leídos/total, más recientes primero -- para el listado de admin."""
    with Session(engine) as s:
        filas = s.exec(select(NotificacionEmpleador).where(
            NotificacionEmpleador.sindicato_id == sindicato_id)
            .order_by(NotificacionEmpleador.id.desc())).all()
        resultado = []
        con_adjunto = _ids_con_bytes(s, NotificacionEmpleador.adjunto_datos, [n.id for n in filas])
        for n in filas:
            dests = s.exec(select(NotificacionEmpleadorDestinatario).where(
                NotificacionEmpleadorDestinatario.notificacion_empleador_id == n.id)).all()
            leidos = sum(1 for d in dests if d.leida_en)
            resultado.append({
                "id": n.id, "remitente": n.remitente, "texto": n.texto,
                "tiene_adjunto": n.id in con_adjunto, "adjunto_nombre": n.adjunto_nombre,
                "criterio": n.criterio, "criterio_valores": n.criterio_valores or [],
                "origen": n.origen, "enviado_en": n.enviado_en,
                "cantidad_destinatarios": n.cantidad_destinatarios,
                "leidos": leidos,
            })
        return resultado


def notificacion_empleador_destinatarios(notificacion_empleador_id: int) -> list:
    """Detalle fila por fila (CUIT + razón social + si leyó y cuándo) de
    una notificación a empleadores."""
    with Session(engine) as s:
        dests = s.exec(select(NotificacionEmpleadorDestinatario).where(
            NotificacionEmpleadorDestinatario.notificacion_empleador_id == notificacion_empleador_id
        ).order_by(NotificacionEmpleadorDestinatario.cuit)).all()
        razones = {e.cuit: e.razon_social for e in s.exec(select(Empleador)).all()}
        return [{
            "cuit": d.cuit, "razon_social": razones.get(d.cuit, ""), "leida_en": d.leida_en,
        } for d in dests]


def notificaciones_de_empleador(cuit: str, sindicato_id: int) -> list:
    """Notificaciones que le llegaron a este CUIT en este sindicato, más
    nuevas primero -- para la pestaña Notificaciones de /empresa."""
    with Session(engine) as s:
        dests = s.exec(select(NotificacionEmpleadorDestinatario).where(
            NotificacionEmpleadorDestinatario.cuit == cuit)).all()
        if not dests:
            return []
        por_id = {d.notificacion_empleador_id: d for d in dests}
        notifs = s.exec(select(NotificacionEmpleador).where(
            NotificacionEmpleador.id.in_(por_id.keys()), NotificacionEmpleador.sindicato_id == sindicato_id)
            .order_by(NotificacionEmpleador.id.desc())).all()
        forms_ref = {n.formulario_id for n in notifs if n.formulario_id}
        activos = {t.id for t in s.exec(select(TipoTramiteEmpleador).where(
            TipoTramiteEmpleador.id.in_(forms_ref),
            TipoTramiteEmpleador.sindicato_id == sindicato_id,
            TipoTramiteEmpleador.activo == True)).all()} if forms_ref else set()  # noqa: E712
        con_adjunto = _ids_con_bytes(s, NotificacionEmpleador.adjunto_datos, [n.id for n in notifs])
        return [{
            "id": n.id, "remitente": n.remitente, "texto": n.texto,
            "tiene_adjunto": n.id in con_adjunto, "adjunto_nombre": n.adjunto_nombre,
            "enviado_en": n.enviado_en, "leida_en": por_id[n.id].leida_en,
            "formulario_id": n.formulario_id if n.formulario_id in activos else None,
        } for n in notifs]


def contar_notificaciones_no_leidas_empleador(cuit: str, sindicato_id: int) -> int:
    return sum(1 for n in notificaciones_de_empleador(cuit, sindicato_id) if not n["leida_en"])


def marcar_notificacion_leida_empleador(notificacion_empleador_id: int, cuit: str) -> bool:
    """Marca como leída la copia de ESTE cuit (aislamiento: no toca la fila
    de otro destinatario). Devuelve False si el cuit no era destinatario."""
    with Session(engine) as s:
        d = s.exec(select(NotificacionEmpleadorDestinatario).where(
            NotificacionEmpleadorDestinatario.notificacion_empleador_id == notificacion_empleador_id,
            NotificacionEmpleadorDestinatario.cuit == cuit)).first()
        if not d:
            return False
        if not d.leida_en:
            d.leida_en = fechas.ahora_texto()
            s.add(d); s.commit()
        return True


# ---------- Trámites (Fase 3 de Módulos + Notificaciones + Trámites) ----------

def _campo_tramite_a_dict(c: "CampoTramite") -> dict:
    return {
        "id": c.id, "orden": c.orden, "etiqueta": c.etiqueta, "tipo_dato": c.tipo_dato,
        "longitud_maxima": c.longitud_maxima, "longitud_exacta": c.longitud_exacta,
        "decimales": c.decimales, "tipos_archivo_permitidos": c.tipos_archivo_permitidos,
        "opciones": c.opciones, "ancho": c.ancho, "obligatorio": c.obligatorio,
        "validaciones": c.validaciones or [],
    }


def crear_tipo_tramite(sindicato_id: int, titulo: str, codigo: str, campos: list,
                        reglas: list = None, area_destino_default_id: int = None,
                        seccional_id: int = None, permite_pase: bool = False,
                        requisitos: list = None, borrador: bool = False) -> int:
    """Crea el tipo y sus campos en un solo alta. `campos` es una lista de
    dicts con las claves de CampoTramite (sin id/tipo_tramite_id); `reglas`
    son las reglas de consistencia ya saneadas
    (validaciones_tramite.reglas_saneadas). Un `borrador` nace inactivo."""
    with Session(engine) as s:
        t = TipoTramite(sindicato_id=sindicato_id, titulo=titulo, codigo=codigo,
                         reglas_consistencia=reglas or [], requisitos=requisitos or [],
                         area_destino_default_id=area_destino_default_id,
                         seccional_id=seccional_id, permite_pase=permite_pase,
                         borrador=borrador, activo=not borrador,
                         creado=fechas.ahora_texto())
        s.add(t); s.commit(); s.refresh(t)
        for i, c in enumerate(campos):
            s.add(CampoTramite(
                tipo_tramite_id=t.id, orden=i, etiqueta=c["etiqueta"], tipo_dato=c["tipo_dato"],
                longitud_maxima=c.get("longitud_maxima"), longitud_exacta=c.get("longitud_exacta"),
                decimales=c.get("decimales"), tipos_archivo_permitidos=c.get("tipos_archivo_permitidos", ""),
                opciones=c.get("opciones", ""), ancho=c.get("ancho") or "completo",
                obligatorio=c.get("obligatorio", True),
                validaciones=c.get("validaciones") or [],
            ))
        s.commit()
        return t.id


def editar_tipo_tramite(tipo_id: int, sindicato_id: int, titulo: str, codigo: str,
                         activo: bool, campos: list, reglas: list = None,
                         area_destino_default_id: int = None,
                         permite_pase: Optional[bool] = None,
                         requisitos: Optional[list] = None,
                         borrador: Optional[bool] = None) -> bool:
    """Actualiza título/código/activo y SINCRONIZA los campos por id: el
    constructor sigue siendo "lo que ves es lo que queda", pero borrar y
    recrear (como se hacía antes) reventaba con FK en cuanto el tipo tenía
    trámites presentados -- RespuestaTramite referencia el campo, y Postgres
    (a diferencia del SQLite de los tests) lo exige. Ahora: un campo que
    vuelve con su id se ACTUALIZA en el lugar, uno nuevo se crea, y uno
    quitado se borra solo si nadie lo respondió; si ya tiene respuestas se
    marca `retirado` (sale del formulario, los trámites viejos conservan su
    etiqueta)."""
    with Session(engine) as s:
        t = s.get(TipoTramite, tipo_id)
        if not t or t.sindicato_id != sindicato_id:
            return False
        t.titulo, t.codigo, t.activo = titulo, codigo, activo
        if borrador is not None:
            t.borrador = borrador
        # La SECCIONAL de un formulario no se edita: cambiarla le sacaría
        # el trámite de la vista a los trabajadores que ya lo tenían
        # disponible. El destino, en cambio, sí -- es la configuración
        # que el sindicato va a querer ajustar con el uso.
        if area_destino_default_id is not None:
            t.area_destino_default_id = area_destino_default_id
        if permite_pase is not None:
            t.permite_pase = permite_pase
        if requisitos is not None:
            t.requisitos = requisitos
        t.reglas_consistencia = reglas or []
        s.add(t)
        existentes = {c.id: c for c in s.exec(select(CampoTramite).where(
            CampoTramite.tipo_tramite_id == tipo_id)).all()}
        vistos = set()
        for i, c in enumerate(campos):
            fila = existentes.get(c.get("id"))
            if fila is None:
                fila = CampoTramite(tipo_tramite_id=tipo_id)
            else:
                vistos.add(fila.id)
            fila.orden, fila.etiqueta, fila.tipo_dato = i, c["etiqueta"], c["tipo_dato"]
            fila.longitud_maxima = c.get("longitud_maxima")
            fila.longitud_exacta = c.get("longitud_exacta")
            fila.decimales = c.get("decimales")
            fila.tipos_archivo_permitidos = c.get("tipos_archivo_permitidos", "")
            fila.opciones = c.get("opciones", "")
            fila.ancho = c.get("ancho") or "completo"
            fila.obligatorio = c.get("obligatorio", True)
            fila.validaciones = c.get("validaciones") or []
            fila.retirado = False
            s.add(fila)
        for fila in existentes.values():
            if fila.id in vistos:
                continue
            respondido = s.exec(select(RespuestaTramite).where(
                RespuestaTramite.campo_tramite_id == fila.id)).first()
            if respondido:
                fila.retirado = True
                s.add(fila)
            else:
                s.delete(fila)
        s.commit()
        return True


def borrar_tipo_tramite(tipo_id: int, sindicato_id: int) -> bool:
    """No borra si ya hay trámites presentados contra este tipo (el FK de
    Tramite.tipo_tramite_id no es opcional) -- el admin puede desactivarlo
    en su lugar (editar_tipo_tramite con activo=False)."""
    with Session(engine) as s:
        t = s.get(TipoTramite, tipo_id)
        if not t or t.sindicato_id != sindicato_id:
            return False
        if s.exec(select(Tramite).where(Tramite.tipo_tramite_id == tipo_id)).first():
            return False
        for c in s.exec(select(CampoTramite).where(CampoTramite.tipo_tramite_id == tipo_id)).all():
            s.delete(c)
        s.delete(t)
        s.commit()
        return True


def tipos_tramite_del_sindicato(sindicato_id: int, solo_activos: bool = False,
                                 seccional_id: Optional[int] = "todas", alcance=None) -> list:
    """Tipos de trámite del sindicato con sus campos, para el constructor de
    admin y el listado que ve el trabajador (con solo_activos=True).

    `seccional_id` recorta a lo que ve un TRABAJADOR de esa seccional: los
    formularios globales más los de su seccional (decisión N7). El default
    "todas" -- y no None, que es un valor con significado propio: "sin
    seccional cargada" -- deja la consulta sin recortar, que es lo que
    necesita el panel."""
    with Session(engine) as s:
        q = select(TipoTramite).where(TipoTramite.sindicato_id == sindicato_id)
        if solo_activos:
            q = q.where(TipoTramite.activo == True)
        if seccional_id != "todas":
            # Un trabajador SIN seccional ve solo los globales: no hay
            # ninguna seccional cuyos formularios le correspondan.
            q = q.where((TipoTramite.seccional_id == None) |  # noqa: E711
                        (TipoTramite.seccional_id == seccional_id)) \
                if seccional_id else q.where(TipoTramite.seccional_id == None)  # noqa: E711
        # `alcance` recorta lo que ve un USUARIO DEL PANEL acotado (bloque 3):
        # los globales (le llegan a su gente) más los de su alcance; los de
        # otras seccionales no viajan. Cada fila dice si es `propio` (la puede
        # editar o borrar): un global lo toca solo el alcance total.
        if alcance is not None:
            if not alcance:
                return []
            q = q.where((TipoTramite.seccional_id == None) |  # noqa: E711
                        (TipoTramite.seccional_id.in_(list(alcance))))
        tipos = s.exec(q.order_by(TipoTramite.creado.desc())).all()
        resultado = []
        for t in tipos:
            campos = s.exec(select(CampoTramite)
                            .where(CampoTramite.tipo_tramite_id == t.id,
                                   CampoTramite.retirado == False)  # noqa: E712
                            .order_by(CampoTramite.orden)).all()
            resultado.append({
                "id": t.id, "titulo": t.titulo, "codigo": t.codigo, "activo": t.activo,
                "borrador": t.borrador,
                "creado": t.creado, "campos": [_campo_tramite_a_dict(c) for c in campos],
                "reglas_consistencia": t.reglas_consistencia or [],
                "requisitos": t.requisitos or [],
                "seccional_id": t.seccional_id,
                "propio": alcance is None or (t.seccional_id in alcance),
                "area_destino_default_id": t.area_destino_default_id,
                "permite_pase": t.permite_pase,
                "areas_pase": sorted({x.area_id for x in s.exec(
                    select(PaseTipoTramite).where(
                        PaseTipoTramite.tipo_tramite_id == t.id)).all()}),
                "destinos": {d.seccional_id: d.area_id for d in s.exec(
                    select(DestinoTipoTramite).where(
                        DestinoTipoTramite.tipo_tramite_id == t.id)).all()},
            })
        return resultado


# ---------- Ruteo de trámites por área (decisión N6) ----------

def area_destino_para(tipo_tramite_id: int, seccional_id: Optional[int]) -> Optional[int]:
    """A qué área cae un trámite de ESE formulario presentado por alguien de
    ESA seccional.

    Dos pasos y en este orden: si la seccional está mapeada, gana el mapa;
    si no, el destino por defecto del formulario. El default es obligatorio
    justamente para que este segundo paso nunca devuelva None -- una
    seccional nueva, o un trabajador sin seccional cargada, tienen que caer
    en algún lado. Si aun así devuelve None es porque el formulario se
    guardó sin default, y eso las rutas ya no lo permiten.
    """
    with Session(engine) as s:
        if seccional_id:
            destino = s.exec(select(DestinoTipoTramite).where(
                DestinoTipoTramite.tipo_tramite_id == tipo_tramite_id,
                DestinoTipoTramite.seccional_id == seccional_id)).first()
            if destino:
                return destino.area_id
        tipo = s.get(TipoTramite, tipo_tramite_id)
        return tipo.area_destino_default_id if tipo else None


def destinos_de_tipo_tramite(tipo_tramite_id: int) -> dict:
    """{seccional_id: area_id} del mapa, para pintar el constructor."""
    with Session(engine) as s:
        return {d.seccional_id: d.area_id for d in s.exec(select(DestinoTipoTramite).where(
            DestinoTipoTramite.tipo_tramite_id == tipo_tramite_id)).all()}


def set_destinos_tipo_tramite(tipo_tramite_id: int, mapa: dict, sindicato_id: int) -> None:
    """Reemplaza el mapa del formulario.

    Descarta las seccionales y áreas que no sean de ESTE sindicato, mismo
    criterio defensivo que set_permisos_area: no se guarda basura que
    después haya que filtrar en cada lectura. Una seccional mapeada a
    "ninguna área" simplemente se saca del mapa -- cae al default, que es
    exactamente lo que significa."""
    with Session(engine) as s:
        tipo = s.get(TipoTramite, tipo_tramite_id)
        if not tipo or tipo.sindicato_id != sindicato_id:
            return
        secs = {x.id for x in s.exec(select(Seccional).where(
            Seccional.sindicato_id == sindicato_id)).all()}
        areas = {a.id for a in s.exec(select(Area).where(
            Area.sindicato_id == sindicato_id)).all()}
        for d in s.exec(select(DestinoTipoTramite).where(
                DestinoTipoTramite.tipo_tramite_id == tipo_tramite_id)).all():
            s.delete(d)
        for sec_id, area_id in (mapa or {}).items():
            if sec_id in secs and area_id in areas:
                s.add(DestinoTipoTramite(tipo_tramite_id=tipo_tramite_id,
                                         seccional_id=sec_id, area_id=area_id))
        s.commit()


def alcance_de_tramites(usuario_id: int):
    """(areas, seccionales) sobre las que este usuario ve trámites.

    None en cualquiera de los dos = sin recorte por ese eje. Son DOS EJES
    QUE SE CRUZAN, no uno: el área dice qué trámites le tocan y la seccional
    sobre qué trabajadores. Dos usuarios de "Legales" en seccionales
    distintas tienen el mismo permiso y ven cosas distintas.

    Los administradores (general y de seccional) no se recortan por área --
    administran, no atienden una ventanilla -- pero el de seccional sí
    arrastra su recorte de seccional, que sale de alcance_seccional().
    """
    with Session(engine) as s:
        u = s.get(UsuarioSindicato, usuario_id)
        if not u or not u.activo:
            return set(), set()
        if u.es_super_admin or u.es_admin_seccional:
            return None, alcance_seccional(usuario_id)
        areas = {u.area_id} if u.area_id else set()
        return areas, alcance_seccional(usuario_id)


def tipo_tramite_por_id(tipo_id: int) -> Optional[dict]:
    with Session(engine) as s:
        t = s.get(TipoTramite, tipo_id)
        if not t:
            return None
        campos = s.exec(select(CampoTramite)
                        .where(CampoTramite.tipo_tramite_id == tipo_id,
                               CampoTramite.retirado == False)  # noqa: E712
                        .order_by(CampoTramite.orden)).all()
        return {
            "id": t.id, "sindicato_id": t.sindicato_id, "titulo": t.titulo, "codigo": t.codigo,
            "activo": t.activo, "borrador": t.borrador, "creado": t.creado,
            "campos": [_campo_tramite_a_dict(c) for c in campos],
            "reglas_consistencia": t.reglas_consistencia or [],
            "requisitos": t.requisitos or [],
            "seccional_id": t.seccional_id,
            "area_destino_default_id": t.area_destino_default_id,
        }


def _log_tramite(s: Session, tramite_id: int, evento: str, detalle: str) -> None:
    """Único punto que escribe en TramiteLog -- recibe la sesión abierta del
    llamador para que el evento quede en la MISMA transacción que el cambio
    que lo generó (alta, cambio de estado, nota)."""
    s.add(TramiteLog(
        tramite_id=tramite_id, evento=evento, detalle=detalle,
        creado=fechas.ahora_texto(),
    ))


def sin_tildes(texto: str) -> str:
    """El texto sin tildes ni diéresis (Ó -> O, Ñ -> N), para lo que una
    persona tiene que tipear o dictar: un código no lleva vocales acentuadas."""
    import unicodedata
    return unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii")


def prefijo_expediente(codigo_tipo: str) -> str:
    """El prefijo del número de expediente, sacado del código del tipo de
    trámite: mayúsculas, letras y números y SIN TILDES (auditoría G3-08: la
    sigla de "Unión…" daba "UNIÓF04-2026-000384", un código que hay que
    tipear en "Buscar expediente" o dictar por teléfono)."""
    return "".join(ch for ch in sin_tildes(codigo_tipo).upper() if ch.isalnum()) or "TRAM"


def _buscar_por_expediente(s: Session, modelo, numero: str):
    """La fila con ese número de expediente. Si no está tal cual, prueba sin
    tildes de los dos lados: así encuentra "UNIOF04-2026-000384" (como lo
    tipea la gente) aunque el número viejo se haya emitido con la Ó, y al
    revés. Los candidatos salen del correlativo, que no lleva tildes."""
    fila = s.exec(select(modelo).where(modelo.numero_expediente == numero)).first()
    if fila or not numero or "-" not in numero:
        return fila
    buscado = sin_tildes(numero).upper()
    cola = numero.split("-", 1)[1]
    for cand in s.exec(select(modelo).where(modelo.numero_expediente.like(f"%-{cola}"))).all():
        if sin_tildes(cand.numero_expediente).upper() == buscado:
            return cand
    return None


def _proximo_numero_expediente(s: Session, modelo, prefijo: str, anio: str) -> str:
    """Siguiente correlativo LIBRE para ese prefijo+año, mirando los números
    que YA existen (no la cantidad de trámites del tipo).

    Por qué: `numero_expediente` es único en TODA la plataforma, pero el
    prefijo sale del código del TipoTramite. Dos sindicatos que elijan el
    mismo código ("F01") comparten espacio de numeración: contar los trámites
    de UN tipo daba un correlativo ya usado por el otro sindicato, y los 25
    reintentos se agotaban apenas el otro tenía más de 25 expedientes
    (reventaba con RuntimeError -- encontrado sembrando el lote de AEFIP).
    Mirando el máximo real la numeración salta al primer hueco libre y no
    colisiona nunca, sin cambiar el formato ni tocar los números ya emitidos."""
    patron = f"{prefijo}-{anio}-%"
    numeros = s.exec(select(modelo.numero_expediente).where(
        modelo.numero_expediente.like(patron))).all()
    maximo = 0
    for numero in numeros:
        sufijo = str(numero).rsplit("-", 1)[-1]
        if sufijo.isdigit():
            maximo = max(maximo, int(sufijo))
    return f"{prefijo}-{anio}-{(maximo + 1):06d}"


def crear_tramite(sindicato_id: int, tipo_tramite_id: int, cuil: str, respuestas: list,
                   advertencias: list = None, origen_tramite_id: Optional[int] = None) -> Optional[dict]:
    """Genera el número de expediente (correlativo por prefijo+año, ver
    _proximo_numero_expediente) y persiste el trámite con sus respuestas en
    una sola operación. `respuestas` es una lista de dicts con
    campo_tramite_id/valor_texto/archivo_datos/archivo_mime/archivo_nombre,
    ya validada por el llamador (ver main.api_enviar_tramite)."""
    with Session(engine) as s:
        tipo = s.get(TipoTramite, tipo_tramite_id)
        if not tipo or tipo.sindicato_id != sindicato_id or not tipo.activo:
            return None
        prefijo = prefijo_expediente(tipo.codigo)
        anio = fechas.ahora().strftime("%Y")
        ahora = fechas.ahora_texto()
        numero = _proximo_numero_expediente(s, Tramite, prefijo, anio)
        # El área se resuelve ACÁ, contra la seccional del trabajador, y
        # queda escrita en la fila. Ver el comentario de Tramite.area_a_cargo_id:
        # recalcularla en cada consulta haría que editar el mapa del
        # formulario moviera de bandeja trámites ya presentados.
        trab = s.exec(select(Trabajador).where(
            Trabajador.sindicato_id == sindicato_id, Trabajador.cuil == cuil)).first()
        area_id = area_destino_para(tipo_tramite_id, trab.seccional_id if trab else None)
        tr = Tramite(sindicato_id=sindicato_id, tipo_tramite_id=tipo_tramite_id, cuil=cuil,
                     numero_expediente=numero, estado="iniciado", creado=ahora, actualizado=ahora,
                     area_a_cargo_id=area_id,
                     advertencias=advertencias or [], origen_tramite_id=origen_tramite_id,
                     visto_trabajador_en=ahora)
        s.add(tr); s.commit(); s.refresh(tr)
        for r in respuestas:
            s.add(RespuestaTramite(
                tramite_id=tr.id, campo_tramite_id=r["campo_tramite_id"],
                valor_texto=r.get("valor_texto", ""), archivo_datos=r.get("archivo_datos"),
                archivo_mime=r.get("archivo_mime", ""), archivo_nombre=r.get("archivo_nombre", ""),
            ))
        _log_tramite(s, tr.id, "creado", f"Trámite presentado por el trabajador ({numero}).")
        s.commit()
        return {"id": tr.id, "numero_expediente": numero}


ESTADOS_TRAMITE = ["iniciado", "en_tratamiento", "respondido", "espera_info", "terminado"]
ESTADOS_TRAMITE_LABEL = {
    "iniciado": "Iniciado", "en_tratamiento": "En tratamiento", "respondido": "Respondido",
    "espera_info": "A la espera de información del afiliado", "terminado": "Terminado",
}


def cambiar_estado_tramite(tramite_id: int, sindicato_id: int, nuevo_estado: str) -> bool:
    """SIN USO desde la decisión N9 -- se deja porque cargar_demo y los
    scripts de datos la usan para armar trámites en un estado dado sin
    inventar un mensaje. Desde el panel NO se llega acá: responder y cambiar
    el estado son un solo acto y pasan por agregar_nota_tramite.

    Si mañana alguien la llama desde una ruta nueva, el estado volvería a
    moverse sin mensaje y el chat volvería a mentir. Esto no es un guard --
    es un cartel.

    False si el estado no es válido, el trámite no es de ese sindicato, o el
    trámite YA está terminado -- un trámite terminado queda bloqueado, no se
    puede reabrir ni cambiar de estado (ver también agregar_nota_tramite)."""
    if nuevo_estado not in ESTADOS_TRAMITE:
        return False
    with Session(engine) as s:
        tr = s.get(Tramite, tramite_id)
        if not tr or tr.sindicato_id != sindicato_id or tr.estado == "terminado":
            return False
        anterior = tr.estado
        tr.estado = nuevo_estado
        tr.actualizado = fechas.ahora_texto()
        tr.visto_trabajador_en = None   # cambio del sindicato = novedad para el trabajador
        if nuevo_estado == "terminado":
            tr.resuelto_en = tr.actualizado
        s.add(tr)
        _log_tramite(s, tramite_id, "cambio_estado",
                     f"{ESTADOS_TRAMITE_LABEL.get(anterior, anterior)} → {ESTADOS_TRAMITE_LABEL.get(nuevo_estado, nuevo_estado)}")
        s.commit()
        return True


def agregar_nota_tramite(tramite_id: int, autor: str, texto: str,
                          adjunto_datos: Optional[bytes] = None, adjunto_mime: str = "",
                          adjunto_nombre: str = "", formulario_id: Optional[int] = None,
                          estado_nuevo: str = "") -> bool:
    """`autor` es "admin" o "trabajador" -- la verificación de que quien
    escribe tiene permiso sobre ESTE trámite la hace el caller (main.py),
    igual que la de que `formulario_id` (solo admin) sea un tipo activo del
    sindicato. Un trámite terminado queda bloqueado para notas nuevas de
    cualquier lado.

    `estado_nuevo` (solo del admin) mueve el estado EN LA MISMA OPERACIÓN y
    en la misma transacción que el mensaje: es la decisión N9. Antes eran
    dos rutas y cada una escribía su línea en el chat, así que un solo acto
    del admin aparecía DOS VECES del lado del trabajador. Ahora el estado
    viaja dentro del mensaje y el log lleva un evento por acto real.

    Un estado inválido se ignora y la nota se manda igual: escribir es lo
    que el admin quiso hacer, y perderle el mensaje por un valor mal formado
    sería peor que no mover el estado."""
    with Session(engine) as s:
        tr = s.get(Tramite, tramite_id)
        if not tr or tr.estado == "terminado":
            return False
        ahora = fechas.ahora_texto()
        cambia = bool(estado_nuevo) and estado_nuevo in ESTADOS_TRAMITE \
            and estado_nuevo != tr.estado and autor == "admin"
        s.add(NotaTramite(
            tramite_id=tramite_id, autor=autor, texto=texto or "",
            adjunto_datos=adjunto_datos, adjunto_mime=adjunto_mime or "",
            adjunto_nombre=adjunto_nombre or "", creado=ahora,
            formulario_id=formulario_id,
            estado_nuevo=estado_nuevo if cambia else "",
        ))
        anterior = tr.estado
        if cambia:
            tr.estado = estado_nuevo
            if estado_nuevo == "terminado":
                tr.resuelto_en = ahora
        tr.actualizado = ahora
        # nota del sindicato = novedad para el trabajador; una nota propia
        # sella el visto (ya está mirando el chat)
        tr.visto_trabajador_en = None if autor == "admin" else tr.actualizado
        s.add(tr)
        # UN evento por acto, con el cambio de estado en el mismo renglón:
        # es lo que hace que el chat deje de mostrar dos movimientos por una
        # sola respuesta.
        detalle = texto[:120] if texto else "(sin texto, con adjunto)"
        if cambia:
            detalle += (f" · Estado: {ESTADOS_TRAMITE_LABEL.get(anterior, anterior)}"
                        f" → {ESTADOS_TRAMITE_LABEL.get(estado_nuevo, estado_nuevo)}")
        _log_tramite(s, tramite_id, f"nota_{autor}", detalle)
        s.commit()
        return True


def _tramite_resumen(s: Session, tr: "Tramite", titulos_tipo: dict,
                     ultimas_notas: Optional[dict] = None,
                     ultimas_con_adjunto: Optional[set] = None) -> dict:
    """`ultimas_notas` (tramite_id -> NotaTramite) lo pasa
    tramites_de_trabajador para la tarjeta "Necesita tu atención" de la
    pestaña Trámites (rediseño "Hilo", 2026-09-03): el último mensaje del
    hilo, sin abrir el detalle. Se resuelve en UNA consulta para toda la
    lista, no una por trámite."""
    ultima = (ultimas_notas or {}).get(tr.id)
    return {
        "id": tr.id, "numero_expediente": tr.numero_expediente, "cuil": tr.cuil,
        "tipo_tramite_id": tr.tipo_tramite_id, "tipo_titulo": titulos_tipo.get(tr.tipo_tramite_id, "—"),
        "estado": tr.estado, "estado_label": ESTADOS_TRAMITE_LABEL.get(tr.estado, tr.estado),
        "creado": tr.creado, "actualizado": tr.actualizado,
        "novedad": not tr.visto_trabajador_en,
        "ultimo_mensaje": {
            "autor": ultima.autor, "texto": ultima.texto, "creado": ultima.creado,
            "tiene_adjunto": ultima.id in (ultimas_con_adjunto or ()), "formulario_id": ultima.formulario_id,
        } if ultima else None,
    }


def guardar_suscripcion_push(cuil: str, endpoint: str, p256dh: str, auth: str) -> None:
    """Alta idempotente: si el endpoint ya existe se reasigna al CUIL (el
    mismo navegador puede cambiar de usuario logueado)."""
    with Session(engine) as s:
        sus = s.exec(select(SuscripcionPush).where(
            SuscripcionPush.endpoint == endpoint)).first()
        if sus:
            sus.cuil, sus.p256dh, sus.auth = cuil, p256dh, auth
        else:
            sus = SuscripcionPush(cuil=cuil, endpoint=endpoint, p256dh=p256dh, auth=auth,
                                   creado=fechas.ahora_texto())
        s.add(sus); s.commit()


def suscripciones_push_de(cuil: str) -> list:
    with Session(engine) as s:
        return [{"endpoint": x.endpoint, "p256dh": x.p256dh, "auth": x.auth}
                for x in s.exec(select(SuscripcionPush).where(
                    SuscripcionPush.cuil == cuil)).all()]


def borrar_suscripcion_push(endpoint: str) -> None:
    with Session(engine) as s:
        sus = s.exec(select(SuscripcionPush).where(
            SuscripcionPush.endpoint == endpoint)).first()
        if sus:
            s.delete(sus); s.commit()


def marcar_tramite_visto(tramite_id: int, cuil: str) -> None:
    """El trabajador abrió el detalle: lo que había hasta acá está visto.
    Apaga su parte del globo de Trámites."""
    with Session(engine) as s:
        tr = s.get(Tramite, tramite_id)
        if tr and tr.cuil == cuil:
            tr.visto_trabajador_en = fechas.ahora_texto()
            s.add(tr); s.commit()


def contar_tramites_con_novedades(cuil: str, sindicato_id: int) -> int:
    """Trámites del trabajador con movimientos que todavía no vio
    (actualizado > visto). Alimenta el globo de Trámites -- las novedades
    de un trámite ya no generan Notificacion (decisión de Sd 2026-09-02)."""
    with Session(engine) as s:
        tramites = s.exec(select(Tramite).where(
            Tramite.cuil == cuil, Tramite.sindicato_id == sindicato_id)).all()
        return sum(1 for tr in tramites if not tr.visto_trabajador_en)


def _recortar_tramites(s: Session, q, sindicato_id: int, usuario_id: Optional[int]):
    """Aplica los DOS EJES del alcance a una consulta de trámites.

    Sin `usuario_id` no recorta nada -- lo usan las consultas internas y los
    scripts. Con usuario, cruza área y seccional: el área dice qué trámites
    le tocan, la seccional sobre qué trabajadores. Recortar por seccional
    obliga a resolver qué CUILs entran, así que se hace con una subconsulta
    sobre el padrón y no con un JOIN -- Tramite guarda el CUIL, no el id del
    trabajador."""
    if not usuario_id:
        return q
    areas, secs = alcance_de_tramites(usuario_id)
    if areas is not None:
        if not areas:
            return q.where(False)
        # El área a cargo O una que lo haya derivado: la que pasó el trámite
        # lo sigue viendo en su bandeja (en solo lectura) para saber en qué
        # terminó. Si solo se filtrara por area_a_cargo_id, derivar sería
        # perderlo de vista y nadie podría seguirle el rastro.
        derivados = select(PaseTramite.tramite_id).where(
            PaseTramite.area_origen_id.in_(list(areas)))
        q = q.where(Tramite.area_a_cargo_id.in_(list(areas)) |
                    Tramite.id.in_(derivados))
    if secs is not None:
        if not secs:
            return q.where(False)
        cuiles = [t.cuil for t in s.exec(select(Trabajador).where(
            Trabajador.sindicato_id == sindicato_id,
            Trabajador.seccional_id.in_(list(secs)))).all()]
        if not cuiles:
            return q.where(False)
        q = q.where(Tramite.cuil.in_(cuiles))
    return q


def tramites_del_sindicato(sindicato_id: int, estado: str = None, tipo_tramite_id: int = None,
                            cuil: str = None, usuario_id: Optional[int] = None) -> list:
    """Listado filtrable para el panel de admin, más recientes primero.

    Con `usuario_id` se recorta al alcance de ese usuario (ver
    _recortar_tramites). El recorte va en la CONSULTA y no en la plantilla,
    por lo mismo de siempre: en el HTML los trámites de otras áreas
    viajarían igual."""
    with Session(engine) as s:
        q = select(Tramite).where(Tramite.sindicato_id == sindicato_id)
        if estado:
            q = q.where(Tramite.estado == estado)
        if tipo_tramite_id:
            q = q.where(Tramite.tipo_tramite_id == tipo_tramite_id)
        if cuil:
            q = q.where(Tramite.cuil == cuil)
        q = _recortar_tramites(s, q, sindicato_id, usuario_id)
        tramites = s.exec(q.order_by(Tramite.id.desc())).all()
        titulos_tipo = {t.id: t.titulo for t in s.exec(
            select(TipoTramite).where(TipoTramite.sindicato_id == sindicato_id)).all()}
        # El nombre de la persona, de su cuenta (el dueño de los datos
        # personales), en UNA consulta para toda la bandeja: el operador
        # busca y recuerda por nombre, no por CUIL (auditoría G5-15).
        cuils = list({tr.cuil for tr in tramites})
        nombres = dict(s.exec(select(CuentaTrabajador.cuil, CuentaTrabajador.nombre).where(
            CuentaTrabajador.cuil.in_(cuils))).all()) if cuils else {}
        # La seccional del afiliado (del padrón, por CUIL), para que la
        # bandeja filtre por seccional sin otra consulta (2026-10-29).
        secs = dict(s.exec(select(Trabajador.cuil, Trabajador.seccional_id).where(
            Trabajador.sindicato_id == sindicato_id, Trabajador.cuil.in_(cuils))).all()) if cuils else {}
        salida = []
        for tr in tramites:
            r = _tramite_resumen(s, tr, titulos_tipo)
            r["nombre"] = nombres.get(tr.cuil) or ""
            r["seccional_id"] = secs.get(tr.cuil)
            salida.append(r)
        return salida


GRUPOS_TRAMITE = {
    # Las mismas pastillas de la bandeja (GRUPOS_TRAMITE en admin.html): el
    # CSV baja lo que la pantalla muestra, así que el grupo se define una
    # vez acá y la plantilla lo lee.
    "abiertos": [e for e in ESTADOS_TRAMITE if e != "terminado"],
    "sindicato": ["iniciado", "en_tratamiento"],
    "afiliado": ["respondido", "espera_info"],
    "terminados": ["terminado"],
    "todos": list(ESTADOS_TRAMITE),
}


def listado_tramites(sindicato_id: int, usuario_id: Optional[int], tipo_tramite_id: Optional[int] = None,
                     estado: str = "", seccional_id: Optional[int] = None, q: str = "",
                     expediente: str = "", grupo: str = "") -> Optional[dict]:
    """Lo que la bandeja de Trámites tiene filtrado, con las respuestas,
    para el CSV (2026-10-28; desde el 29 el formulario es un filtro más y no
    una condición: SDN, «ponés los filtros para todo el listado y con lo
    filtrado bajás a CSV»). Dentro del alcance del operador (área y
    seccional, _recortar_tramites: el recorte va en la consulta), con los
    mismos filtros que la pantalla: formulario, estado o grupo de la
    pastilla, seccional del afiliado, nombre o CUIL y expediente. Con un
    formulario elegido sale una columna por pregunta; sin formulario, las
    columnas comunes más el nombre del formulario. None si el tipo pedido
    no es de este sindicato. Las respuestas de archivo salen como el nombre
    del archivo, nunca los bytes."""
    with Session(engine) as s:
        tipo = None
        if tipo_tramite_id:
            tipo = s.get(TipoTramite, tipo_tramite_id)
            if not tipo or tipo.sindicato_id != sindicato_id:
                return None
        q_ = select(Tramite).where(Tramite.sindicato_id == sindicato_id)
        if tipo:
            q_ = q_.where(Tramite.tipo_tramite_id == tipo.id)
        if estado:
            q_ = q_.where(Tramite.estado == estado)
        elif grupo and grupo in GRUPOS_TRAMITE:
            q_ = q_.where(Tramite.estado.in_(GRUPOS_TRAMITE[grupo]))
        if expediente:
            q_ = q_.where(Tramite.numero_expediente.ilike(f"%{expediente.strip()}%"))
        q_ = _recortar_tramites(s, q_, sindicato_id, usuario_id)
        padron = {t.cuil: t.seccional_id for t in s.exec(select(Trabajador).where(
            Trabajador.sindicato_id == sindicato_id)).all()}
        if seccional_id:
            cuiles = [c for c, sec in padron.items() if sec == seccional_id]
            q_ = q_.where(Tramite.cuil.in_(cuiles)) if cuiles else q_.where(False)
        tramites = s.exec(q_.order_by(Tramite.id)).all()
        cuils = list({tr.cuil for tr in tramites})
        nombres = dict(s.exec(select(CuentaTrabajador.cuil, CuentaTrabajador.nombre).where(
            CuentaTrabajador.cuil.in_(cuils))).all()) if cuils else {}
        # Nombre o CUIL, con la misma regla que la pantalla: si lo escrito
        # son solo dígitos (con o sin puntos y guiones) busca en el CUIL,
        # si no en el nombre.
        q = (q or "").strip()
        if q:
            digitos = re.sub(r"\D", "", q)
            por_cuil = bool(digitos) and len(digitos) == len(re.sub(r"[\s.\-]", "", q))
            if por_cuil:
                tramites = [tr for tr in tramites if digitos in re.sub(r"\D", "", tr.cuil)]
            else:
                tramites = [tr for tr in tramites if q.lower() in (nombres.get(tr.cuil) or "").lower()]
        campos = s.exec(select(CampoTramite).where(CampoTramite.tipo_tramite_id == tipo.id)
                        .order_by(CampoTramite.orden)).all() if tipo else []
        ids = [tr.id for tr in tramites]
        respuestas = {}
        if ids and campos:
            filas_r = s.exec(select(RespuestaTramite).where(RespuestaTramite.tramite_id.in_(ids))).all()
            con_archivo = _ids_con_bytes(s, RespuestaTramite.archivo_datos, [r.id for r in filas_r])
            for r in filas_r:
                respuestas[(r.tramite_id, r.campo_tramite_id)] = r.archivo_nombre if r.id in con_archivo else r.valor_texto
        titulos = {t.id: t.titulo for t in s.exec(select(TipoTramite).where(TipoTramite.sindicato_id == sindicato_id)).all()}
        secs = {x.id: x.nombre for x in s.exec(select(Seccional).where(Seccional.sindicato_id == sindicato_id)).all()}
        areas = {a.id: a.nombre for a in s.exec(select(Area).where(Area.sindicato_id == sindicato_id)).all()}
        filas = []
        for tr in tramites:
            filas.append({
                "expediente": tr.numero_expediente, "formulario": titulos.get(tr.tipo_tramite_id, ""),
                "creado": tr.creado, "actualizado": tr.actualizado,
                "estado": ESTADOS_TRAMITE_LABEL.get(tr.estado, tr.estado), "cuil": tr.cuil,
                "nombre": nombres.get(tr.cuil) or "", "seccional": secs.get(padron.get(tr.cuil), ""),
                "area": areas.get(tr.area_a_cargo_id, ""),
                "respuestas": [respuestas.get((tr.id, c.id), "") for c in campos],
            })
        return {"tipo": {"id": tipo.id, "titulo": tipo.titulo, "codigo": tipo.codigo} if tipo else None,
                "campos": [c.etiqueta + (" (retirado)" if c.retirado else "") for c in campos
                           if c.tipo_dato != "separador"],
                "indices": [i for i, c in enumerate(campos) if c.tipo_dato != "separador"],
                "filas": filas}


def registrar_descarga_listado(sindicato_id: int, tipo_tramite_id: Optional[int], usuario_id: Optional[int],
                               filtros: str, filas: int) -> None:
    with Session(engine) as s:
        s.add(DescargaListado(sindicato_id=sindicato_id, tipo_tramite_id=tipo_tramite_id or None,
                              usuario_id=usuario_id or None, filtros=filtros[:300], filas=filas,
                              fecha=fechas.ahora_texto()))
        s.commit()


# ---------- Pase entre áreas (decisión N8) ----------

def areas_de_pase_de_tipo(tipo_tramite_id: int) -> list:
    """Los ids de área a los que ESTE formulario habilita derivar."""
    with Session(engine) as s:
        return sorted({x.area_id for x in s.exec(select(PaseTipoTramite).where(
            PaseTipoTramite.tipo_tramite_id == tipo_tramite_id)).all()})


def set_areas_de_pase(tipo_tramite_id: int, areas: list, sindicato_id: int) -> None:
    """Reemplaza la lista cerrada de destinos de pase del formulario.

    Descarta áreas de otro sindicato, mismo criterio defensivo que el resto
    de los set_*: no se guarda basura que después haya que filtrar."""
    with Session(engine) as s:
        tipo = s.get(TipoTramite, tipo_tramite_id)
        if not tipo or tipo.sindicato_id != sindicato_id:
            return
        propias = {a.id for a in s.exec(select(Area).where(
            Area.sindicato_id == sindicato_id)).all()}
        for x in s.exec(select(PaseTipoTramite).where(
                PaseTipoTramite.tipo_tramite_id == tipo_tramite_id)).all():
            s.delete(x)
        for area_id in dict.fromkeys(areas or []):
            if area_id in propias:
                s.add(PaseTipoTramite(tipo_tramite_id=tipo_tramite_id, area_id=area_id))
        s.commit()


def areas_a_las_que_puede_pasar(tramite_id: int) -> list:
    """[{id, nombre, seccional}] de los destinos VÁLIDOS ahora mismo.

    Se saca el área que ya lo tiene -- derivarle al que lo tiene no es un
    pase -- y las áreas desactivadas, que no pueden recibir trabajo. La
    lista sale de aplicar las dos cosas a los destinos que declara el
    formulario; si el formulario no permite pase, es vacía."""
    with Session(engine) as s:
        tr = s.get(Tramite, tramite_id)
        if not tr:
            return []
        tipo = s.get(TipoTramite, tr.tipo_tramite_id)
        if not tipo or not tipo.permite_pase:
            return []
        ids = {x.area_id for x in s.exec(select(PaseTipoTramite).where(
            PaseTipoTramite.tipo_tramite_id == tr.tipo_tramite_id)).all()}
        ids.discard(tr.area_a_cargo_id)
        if not ids:
            return []
        areas = s.exec(select(Area).where(Area.id.in_(list(ids)),
                                          Area.activo == True)).all()
        secs = {x.id: x.nombre for x in s.exec(select(Seccional).where(
            Seccional.sindicato_id == tr.sindicato_id)).all()}
        return sorted(({"id": a.id, "nombre": a.nombre,
                        "seccional": secs.get(a.seccional_id, "")} for a in areas),
                      key=lambda a: (a["seccional"], a["nombre"]))


def areas_que_vieron(tramite_id: int) -> set:
    """Las áreas que tuvieron el trámite alguna vez: la que lo tiene ahora
    más todas las que lo derivaron. Es el conjunto que conserva LECTURA."""
    with Session(engine) as s:
        tr = s.get(Tramite, tramite_id)
        if not tr:
            return set()
        pasados = {x.area_origen_id for x in s.exec(select(PaseTramite).where(
            PaseTramite.tramite_id == tramite_id)).all() if x.area_origen_id}
        if tr.area_a_cargo_id:
            pasados.add(tr.area_a_cargo_id)
        return pasados


def pasar_tramite(tramite_id: int, area_destino_id: int, usuario_id: int,
                   sindicato_id: int, motivo: str = "") -> bool:
    """Deriva el trámite a otra área. False si no corresponde.

    Chequea TODO acá adentro y no en la ruta, a propósito: es una operación
    que cambia quién puede responder, y dejar la mitad de las condiciones en
    el llamador es la forma de que un camino nuevo se olvide de alguna.

    Un trámite TERMINADO no se deriva: está cerrado, igual que no admite
    notas ni cambios de estado."""
    with Session(engine) as s:
        tr = s.get(Tramite, tramite_id)
        if not tr or tr.sindicato_id != sindicato_id or tr.estado == "terminado":
            return False
        tipo = s.get(TipoTramite, tr.tipo_tramite_id)
        if not tipo or not tipo.permite_pase:
            return False
        # El destino tiene que estar en la lista CERRADA del formulario, ser
        # de este sindicato, estar activo, y no ser el que ya lo tiene.
        permitidas = {x.area_id for x in s.exec(select(PaseTipoTramite).where(
            PaseTipoTramite.tipo_tramite_id == tr.tipo_tramite_id)).all()}
        destino = s.get(Area, area_destino_id)
        if (area_destino_id not in permitidas or not destino
                or destino.sindicato_id != sindicato_id or not destino.activo
                or area_destino_id == tr.area_a_cargo_id):
            return False
        origen = s.get(Area, tr.area_a_cargo_id) if tr.area_a_cargo_id else None
        ahora = fechas.ahora_texto()
        s.add(PaseTramite(tramite_id=tramite_id, area_origen_id=tr.area_a_cargo_id,
                          area_destino_id=area_destino_id, usuario_id=usuario_id,
                          motivo=motivo, creado=ahora))
        tr.area_a_cargo_id = area_destino_id
        tr.actualizado = ahora
        # Un pase es actividad del sindicato sobre el expediente: al
        # trabajador le cuenta como novedad, igual que una respuesta.
        tr.visto_trabajador_en = None
        s.add(tr)
        # El movimiento queda en el chat nombrando ÁREAS, nunca personas:
        # es lo que ve el trabajador (misma regla que las respuestas).
        detalle = f"Pasó de {origen.nombre} a {destino.nombre}." if origen \
            else f"Pasó a {destino.nombre}."
        if motivo:
            detalle += f" Motivo: {motivo}"
        _log_tramite(s, tramite_id, "pase", detalle)
        s.commit()
        return True


def puede_responder_tramite(tramite_id: int, usuario_id: int, sindicato_id: int) -> bool:
    """Ver y RESPONDER son cosas distintas desde que existe el pase.

    El área que derivó conserva lectura -- para saber en qué terminó lo que
    pasó -- pero ya no escribe. Si las dos pudieran, el trabajador podría
    recibir dos respuestas distintas al mismo planteo, que es justo lo que
    "siempre hay exactamente un área responsable" evita.

    Los administradores no quedan afuera: no atienden una ventanilla."""
    if not puede_ver_tramite(tramite_id, usuario_id, sindicato_id):
        return False
    with Session(engine) as s:
        u = s.get(UsuarioSindicato, usuario_id)
        if not u or not u.activo:
            return False
        if u.es_super_admin or u.es_admin_seccional:
            return True
        tr = s.get(Tramite, tramite_id)
        return bool(tr and tr.area_a_cargo_id == u.area_id)


def puede_ver_tramite(tramite_id: int, usuario_id: int, sindicato_id: int) -> bool:
    """Si ESTE usuario alcanza ESE trámite, por los dos ejes.

    No alcanza con filtrar el listado: en el detalle, la nota y el estado el
    id llega por la URL o el form y se puede escribir a mano. Cada una de
    esas rutas chequea por separado -- esconder una fila de una tabla nunca
    fue un control de acceso."""
    with Session(engine) as s:
        tr = s.get(Tramite, tramite_id)
        if not tr or tr.sindicato_id != sindicato_id:
            return False
        areas, secs = alcance_de_tramites(usuario_id)
        if areas is not None:
            # No alcanza con el área a cargo: la que DERIVÓ conserva lectura,
            # para poder saber en qué terminó lo que pasó (decisión N8).
            if not (areas & areas_que_vieron(tramite_id)):
                return False
        if secs is not None:
            trab = s.exec(select(Trabajador).where(
                Trabajador.sindicato_id == sindicato_id, Trabajador.cuil == tr.cuil)).first()
            # Un trámite de alguien que no está en el padrón, o que quedó sin
            # seccional, no lo alcanza nadie acotado. Es el lado seguro: un
            # dato incompleto no puede terminar en más acceso del que toca.
            if not trab or trab.seccional_id not in secs:
                return False
        return True


def contar_tramites_nuevos(sindicato_id: int, usuario_id: Optional[int] = None) -> int:
    """Trámites recién presentados (estado "iniciado", el admin todavía no
    los tocó) -- para el globo de notificación de la portada de admin y de
    la pestaña "Ver trámites" dentro de /admin.

    Se recorta con el MISMO alcance que la bandeja, y no es un detalle: un
    globo que contara trámites de otra área nunca bajaría a cero, porque al
    abrir la pestaña esos trámites no aparecen. El usuario vería un número
    que no puede hacer desaparecer."""
    with Session(engine) as s:
        q = select(Tramite).where(Tramite.sindicato_id == sindicato_id,
                                  Tramite.estado == "iniciado")
        q = _recortar_tramites(s, q, sindicato_id, usuario_id)
        return len(s.exec(q).all())


def estado_portada_panel(sindicato_id: int, usuario_id: int, modulos, permisos,
                         tramites_nuevos: int = 0) -> dict:
    """La línea de estado de cada acceso de la portada del panel (auditoría
    de diseño 2026-10, G4-01): un dato real en vez de una descripción fija
    -- «206 activos · 38 sin registrar», «3 vigentes». El operador entra
    todos los días y tiene que enterarse de algo sin abrir cada pestaña.

    Cada número se cuenta con el MISMO recorte que la pestaña a la que lleva
    (alcance de seccional, área de los trámites, cláusula de Reportes): un
    número que no coincide con lo que se ve al entrar es peor que ninguno.
    Solo se cuenta lo que la persona puede abrir (módulo y permiso); un
    acceso sin dato (Reglas, Convenio...) no aparece y la portada deja su
    descripción. Todo son COUNT en SQL; los trámites usan la misma ruta que
    el globo (`_recortar_tramites`)."""
    import formato_ar as fa
    from sqlalchemy import func

    def puede(*x):
        return any(p in permisos for p in x)

    alcance = alcance_seccional(usuario_id)
    super_admin = es_super_admin(usuario_id)
    hoy = fechas.hoy_texto()
    sal: dict = {}
    recibos = "recibos" in modulos
    with Session(engine) as s:
        if recibos and puede("reportes"):
            sind = s.get(Sindicato, sindicato_id)
            q = select(func.count(), func.count().filter(ReciboVerificado.estado != "OK")) \
                .select_from(ReciboVerificado).where(ReciboVerificado.sindicato_id == sindicato_id)
            if not (sind and sind.clausula_confidencialidad):
                q = q.where(ReciboVerificado.enviado_sindicato == True)  # noqa: E712
            if alcance is not None:
                cuiles = select(Trabajador.cuil).where(
                    Trabajador.sindicato_id == sindicato_id,
                    Trabajador.seccional_id.in_(list(alcance) or [-1]))
                q = q.where(ReciboVerificado.cuil.in_(cuiles))
            total, con_dif = s.exec(q).one()
            sal["reportes"] = (fa.contar(total, "recibo", "recibos") + " · "
                               + fa.porcentaje(round(100 * con_dif / total)) + " con diferencias"
                               ) if total else "Todavía no hay recibos verificados"
        if recibos and puede("conceptos"):
            total, pend = s.exec(select(func.count(), func.count().filter(Concepto.pendiente_revision))
                                 .where(Concepto.sindicato_id == sindicato_id)).one()
            sal["conceptos"] = (fa.contar(total, "concepto", "conceptos")
                                + (f" · {fa.miles(pend)} por revisar" if pend else "")
                                ) if total else "El catálogo está vacío"
        if puede("trabajadores"):
            sub = _consulta_padron(sindicato_id, alcance).subquery() \
                if alcance is None or alcance else None
            if sub is None:
                activos = sin_reg = 0
            else:
                activos, sin_reg = s.exec(select(
                    func.count().filter(sub.c.activo),
                    func.count().filter(sub.c.activo & ~sub.c.registrado))).one()
            sal["trabajadores"] = (fa.contar(activos, "activo", "activos")
                                   + (f" · {fa.miles(sin_reg)} sin registrar" if sin_reg
                                      else ", todos registrados")
                                   ) if activos else "Todavía no hay afiliados cargados"
        for clave, modelo, sing, plur in (("noticias", Noticia, "vigente", "vigentes"),
                                          ("beneficios", Beneficio, "vigente", "vigentes")):
            if clave in modulos and puede(clave):
                n = sum(1 for x in s.exec(select(modelo).where(
                            modelo.sindicato_id == sindicato_id,
                            modelo.fecha_desde <= hoy, modelo.fecha_hasta >= hoy)).all()
                        if publicacion_visible(x.destino_seccionales or [], alcance))
                ninguna = "Ninguna vigente" if clave == "noticias" else "Ninguno vigente"
                sal[clave] = fa.contar(n, sing, plur) if n else ninguna
        if "encuestas" in modulos and puede("encuestas", "encuestas_resultados"):
            q = select(Encuesta).where(Encuesta.sindicato_id == sindicato_id,
                                       Encuesta.publicada == True)  # noqa: E712
            if alcance is not None:
                q = q.where(or_(Encuesta.seccional_id.in_(list(alcance) or [-1]),
                                Encuesta.seccional_id == None))   # noqa: E711
            abiertas = sum(1 for e in s.exec(q).all() if encuestas.estado(
                e.publicada, e.fecha_desde, e.fecha_hasta, hoy, e.cerrada_en) == encuestas.ABIERTA)
            sal["encuestas"] = fa.contar(abiertas, "abierta", "abiertas") if abiertas \
                else "Ninguna abierta"
        if puede("seccionales"):
            q = select(func.count(), func.count().filter(
                Seccional.precision_geo.not_in(list(geo.PRECISIONES_SECCIONAL)))) \
                .where(Seccional.sindicato_id == sindicato_id)
            if alcance is not None:
                q = q.where(Seccional.id.in_(list(alcance) or [-1]))
            total, sin_ubicar = s.exec(q).one()
            if total:
                sal["seccionales"] = (fa.contar(total, "seccional", "seccionales")
                                      + (f" · {fa.miles(sin_ubicar)} sin ubicar" if sin_ubicar else ""))
        if puede("listas"):
            q = select(func.count()).select_from(ListaSindicato).where(
                ListaSindicato.sindicato_id == sindicato_id)
            if alcance is not None:
                q = q.where(ListaSindicato.seccional_id.in_(list(alcance) or [-1]))
            n = s.exec(q).one()
            sal["listas"] = fa.contar(n, "lista cargada", "listas cargadas") if n \
                else "Ninguna lista cargada"
        if "empleadores" in modulos and puede("emp_empresas"):
            n = s.exec(select(func.count()).select_from(Empleador).where(
                Empleador.sindicato_id == sindicato_id, Empleador.activo == True)).one()  # noqa: E712
            sal["empleadores"] = fa.contar(n, "empresa activa", "empresas activas") if n \
                else "Ninguna empresa cargada"
        if super_admin:
            n = s.exec(select(func.count()).select_from(UsuarioSindicato).where(
                UsuarioSindicato.sindicato_id == sindicato_id,
                UsuarioSindicato.activo == True)).one()  # noqa: E712
            sal["usuarios"] = fa.contar(n, "usuario activo", "usuarios activos")
    if "tramites" in modulos and puede("tramites_recibidos"):
        with Session(engine) as s:
            q = select(Tramite.estado).where(Tramite.sindicato_id == sindicato_id,
                                             Tramite.estado.not_in(["iniciado", "terminado"]))
            en_curso = len(s.exec(_recortar_tramites(s, q, sindicato_id, usuario_id)).all())
        partes = []
        if tramites_nuevos:
            partes.append(f"{fa.miles(tramites_nuevos)} sin leer")
        if en_curso:
            partes.append(f"{fa.miles(en_curso)} en curso")
        sal["tramites"] = " · ".join(partes) or "Nada pendiente"
    return sal


def tramites_de_trabajador(cuil: str, sindicato_id: int) -> list:
    """Los trámites que presentó ESTE trabajador en ESTE sindicato, con el
    último movimiento más nuevo primero -- para "Mis trámites". Es la fecha
    que muestra cada fila: ordenar por alta hacía que las fechas saltaran
    (auditoría G3-04)."""
    with Session(engine) as s:
        tramites = s.exec(select(Tramite).where(
            Tramite.cuil == cuil, Tramite.sindicato_id == sindicato_id).order_by(
                Tramite.actualizado.desc(), Tramite.id.desc())).all()
        titulos_tipo = {t.id: t.titulo for t in s.exec(
            select(TipoTramite).where(TipoTramite.sindicato_id == sindicato_id)).all()}
        # último mensaje de cada hilo, en una sola consulta (ordenada por id:
        # la última fila que se asigna por tramite_id es la más nueva)
        ultimas: dict = {}
        if tramites:
            for n in s.exec(select(NotaTramite).where(
                    NotaTramite.tramite_id.in_([t.id for t in tramites])).order_by(NotaTramite.id)).all():
                ultimas[n.tramite_id] = n
        con_adjunto = _ids_con_bytes(s, NotaTramite.adjunto_datos, [n.id for n in ultimas.values()])
        return [_tramite_resumen(s, tr, titulos_tipo, ultimas, con_adjunto) for tr in tramites]


def _orden_de_notas(notas: list, log: list) -> dict:
    """{id de nota -> id de su fila en el log}: el reloj fino del chat.

    El hilo mezcla notas y eventos, y los dos guardan la hora AL MINUTO.
    Dentro del mismo minuto el empate lo rompía el orden en que el cliente
    concatena las dos listas, así que un pase y la respuesta que lo motivó
    salían al revés -- se ve enseguida cuando el sindicato contesta y deriva
    seguido, que es el caso normal.

    La tabla de log ya es una secuencia global (toda nota escribe su fila),
    así que su id ordena las dos listas con precisión de acto, sin tocar el
    formato de las fechas ni agregar una columna. La k-ésima fila
    "nota_<autor>" es la k-ésima nota de ese autor: `_log_tramite` es el
    único punto que escribe ahí y una nota no se guarda sin su fila.

    Sirve igual para el mirror de empleadores (autor "empresa" en vez de
    "trabajador"), por eso el autor sale del propio evento.
    """
    pendientes: dict = {}
    for n in notas:
        pendientes.setdefault(n.autor, []).append(n.id)
    orden, vistas = {}, {}
    for l in log:
        if not (l.evento or "").startswith("nota_"):
            continue
        autor = l.evento[len("nota_"):]
        i = vistas.get(autor, 0)
        cola = pendientes.get(autor, [])
        if i < len(cola):
            orden[cola[i]] = l.id
        vistas[autor] = i + 1
    return orden


def _tramite_detalle_completo(s: Session, tr: "Tramite") -> dict:
    tipo = s.get(TipoTramite, tr.tipo_tramite_id)
    campos = s.exec(select(CampoTramite).where(CampoTramite.tipo_tramite_id == tr.tipo_tramite_id)
                    .order_by(CampoTramite.orden)).all()
    campos_por_id = {c.id: c for c in campos}
    respuestas = s.exec(select(RespuestaTramite).where(RespuestaTramite.tramite_id == tr.id)).all()
    notas = s.exec(select(NotaTramite).where(NotaTramite.tramite_id == tr.id)
                   .order_by(NotaTramite.id)).all()
    log = s.exec(select(TramiteLog).where(TramiteLog.tramite_id == tr.id)
                 .order_by(TramiteLog.id)).all()
    # Título/estado de los formularios adjuntados en mensajes del chat: se
    # resuelven acá (no hay FK, un tipo borrado se muestra "no disponible").
    forms_ref = {n.formulario_id for n in notas if n.formulario_id}
    formularios = {t.id: t for t in s.exec(select(TipoTramite).where(
        TipoTramite.id.in_(forms_ref), TipoTramite.sindicato_id == tr.sindicato_id)).all()} \
        if forms_ref else {}

    orden_de_nota = _orden_de_notas(notas, log)
    resp_con_archivo = _ids_con_bytes(s, RespuestaTramite.archivo_datos, [r.id for r in respuestas])
    nota_con_adjunto = _ids_con_bytes(s, NotaTramite.adjunto_datos, [n.id for n in notas])

    # Trámites encadenados: el que ORIGINÓ este (el trabajador lo inició
    # desde el formulario adjunto en aquel chat) y los DERIVADOS que se
    # iniciaron desde este. Los dos chats muestran el vínculo clickeable.
    def _vinculo(otro):
        t_otro = s.get(TipoTramite, otro.tipo_tramite_id)
        return {"id": otro.id, "numero_expediente": otro.numero_expediente,
                "tipo_titulo": t_otro.titulo if t_otro else "—", "creado": otro.creado}
    origen = s.get(Tramite, tr.origen_tramite_id) if tr.origen_tramite_id else None
    derivados = s.exec(select(Tramite).where(Tramite.origen_tramite_id == tr.id)
                       .order_by(Tramite.id)).all()
    return {
        "id": tr.id, "numero_expediente": tr.numero_expediente, "cuil": tr.cuil,
        "sindicato_id": tr.sindicato_id, "estado": tr.estado,
        "estado_label": ESTADOS_TRAMITE_LABEL.get(tr.estado, tr.estado),
        "creado": tr.creado, "actualizado": tr.actualizado,
        "advertencias": tr.advertencias or [],
        "origen_tramite": _vinculo(origen) if origen else None,
        "derivados": [_vinculo(d) for d in derivados],
        "tipo_titulo": tipo.titulo if tipo else "—", "tipo_codigo": tipo.codigo if tipo else "",
        "respuestas": [{
            "campo_id": r.campo_tramite_id,
            "etiqueta": campos_por_id[r.campo_tramite_id].etiqueta if r.campo_tramite_id in campos_por_id else "—",
            "tipo_dato": campos_por_id[r.campo_tramite_id].tipo_dato if r.campo_tramite_id in campos_por_id else "texto",
            "valor_texto": r.valor_texto, "tiene_archivo": r.id in resp_con_archivo,
            "archivo_nombre": r.archivo_nombre, "respuesta_id": r.id,
        } for r in respuestas],
        "notas": [{
            "id": n.id, "autor": n.autor, "texto": n.texto, "creado": n.creado,
            "orden": orden_de_nota.get(n.id, 0),
            "tiene_adjunto": n.id in nota_con_adjunto, "adjunto_nombre": n.adjunto_nombre,
            "formulario_id": n.formulario_id,
            # El estado que fijó ESE mensaje (N9): el chat lo pinta pegado a
            # la burbuja en vez de como un movimiento aparte.
            "estado_nuevo": n.estado_nuevo,
            "estado_nuevo_label": ESTADOS_TRAMITE_LABEL.get(n.estado_nuevo, ""),
            "formulario_titulo": formularios[n.formulario_id].titulo
                if n.formulario_id in formularios else None,
            "formulario_activo": formularios[n.formulario_id].activo
                if n.formulario_id in formularios else False,
        } for n in notas],
        "log": [{"evento": l.evento, "detalle": l.detalle, "creado": l.creado,
                  "orden": l.id} for l in log],
        "area_a_cargo_id": tr.area_a_cargo_id,
        "area_a_cargo": (s.get(Area, tr.area_a_cargo_id).nombre
                         if tr.area_a_cargo_id and s.get(Area, tr.area_a_cargo_id) else ""),
    }


def tramite_detalle(tramite_id: int, usuario_id: Optional[int] = None) -> Optional[dict]:
    """Con `usuario_id`, el detalle informa además si ESE usuario puede
    responder y a qué áreas puede derivar. Van juntos y no en un endpoint
    aparte porque la pantalla los necesita a la vez: sin saber si puede
    escribir, el chat no sabe si mostrar el cajón de respuesta."""
    with Session(engine) as s:
        tr = s.get(Tramite, tramite_id)
        if not tr:
            return None
        detalle = _tramite_detalle_completo(s, tr)
    if usuario_id:
        detalle["puede_responder"] = puede_responder_tramite(
            tramite_id, usuario_id, detalle["sindicato_id"])
        detalle["areas_pase"] = areas_a_las_que_puede_pasar(tramite_id) \
            if detalle["puede_responder"] else []
    return detalle


def tramite_por_numero_expediente(numero_expediente: str) -> Optional[dict]:
    with Session(engine) as s:
        tr = _buscar_por_expediente(s, Tramite, numero_expediente)
        return _tramite_detalle_completo(s, tr) if tr else None


# ---------- Trámites externos a empleadores (Fase 5 del plan de Empleadores) ----------
# Mirror 1:1 de la sección "Trámites" de arriba (cuil -> cuit, autor "empresa"
# en vez de "trabajador") -- reusa ESTADOS_TRAMITE/ESTADOS_TRAMITE_LABEL, que
# son constantes de datos sin estado propio, no específicas de trabajador.

def _campo_tramite_empleador_a_dict(c: "CampoTramiteEmpleador") -> dict:
    return {
        "id": c.id, "orden": c.orden, "etiqueta": c.etiqueta, "tipo_dato": c.tipo_dato,
        "longitud_maxima": c.longitud_maxima, "longitud_exacta": c.longitud_exacta,
        "decimales": c.decimales, "tipos_archivo_permitidos": c.tipos_archivo_permitidos,
        "opciones": c.opciones, "ancho": c.ancho, "obligatorio": c.obligatorio,
        "validaciones": c.validaciones or [],
    }


def crear_tipo_tramite_empleador(sindicato_id: int, titulo: str, codigo: str, campos: list,
                                  reglas: list = None) -> int:
    with Session(engine) as s:
        t = TipoTramiteEmpleador(sindicato_id=sindicato_id, titulo=titulo, codigo=codigo,
                                  reglas_consistencia=reglas or [],
                                  creado=fechas.ahora_texto())
        s.add(t); s.commit(); s.refresh(t)
        for i, c in enumerate(campos):
            s.add(CampoTramiteEmpleador(
                tipo_tramite_id=t.id, orden=i, etiqueta=c["etiqueta"], tipo_dato=c["tipo_dato"],
                longitud_maxima=c.get("longitud_maxima"), longitud_exacta=c.get("longitud_exacta"),
                decimales=c.get("decimales"), tipos_archivo_permitidos=c.get("tipos_archivo_permitidos", ""),
                opciones=c.get("opciones", ""), ancho=c.get("ancho") or "completo",
                obligatorio=c.get("obligatorio", True),
                validaciones=c.get("validaciones") or [],
            ))
        s.commit()
        return t.id


def editar_tipo_tramite_empleador(tipo_id: int, sindicato_id: int, titulo: str, codigo: str,
                                   activo: bool, campos: list, reglas: list = None) -> bool:
    """Mirror de editar_tipo_tramite: sincroniza por id en vez de borrar y
    recrear (mismo fix del FK con trámites ya presentados)."""
    with Session(engine) as s:
        t = s.get(TipoTramiteEmpleador, tipo_id)
        if not t or t.sindicato_id != sindicato_id:
            return False
        t.titulo, t.codigo, t.activo = titulo, codigo, activo
        t.reglas_consistencia = reglas or []
        s.add(t)
        existentes = {c.id: c for c in s.exec(select(CampoTramiteEmpleador).where(
            CampoTramiteEmpleador.tipo_tramite_id == tipo_id)).all()}
        vistos = set()
        for i, c in enumerate(campos):
            fila = existentes.get(c.get("id"))
            if fila is None:
                fila = CampoTramiteEmpleador(tipo_tramite_id=tipo_id)
            else:
                vistos.add(fila.id)
            fila.orden, fila.etiqueta, fila.tipo_dato = i, c["etiqueta"], c["tipo_dato"]
            fila.longitud_maxima = c.get("longitud_maxima")
            fila.longitud_exacta = c.get("longitud_exacta")
            fila.decimales = c.get("decimales")
            fila.tipos_archivo_permitidos = c.get("tipos_archivo_permitidos", "")
            fila.opciones = c.get("opciones", "")
            fila.ancho = c.get("ancho") or "completo"
            fila.obligatorio = c.get("obligatorio", True)
            fila.validaciones = c.get("validaciones") or []
            fila.retirado = False
            s.add(fila)
        for fila in existentes.values():
            if fila.id in vistos:
                continue
            respondido = s.exec(select(RespuestaTramiteEmpleador).where(
                RespuestaTramiteEmpleador.campo_tramite_id == fila.id)).first()
            if respondido:
                fila.retirado = True
                s.add(fila)
            else:
                s.delete(fila)
        s.commit()
        return True


def borrar_tipo_tramite_empleador(tipo_id: int, sindicato_id: int) -> bool:
    with Session(engine) as s:
        t = s.get(TipoTramiteEmpleador, tipo_id)
        if not t or t.sindicato_id != sindicato_id:
            return False
        if s.exec(select(TramiteEmpleador).where(TramiteEmpleador.tipo_tramite_id == tipo_id)).first():
            return False
        for c in s.exec(select(CampoTramiteEmpleador).where(
                CampoTramiteEmpleador.tipo_tramite_id == tipo_id)).all():
            s.delete(c)
        s.delete(t)
        s.commit()
        return True


def tipos_tramite_empleador_del_sindicato(sindicato_id: int, solo_activos: bool = False) -> list:
    with Session(engine) as s:
        q = select(TipoTramiteEmpleador).where(TipoTramiteEmpleador.sindicato_id == sindicato_id)
        if solo_activos:
            q = q.where(TipoTramiteEmpleador.activo == True)
        tipos = s.exec(q.order_by(TipoTramiteEmpleador.creado.desc())).all()
        resultado = []
        for t in tipos:
            campos = s.exec(select(CampoTramiteEmpleador)
                            .where(CampoTramiteEmpleador.tipo_tramite_id == t.id,
                                   CampoTramiteEmpleador.retirado == False)  # noqa: E712
                            .order_by(CampoTramiteEmpleador.orden)).all()
            resultado.append({
                "id": t.id, "titulo": t.titulo, "codigo": t.codigo, "activo": t.activo,
                "creado": t.creado, "campos": [_campo_tramite_empleador_a_dict(c) for c in campos],
                "reglas_consistencia": t.reglas_consistencia or [],
            })
        return resultado


def tipo_tramite_empleador_por_id(tipo_id: int) -> Optional[dict]:
    with Session(engine) as s:
        t = s.get(TipoTramiteEmpleador, tipo_id)
        if not t:
            return None
        campos = s.exec(select(CampoTramiteEmpleador)
                        .where(CampoTramiteEmpleador.tipo_tramite_id == tipo_id,
                               CampoTramiteEmpleador.retirado == False)  # noqa: E712
                        .order_by(CampoTramiteEmpleador.orden)).all()
        return {
            "id": t.id, "sindicato_id": t.sindicato_id, "titulo": t.titulo, "codigo": t.codigo,
            "activo": t.activo, "creado": t.creado,
            "campos": [_campo_tramite_empleador_a_dict(c) for c in campos],
            "reglas_consistencia": t.reglas_consistencia or [],
        }


def _log_tramite_empleador(s: Session, tramite_id: int, evento: str, detalle: str) -> None:
    s.add(TramiteEmpleadorLog(
        tramite_id=tramite_id, evento=evento, detalle=detalle,
        creado=fechas.ahora_texto(),
    ))


def crear_tramite_empleador(sindicato_id: int, tipo_tramite_id: int, cuit: str, respuestas: list,
                             advertencias: list = None,
                             origen_tramite_id: Optional[int] = None) -> Optional[dict]:
    with Session(engine) as s:
        tipo = s.get(TipoTramiteEmpleador, tipo_tramite_id)
        if not tipo or tipo.sindicato_id != sindicato_id or not tipo.activo:
            return None
        prefijo = prefijo_expediente(tipo.codigo)
        anio = fechas.ahora().strftime("%Y")
        ahora = fechas.ahora_texto()
        # Mismo criterio que crear_tramite (ver _proximo_numero_expediente):
        # la numeración de empleadores es su propio espacio, pero comparte el
        # problema de prefijos repetidos entre sindicatos.
        numero = _proximo_numero_expediente(s, TramiteEmpleador, prefijo, anio)
        tr = TramiteEmpleador(sindicato_id=sindicato_id, tipo_tramite_id=tipo_tramite_id, cuit=cuit,
                               numero_expediente=numero, estado="iniciado", creado=ahora, actualizado=ahora,
                               advertencias=advertencias or [], origen_tramite_id=origen_tramite_id,
                               visto_empresa_en=ahora)
        s.add(tr); s.commit(); s.refresh(tr)
        for r in respuestas:
            s.add(RespuestaTramiteEmpleador(
                tramite_id=tr.id, campo_tramite_id=r["campo_tramite_id"],
                valor_texto=r.get("valor_texto", ""), archivo_datos=r.get("archivo_datos"),
                archivo_mime=r.get("archivo_mime", ""), archivo_nombre=r.get("archivo_nombre", ""),
            ))
        _log_tramite_empleador(s, tr.id, "creado", f"Trámite presentado por la empresa ({numero}).")
        s.commit()
        return {"id": tr.id, "numero_expediente": numero}


def cambiar_estado_tramite_empleador(tramite_id: int, sindicato_id: int, nuevo_estado: str) -> bool:
    if nuevo_estado not in ESTADOS_TRAMITE:
        return False
    with Session(engine) as s:
        tr = s.get(TramiteEmpleador, tramite_id)
        if not tr or tr.sindicato_id != sindicato_id or tr.estado == "terminado":
            return False
        anterior = tr.estado
        tr.estado = nuevo_estado
        tr.actualizado = fechas.ahora_texto()
        tr.visto_empresa_en = None      # cambio del sindicato = novedad para la empresa
        s.add(tr)
        _log_tramite_empleador(s, tramite_id, "cambio_estado",
                     f"{ESTADOS_TRAMITE_LABEL.get(anterior, anterior)} → {ESTADOS_TRAMITE_LABEL.get(nuevo_estado, nuevo_estado)}")
        s.commit()
        return True


def agregar_nota_tramite_empleador(tramite_id: int, autor: str, texto: str,
                                    adjunto_datos: Optional[bytes] = None, adjunto_mime: str = "",
                                    adjunto_nombre: str = "", formulario_id: Optional[int] = None) -> bool:
    with Session(engine) as s:
        tr = s.get(TramiteEmpleador, tramite_id)
        if not tr or tr.estado == "terminado":
            return False
        s.add(NotaTramiteEmpleador(
            tramite_id=tramite_id, autor=autor, texto=texto or "",
            adjunto_datos=adjunto_datos, adjunto_mime=adjunto_mime or "",
            adjunto_nombre=adjunto_nombre or "", creado=fechas.ahora_texto(),
            formulario_id=formulario_id,
        ))
        tr.actualizado = fechas.ahora_texto()
        tr.visto_empresa_en = None if autor == "admin" else tr.actualizado
        s.add(tr)
        _log_tramite_empleador(s, tramite_id, f"nota_{autor}", texto[:120] if texto else "(sin texto, con adjunto)")
        s.commit()
        return True


def _tramite_empleador_resumen(s: Session, tr: "TramiteEmpleador", titulos_tipo: dict) -> dict:
    return {
        "id": tr.id, "numero_expediente": tr.numero_expediente, "cuit": tr.cuit,
        "tipo_tramite_id": tr.tipo_tramite_id, "tipo_titulo": titulos_tipo.get(tr.tipo_tramite_id, "—"),
        "estado": tr.estado, "estado_label": ESTADOS_TRAMITE_LABEL.get(tr.estado, tr.estado),
        "creado": tr.creado, "actualizado": tr.actualizado,
        "novedad": not tr.visto_empresa_en,
    }


def marcar_tramite_empleador_visto(tramite_id: int, cuit: str) -> None:
    """Mirror de marcar_tramite_visto."""
    with Session(engine) as s:
        tr = s.get(TramiteEmpleador, tramite_id)
        if tr and tr.cuit == cuit:
            tr.visto_empresa_en = fechas.ahora_texto()
            s.add(tr); s.commit()


def contar_tramites_empleador_con_novedades(cuit: str, sindicato_id: int) -> int:
    """Mirror de contar_tramites_con_novedades."""
    with Session(engine) as s:
        tramites = s.exec(select(TramiteEmpleador).where(
            TramiteEmpleador.cuit == cuit, TramiteEmpleador.sindicato_id == sindicato_id)).all()
        return sum(1 for tr in tramites if not tr.visto_empresa_en)


def tramites_empleador_del_sindicato(sindicato_id: int, estado: str = None, tipo_tramite_id: int = None,
                                      cuit: str = None) -> list:
    with Session(engine) as s:
        q = select(TramiteEmpleador).where(TramiteEmpleador.sindicato_id == sindicato_id)
        if estado:
            q = q.where(TramiteEmpleador.estado == estado)
        if tipo_tramite_id:
            q = q.where(TramiteEmpleador.tipo_tramite_id == tipo_tramite_id)
        if cuit:
            q = q.where(TramiteEmpleador.cuit == cuit)
        tramites = s.exec(q.order_by(TramiteEmpleador.id.desc())).all()
        titulos_tipo = {t.id: t.titulo for t in s.exec(
            select(TipoTramiteEmpleador).where(TipoTramiteEmpleador.sindicato_id == sindicato_id)).all()}
        return [_tramite_empleador_resumen(s, tr, titulos_tipo) for tr in tramites]


def contar_tramites_empleador_nuevos(sindicato_id: int) -> int:
    with Session(engine) as s:
        return len(s.exec(select(TramiteEmpleador).where(
            TramiteEmpleador.sindicato_id == sindicato_id, TramiteEmpleador.estado == "iniciado")).all())


def tramites_de_empresa(cuit: str, sindicato_id: int) -> list:
    with Session(engine) as s:
        tramites = s.exec(select(TramiteEmpleador).where(
            TramiteEmpleador.cuit == cuit, TramiteEmpleador.sindicato_id == sindicato_id
        ).order_by(TramiteEmpleador.id.desc())).all()
        titulos_tipo = {t.id: t.titulo for t in s.exec(
            select(TipoTramiteEmpleador).where(TipoTramiteEmpleador.sindicato_id == sindicato_id)).all()}
        return [_tramite_empleador_resumen(s, tr, titulos_tipo) for tr in tramites]


def _tramite_empleador_detalle_completo(s: Session, tr: "TramiteEmpleador") -> dict:
    tipo = s.get(TipoTramiteEmpleador, tr.tipo_tramite_id)
    campos = s.exec(select(CampoTramiteEmpleador).where(CampoTramiteEmpleador.tipo_tramite_id == tr.tipo_tramite_id)
                    .order_by(CampoTramiteEmpleador.orden)).all()
    campos_por_id = {c.id: c for c in campos}
    respuestas = s.exec(select(RespuestaTramiteEmpleador).where(
        RespuestaTramiteEmpleador.tramite_id == tr.id)).all()
    notas = s.exec(select(NotaTramiteEmpleador).where(NotaTramiteEmpleador.tramite_id == tr.id)
                   .order_by(NotaTramiteEmpleador.id)).all()
    log = s.exec(select(TramiteEmpleadorLog).where(TramiteEmpleadorLog.tramite_id == tr.id)
                 .order_by(TramiteEmpleadorLog.id)).all()
    orden_de_nota = _orden_de_notas(notas, log)
    resp_con_archivo = _ids_con_bytes(s, RespuestaTramiteEmpleador.archivo_datos, [r.id for r in respuestas])
    nota_con_adjunto = _ids_con_bytes(s, NotaTramiteEmpleador.adjunto_datos, [n.id for n in notas])
    forms_ref = {n.formulario_id for n in notas if n.formulario_id}
    formularios = {t.id: t for t in s.exec(select(TipoTramiteEmpleador).where(
        TipoTramiteEmpleador.id.in_(forms_ref),
        TipoTramiteEmpleador.sindicato_id == tr.sindicato_id)).all()} \
        if forms_ref else {}

    def _vinculo(otro):
        t_otro = s.get(TipoTramiteEmpleador, otro.tipo_tramite_id)
        return {"id": otro.id, "numero_expediente": otro.numero_expediente,
                "tipo_titulo": t_otro.titulo if t_otro else "—", "creado": otro.creado}
    origen = s.get(TramiteEmpleador, tr.origen_tramite_id) if tr.origen_tramite_id else None
    derivados = s.exec(select(TramiteEmpleador).where(
        TramiteEmpleador.origen_tramite_id == tr.id).order_by(TramiteEmpleador.id)).all()
    return {
        "id": tr.id, "numero_expediente": tr.numero_expediente, "cuit": tr.cuit,
        "sindicato_id": tr.sindicato_id, "estado": tr.estado,
        "estado_label": ESTADOS_TRAMITE_LABEL.get(tr.estado, tr.estado),
        "creado": tr.creado, "actualizado": tr.actualizado,
        "advertencias": tr.advertencias or [],
        "origen_tramite": _vinculo(origen) if origen else None,
        "derivados": [_vinculo(d) for d in derivados],
        "tipo_titulo": tipo.titulo if tipo else "—", "tipo_codigo": tipo.codigo if tipo else "",
        "respuestas": [{
            "campo_id": r.campo_tramite_id,
            "etiqueta": campos_por_id[r.campo_tramite_id].etiqueta if r.campo_tramite_id in campos_por_id else "—",
            "tipo_dato": campos_por_id[r.campo_tramite_id].tipo_dato if r.campo_tramite_id in campos_por_id else "texto",
            "valor_texto": r.valor_texto, "tiene_archivo": r.id in resp_con_archivo,
            "archivo_nombre": r.archivo_nombre, "respuesta_id": r.id,
        } for r in respuestas],
        "notas": [{
            "id": n.id, "autor": n.autor, "texto": n.texto, "creado": n.creado,
            "orden": orden_de_nota.get(n.id, 0),
            "tiene_adjunto": n.id in nota_con_adjunto, "adjunto_nombre": n.adjunto_nombre,
            "formulario_id": n.formulario_id,
            "formulario_titulo": formularios[n.formulario_id].titulo
                if n.formulario_id in formularios else None,
            "formulario_activo": formularios[n.formulario_id].activo
                if n.formulario_id in formularios else False,
        } for n in notas],
        "log": [{"evento": l.evento, "detalle": l.detalle, "creado": l.creado,
                  "orden": l.id} for l in log],
    }


def tramite_empleador_detalle(tramite_id: int) -> Optional[dict]:
    with Session(engine) as s:
        tr = s.get(TramiteEmpleador, tramite_id)
        return _tramite_empleador_detalle_completo(s, tr) if tr else None


def tramite_empleador_por_numero_expediente(numero_expediente: str) -> Optional[dict]:
    with Session(engine) as s:
        tr = _buscar_por_expediente(s, TramiteEmpleador, numero_expediente)
        return _tramite_empleador_detalle_completo(s, tr) if tr else None


# ==================== Planes de Render: programación y bitácora ====================
# La hora de estas dos tablas sale de fechas.ahora_con_segundos(), como la
# del resto de la app. Acá nació la regla: la hora programada de un plan
# SIEMPRE es hora de Buenos Aires (es lo que el usuario escribe en la
# pantalla), y verla al lado de una bitácora en UTC hacía parecer que el
# cambio se aplicó tres horas tarde -- la regla decía 22:02 y la bitácora
# 01:02 (prueba de punta a punta del 2026-09-11).


class PlanProgramado(SQLModel, table=True):
    """Una regla semanal: "los días D, a las HH:MM de Buenos Aires, poné el
    servicio X en el plan P".

    Existe porque el tráfico de esta app es muy desparejo -- días de
    liquidación contra fines de semana con veinte veces menos gente -- y
    Render prorratea por segundo, así que subir de plan solo las horas que
    hace falta es plata real. Hasta ahora eso se hacía a mano en la consola
    de Render y dependía de que alguien se acordara.

    `ultimo_disparo` no es informativo: es el candado. El planificador
    reclama la regla con un UPDATE condicional sobre este campo, así que si
    el servicio web corre en varias instancias, solo una puede ganar el
    reclamo y el cambio se aplica una sola vez."""
    id: Optional[int] = Field(default=None, primary_key=True)
    activo: bool = True
    destino: str = "web"                  # "web" | "db"
    # Días ISO separados por coma: 1 = lunes ... 7 = domingo.
    dias: str = "1,2,3,4,5"
    hora: str = "08:00"                   # HH:MM en hora de Buenos Aires
    plan: str = ""                        # identificador de Render ("4c-8g")
    instancias: Optional[int] = None      # solo para "web"; None = no tocar
    ajustar_workers: bool = True          # un worker por núcleo al aplicar
    nota: str = ""
    ultimo_disparo: str = ""              # "AAAA-MM-DD HH:MM" (BA) ya aplicado
    creado_en: str = Field(default_factory=fechas.ahora_con_segundos)   # hora de Buenos Aires


class CambioPlan(SQLModel, table=True):
    """Bitácora de todo cambio de plan, manual o programado. Sin esto, la
    única forma de saber por qué cambió el gasto sería el historial de
    Render, que para las bases de datos ni siquiera existe."""
    id: Optional[int] = Field(default=None, primary_key=True)
    cuando: str = Field(default_factory=fechas.ahora_con_segundos)      # hora de Buenos Aires
    origen: str = "manual"                # "manual" | "programado"
    programado_id: Optional[int] = None
    destino: str = "web"
    plan_anterior: str = ""
    plan_nuevo: str = ""
    detalle: str = ""
    ok: bool = True
    error: str = ""


class CasoHerramienta(SQLModel, table=True):
    """Un caso guardado desde una herramienta de /entornos → Herramientas (la
    primera, la Calculadora bancaria): lo que se eligió, lo que la
    herramienta calculó, lo que decía el recibo real y una nota. Existe para
    revisarlos después y corregir la calculadora o el auditor de recibos.
    Sin nombre ni CUIL: el banco es opcional y la nota, libre."""
    id: Optional[int] = Field(default=None, primary_key=True)
    herramienta: str = Field(default="bancaria", index=True)
    creado: str = Field(default_factory=fechas.ahora_con_segundos)     # hora de Buenos Aires
    quien: str = ""                       # usuario de plataforma, o "pase" si entró con el PIN
    grilla: str = ""                      # período de la grilla usada (AAAA-MM)
    banco: str = ""
    nota: str = ""
    entrada: dict = Field(default={}, sa_column=Column(JSON_TIPO, nullable=False))
    esperado: dict = Field(default={}, sa_column=Column(JSON_TIPO, nullable=False))
    real: dict = Field(default={}, sa_column=Column(JSON_TIPO, nullable=False))
    diferencias: dict = Field(default={}, sa_column=Column(JSON_TIPO, nullable=False))
    distintos: int = 0                    # renglones y totales que no coinciden
    estado: str = "nuevo"                 # nuevo | revisado | aplicado | descartado
    estado_cambiado: str = ""
    estado_quien: str = ""


ESTADOS_CASO = ("nuevo", "revisado", "aplicado", "descartado")


def guardar_caso_herramienta(**campos) -> int:
    with Session(engine) as s:
        caso = CasoHerramienta(**campos)
        s.add(caso)
        s.commit()
        s.refresh(caso)
        return caso.id


def sindicatos_para_asistente() -> list:
    """Los sindicatos activos del entorno, para elegir uno en el Asistente
    de trámites (Herramientas de /entornos, D6). Solo id y nombre."""
    with Session(engine) as s:
        return [{"id": x.id, "nombre": x.nombre} for x in
                s.exec(select(Sindicato).where(Sindicato.activo == True).order_by(Sindicato.nombre)).all()]  # noqa: E712


def actualizar_caso_herramienta(herramienta: str, caso_id: int, **campos) -> bool:
    """Reescribe un caso guardado (V1 del Asistente de trámites: guardar un
    trámite ya guardado lo ACTUALIZA, no crea otro). Solo las columnas que
    vienen; el estado y su traza no se tocan por acá."""
    with Session(engine) as s:
        caso = s.get(CasoHerramienta, caso_id)
        if not caso or caso.herramienta != herramienta:
            return False
        for k, v in campos.items():
            if k in ("entrada", "esperado", "real", "diferencias", "distintos", "nota", "banco", "grilla"):
                setattr(caso, k, v)
        s.add(caso)
        s.commit()
        return True


def formularios_para_asistente(sindicato_id: int) -> list:
    """Los tipos de trámite del sindicato, livianos (sin campos), para que el
    Asistente de trámites sepa si un formulario previo ya existe (V4) y
    qué códigos están tomados (V6)."""
    with Session(engine) as s:
        filas = s.exec(select(TipoTramite).where(TipoTramite.sindicato_id == sindicato_id)
                       .order_by(TipoTramite.titulo)).all()
        return [{"id": t.id, "titulo": t.titulo, "codigo": t.codigo, "activo": t.activo,
                 "borrador": t.borrador} for t in filas]


def casos_herramienta(herramienta: str) -> list:
    with Session(engine) as s:
        return list(s.exec(select(CasoHerramienta).where(CasoHerramienta.herramienta == herramienta)
                           .order_by(CasoHerramienta.id.desc())).all())


def caso_herramienta(herramienta: str, caso_id: int):
    with Session(engine) as s:
        caso = s.get(CasoHerramienta, caso_id)
        return caso if caso and caso.herramienta == herramienta else None


def cambiar_estado_caso(herramienta: str, caso_id: int, estado: str, quien: str) -> bool:
    if estado not in ESTADOS_CASO:
        raise ValueError("Estado desconocido.")
    with Session(engine) as s:
        caso = s.get(CasoHerramienta, caso_id)
        if not caso or caso.herramienta != herramienta:
            return False
        caso.estado = estado
        caso.estado_cambiado = fechas.ahora_con_segundos()
        caso.estado_quien = quien
        s.add(caso)
        s.commit()
        return True


def planes_programados() -> list:
    with Session(engine) as s:
        filas = s.exec(select(PlanProgramado).order_by(
            PlanProgramado.hora, PlanProgramado.id)).all()
        return [{
            "id": p.id, "activo": p.activo, "destino": p.destino,
            "dias": [int(d) for d in p.dias.split(",") if d.strip().isdigit()],
            "hora": p.hora, "plan": p.plan, "instancias": p.instancias,
            "ajustar_workers": p.ajustar_workers, "nota": p.nota,
            "ultimo_disparo": p.ultimo_disparo, "creado_en": p.creado_en,
        } for p in filas]


def crear_plan_programado(destino: str, dias: list, hora: str, plan: str,
                          instancias: int = None, ajustar_workers: bool = True,
                          nota: str = "") -> int:
    with Session(engine) as s:
        p = PlanProgramado(
            destino=destino, dias=",".join(str(int(d)) for d in sorted(set(dias))),
            hora=hora, plan=plan, instancias=instancias,
            ajustar_workers=ajustar_workers, nota=nota)
        s.add(p); s.commit(); s.refresh(p)
        return p.id


def borrar_plan_programado(regla_id: int) -> bool:
    with Session(engine) as s:
        p = s.get(PlanProgramado, regla_id)
        if not p:
            return False
        s.delete(p); s.commit()
        return True


def alternar_plan_programado(regla_id: int, activo: bool) -> bool:
    with Session(engine) as s:
        p = s.get(PlanProgramado, regla_id)
        if not p:
            return False
        p.activo = activo
        s.add(p); s.commit()
        return True


def reclamar_plan_programado(regla_id: int, marca: str) -> bool:
    """Intenta quedarse con el derecho a aplicar esta regla en esta marca de
    tiempo. Devuelve True solo si GANÓ el reclamo.

    Es un UPDATE condicional, no un SELECT seguido de UPDATE: la condición y
    la escritura viajan en la misma sentencia, así que dos instancias del
    servicio web que despierten en el mismo minuto no pueden aplicar las dos
    -- la segunda actualiza cero filas y se va. Funciona igual en Postgres y
    en SQLite, sin locks explícitos."""
    with Session(engine) as s:
        r = s.exec(text(
            "UPDATE planprogramado SET ultimo_disparo = :marca "
            "WHERE id = :id AND activo = :si AND ultimo_disparo <> :marca"
        ).bindparams(marca=marca, id=regla_id, si=True))
        s.commit()
        return (r.rowcount or 0) == 1


class AvisoEnviado(SQLModel, table=True):
    """Una fila por (clave, fecha): "este aviso diario ya salió hoy". Es el
    candado del resumen por Telegram (resumen_diario.py): antes de mandar,
    cada proceso intenta insertar la fila del día y solo manda si ganó el
    INSERT. Mismo criterio que `PlanProgramado.ultimo_disparo`, para avisos
    que salen una vez por día y no por regla."""
    __table_args__ = (UniqueConstraint("clave", "fecha", name="uq_avisoenviado_clave_fecha"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    clave: str = Field(index=True)
    fecha: str                                   # "AAAA-MM-DD" de Buenos Aires


def reclamar_aviso_diario(clave: str, fecha: str) -> bool:
    """True solo si ESTE proceso ganó el derecho a mandar el aviso `clave` del
    día `fecha`. INSERT ... ON CONFLICT DO NOTHING: la condición y la escritura
    viajan juntas, así que dos instancias no pueden ganar las dos."""
    with Session(engine) as s:
        r = s.exec(text(
            "INSERT INTO avisoenviado (clave, fecha) VALUES (:clave, :fecha) "
            "ON CONFLICT (clave, fecha) DO NOTHING"
        ).bindparams(clave=clave, fecha=fecha))
        s.commit()
        return (r.rowcount or 0) == 1


def registrar_cambio_plan(destino: str, plan_anterior: str, plan_nuevo: str,
                          detalle: str, ok: bool = True, error: str = "",
                          origen: str = "manual", programado_id: int = None) -> int:
    with Session(engine) as s:
        c = CambioPlan(origen=origen, programado_id=programado_id, destino=destino,
                       plan_anterior=plan_anterior, plan_nuevo=plan_nuevo,
                       detalle=detalle, ok=ok, error=error)
        s.add(c); s.commit(); s.refresh(c)
        return c.id


def cambios_de_plan(limite: int = 20) -> list:
    with Session(engine) as s:
        filas = s.exec(select(CambioPlan).order_by(
            CambioPlan.id.desc()).limit(limite)).all()
        return [{"id": c.id, "cuando": c.cuando, "origen": c.origen,
                 "destino": c.destino, "plan_anterior": c.plan_anterior,
                 "plan_nuevo": c.plan_nuevo, "detalle": c.detalle,
                 "ok": c.ok, "error": c.error} for c in filas]


def actualizar_cambio_plan(cambio_id: int, ok: bool, detalle: str = "",
                           error: str = "") -> bool:
    """Cierra una entrada de bitácora abierta. El planificador anota el
    cambio ANTES de pedírselo a Render y lo cierra después: si el proceso
    muere en el medio -- que es justo lo que pasa al cambiar el plan del
    propio servicio web, porque Render lo reinicia -- la entrada queda
    marcada como "en curso" en vez de desaparecer sin dejar rastro."""
    with Session(engine) as s:
        c = s.get(CambioPlan, cambio_id)
        if not c:
            return False
        c.ok, c.error = ok, error
        if detalle:
            c.detalle = detalle
        s.add(c); s.commit()
        return True


# ==================== Encuestas (SPRINT_ENCUESTAS.md) ====================
# El catálogo, los estados y el disclaimer viven en `encuestas.py`, que no
# toca la base. Acá está solo el modelo.
#
# LA FORMA DE ESTAS TABLAS ES LA GARANTÍA DE ANONIMATO, no un cartel en la
# pantalla. Son cuatro cosas que solo sirven juntas (decisión N2):
#
#   1. Las filas de EncuestaParticipante (el PADRÓN) se crean AL PUBLICAR,
#      una por destinatario; responder solo prende un booleano. Su orden de
#      id es el del padrón, no el de las respuestas.
#   2. RespuestaEncuesta (la URNA) guarda el DÍA, nunca la hora: sin
#      timestamp fino no hay forma de ordenar las respuestas en el tiempo
#      para alinearlas con nada.
#   3. El padrón NO guarda cuándo respondió cada uno. La curva de ritmo del
#      dashboard sale del día que guarda la urna.
#   4. La urna no tiene ninguna columna que apunte a una persona: ni cuil,
#      ni id de participante, ni sesión.
#
# Sacá una sola de las cuatro y el orden de inserción alcanza para
# reconstruir quién contestó qué. Hay tests que las verifican una por una
# (test_encuestas.py); no se tocan sin leer SPRINT_ENCUESTAS.md.
class Encuesta(SQLModel, table=True):
    """Una encuesta del sindicato a un grupo de su padrón.

    No es un trámite: no tiene número de expediente, no cae en ningún área,
    no tiene estados de gestión ni chat. Se responde una vez y se cuenta.
    El `estado` (borrador/programada/abierta/cerrada) NO se guarda: lo
    deriva `encuestas.estado()` de `publicada` y las dos fechas.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(foreign_key="sindicato.id", index=True)
    titulo: str
    descripcion: str = ""
    # "nominal" = la respuesta queda asociada al CUIL; "anonima" = no.
    modo: str = "nominal"
    # Qué atributos se guardan pegados a cada respuesta para poder filtrar
    # (subconjunto de encuestas.CORTES). En una anónima los tilda el admin;
    # en una nominal están todos. Lista vacía en una anónima = solo totales.
    cortes: list = Field(default=[], sa_column=Column(JSON_TIPO, nullable=False))
    # Mínimo de respuestas para mostrar un grupo. Se copia de
    # ConfiguracionPlataforma AL PUBLICAR: si plataforma lo cambia después,
    # una encuesta ya cerrada no empieza a mostrar u ocultar cosas distintas.
    umbral_minimo: int = encuestas.UMBRAL_MINIMO_DEFAULT
    fecha_desde: str = ""   # AAAA-MM-DD, obligatorias las dos (como Noticia)
    fecha_hasta: str = ""
    publicada: bool = False
    publicada_en: str = ""  # "AAAA-MM-DD HH:MM"
    # Cierre anticipado (N7). Vacío = cierra sola por fecha_hasta. Una
    # encuesta cerrada NO se puede reabrir: si hace falta más gente, se
    # duplica y se lanza otra ronda, que queda como un hecho separado.
    cerrada_en: str = ""
    # Si al cerrarse el afiliado ve los totales generales (N12). Nunca los
    # cortes: es por ahí por donde se identifica gente.
    mostrar_resultados: bool = False
    # A quién se dirigió, con los mismos criterios que Notificacion.
    criterio: str = ""      # "cuil" | "cuit_empleador" | "seccional" | "provincia"
    criterio_valores: list = Field(default=[], sa_column=Column(JSON_TIPO, nullable=False))
    # Snapshot: cuántos quedaron en el padrón al publicar. Es el
    # denominador de la participación, y por eso no se recalcula.
    cantidad_destinatarios: int = 0
    usuario_id: Optional[int] = Field(default=None, foreign_key="usuariosindicato.id")
    # Seccional de quien la creó, para que una seccional vea las suyas y las
    # centrales recortadas a su gente (N18). NULL = la lanzó sede central.
    seccional_id: Optional[int] = Field(default=None, foreign_key="seccional.id", index=True)
    # De qué encuesta se duplicó (N23), para comparar tomas sucesivas de la
    # misma encuesta en el tiempo. Int SIN FK, mismo criterio que
    # Noticia.formulario_id: si la original se borra, la copia sigue viva.
    origen_id: Optional[int] = Field(default=None, index=True)
    creada: str = ""


class PreguntaEncuesta(SQLModel, table=True):
    """Una pregunta de una Encuesta. El orden decide cómo se renderiza.

    Mismo vocabulario de tipos que CampoTramite (más escala y ranking, menos
    archivo en las anónimas), pero sin validaciones: una encuesta no valida
    nada contra el padrón ni frena a nadie, solo pregunta.

    Con respuestas ya cargadas las preguntas se CONGELAN (N5): se puede
    corregir la redacción -- queda registrado en EventoEncuesta -- pero no
    agregar, borrar, reordenar ni cambiar el tipo o las opciones.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    encuesta_id: int = Field(foreign_key="encuesta.id", index=True)
    orden: int = 0
    etiqueta: str = ""      # obligatoria salvo para tipo_dato="separador"
    tipo_dato: str          # ver encuestas.TIPOS_PREGUNTA
    opciones: str = ""      # separadas por coma -- seleccion/opcion_unica/multiple/ranking
    escala_min: Optional[int] = Field(default=None)   # solo tipo_dato="escala"
    escala_max: Optional[int] = Field(default=None)
    etiqueta_min: str = ""  # "Muy en desacuerdo"
    etiqueta_max: str = ""  # "Muy de acuerdo"
    ancho: str = "completo"  # completo | mitad | tercio
    obligatorio: bool = True


class RespuestaEncuesta(SQLModel, table=True):
    """LA URNA: una respuesta, sin dueño.

    Una fila por opción elegida (una sola en opción única o escala, varias
    en múltiple y en ranking) o una por valor libre. Así los gráficos se
    agregan en SQL con un GROUP BY y no leyendo JSON, mismo criterio que las
    columnas analíticas de ReciboVerificado en el dashboard.

    **No tiene ninguna columna que lleve a una persona**, y guarda el DÍA y
    no la hora, a propósito (ver el bloque de arriba). Los ids consecutivos
    sí permiten saber qué respuestas entraron juntas, es decir cuáles son de
    una misma persona anónima -- eso es inevitable y no identifica a nadie
    mientras el padrón no se pueda alinear con la urna, que es justamente lo
    que garantizan los puntos 1 a 3.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    encuesta_id: int = Field(foreign_key="encuesta.id", index=True)
    pregunta_id: int = Field(foreign_key="preguntaencuesta.id", index=True)
    # Para las preguntas con opciones: el índice de la opción elegida en
    # PreguntaEncuesta.opciones. Por índice y no por texto, para que corregir
    # una errata de redacción (lo único editable) no huerfanice respuestas.
    opcion_indice: Optional[int] = Field(default=None)
    # Ranking: en qué lugar quedó esa opción (1 = primera prioridad).
    posicion: Optional[int] = Field(default=None)
    valor_texto: str = ""
    valor_numero: Optional[float] = Field(default=None)   # número y escala
    valor_fecha: str = ""
    # El día en que se respondió, "AAAA-MM-DD". SIN hora: es lo que alimenta
    # la curva de ritmo del dashboard sin dejar un rastro fino que se pueda
    # cruzar con nada.
    dia: str = Field(default="", index=True)
    # Los cortes que la encuesta habilitó, copiados al responder. En una
    # anónima, los que el admin tildó; en una nominal, todos. Se copian y no
    # se resuelven después a propósito: si el afiliado cambia de seccional,
    # su respuesta tiene que seguir contando donde estaba cuando respondió.
    seccional_id: Optional[int] = Field(default=None, index=True)
    provincia: str = ""
    cuit_empleador: str = ""


class EncuestaParticipante(SQLModel, table=True):
    """EL PADRÓN: quién puede responder, y si ya lo hizo.

    Las filas se crean AL PUBLICAR, una por destinatario (N10): la lista se
    fija en ese momento y no se recalcula, así el "620 de 1.000" significa
    algo. `respondio` se prende al recibir la respuesta; la fila es la misma
    y conserva su id, que es lo que impide alinear este orden con el de la
    urna.

    NO guarda cuándo respondió cada uno, a propósito: una fecha acá, por
    gruesa que fuera, volvería a abrir la puerta a cruzarla con la urna.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    encuesta_id: int = Field(foreign_key="encuesta.id", index=True)
    cuil: str = Field(index=True)
    respondio: bool = False


class RespuestaNominal(SQLModel, table=True):
    """El vínculo respuesta → persona. SOLO existe en encuestas NOMINALES.

    En una nominal no hay anonimato que proteger: el afiliado respondió
    sabiendo que su nombre queda pegado a lo que contestó, y el sindicato
    tiene que poder exportarlo (N20). Pero ese vínculo NO puede vivir como
    una columna de la urna, porque entonces la garantía de las anónimas
    pasaría a ser "nos acordamos de dejarla en NULL" -- justo el tipo de
    promesa que este módulo no quiere hacer.

    Por eso es una tabla aparte y la flecha apunta AL REVÉS: de acá a la
    respuesta, nunca de la respuesta a acá. RespuestaEncuesta sigue sin
    ninguna columna que lleve a una persona, y en una encuesta anónima esta
    tabla simplemente no tiene filas -- hay un test que lo verifica.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    encuesta_id: int = Field(foreign_key="encuesta.id", index=True)
    respuesta_id: int = Field(foreign_key="respuestaencuesta.id", index=True)
    cuil: str = Field(index=True)


class EventoEncuesta(SQLModel, table=True):
    """El historial de una encuesta: todo lo que alguien hizo con ella.

    Una sola tabla para los cinco: corrección de una errata (N5), prórroga y
    cierre anticipado (N7), envío de un recordatorio (N14) y descarga de
    resultados (N20). La descarga está acá y no en un log del servidor que
    nadie mira: si alguna vez circula una planilla que no debía, hay a quién
    preguntarle.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    encuesta_id: int = Field(foreign_key="encuesta.id", index=True)
    usuario_id: Optional[int] = Field(default=None, foreign_key="usuariosindicato.id")
    evento: str = ""    # edicion | prorroga | cierre | recordatorio | descarga
    detalle: str = ""
    fecha: str = ""     # "AAAA-MM-DD HH:MM"


def umbral_encuestas() -> int:
    """El mínimo de respuestas por grupo que fija plataforma."""
    with Session(engine) as s:
        c = s.get(ConfiguracionPlataforma, 1)
        return int(c.encuestas_umbral_minimo) if c else encuestas.UMBRAL_MINIMO_DEFAULT


def _pregunta_a_dict(p: "PreguntaEncuesta") -> dict:
    return {
        "id": p.id, "orden": p.orden, "etiqueta": p.etiqueta, "tipo_dato": p.tipo_dato,
        "opciones": p.opciones, "escala_min": p.escala_min, "escala_max": p.escala_max,
        "etiqueta_min": p.etiqueta_min, "etiqueta_max": p.etiqueta_max,
        "ancho": p.ancho, "obligatorio": p.obligatorio,
    }


def _encuesta_a_dict(s: Session, e: "Encuesta", hoy: str) -> dict:
    preguntas = s.exec(select(PreguntaEncuesta)
                       .where(PreguntaEncuesta.encuesta_id == e.id)
                       .order_by(PreguntaEncuesta.orden)).all()
    return {
        "id": e.id, "sindicato_id": e.sindicato_id,
        "titulo": e.titulo, "descripcion": e.descripcion, "modo": e.modo,
        "cortes": list(e.cortes or []), "umbral_minimo": e.umbral_minimo,
        "fecha_desde": e.fecha_desde, "fecha_hasta": e.fecha_hasta,
        "publicada": e.publicada, "publicada_en": e.publicada_en,
        "cerrada_en": e.cerrada_en, "mostrar_resultados": e.mostrar_resultados,
        "criterio": e.criterio, "criterio_valores": list(e.criterio_valores or []),
        "cantidad_destinatarios": e.cantidad_destinatarios,
        "usuario_id": e.usuario_id, "seccional_id": e.seccional_id,
        "origen_id": e.origen_id, "creada": e.creada,
        "estado": encuestas.estado(e.publicada, e.fecha_desde, e.fecha_hasta,
                                   hoy, e.cerrada_en),
        "preguntas": [_pregunta_a_dict(p) for p in preguntas],
    }


def encuestas_del_sindicato(sindicato_id: int, alcance=None) -> list:
    """Las encuestas del sindicato, más nuevas primero.

    `alcance` es el de seccional de quien mira (db.alcance_seccional):
    None = todas, un set = las que lanzó alguna de esas seccionales MÁS las
    centrales (decisión N18: la seccional ve las suyas para trabajarlas, y
    la encuesta nacional para leer sus resultados recortados a su gente).

    Cada fila trae `propia`: False en una central mirada por una seccional.
    Es lo que separa "la puedo leer" de "la puedo tocar" -- editar, publicar,
    cerrar o borrar una encuesta ajena lo frena el servidor
    (main._exigir_alcance_encuesta), no el hecho de que el botón no esté.
    """
    if alcance is not None and not alcance:
        return []
    hoy = fechas.hoy_texto()
    with Session(engine) as s:
        q = select(Encuesta).where(Encuesta.sindicato_id == sindicato_id)
        if alcance is not None:
            q = q.where(or_(Encuesta.seccional_id.in_(list(alcance)),
                            Encuesta.seccional_id == None))   # noqa: E711
        filas = s.exec(q.order_by(Encuesta.id.desc())).all()
        salida = []
        for e in filas:
            d = _encuesta_a_dict(s, e, hoy)
            # GENTE que respondió, no filas de la urna: una múltiple deja
            # varias filas por persona y la lista informaba "391 de 106",
            # que parece un error del sistema. El dato sale del padrón, que
            # es justamente lo único que sabe quién participó.
            d["respuestas"] = _cuenta_si(s, EncuestaParticipante, e.id)
            d["participantes"] = _cuenta(s, EncuestaParticipante.encuesta_id, e.id,
                                          EncuestaParticipante)
            d["propia"] = encuesta_en_alcance(e.seccional_id, alcance)
            salida.append(d)
        return salida


def encuesta_en_alcance(seccional_id, alcance) -> bool:
    """Si quien tiene ese alcance puede TOCAR una encuesta de esa seccional.

    Leer una central y modificarla son dos cosas distintas: la seccional ve
    la nacional para sus resultados (N18), pero editarla, publicarla,
    cerrarla o borrarla es de quien alcanza todo.
    """
    if alcance is None:
        return True
    return bool(seccional_id) and seccional_id in alcance


def _cuenta(s: Session, columna, valor, modelo) -> int:
    from sqlalchemy import func
    return s.execute(select(func.count()).select_from(modelo)
                     .where(columna == valor)).scalar() or 0


def _cuenta_si(s: Session, modelo, encuesta_id: int) -> int:
    """Cuántos del padrón de esa encuesta ya respondieron."""
    from sqlalchemy import func
    return s.execute(select(func.count()).select_from(modelo).where(
        modelo.encuesta_id == encuesta_id,
        modelo.respondio == True)).scalar() or 0   # noqa: E712


def encuesta_por_id(encuesta_id: int, sindicato_id: int = 0) -> Optional[dict]:
    """Una encuesta con sus preguntas. `sindicato_id` acota: una encuesta de
    otro sindicato devuelve None, no una excepción."""
    with Session(engine) as s:
        e = s.get(Encuesta, encuesta_id)
        if not e or (sindicato_id and e.sindicato_id != sindicato_id):
            return None
        return _encuesta_a_dict(s, e, fechas.hoy_texto())


def encuesta_tiene_respuestas(encuesta_id: int) -> bool:
    """Si ya entró aunque sea una respuesta. Es lo que congela las preguntas."""
    with Session(engine) as s:
        return _cuenta(s, RespuestaEncuesta.encuesta_id, encuesta_id,
                       RespuestaEncuesta) > 0


def seccional_de_usuario(usuario_id: Optional[int]) -> Optional[int]:
    """La seccional con la que nace lo que crea este usuario.

    None cuando alcanza TODAS las seccionales (sede central): lo que lanza
    es del sindicato entero, no de una delegación. Es lo que después hace
    que cada seccional vea sus encuestas y no las de las otras (N18).
    """
    if not usuario_id:
        return None
    if alcance_seccional(usuario_id) is None:
        return None
    with Session(engine) as s:
        u = s.get(UsuarioSindicato, usuario_id)
        return u.seccional_id if u else None


def registrar_evento_encuesta(encuesta_id: int, usuario_id: Optional[int],
                               evento: str, detalle: str = "") -> None:
    """Una línea en el historial de la encuesta (ver EventoEncuesta)."""
    with Session(engine) as s:
        s.add(EventoEncuesta(encuesta_id=encuesta_id, usuario_id=usuario_id,
                             evento=evento, detalle=detalle[:2000],
                             fecha=fechas.ahora_texto()))
        s.commit()


def eventos_de_encuesta(encuesta_id: int) -> list:
    """El historial de la encuesta, más nuevo primero, con el NOMBRE de quien
    hizo cada cosa. Un "corrección de texto" sin autor no sirve para lo que
    el historial existe (N5): saber quién cambió qué y cuándo."""
    with Session(engine) as s:
        filas = s.exec(select(EventoEncuesta)
                       .where(EventoEncuesta.encuesta_id == encuesta_id)
                       .order_by(EventoEncuesta.id.desc())).all()
        ids = {v.usuario_id for v in filas if v.usuario_id}
        nombres = {u.id: (u.nombre or u.usuario) for u in s.exec(select(UsuarioSindicato).where(
            UsuarioSindicato.id.in_(ids))).all()} if ids else {}
        return [{"evento": v.evento, "detalle": v.detalle, "fecha": v.fecha,
                 "usuario_id": v.usuario_id,
                 "usuario": nombres.get(v.usuario_id, "")} for v in filas]


def _guardar_preguntas(s: Session, encuesta_id: int, preguntas: list) -> None:
    """Reemplaza las preguntas de la encuesta por esta lista.

    Borrar y volver a crear solo es seguro mientras NO haya respuestas (las
    respuestas apuntan a pregunta_id): quien llama tiene que haberlo
    verificado. Con respuestas cargadas se edita en el lugar, ver
    editar_encuesta."""
    viejas = s.exec(select(PreguntaEncuesta)
                    .where(PreguntaEncuesta.encuesta_id == encuesta_id)).all()
    for v in viejas:
        s.delete(v)
    s.flush()
    for i, p in enumerate(preguntas):
        s.add(PreguntaEncuesta(encuesta_id=encuesta_id, orden=i, **p))


def crear_encuesta(sindicato_id: int, usuario_id: Optional[int],
                    seccional_id: Optional[int], datos: dict, preguntas: list) -> int:
    """Crea una encuesta en BORRADOR. Publicar es otro acto (Fase 3)."""
    with Session(engine) as s:
        e = Encuesta(
            sindicato_id=sindicato_id, usuario_id=usuario_id, seccional_id=seccional_id,
            titulo=datos.get("titulo", "").strip(),
            descripcion=datos.get("descripcion", "").strip(),
            modo=datos.get("modo") or encuestas.NOMINAL,
            cortes=encuestas.cortes_saneados(datos.get("modo") or encuestas.NOMINAL,
                                             datos.get("cortes")),
            umbral_minimo=umbral_encuestas(),
            fecha_desde=datos.get("fecha_desde", ""), fecha_hasta=datos.get("fecha_hasta", ""),
            mostrar_resultados=bool(datos.get("mostrar_resultados")),
            origen_id=datos.get("origen_id"),
            creada=fechas.ahora_texto(),
        )
        s.add(e); s.commit(); s.refresh(e)
        _guardar_preguntas(s, e.id, preguntas)
        s.commit()
        return e.id


def editar_encuesta(encuesta_id: int, sindicato_id: int, datos: dict,
                     preguntas: list, usuario_id: Optional[int] = None) -> dict:
    """Edita una encuesta. Devuelve {"ok": bool, "error": str}.

    Con respuestas ya cargadas rige el congelado (N5): se pueden corregir
    título, descripción y la REDACCIÓN de preguntas y opciones, y estirar la
    fecha de cierre. No se puede agregar, borrar ni reordenar preguntas, ni
    cambiar tipos, anchos, obligatoriedad ni la cantidad de opciones. Cada
    corrección de texto queda en el historial, porque el sistema no puede
    distinguir una errata de un cambio de sentido.
    """
    with Session(engine) as s:
        e = s.get(Encuesta, encuesta_id)
        if not e or e.sindicato_id != sindicato_id:
            return {"ok": False, "error": "La encuesta no existe."}

        con_respuestas = _cuenta(s, RespuestaEncuesta.encuesta_id, e.id,
                                 RespuestaEncuesta) > 0
        viejas = [_pregunta_a_dict(p) for p in s.exec(
            select(PreguntaEncuesta).where(PreguntaEncuesta.encuesta_id == e.id)
            .order_by(PreguntaEncuesta.orden)).all()]

        cambios = []
        if con_respuestas:
            if encuestas.cambio_estructural(viejas, preguntas):
                return {"ok": False, "error":
                        "Esta encuesta ya tiene respuestas: solo se puede corregir el "
                        "texto de las preguntas y las opciones. Agregar, quitar o "
                        "reordenar preguntas cambiaría el sentido de lo ya respondido. "
                        "Si necesitás cambiarla de verdad, duplicala y lanzá otra ronda."}
            cambios = [f"«{a['etiqueta']}» → «{d['etiqueta']}»"
                       for a, d in zip(viejas, preguntas) if a["etiqueta"] != d["etiqueta"]]
            cambios += [f"opciones de «{d['etiqueta']}»"
                        for a, d in zip(viejas, preguntas) if a["opciones"] != d["opciones"]]
            for i, (a, d) in enumerate(zip(viejas, preguntas)):
                p = s.get(PreguntaEncuesta, a["id"])
                p.etiqueta = d["etiqueta"]
                p.opciones = d["opciones"]
                p.etiqueta_min, p.etiqueta_max = d["etiqueta_min"], d["etiqueta_max"]
                s.add(p)
        else:
            # Sin respuestas la estructura es libre, y el modo y los cortes
            # también: nadie vio todavía el disclaimer de esta encuesta.
            e.modo = datos.get("modo") or encuestas.NOMINAL
            e.cortes = encuestas.cortes_saneados(e.modo, datos.get("cortes"))
            _guardar_preguntas(s, e.id, preguntas)

        e.titulo = datos.get("titulo", "").strip()
        e.descripcion = datos.get("descripcion", "").strip()
        e.mostrar_resultados = bool(datos.get("mostrar_resultados"))
        if not e.publicada:
            e.fecha_desde = datos.get("fecha_desde", "")
        # Mover la fecha de cierre de una encuesta YA PUBLICADA es un hecho,
        # no un retoque: cambia hasta cuándo se puede responder cuando ya hay
        # gente avisada. Va al historial, como el cierre anticipado (N7).
        antes = e.fecha_hasta
        e.fecha_hasta = datos.get("fecha_hasta", "")
        prorroga = ""
        if e.publicada and e.fecha_hasta != antes:
            prorroga = (f"El cierre pasó del {fechas.dia_legible(antes)} al "
                        f"{fechas.dia_legible(e.fecha_hasta)}")
        s.add(e); s.commit()

    if prorroga:
        registrar_evento_encuesta(encuesta_id, usuario_id, "prorroga", prorroga)
    if con_respuestas and cambios:
        registrar_evento_encuesta(encuesta_id, usuario_id, "edicion",
                                  "Corrección de texto: " + "; ".join(cambios))
    return {"ok": True, "error": ""}


def borrar_encuesta(encuesta_id: int, sindicato_id: int) -> dict:
    """Borra una encuesta que todavía es borrador.

    Una encuesta PUBLICADA no se borra: tiene un padrón fijado, puede tener
    respuestas y es un hecho del sindicato. Si no se va a usar más, se
    cierra."""
    with Session(engine) as s:
        e = s.get(Encuesta, encuesta_id)
        if not e or e.sindicato_id != sindicato_id:
            return {"ok": False, "error": "La encuesta no existe."}
        if e.publicada:
            return {"ok": False, "error":
                    "No se puede borrar una encuesta publicada: ya se la mostró a los "
                    "afiliados. Cerrala en vez de borrarla."}
        for p in s.exec(select(PreguntaEncuesta)
                        .where(PreguntaEncuesta.encuesta_id == e.id)).all():
            s.delete(p)
        for v in s.exec(select(EventoEncuesta)
                        .where(EventoEncuesta.encuesta_id == e.id)).all():
            s.delete(v)
        # El flush no es decorativo: sin él, SQLAlchemy puede mandar el
        # DELETE de la encuesta ANTES que el de sus hijos (estos modelos no
        # declaran relationship, solo la FK), y Postgres lo rechaza con
        # ForeignKeyViolation. En SQLite pasaba sin chistar.
        s.flush()
        s.delete(e); s.commit()
        return {"ok": True, "error": ""}


def duplicar_encuesta(encuesta_id: int, sindicato_id: int,
                       usuario_id: Optional[int] = None,
                       seccional_id: Optional[int] = None) -> Optional[int]:
    """Copia la estructura en un borrador nuevo, guardando de dónde salió.

    Es la salida cuando una encuesta con respuestas quedó mal (N5) y, sobre
    todo, la forma de repetir la misma encuesta cada trimestre: con
    `origen_id` las tomas sucesivas se pueden comparar en el tiempo (N23).
    Las fechas NO se copian: la ventana es de cada toma.
    """
    original = encuesta_por_id(encuesta_id, sindicato_id)
    if not original:
        return None
    preguntas = [{k: v for k, v in p.items() if k not in ("id", "orden")}
                 for p in original["preguntas"]]
    nueva = crear_encuesta(
        sindicato_id, usuario_id,
        seccional_id if seccional_id is not None else original["seccional_id"],
        {"titulo": _titulo_de_copia(original["titulo"]),
         "descripcion": original["descripcion"], "modo": original["modo"],
         "cortes": original["cortes"], "mostrar_resultados": original["mostrar_resultados"],
         "fecha_desde": "", "fecha_hasta": "",
         "origen_id": original["origen_id"] or original["id"]},
        preguntas)
    registrar_evento_encuesta(nueva, usuario_id, "duplicada",
                              f"Copiada de la encuesta #{encuesta_id}")
    return nueva


def _titulo_de_copia(titulo: str) -> str:
    """"Clima laboral" -> "Clima laboral (2)"; "Clima laboral (2)" -> "(3)".

    Repetir la misma encuesta cada trimestre es el caso de uso, así que la
    copia se numera en vez de llamarse "copia de copia de"."""
    import re
    m = re.match(r"^(.*) \((\d+)\)$", titulo.strip())
    if m:
        return f"{m.group(1)} ({int(m.group(2)) + 1})"
    return f"{titulo.strip()} (2)"


def publicar_encuesta(encuesta_id: int, sindicato_id: int, criterio: str,
                       valores: list, usuario_id: Optional[int] = None) -> dict:
    """Fija el padrón y abre la encuesta. Devuelve {ok, error, cantidad}.

    Publicar es EL acto que vuelve real una encuesta, y hace dos cosas que
    no se deshacen:

    1. **Resuelve los destinatarios y los GUARDA** (N10), una fila por CUIL,
       igual que `crear_notificacion`. No se recalcula nunca más: es lo que
       hace que "respondieron 620 de 1.000" signifique algo, porque esos
       1.000 son siempre los mismos. Se recorta por el alcance de seccional
       de quien publica, con la MISMA función que usa el preview.
    2. **Congela el umbral** vigente de plataforma: si mañana lo cambian,
       una encuesta ya cerrada no empieza a mostrar u ocultar cosas
       distintas de las que venía mostrando.

    Las filas del padrón nacen todas acá, al publicar, y responder solo
    prende un booleano. Ese detalle es la mitad de la garantía de anonimato:
    el orden de sus id es el del padrón, no el de las respuestas.
    """
    e = encuesta_por_id(encuesta_id, sindicato_id)
    if not e:
        return {"ok": False, "error": "La encuesta no existe.", "cantidad": 0}
    if e["publicada"]:
        return {"ok": False, "error": "Esta encuesta ya está publicada.", "cantidad": 0}
    if not [p for p in e["preguntas"] if p["tipo_dato"] not in encuestas.TIPOS_SIN_RESPUESTA]:
        return {"ok": False, "error": "La encuesta no tiene ninguna pregunta para responder.",
                "cantidad": 0}
    if not e["fecha_desde"] or not e["fecha_hasta"]:
        return {"ok": False, "error": "Antes de publicar hay que poner las dos fechas: "
                                      "cuándo abre y cuándo cierra.", "cantidad": 0}
    if e["fecha_hasta"] < e["fecha_desde"]:
        return {"ok": False, "error": "La fecha de cierre es anterior a la de apertura.",
                "cantidad": 0}

    cuils = resolver_destinatarios(sindicato_id, criterio, valores, usuario_id=usuario_id)
    if not cuils:
        return {"ok": False, "error": "Ese criterio no alcanza a ningún afiliado activo: "
                                      "la encuesta no se publicó.", "cantidad": 0}

    with Session(engine) as s:
        fila = s.get(Encuesta, encuesta_id)
        fila.publicada = True
        fila.publicada_en = fechas.ahora_texto()
        fila.criterio = criterio
        fila.criterio_valores = list(valores or [])
        fila.cantidad_destinatarios = len(cuils)
        fila.umbral_minimo = umbral_encuestas()
        s.add(fila)
        for cuil in cuils:
            s.add(EncuestaParticipante(encuesta_id=encuesta_id, cuil=cuil))
        s.commit()
    registrar_evento_encuesta(encuesta_id, usuario_id, "publicada",
                              f"Padrón fijado: {len(cuils)} afiliados ({criterio})")
    return {"ok": True, "error": "", "cantidad": len(cuils)}


def cerrar_encuesta(encuesta_id: int, sindicato_id: int,
                     usuario_id: Optional[int] = None) -> dict:
    """Cierra una encuesta antes de tiempo (N7). No se puede reabrir: una
    encuesta que se reabre después de ver los resultados deja de ser
    confiable, y en un gremio con internas eso se discute. Si hace falta
    más gente, se duplica y se lanza otra ronda."""
    with Session(engine) as s:
        e = s.get(Encuesta, encuesta_id)
        if not e or e.sindicato_id != sindicato_id:
            return {"ok": False, "error": "La encuesta no existe."}
        if not e.publicada:
            return {"ok": False, "error": "Esta encuesta todavía es un borrador."}
        if e.cerrada_en:
            return {"ok": False, "error": "Esta encuesta ya está cerrada."}
        e.cerrada_en = fechas.ahora_texto()
        s.add(e); s.commit()
    registrar_evento_encuesta(encuesta_id, usuario_id, "cierre", "Cierre anticipado")
    return {"ok": True, "error": ""}


def encuestas_de_trabajador(cuil: str, sindicato_id: int) -> list:
    """Las encuestas de este sindicato a las que ESTE CUIL fue invitado.

    Solo las publicadas y solo si está en el padrón: una encuesta a la que
    no fue invitado no existe para él. Trae `respondio` (del padrón, que es
    lo único que sabe quién participó) y las preguntas, para la pantalla.
    """
    hoy = fechas.hoy_texto()
    with Session(engine) as s:
        participaciones = s.exec(select(EncuestaParticipante)
                                 .where(EncuestaParticipante.cuil == cuil)).all()
        if not participaciones:
            return []
        por_encuesta = {p.encuesta_id: p for p in participaciones}
        filas = s.exec(select(Encuesta).where(
            Encuesta.id.in_(list(por_encuesta)),
            Encuesta.sindicato_id == sindicato_id,
            Encuesta.publicada == True).order_by(Encuesta.id.desc())).all()
        salida = []
        for e in filas:
            d = _encuesta_a_dict(s, e, hoy)
            d["respondio"] = por_encuesta[e.id].respondio
            d["disclaimer"] = encuestas.disclaimer(e.modo, e.cortes, e.umbral_minimo)
            # Lo que la tarjeta necesita para no ser una caja de texto: cuánto
            # trabajo es y cuánto tiempo queda. Los días los cuenta el
            # SERVIDOR, en hora de Buenos Aires: con el reloj del teléfono,
            # uno mal puesto o en otra zona muestra un plazo que no existe.
            d["preguntas_reales"] = encuestas.preguntas_reales(d["preguntas"])
            d["minutos"] = encuestas.minutos_estimados(d["preguntas"])
            d["dias_restantes"] = _dias_hasta(e.fecha_hasta, hoy)
            d["avance"] = _avance_de_ventana(e.fecha_desde, e.fecha_hasta, hoy)
            salida.append(d)
        # Las abiertas y sin responder primero: es lo que el afiliado vino a hacer.
        salida.sort(key=lambda d: (d["respondio"], d["estado"] != encuestas.ABIERTA))
        return salida


def esta_en_el_padron(encuesta_id: int, cuil: str, sindicato_id: int) -> bool:
    """Si este CUIL fue invitado a esta encuesta de este sindicato.

    Es control de acceso, no un dato: una encuesta a la que no lo invitaron
    no existe para él, ni siquiera para leer sus resultados.
    """
    with Session(engine) as s:
        e = s.get(Encuesta, encuesta_id)
        if not e or e.sindicato_id != sindicato_id:
            return False
        return s.exec(select(EncuestaParticipante).where(
            EncuestaParticipante.encuesta_id == encuesta_id,
            EncuestaParticipante.cuil == cuil)).first() is not None


def _dias_hasta(fecha_hasta: str, hoy: str) -> Optional[int]:
    """Cuántos días faltan para el cierre. 0 = cierra HOY (el último día se
    puede responder, es inclusive). None si no hay fecha."""
    try:
        return (date.fromisoformat(fecha_hasta) - date.fromisoformat(hoy)).days
    except (TypeError, ValueError):
        return None


def _avance_de_ventana(desde: str, hasta: str, hoy: str) -> int:
    """Qué porcentaje del período ya pasó, 0..100. Es la barra de avance de
    N19 -- la tarjeta muestra el tiempo que corre, no un progreso de
    respuestas que el afiliado no tiene."""
    try:
        d, h, a = (date.fromisoformat(x) for x in (desde, hasta, hoy))
    except (TypeError, ValueError):
        return 0
    total = (h - d).days
    if total <= 0:
        return 100 if a >= h else 0
    return max(0, min(100, round((a - d).days * 100 / total)))


def contar_encuestas_pendientes(cuil: str, sindicato_id: int) -> int:
    """Encuestas ABIERTAS a las que este CUIL fue invitado y no respondió.

    Es el número del globo de la portada: sin él, una encuesta lanzada
    depende de que el afiliado entre a la pestaña por casualidad.
    """
    hoy = fechas.hoy_texto()
    with Session(engine) as s:
        filas = s.exec(
            select(Encuesta).join(
                EncuestaParticipante,
                EncuestaParticipante.encuesta_id == Encuesta.id)
            .where(EncuestaParticipante.cuil == cuil,
                   EncuestaParticipante.respondio == False,
                   Encuesta.sindicato_id == sindicato_id,
                   Encuesta.publicada == True)).all()
    return sum(1 for e in filas
               if encuestas.acepta_respuestas(e.publicada, e.fecha_desde, e.fecha_hasta,
                                              hoy, e.cerrada_en))


def registrar_respuesta_encuesta(encuesta_id: int, cuil: str, sindicato_id: int,
                                  crudas: dict) -> dict:
    """Guarda una respuesta. Devuelve {ok, error}.

    Acá se cumple el anonimato, y es UNA transacción: se escriben las filas
    de la urna y se prende `respondio` del padrón juntas, o no se escribe
    nada. Lo que NO va a la urna: el CUIL, el id del participante, la hora.
    Lo que sí, y solo si la encuesta los habilitó: seccional, provincia y
    empleador, copiados en el momento (si el afiliado cambia de seccional
    después, su respuesta sigue contando donde estaba cuando respondió).
    """
    e = encuesta_por_id(encuesta_id, sindicato_id)
    if not e:
        return {"ok": False, "error": "La encuesta no existe."}
    if not encuestas.acepta_respuestas(e["publicada"], e["fecha_desde"], e["fecha_hasta"],
                                       fechas.hoy_texto(), e["cerrada_en"]):
        return {"ok": False, "error": "Esta encuesta no está abierta."}

    # El padrón se chequea ANTES de mirar las respuestas: es control de
    # acceso, no validación. Al revés, alguien que no fue invitado recibiría
    # mensajes sobre las preguntas ("falta responder tal cosa") y se
    # enteraría de cómo está armada una encuesta que no le toca.
    with Session(engine) as s:
        invitado = s.exec(select(EncuestaParticipante).where(
            EncuestaParticipante.encuesta_id == encuesta_id,
            EncuestaParticipante.cuil == cuil)).first()
        if not invitado:
            return {"ok": False, "error": "Esta encuesta no está dirigida a vos."}
        if invitado.respondio:
            return {"ok": False, "error": "Ya respondiste esta encuesta."}

    filas, errores = encuestas.respuestas_saneadas(e["preguntas"], crudas or {})
    if errores:
        return {"ok": False, "error": errores[0]}

    cortes = set(e["cortes"] or [])
    datos_corte = {"seccional_id": None, "provincia": "", "cuit_empleador": ""}
    if cortes:
        with Session(engine) as s:
            # La provincia es de la persona y el resto del empadronamiento;
            # las dos se leen de una, en la misma sesión (regla de una sola
            # conexión por request).
            fila = s.exec(
                select(Trabajador, CuentaTrabajador.provincia)
                .join(CuentaTrabajador, CuentaTrabajador.cuil == Trabajador.cuil, isouter=True)
                .where(Trabajador.sindicato_id == sindicato_id,
                       Trabajador.cuil == cuil)).first()
            if fila:
                t, provincia = fila
                if "seccional" in cortes:
                    datos_corte["seccional_id"] = t.seccional_id
                if "provincia" in cortes:
                    datos_corte["provincia"] = provincia or ""
                if "empleador" in cortes:
                    datos_corte["cuit_empleador"] = cuit.normalizar(t.cuit_empleador)   # sin guiones: un empleador, un grupo

    dia = fechas.hoy_texto()
    with Session(engine) as s:
        # Se vuelve a leer el padrón DENTRO de la transacción que escribe:
        # entre el chequeo de arriba y esto pueden haber pasado dos
        # pestañas mandando a la vez, y la que llegue segunda tiene que
        # encontrar la fila ya en True y no escribir nada.
        participante = s.exec(select(EncuestaParticipante).where(
            EncuestaParticipante.encuesta_id == encuesta_id,
            EncuestaParticipante.cuil == cuil).with_for_update()).first()
        if not participante:
            return {"ok": False, "error": "Esta encuesta no está dirigida a vos."}
        if participante.respondio:
            return {"ok": False, "error": "Ya respondiste esta encuesta."}
        participante.respondio = True
        s.add(participante)
        nuevas = []
        for f in filas:
            fila = RespuestaEncuesta(encuesta_id=encuesta_id, dia=dia, **f, **datos_corte)
            s.add(fila)
            nuevas.append(fila)
        if e["modo"] == encuestas.NOMINAL:
            # Solo en las nominales, y en su tabla aparte: la urna nunca
            # sabe de quién es una respuesta (ver RespuestaNominal).
            s.flush()   # para tener los id de las filas recién creadas
            for fila in nuevas:
                s.add(RespuestaNominal(encuesta_id=encuesta_id, respuesta_id=fila.id, cuil=cuil))
        s.commit()
    return {"ok": True, "error": ""}


def _cuils_del_padron(encuesta_id: int, solo_pendientes: bool = False) -> list:
    with Session(engine) as s:
        q = select(EncuestaParticipante).where(
            EncuestaParticipante.encuesta_id == encuesta_id)
        if solo_pendientes:
            q = q.where(EncuestaParticipante.respondio == False)   # noqa: E712
        return sorted({p.cuil for p in s.exec(q).all()})


def contar_pendientes_de_encuesta(encuesta_id: int) -> int:
    """Cuántos del padrón todavía no respondieron. Se sabe del padrón, sin
    mirar la urna: funciona igual en las anónimas."""
    return len(_cuils_del_padron(encuesta_id, solo_pendientes=True))


def recordatorios_de_hoy(encuesta_id: int) -> int:
    """Cuántos recordatorios se mandaron hoy. El freno de N14 vive acá: uno
    por día. Cuatro recordatorios y el afiliado apaga las notificaciones de
    la app -- y ahí se pierde el canal para todo, no solo para encuestas."""
    hoy = fechas.hoy_texto()
    return sum(1 for v in eventos_de_encuesta(encuesta_id)
               if v["evento"] == "recordatorio" and v["fecha"].startswith(hoy))


def notificar_encuesta(encuesta_id: int, sindicato_id: int, usuario_id: Optional[int],
                        texto: str, remitente: str = "", tipo: str = "lanzamiento") -> dict:
    """Le avisa al padrón de la encuesta. Devuelve {ok, error, cantidad}.

    Va SIEMPRE al padrón fijado de la encuesta, nunca a un criterio elegido
    aparte (N13): si no, "leídas / no leídas" se mediría contra un universo
    distinto al de "respondieron / no respondieron" y los dos números del
    dashboard no se podrían comparar. El recordatorio va solo a los que
    todavía no respondieron -- eso se sabe del padrón, sin saber qué
    contestó nadie, así que funciona igual en las anónimas.
    """
    e = encuesta_por_id(encuesta_id, sindicato_id)
    if not e:
        return {"ok": False, "error": "La encuesta no existe.", "cantidad": 0}
    if not e["publicada"]:
        return {"ok": False, "error": "Primero hay que publicar la encuesta.", "cantidad": 0}
    if not (texto or "").strip():
        return {"ok": False, "error": "El aviso no puede ir vacío.", "cantidad": 0}

    es_recordatorio = tipo == encuestas.RECORDATORIO
    if es_recordatorio:
        if not encuestas.acepta_respuestas(e["publicada"], e["fecha_desde"], e["fecha_hasta"],
                                           fechas.hoy_texto(), e["cerrada_en"]):
            return {"ok": False, "error": "La encuesta no está abierta: no tiene sentido "
                                          "recordarla.", "cantidad": 0}
        if recordatorios_de_hoy(encuesta_id):
            return {"ok": False, "error": "Ya mandaste un recordatorio hoy. Se puede uno por "
                                          "día: más que eso y el afiliado apaga las "
                                          "notificaciones de la app.", "cantidad": 0}

    cuils = _cuils_del_padron(encuesta_id, solo_pendientes=es_recordatorio)
    if not cuils:
        return {"ok": False, "error": "Ya respondieron todos: no hay a quién recordarle."
                if es_recordatorio else "La encuesta no tiene padrón.", "cantidad": 0}

    r = crear_notificacion(sindicato_id, usuario_id, remitente, texto,
                           criterio="cuil", valores=cuils, encuesta_id=encuesta_id)
    registrar_evento_encuesta(
        encuesta_id, usuario_id, tipo,
        f"Aviso a {r['cantidad_destinatarios']} afiliados"
        + (" que todavía no respondieron" if es_recordatorio else ""))
    return {"ok": True, "error": "", "cantidad": r["cantidad_destinatarios"]}


def noticia_de_encuesta(encuesta_id: int, sindicato_id: int, usuario_id: Optional[int],
                         titulo: str, bajada: str, texto: str) -> dict:
    """Publica la noticia que anuncia la encuesta, con su mismo período.

    A diferencia de la notificación, la noticia es PÚBLICA en la portada y
    no se dirige al padrón: la puede ver alguien que no fue invitado. Por
    eso su vigencia es la ventana de la encuesta y ni un día más.

    **Hereda el alcance de la encuesta** (PLAN_ALCANCE_SECCIONAL.md, bloque
    7, G1): si la encuesta nació en una seccional (la creó un Admin de
    Seccional, N18), la noticia va solo a esa seccional; si la creó el
    general (`seccional_id` NULL), va a todas, como siempre. No hace falta
    mirar el alcance de quien publica la noticia: la encuesta ya lo lleva, y
    sin esto una encuesta de una seccional se anunciaba a todo el sindicato
    (`destino_seccionales` vacío = todas).
    """
    e = encuesta_por_id(encuesta_id, sindicato_id)
    if not e:
        return {"ok": False, "error": "La encuesta no existe."}
    if not e["publicada"]:
        return {"ok": False, "error": "Primero hay que publicar la encuesta."}
    if not (titulo or "").strip():
        return {"ok": False, "error": "La noticia necesita un título."}
    with Session(engine) as s:
        s.add(Noticia(sindicato_id=sindicato_id, titulo=titulo.strip(),
                      bajada=(bajada or "").strip(), texto_completo=(texto or "").strip(),
                      fecha_desde=e["fecha_desde"], fecha_hasta=e["fecha_hasta"],
                      creada=fechas.ahora_texto(), encuesta_id=encuesta_id,
                      destino_seccionales=([e["seccional_id"]] if e.get("seccional_id") else [])))
        s.commit()
    registrar_evento_encuesta(encuesta_id, usuario_id, "noticia", titulo.strip()[:200])
    return {"ok": True, "error": ""}


def avisos_de_encuesta(encuesta_id: int) -> list:
    """Los avisos de esta encuesta con su lectura: enviados y leídos.

    Es el "2 envíos · 1.000 destinatarios · 640 leídos" del dashboard, y el
    desglose por envío que dice si el recordatorio sirvió o no.
    """
    with Session(engine) as s:
        notifs = s.exec(select(Notificacion)
                        .where(Notificacion.encuesta_id == encuesta_id)
                        .order_by(Notificacion.id)).all()
        salida = []
        for n in notifs:
            destinatarios = s.exec(select(NotificacionDestinatario).where(
                NotificacionDestinatario.notificacion_id == n.id)).all()
            salida.append({
                "id": n.id, "enviado_en": n.enviado_en, "texto": n.texto,
                "enviados": len(destinatarios),
                "leidos": sum(1 for d in destinatarios if d.leida_en),
            })
        return salida


# ==================== Listas del sindicato (PLAN_LISTAS_VALIDACIONES.md) ====================

class ListaSindicato(SQLModel, table=True):
    """Una lista que subió el admin del sindicato por CSV: la tabla genérica
    por debajo de las plantillas tipadas de `listas.PLANTILLAS` (D1). Se
    identifica por sindicato + plantilla + nombre + seccional, y una carga
    nueva la REEMPLAZA entera (D5): es una foto del padrón del sindicato.
    `seccional_id` NULL = vale para todo el sindicato."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(foreign_key="sindicato.id", index=True)
    plantilla: str
    nombre: str
    seccional_id: Optional[int] = Field(default=None, foreign_key="seccional.id", index=True)
    columnas: list = Field(default=[], sa_column=Column(JSON_TIPO, nullable=False))
    filas: int = 0
    archivo: str = ""                      # nombre del CSV que se subió
    cargada_en: str = ""                   # hora de Buenos Aires
    cargada_por: str = ""                  # usuario del panel


class FilaLista(SQLModel, table=True):
    """Una fila de una lista. `clave1` es SIEMPRE el CUIL del afiliado
    (normalizado); `clave2` la segunda clave de la plantilla (el DNI del
    familiar) o "". `datos` trae todas las columnas ya normalizadas."""
    __table_args__ = (Index("ix_filalista_claves", "lista_id", "clave1", "clave2"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    lista_id: int = Field(foreign_key="listasindicato.id", index=True)
    clave1: str
    clave2: str = ""
    datos: dict = Field(default={}, sa_column=Column(JSON_TIPO, nullable=False))


def _lista_a_dict(l: "ListaSindicato", seccional: str = "") -> dict:
    return {"id": l.id, "plantilla": l.plantilla, "nombre": l.nombre, "seccional_id": l.seccional_id,
            "seccional": seccional, "columnas": l.columnas or [], "filas": l.filas, "archivo": l.archivo,
            "cargada_en": l.cargada_en, "cargada_por": l.cargada_por}


def listas_del_sindicato(sindicato_id: int, alcance=None) -> list:
    """Las listas del sindicato, recortadas al alcance de quien mira EN LA
    CONSULTA (None = todas; un set = solo las de esas seccionales; una lista
    sin seccional la alcanza solo quien tiene alcance total)."""
    with Session(engine) as s:
        q = select(ListaSindicato).where(ListaSindicato.sindicato_id == sindicato_id)
        if alcance is not None:
            if not alcance:
                return []
            q = q.where(ListaSindicato.seccional_id.in_(list(alcance)))
        listas = s.exec(q.order_by(ListaSindicato.plantilla, ListaSindicato.nombre)).all()
        secs = {x.id: x.nombre for x in s.exec(select(Seccional).where(Seccional.sindicato_id == sindicato_id)).all()}
        return [_lista_a_dict(l, secs.get(l.seccional_id, "")) for l in listas]


def lista_del_sindicato(sindicato_id: int, lista_id: int) -> Optional[dict]:
    with Session(engine) as s:
        l = s.get(ListaSindicato, lista_id)
        if not l or l.sindicato_id != sindicato_id:
            return None
        sec = s.get(Seccional, l.seccional_id) if l.seccional_id else None
        return _lista_a_dict(l, sec.nombre if sec else "")


def reemplazar_lista(sindicato_id: int, plantilla: str, nombre: str, seccional_id: Optional[int],
                     columnas: list, filas: list, archivo: str, quien: str) -> int:
    """Crea la lista o la REEMPLAZA entera (misma plantilla + nombre +
    seccional), en una transacción: si algo falla a mitad, la lista anterior
    queda como estaba."""
    with Session(engine) as s:
        l = s.exec(select(ListaSindicato).where(
            ListaSindicato.sindicato_id == sindicato_id, ListaSindicato.plantilla == plantilla,
            ListaSindicato.nombre == nombre, ListaSindicato.seccional_id == seccional_id)).first()
        if l:
            s.exec(sa_delete(FilaLista).where(FilaLista.lista_id == l.id))
        else:
            l = ListaSindicato(sindicato_id=sindicato_id, plantilla=plantilla, nombre=nombre, seccional_id=seccional_id)
            s.add(l)
            s.flush()
        l.columnas = columnas
        l.filas = len(filas)
        l.archivo = archivo[:200]
        l.cargada_en = fechas.ahora_texto()
        l.cargada_por = quien
        s.add_all(FilaLista(lista_id=l.id, clave1=f["clave1"], clave2=f.get("clave2") or "", datos=f["datos"]) for f in filas)
        s.add(l)
        s.commit()
        return l.id


def borrar_lista(sindicato_id: int, lista_id: int) -> bool:
    with Session(engine) as s:
        l = s.get(ListaSindicato, lista_id)
        if not l or l.sindicato_id != sindicato_id:
            return False
        s.exec(sa_delete(FilaLista).where(FilaLista.lista_id == lista_id))
        s.delete(l)
        s.commit()
        return True


def filas_de_lista(lista_id: int, limite: Optional[int] = 200) -> list:
    with Session(engine) as s:
        q = select(FilaLista).where(FilaLista.lista_id == lista_id).order_by(FilaLista.id)
        if limite:
            q = q.limit(limite)
        return [f.datos for f in s.exec(q).all()]


def buscar_en_lista(sindicato_id: int, plantilla: str, clave1: str, clave2: str = "",
                    seccional_id: Optional[int] = None, nombre: Optional[str] = None) -> Optional[dict]:
    """La fila que coincide, o None. Busca en las listas de esa plantilla del
    sindicato que valgan para todos (sin seccional) o para `seccional_id`;
    con `nombre`, solo en esa. Es lo que van a usar las validaciones de
    fuente `funcion` (bloque 3)."""
    with Session(engine) as s:
        q = select(ListaSindicato.id).where(ListaSindicato.sindicato_id == sindicato_id,
                                            ListaSindicato.plantilla == plantilla)
        if nombre:
            q = q.where(ListaSindicato.nombre == nombre)
        ids = [i for i in s.exec(q).all()]
        if not ids:
            return None
        q = select(FilaLista).where(FilaLista.lista_id.in_(ids), FilaLista.clave1 == cuit.normalizar(clave1),
                                    FilaLista.clave2 == (clave2 or ""))
        for f in s.exec(q).all():
            l = s.get(ListaSindicato, f.lista_id)
            if l.seccional_id is None or l.seccional_id == seccional_id:
                return dict(f.datos)
        return None


def contexto_validaciones(sindicato_id: int, cuil: str, tipo: dict, valores: dict = None) -> dict:
    """Lo que las validaciones de fuente `funcion` miran fuera del formulario
    (PLAN_LISTAS_VALIDACIONES.md, bloque 3), para `cuil` en este sindicato:

    - `sistema`: los datos del padrón que nombra `validaciones_tramite.DATOS_SISTEMA`.
    - `buscar(plantilla, clave2)`: la fila de la lista, YA TRAÍDA. Las
      búsquedas que el envío necesita salen de `busquedas_necesarias` y se
      hacen acá, antes de evaluar, con el CUIL de la SESIÓN como primera
      clave siempre (nunca uno que venga del formulario). Así la evaluación
      queda pura y el request no abre una sesión adentro de otra.

    Un CUIL que no está en este padrón devuelve `en_padron=False` y lo
    demás vacío: una validación que lo mire no pasa, no revienta."""
    from sqlalchemy import func
    import validaciones_tramite as _vt
    valores = valores or {}
    cuil = cuit.normalizar(cuil) or (cuil or "")
    with Session(engine) as s:
        t = s.exec(select(Trabajador).where(
            Trabajador.cuil == cuil, Trabajador.sindicato_id == sindicato_id)).first()
        c = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first()
        sec = s.get(Seccional, t.seccional_id) if t and t.seccional_id else None
        recibos = s.exec(select(func.count(ReciboVerificado.id)).where(
            ReciboVerificado.sindicato_id == sindicato_id,
            ReciboVerificado.cuil == cuil)).one()
        semaforo = (t.semaforo_datos or {}).get("color") if t else None
        hoy = fechas.hoy_texto()
        # La credencial: generada y, si el admin le puso vigencia, no vencida
        # (sin fecha, vigente: es lo que muestra la app). Decisión de SDN,
        # 2026-10-18.
        credencial = bool(t and t.codigo_credencial and (not t.vigencia_credencial or t.vigencia_credencial >= hoy))
        ultimo = s.exec(select(ReciboVerificado).where(
            ReciboVerificado.cuil == cuil, ReciboVerificado.sindicato_id == sindicato_id)
            .order_by(ReciboVerificado.periodo.desc(), ReciboVerificado.procesado_en.desc()).limit(1)).first()
        empleador = None
        if t and t.cuit_empleador:
            empleador = s.exec(select(Empleador).where(
                Empleador.sindicato_id == sindicato_id, Empleador.cuit == t.cuit_empleador)).first()
        abiertos_todos = s.exec(select(func.count(Tramite.id)).where(
            Tramite.sindicato_id == sindicato_id, Tramite.cuil == cuil,
            Tramite.estado != "terminado")).one() or 0
        ultimo_pedido = None
        if tipo.get("id"):
            ultimo_pedido = s.exec(select(Tramite.creado).where(
                Tramite.sindicato_id == sindicato_id, Tramite.cuil == cuil,
                Tramite.tipo_tramite_id == tipo["id"]).order_by(Tramite.creado.desc()).limit(1)).first()
        # "Una sola vez" / "no repetir mientras haya uno abierto": cuenta los
        # pedidos de ESTE formulario del afiliado. Un tipo sin id (el banco
        # de pruebas con un formulario sin guardar) no tiene pedidos.
        de_este_tipo = abiertos = 0
        if tipo.get("id"):
            de_este_tipo = s.exec(select(func.count(Tramite.id)).where(
                Tramite.sindicato_id == sindicato_id, Tramite.cuil == cuil,
                Tramite.tipo_tramite_id == tipo["id"])).one() or 0
            abiertos = s.exec(select(func.count(Tramite.id)).where(
                Tramite.sindicato_id == sindicato_id, Tramite.cuil == cuil,
                Tramite.tipo_tramite_id == tipo["id"], Tramite.estado != "terminado")).one() or 0
        sistema = {
            "nombre": (c.nombre or None) if c else None,
            "cuil": cuil or None,
            "en_padron": t is not None,
            "activo": bool(t and t.activo),
            "registrado": bool(t and t.registrado),
            "seccional": sec.nombre if sec else None,
            "provincia": (c.provincia or None) if c else None,
            "localidad": (c.localidad or None) if c else None,
            "nivel_fiabilidad": float(c.nivel_fiabilidad or 1) if (c and c.clave_hash) else None,
            "recibos_verificados": float(recibos or 0),
            "semaforo": semaforo or None,
            "fecha_afiliacion": (t.fecha_afiliacion or None) if t else None,
            "fecha_nacimiento": (c.fecha_nacimiento or None) if c else None,
            "tramites_de_este_tipo": float(de_este_tipo),
            "tramites_abiertos_de_este_tipo": float(abiertos),
            "credencial_vigente": credencial,
            "numero_credencial": (t.codigo_credencial or None) if t else None,
            "edad": _vt.anios_cumplidos(c.fecha_nacimiento) if c else None,
            "antiguedad_meses": _vt.meses_cumplidos(t.fecha_afiliacion) if t else None,
            "ultimo_recibo_periodo": (ultimo.periodo or None) if ultimo else None,
            "meses_sin_recibo": _vt.meses_cumplidos(ultimo.periodo) if ultimo else None,
            "ultimo_recibo_bruto": (float(ultimo.bruto) if ultimo.bruto is not None else None) if ultimo else None,
            "empleador_cuit": (t.cuit_empleador or None) if t else None,
            "empleador_nombre": (empleador.razon_social or None) if empleador else None,
            "tramites_abiertos": float(abiertos_todos),
            "dias_desde_ultimo_pedido_de_este_tipo": (
                (fechas.hoy() - date.fromisoformat(ultimo_pedido[:10])).days
                if ultimo_pedido and _vt._RE_FECHA.match(ultimo_pedido[:10]) else None),
        }
        seccional_id = t.seccional_id if t else None
    filas = {}
    for plantilla, clave2 in _vt.busquedas_necesarias(tipo.get("campos"), tipo.get("requisitos"), valores):
        filas[(plantilla, clave2)] = buscar_en_lista(sindicato_id, plantilla, cuil, clave2,
                                                    seccional_id=seccional_id)
    return {"sistema": sistema, "buscar": lambda plantilla, clave2: filas.get((plantilla, clave2)),
            "cuil": cuil}


def quien_es_usuario_sindicato(usuario_id: int) -> str:
    """«Nombre (CUIT)» del usuario del panel, para dejar escrito quién cargó
    una lista. Vacío si no existe."""
    with Session(engine) as s:
        u = s.get(UsuarioSindicato, usuario_id)
        if not u:
            return ""
        return f"{u.nombre} ({u.usuario})" if u.nombre else u.usuario


# =====================================================================
# Fiesta de Fin de Año: entradas con pago por MercadoPago (PLAN_FIESTA.md)
# =====================================================================
# Subproducto aparte, en Herramientas de /entornos. Las reglas puras (cupo,
# topes, ventana de la entrada, CSV) viven en fiesta.py; acá los modelos y el
# acceso a datos. Toda función RECIBE la sesión: una sesión por request.
from fastapi import HTTPException
import fiesta

class FiestaEvento(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nombre: str = ""
    fecha_hora: str = ""                  # ISO "2026-11-14T21:00"
    lugar: str = ""
    direccion: str = ""                   # dirección del lugar (para el mapa)
    leyenda_ticket: str = ""              # texto libre del ticket
    precio: int = 0                       # pesos por entrada
    tope_por_afiliado: int = 4
    tope_general: int = 1000
    horas_antes: int = 24                 # la entrada se habilita tantas horas antes
    minutos_vencimiento: int = 30         # lo que dura una reserva sin pagar (D3)
    leyenda_cortesia: str = "Invitado Especial"
    activo: bool = Field(default=True, index=True)
    creado: str = Field(default_factory=fechas.ahora_con_segundos)
    foto_datos: Optional[bytes] = Field(default=None, sa_column=Column(_LargeBinary, nullable=True))
    foto_mime: str = ""


class FiestaPadron(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("evento_id", "legajo", name="uq_fiestapadron_evento_legajo"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    evento_id: int = Field(index=True)
    legajo: str = ""
    dni: str = Field(default="", index=True)       # solo dígitos
    nombre: str = ""
    mail: str = ""
    activo: bool = True
    creado: str = Field(default_factory=fechas.ahora_con_segundos)


class FiestaReserva(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    evento_id: int = Field(index=True)
    padron_id: Optional[int] = Field(default=None, index=True)
    tipo: str = "afiliado"                # afiliado | cortesia
    legajo: str = ""
    dni: str = Field(default="", index=True)
    nombre: str = ""                      # copia del padrón o de la cortesía
    cantidad: int = 1
    importe: int = 0
    estado: str = Field(default="pendiente", index=True)   # pendiente|pagada|vencida|anulada
    creada: str = Field(default_factory=fechas.ahora_con_segundos)
    vence: str = ""                       # vacío en cortesías
    pagada_en: str = ""
    mp_preference_id: str = ""
    mp_init_point: str = ""               # el checkout real que devolvió MercadoPago
    mp_payment_id: str = Field(default="", index=True)
    mp_estado: str = ""
    sobrecupo: bool = False               # D9: pagó después de vencer y ya no había lugar
    token: str = Field(default="", sa_column_kwargs={"unique": True})
    ingresados: int = 0
    ultimo_ingreso: str = ""
    nota: str = ""
    leyenda: str = ""                     # la de la cortesía
    emitida_por: str = ""


class FiestaIngreso(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    reserva_id: int = Field(index=True)
    cuando: str = Field(default_factory=fechas.ahora_con_segundos)
    cantidad: int = 0
    modo: str = "qr"                      # qr | documento
    quien: str = ""
    motivo: str = ""


class FiestaOperador(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("evento_id", "usuario", name="uq_fiestaoperador_evento_usuario"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    evento_id: int = Field(index=True)
    usuario: str = ""
    nombre: str = ""
    clave_hash: str = ""
    rol: str = "puerta"                   # admin | puerta
    activo: bool = True
    creado: str = Field(default_factory=fechas.ahora_con_segundos)
    debe_cambiar_clave: bool = True


class FiestaAvisoPago(SQLModel, table=True):
    """Cada aviso de MercadoPago (o del simulado) que llegó: la idempotencia y
    la prueba de qué pasó con cada pago."""
    id: Optional[int] = Field(default=None, primary_key=True)
    evento_id: int = Field(index=True)
    mp_payment_id: str = Field(default="", index=True)
    accion: str = ""                      # el status del pago: approved, rejected...
    recibido: str = Field(default_factory=fechas.ahora_con_segundos)
    cuerpo: dict = Field(default={}, sa_column=Column(JSON_TIPO, nullable=False))
    procesado: bool = False
    resultado: str = ""


def fiesta_evento_activo(s: Session) -> Optional[FiestaEvento]:
    """El evento que muestran las dos apps (la tabla admite varios; se ve el
    activo más nuevo). Sin los bytes de la foto."""
    return s.exec(select(FiestaEvento).options(*_sin_bytes(FiestaEvento))
                  .where(FiestaEvento.activo == True)       # noqa: E712
                  .order_by(FiestaEvento.id.desc())).first()


def fiesta_tiene_foto(s: Session, evento_id: int) -> bool:
    from sqlalchemy import func
    n = s.exec(select(func.coalesce(func.octet_length(FiestaEvento.foto_datos), 0))
               .where(FiestaEvento.id == evento_id)).first()
    return bool(n)


def fiesta_evento_dict(s: Session, e: FiestaEvento) -> dict:
    return {"id": e.id, "nombre": e.nombre, "fecha_hora": e.fecha_hora,
            "fecha_texto": fiesta.fecha_texto(e.fecha_hora), "lugar": e.lugar,
            "direccion": e.direccion or "", "url_mapa": fiesta.url_mapa(e.lugar, e.direccion),
            "leyenda_ticket": e.leyenda_ticket, "precio": e.precio,
            "tope_por_afiliado": e.tope_por_afiliado, "tope_general": e.tope_general,
            "horas_antes": e.horas_antes, "minutos_vencimiento": e.minutos_vencimiento,
            "leyenda_cortesia": e.leyenda_cortesia,
            "foto": fiesta_tiene_foto(s, e.id)}


def fiesta_vencer_pendientes(s: Session, evento_id: int, commit: bool = True) -> int:
    """Vencimiento perezoso: pasa a `vencida` toda pendiente cuyo `vence` ya
    pasó. Se llama antes de contar o listar, así no hace falta un proceso.
    Con `commit=False` no suelta el lock del evento (lo usan las altas)."""
    r = s.exec(text(
        "UPDATE fiestareserva SET estado = 'vencida' WHERE evento_id = :e "
        "AND estado = 'pendiente' AND vence <> '' AND vence < :ahora"
    ).bindparams(e=evento_id, ahora=fiesta.sello()))
    if commit:
        s.commit()
    return r.rowcount or 0


def _fiesta_activas(s: Session, evento_id: int, padron_id: int = None) -> list:
    q = select(FiestaReserva.cantidad, FiestaReserva.estado, FiestaReserva.vence).where(
        FiestaReserva.evento_id == evento_id,
        FiestaReserva.estado.in_(("pendiente", "pagada")))
    if padron_id is not None:
        q = q.where(FiestaReserva.padron_id == padron_id)
    return [{"cantidad": c, "estado": est, "vence": v} for c, est, v in s.exec(q).all()]


def fiesta_disponibles(s: Session, evento: FiestaEvento, padron_id: int = None) -> int:
    """Lo que queda del tope general (o del tope del afiliado si se pasa su
    padron_id). Vence primero lo que haya que vencer."""
    fiesta_vencer_pendientes(s, evento.id)
    if padron_id is None:
        return fiesta.disponibles(evento.tope_general, _fiesta_activas(s, evento.id))
    return fiesta.disponibles_afiliado(evento.tope_por_afiliado, _fiesta_activas(s, evento.id, padron_id))


def fiesta_crear_reserva(s: Session, evento: FiestaEvento, padron: FiestaPadron,
                         cantidad: int) -> FiestaReserva:
    """Cuenta y descuenta en LA MISMA transacción, con el evento bloqueado
    (SELECT ... FOR UPDATE): dos personas reservando las últimas entradas a la
    vez no pueden pasarse del tope. Lanza E-FIESTA-02 (sin cupo general) o
    E-FIESTA-03 (pasa el tope del afiliado)."""
    n = fiesta.cantidad_valida(cantidad)
    if not n:
        raise HTTPException(400, "Elegí cuántas entradas querés reservar.")
    evento_id, precio, minutos = evento.id, evento.precio, evento.minutos_vencimiento
    padron_id, legajo, dni, nombre = padron.id, padron.legajo, padron.dni, padron.nombre
    s.commit()                            # cierra lo anterior: el lock arranca limpio
    bloqueado = s.exec(select(FiestaEvento).options(*_sin_bytes(FiestaEvento))
                       .where(FiestaEvento.id == evento_id).with_for_update()).one()
    fiesta_vencer_pendientes(s, evento_id, commit=False)
    if n > fiesta.disponibles_afiliado(bloqueado.tope_por_afiliado,
                                       _fiesta_activas(s, evento_id, padron_id)):
        s.rollback()
        raise errores.ErrorApp("E-FIESTA-03")
    if n > fiesta.disponibles(bloqueado.tope_general, _fiesta_activas(s, evento_id)):
        s.rollback()
        raise errores.ErrorApp("E-FIESTA-02")
    r = FiestaReserva(evento_id=evento_id, padron_id=padron_id, tipo="afiliado",
                      legajo=legajo, dni=dni, nombre=nombre,
                      cantidad=n, importe=precio * n, estado="pendiente",
                      vence=fiesta.vence_en(minutos), token=fiesta.nuevo_token())
    s.add(r)
    s.commit()
    s.refresh(r)
    return r


def fiesta_crear_cortesia(s: Session, evento: FiestaEvento, nombre: str, dni: str,
                          cantidad: int, leyenda: str, quien: str) -> FiestaReserva:
    """Entrada de cortesía (D7): descuenta del tope general, no pasa por MP.
    Nace pagada, importe 0 y sin vencimiento."""
    n = fiesta.cantidad_valida(cantidad)
    if not n:
        raise HTTPException(400, "Indicá cuántas entradas.")
    evento_id = evento.id
    s.commit()
    bloqueado = s.exec(select(FiestaEvento).options(*_sin_bytes(FiestaEvento))
                       .where(FiestaEvento.id == evento_id).with_for_update()).one()
    fiesta_vencer_pendientes(s, evento_id, commit=False)
    if n > fiesta.disponibles(bloqueado.tope_general, _fiesta_activas(s, evento_id)):
        s.rollback()
        raise errores.ErrorApp("E-FIESTA-02")
    r = FiestaReserva(evento_id=evento_id, padron_id=None, tipo="cortesia", dni=dni,
                      nombre=nombre, cantidad=n, importe=0, estado="pagada",
                      pagada_en=fiesta.sello(), vence="", token=fiesta.nuevo_token(),
                      leyenda=(leyenda or "").strip() or bloqueado.leyenda_cortesia
                      or fiesta.LEYENDA_CORTESIA, emitida_por=quien)
    s.add(r)
    s.commit()
    s.refresh(r)
    return r


def fiesta_aplicar_pago(s: Session, evento: FiestaEvento, reserva_id: int, pago: dict) -> dict:
    """Aplica un pago a una reserva (lo llaman el webhook y el simulado, por el
    MISMO camino). `pago`: {id, status, external_reference, transaction_amount}.
    Idempotente: cada aviso queda en FiestaAvisoPago y el mismo (pago, estado)
    ya procesado no hace nada. Devuelve {"resultado", "estado"}.

    - approved -> pagada. Si estaba vencida o anulada se toma igual (D9: la
      persona pagó, nunca se pierde un pago) y, si con eso se pasa el tope
      general, queda `sobrecupo`.
    - El monto tiene que coincidir con el importe: si no, se registra y NO se
      marca pagada.
    - rejected / cancelled / pending: la reserva sigue pendiente hasta que venza."""
    evento_id = evento.id
    payment_id = str(pago.get("id", ""))
    status = str(pago.get("status", ""))
    s.commit()
    # Mismo orden de bloqueo que crear_reserva: primero el evento, después la reserva.
    s.exec(select(FiestaEvento.id).where(FiestaEvento.id == evento_id).with_for_update()).first()
    previo = s.exec(select(FiestaAvisoPago).where(
        FiestaAvisoPago.evento_id == evento_id, FiestaAvisoPago.mp_payment_id == payment_id,
        FiestaAvisoPago.accion == status, FiestaAvisoPago.procesado == True)).first()   # noqa: E712
    if previo:
        s.rollback()
        return {"resultado": "duplicado", "estado": None}
    aviso = FiestaAvisoPago(evento_id=evento_id, mp_payment_id=payment_id, accion=status,
                            cuerpo={k: pago.get(k) for k in
                                    ("id", "status", "external_reference", "transaction_amount")})
    s.add(aviso)
    r = s.exec(select(FiestaReserva).where(
        FiestaReserva.id == reserva_id, FiestaReserva.evento_id == evento_id).with_for_update()).first()
    if not r:
        aviso.resultado, aviso.procesado = "reserva inexistente", True
        s.commit()
        return {"resultado": "reserva inexistente", "estado": None}
    r.mp_estado = status
    if status == "approved":
        try:
            monto_ok = abs(float(pago.get("transaction_amount") or 0) - float(r.importe)) < 0.01
        except (TypeError, ValueError):
            monto_ok = False
        if not monto_ok:
            aviso.resultado = "monto distinto: no se marcó pagada"
        elif r.estado == "pagada":
            if r.mp_payment_id and payment_id and r.mp_payment_id != payment_id:
                # Segundo pago aprobado sobre la misma reserva: no cambia el estado,
                # pero el sindicato tiene que verlo para devolverlo.
                aviso.resultado = "duplicado"
                r.nota = (r.nota + " | " if r.nota else "") + \
                    f"Pago duplicado {payment_id}: devolver desde MercadoPago"
            else:
                aviso.resultado = "ya estaba pagada"
        else:
            tarde = r.estado in ("vencida", "anulada")
            if tarde:
                en_uso = fiesta.ocupadas(_fiesta_activas(s, evento_id))
                tope = s.exec(select(FiestaEvento.tope_general).where(FiestaEvento.id == evento_id)).first()
                r.sobrecupo = en_uso + r.cantidad > (tope or 0)
            if r.estado == "anulada":
                r.nota = (r.nota + " | " if r.nota else "") + \
                    "Pago recibido sobre una reserva anulada: revisar o devolver desde MercadoPago"
            r.estado, r.pagada_en, r.mp_payment_id = "pagada", fiesta.sello(), payment_id or r.mp_payment_id
            aviso.resultado = "pagada tarde (D9)" if tarde else "pagada"
    else:
        aviso.resultado = f"estado {status or '?'}: la reserva sigue como estaba"
    aviso.procesado = True
    s.add(r)
    s.commit()
    return {"resultado": aviso.resultado, "estado": r.estado}


def fiesta_anular_reserva(s: Session, reserva: FiestaReserva) -> None:
    reserva.estado = "anulada"
    s.add(reserva)
    s.commit()


def fiesta_registrar_ingreso(s: Session, reserva_id: int, cantidad: Optional[int],
                             modo: str, quien: str, motivo: str = "") -> dict:
    """Marca el ingreso de N personas de una reserva pagada (o cortesía), con
    la reserva bloqueada para que dos puertas no la cuenten dos veces.
    E-FIESTA-09 si no está pagada, E-FIESTA-08 si ya entraron todos."""
    s.commit()
    r = s.exec(select(FiestaReserva).where(FiestaReserva.id == reserva_id).with_for_update()).first()
    if not r:
        raise HTTPException(404, "No existe esa reserva.")
    if r.estado != "pagada":
        s.rollback()
        raise errores.ErrorApp("E-FIESTA-09")
    faltan = r.cantidad - r.ingresados
    if faltan <= 0:
        s.rollback()
        raise errores.ErrorApp("E-FIESTA-08")
    n = faltan if cantidad in (None, 0) else fiesta.cantidad_valida(cantidad)
    if not n:
        s.rollback()
        raise HTTPException(400, "Indicá cuántas personas ingresan.")
    if n > faltan:
        s.rollback()
        raise HTTPException(400, f"Solo faltan ingresar {faltan}.")
    ya = r.ingresados
    r.ingresados += n
    r.ultimo_ingreso = fiesta.sello()
    s.add(r)
    s.add(FiestaIngreso(reserva_id=r.id, cantidad=n, modo=modo, quien=quien,
                        motivo=(motivo or "").strip()))
    s.commit()
    s.refresh(r)
    return {"ya_ingresados": ya, "ingresaron": n, "faltan": r.cantidad - r.ingresados,
            "reserva": fiesta_reserva_dict(r)}


def fiesta_reserva_dict(r: FiestaReserva, evento: FiestaEvento = None) -> dict:
    d = {"id": r.id, "numero": fiesta.numero_reserva(r.id), "tipo": r.tipo, "legajo": r.legajo,
         "dni": r.dni, "nombre": r.nombre, "cantidad": r.cantidad, "importe": r.importe,
         "estado": r.estado, "creada": r.creada, "vence": r.vence, "pagada_en": r.pagada_en,
         "mp_estado": r.mp_estado, "sobrecupo": r.sobrecupo, "ingresados": r.ingresados,
         "ultimo_ingreso": r.ultimo_ingreso, "nota": r.nota,
         "leyenda": fiesta.leyenda_entrada(r.tipo, r.leyenda), "emitida_por": r.emitida_por}
    if evento is not None:
        hab, desde = fiesta.ventana_entrada(evento.fecha_hora, evento.horas_antes)
        d["entrada_habilitada"] = hab and r.estado == "pagada"
        d["entrada_desde"] = fiesta.fecha_texto(desde)
        d["horas_antes"] = evento.horas_antes
    return d


def fiesta_reservas_del_padron(s: Session, evento_id: int, padron_id: int) -> list:
    return list(s.exec(select(FiestaReserva).where(
        FiestaReserva.evento_id == evento_id, FiestaReserva.padron_id == padron_id)
        .order_by(FiestaReserva.id.desc())).all())


def fiesta_listar_reservas(s: Session, evento_id: int, estado: str = "", tipo: str = "",
                           q: str = "", ingreso: str = "todas") -> list:
    fiesta_vencer_pendientes(s, evento_id)
    cond = [FiestaReserva.evento_id == evento_id]
    if estado in fiesta.ESTADOS:
        cond.append(FiestaReserva.estado == estado)
    if tipo in fiesta.TIPOS:
        cond.append(FiestaReserva.tipo == tipo)
    if ingreso == "si":
        cond.append(FiestaReserva.ingresados > 0)
    elif ingreso == "no":
        cond.append(FiestaReserva.ingresados == 0)
    q = (q or "").strip()
    if q:
        patron = f"%{q}%"
        cond.append(or_(FiestaReserva.nombre.ilike(patron), FiestaReserva.legajo.ilike(patron),
                        FiestaReserva.dni.like(f"%{fiesta.normalizar_dni(q) or q}%")))
    return list(s.exec(select(FiestaReserva).where(*cond).order_by(FiestaReserva.id.desc())).all())


def fiesta_buscar_para_puerta(s: Session, evento_id: int, q: str) -> list:
    """Reservas pagadas y cortesías por DNI, legajo o nombre (D8)."""
    q = (q or "").strip()
    if len(q) < 3:
        return []
    patron = f"%{q}%"
    filas = s.exec(select(FiestaReserva).where(
        FiestaReserva.evento_id == evento_id, FiestaReserva.estado == "pagada",
        or_(FiestaReserva.nombre.ilike(patron), FiestaReserva.legajo.ilike(patron),
            FiestaReserva.dni.like(f"%{fiesta.normalizar_dni(q) or q}%")))
        .order_by(FiestaReserva.nombre).limit(30)).all()
    return list(filas)


def fiesta_contadores(s: Session, evento: FiestaEvento) -> dict:
    from sqlalchemy import func
    fiesta_vencer_pendientes(s, evento.id)
    filas = s.exec(select(FiestaReserva.estado, FiestaReserva.tipo, func.count(),
                          func.coalesce(func.sum(FiestaReserva.cantidad), 0),
                          func.coalesce(func.sum(FiestaReserva.importe), 0),
                          func.coalesce(func.sum(FiestaReserva.ingresados), 0))
                   .where(FiestaReserva.evento_id == evento.id)
                   .group_by(FiestaReserva.estado, FiestaReserva.tipo)).all()
    c = {"tope_general": evento.tope_general, "reservadas": 0, "pagadas": 0, "pendientes": 0,
         "vencidas": 0, "cortesias": 0, "personas_pagadas": 0, "ingresadas": 0,
         "disponibles": 0, "recaudado": 0, "sobrecupo": 0, "padron": 0, "padron_total": 0}
    ocupan = 0
    for estado, tipo, reservas, personas, importe, ingresadas in filas:
        if estado in ("pendiente", "pagada"):
            ocupan += int(personas)
        if estado == "pagada":
            c["personas_pagadas"] += int(personas)
            c["ingresadas"] += int(ingresadas)
            if tipo == "cortesia":
                c["cortesias"] += int(personas)
            else:
                c["pagadas"] += int(reservas)
                c["recaudado"] += int(importe)
        elif estado == "pendiente":
            c["pendientes"] += int(reservas)
        elif estado == "vencida":
            c["vencidas"] += int(reservas)
    c["reservadas"] = ocupan
    c["disponibles"] = max(0, evento.tope_general - ocupan)
    pad = s.exec(select(FiestaPadron.activo, func.count()).where(
        FiestaPadron.evento_id == evento.id).group_by(FiestaPadron.activo)).all()
    for activo, n in pad:
        c["padron_total"] += int(n)
        if activo:
            c["padron"] += int(n)
    c["sobrecupo"] = s.exec(select(func.count()).select_from(FiestaReserva).where(
        FiestaReserva.evento_id == evento.id, FiestaReserva.sobrecupo == True)).one()   # noqa: E712
    return c


def fiesta_padron_por_credenciales(s: Session, evento_id: int, legajo: str, dni: str) -> Optional[FiestaPadron]:
    """Legajo + DNI tienen que coincidir los dos con el padrón activo (D1)."""
    p = s.exec(select(FiestaPadron).where(
        FiestaPadron.evento_id == evento_id, FiestaPadron.legajo == fiesta.normalizar_legajo(legajo),
        FiestaPadron.activo == True)).first()                                          # noqa: E712
    if p and p.dni and fiesta.normalizar_dni(dni) == p.dni:
        return p
    return None


def fiesta_cargar_padron(s: Session, evento_id: int, filas: list) -> dict:
    """Alta o actualización por (evento, legajo). Devuelve {nuevos, actualizados}."""
    nuevos = actualizados = 0
    existentes = {p.legajo: p for p in s.exec(select(FiestaPadron).where(
        FiestaPadron.evento_id == evento_id)).all()}
    for f in filas:
        p = existentes.get(f["legajo"])
        if p:
            # No se reactiva: quien lo desactivó a mano sigue desactivado.
            p.dni, p.nombre, p.mail = f["dni"], f["nombre"], f.get("mail", "")
            actualizados += 1
        else:
            p = FiestaPadron(evento_id=evento_id, legajo=f["legajo"], dni=f["dni"],
                             nombre=f["nombre"], mail=f.get("mail", ""))
            existentes[f["legajo"]] = p
            nuevos += 1
        s.add(p)
    s.commit()
    return {"nuevos": nuevos, "actualizados": actualizados}


def fiesta_operador_por_usuario(s: Session, evento_id: int, usuario: str) -> Optional[FiestaOperador]:
    return s.exec(select(FiestaOperador).where(
        FiestaOperador.evento_id == evento_id,
        FiestaOperador.usuario == (usuario or "").strip().lower())).first()


def fiesta_usuarios_admin(s: Session, evento_id: int) -> list:
    """Los usuarios de los administradores activos del evento, para que la
    tarjeta de Herramientas muestre qué quedó guardado (solo el usuario)."""
    return list(s.exec(select(FiestaOperador.usuario).where(
        FiestaOperador.evento_id == evento_id, FiestaOperador.rol == "admin",
        FiestaOperador.activo == True).order_by(FiestaOperador.id)).all())  # noqa: E712


def fiesta_hay_admin(s: Session, evento_id: int) -> bool:
    return s.exec(select(FiestaOperador.id).where(
        FiestaOperador.evento_id == evento_id, FiestaOperador.rol == "admin",
        FiestaOperador.activo == True)).first() is not None                             # noqa: E712


# =====================================================================
# Mesa de implementación (PLAN_IMPLEMENTACION.md, bloque 1)
# =====================================================================
# Menú Implementación de /entornos: plan operativo (etapas e hitos) y una
# ticketera mínima entre el equipo de Colm3na y el sindicato. Las reglas puras
# (tipos, estados, a quién le toca, permisos de archivos y notas) viven en
# implementacion.py; acá los modelos y el acceso a datos. Toda función RECIBE
# la sesión (una sesión por request) y toda consulta lleva el proyecto: un id
# de otro proyecto devuelve None y la ruta contesta 404.
#
# Son DATOS REALES en Pruebas (I3): las tablas `impl*` no tienen claves
# foráneas hacia el resto (así cargar_demo no las arrastra al borrar un
# sindicato) y clonar_demo_a_pruebas.py las deja fuera del dump.
import implementacion
from sqlalchemy import func, case, update as sa_update


class ImplProyecto(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nombre: str = ""
    sindicato_id: Optional[int] = Field(default=None, index=True)   # puede no existir todavía (I4)
    activo: bool = Field(default=True, index=True)
    ultimo_numero: int = 0                    # el correlativo de tarjetas, bajo FOR UPDATE
    creado: str = Field(default_factory=fechas.ahora_con_segundos)


class ImplUsuario(SQLModel, table=True):
    """Usuario del SINDICATO en la herramienta (I2); el equipo entra con su
    usuario nominal de plataforma."""
    __table_args__ = (UniqueConstraint("proyecto_id", "mail", name="uq_implusuario_proyecto_mail"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    proyecto_id: int = Field(index=True)
    nombre: str = ""
    mail: str = ""
    clave_hash: str = ""
    debe_cambiar_clave: bool = True
    activo: bool = True
    creado: str = Field(default_factory=fechas.ahora_con_segundos)


class ImplEtapa(SQLModel, table=True):
    __table_args__ = (Index("ix_impletapa_proyecto_orden", "proyecto_id", "orden"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    proyecto_id: int = Field(index=True)
    nombre: str = ""
    descripcion: str = ""
    orden: int = 0


class ImplHito(SQLModel, table=True):
    __table_args__ = (Index("ix_implhito_proyecto_etapa", "proyecto_id", "etapa_id", "orden"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    proyecto_id: int = Field(index=True)
    etapa_id: int = Field(index=True)
    texto: str = ""
    orden: int = 0
    hecho: bool = False
    hecho_por: str = ""
    hecho_en: str = ""


class ImplTarjeta(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("proyecto_id", "numero", name="uq_impltarjeta_proyecto_numero"),
        Index("ix_impltarjeta_proyecto_estado", "proyecto_id", "estado"),
        Index("ix_impltarjeta_proyecto_espera", "proyecto_id", "lado_que_espera"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    proyecto_id: int
    numero: int = 0                           # correlativo por proyecto
    tipo: str = "pedido"
    titulo: str = ""
    estado: str = "abierta"
    lado_que_espera: str = ""                 # equipo | sindicato | "" (a nadie)
    etapa_id: Optional[int] = Field(default=None, index=True)
    hito_id: Optional[int] = Field(default=None, index=True)
    responsable_lado: str = ""
    responsable: str = ""                     # nombre, copiado
    fecha_limite: str = ""
    autor_lado: str = ""
    autor_id: int = 0
    autor_nombre: str = ""
    creada: str = Field(default_factory=fechas.ahora_con_segundos)
    actualizada: str = Field(default_factory=fechas.ahora_con_segundos)
    # Resolución de una aprobación: quién y cuándo. Inmutable una vez escrita.
    resuelta_por_lado: str = ""
    resuelta_por_id: int = 0
    resuelta_por_nombre: str = ""
    resuelta_en: str = ""


class ImplMensaje(SQLModel, table=True):
    __table_args__ = (Index("ix_implmensaje_proyecto_tarjeta", "proyecto_id", "tarjeta_id"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    proyecto_id: int
    tarjeta_id: int
    autor_lado: str = ""
    autor_id: int = 0
    autor_nombre: str = ""
    texto: str = ""
    solo_equipo: bool = False                 # nota interna (I8)
    creado: str = Field(default_factory=fechas.ahora_con_segundos)


class ImplArchivo(SQLModel, table=True):
    __table_args__ = (Index("ix_implarchivo_proyecto_tarjeta", "proyecto_id", "tarjeta_id"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    proyecto_id: int
    tarjeta_id: int
    mensaje_id: Optional[int] = Field(default=None, index=True)
    nombre: str = ""
    mime: str = ""
    tamano: int = 0
    datos: Optional[bytes] = Field(default=None, sa_column=Column(_LargeBinary, nullable=True))
    datos_personales: bool = False
    subido_por_lado: str = ""
    subido_por_id: int = 0
    subido_por_nombre: str = ""
    subido_en: str = Field(default_factory=fechas.ahora_con_segundos)
    # Borrado: los bytes se van y queda la constancia (nombre, tamaño, quién).
    borrado_en: str = ""
    borrado_por_lado: str = ""
    borrado_por_id: int = 0
    borrado_por_nombre: str = ""


class ImplEvento(SQLModel, table=True):
    """La traza: no se edita ni se borra (lo imponen los escuchas de abajo)."""
    __table_args__ = (Index("ix_implevento_proyecto_tarjeta", "proyecto_id", "tarjeta_id"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    proyecto_id: int
    tarjeta_id: Optional[int] = None          # vacío en lo que es del proyecto (hitos)
    actor_lado: str = ""
    actor_id: int = 0
    actor_nombre: str = ""
    cuando: str = Field(default_factory=fechas.ahora_con_segundos)
    accion: str = ""
    solo_equipo: bool = False                 # lo que cuenta una nota interna no lo ve el sindicato
    detalle: dict = Field(default={}, sa_column=Column(JSON_TIPO, nullable=False))


class ImplDescarga(SQLModel, table=True):
    __table_args__ = (Index("ix_impldescarga_proyecto_archivo", "proyecto_id", "archivo_id"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    proyecto_id: int
    archivo_id: int
    tarjeta_id: int = 0
    lado: str = ""
    usuario_id: int = 0
    nombre: str = ""
    cuando: str = Field(default_factory=fechas.ahora_con_segundos)


class ImplLecturaAviso(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("tarjeta_id", "lado", "usuario_id", name="uq_impllecturaaviso_persona"),
        Index("ix_impllecturaaviso_proyecto_tarjeta", "proyecto_id", "tarjeta_id"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    proyecto_id: int
    tarjeta_id: int
    lado: str = ""
    usuario_id: int = 0
    nombre: str = ""
    cuando: str = Field(default_factory=fechas.ahora_con_segundos)


# Las tablas del módulo, a la vista de los resguardos de I3 y de su test.
IMPL_TABLAS = tuple(sorted(
    m.__tablename__ for m in (ImplProyecto, ImplUsuario, ImplEtapa, ImplHito, ImplTarjeta,
                              ImplMensaje, ImplArchivo, ImplEvento, ImplDescarga,
                              ImplLecturaAviso)))


def _traza_inmutable(mapper, connection, target):
    raise ValueError(f"{type(target).__name__}: la traza no se edita ni se borra")


for _modelo_traza in (ImplEvento, ImplDescarga):
    event.listen(_modelo_traza, "before_update", _traza_inmutable)
    event.listen(_modelo_traza, "before_delete", _traza_inmutable)


def _impl_actor(actor) -> "implementacion.Actor":
    return actor if isinstance(actor, implementacion.Actor) else implementacion.Actor(*actor)


def _impl_evento(s: Session, proyecto_id: int, actor, accion: str, tarjeta_id: int = None,
                 detalle: dict = None, solo_equipo: bool = False) -> ImplEvento:
    a = _impl_actor(actor)
    ev = ImplEvento(proyecto_id=proyecto_id, tarjeta_id=tarjeta_id, actor_lado=a.lado,
                    actor_id=a.id, actor_nombre=a.nombre, accion=accion,
                    solo_equipo=solo_equipo, detalle=detalle or {})
    s.add(ev)
    return ev


def _impl_tarjeta(s: Session, proyecto_id: int, tarjeta_id: int, bloquear: bool = False) -> Optional[ImplTarjeta]:
    """La tarjeta SOLO si es de ese proyecto."""
    q = select(ImplTarjeta).where(ImplTarjeta.id == tarjeta_id, ImplTarjeta.proyecto_id == proyecto_id)
    if bloquear:
        q = q.with_for_update()
    return s.exec(q).first()


# ---------- Proyecto y etapas ----------
def impl_crear_proyecto(s: Session, nombre: str, actor, sindicato_id: int = None) -> ImplProyecto:
    """Un proyecto con sus seis etapas por defecto (I7). Sin hitos: los carga
    el bloque 4 o el equipo desde la pantalla."""
    nombre = (nombre or "").strip()
    if not nombre:
        raise implementacion.ErrorImpl("nombre", "El proyecto necesita un nombre.")
    p = ImplProyecto(nombre=nombre, sindicato_id=sindicato_id)
    s.add(p)
    s.flush()
    for orden, (n, d) in enumerate(implementacion.FASES_POR_DEFECTO, start=1):
        s.add(ImplEtapa(proyecto_id=p.id, nombre=n, descripcion=d, orden=orden))
    _impl_evento(s, p.id, actor, "crear_proyecto", detalle={"nombre": nombre, "sindicato_id": sindicato_id},
                 solo_equipo=True)
    s.commit()
    s.refresh(p)
    return p


def impl_proyecto(s: Session, proyecto_id: int) -> Optional[ImplProyecto]:
    return s.get(ImplProyecto, proyecto_id)


def impl_etapas(s: Session, proyecto_id: int) -> list:
    return list(s.exec(select(ImplEtapa).where(ImplEtapa.proyecto_id == proyecto_id)
                       .order_by(ImplEtapa.orden, ImplEtapa.id)).all())


def impl_agregar_hito(s: Session, proyecto_id: int, etapa_id: int, texto: str, actor) -> Optional[ImplHito]:
    """Suma un hito al final de la etapa (solo el equipo edita el plan)."""
    a = _impl_actor(actor)
    if a.lado != implementacion.EQUIPO:
        raise implementacion.ErrorImpl("sin_permiso", "El plan lo edita el equipo.")
    et = s.exec(select(ImplEtapa).where(ImplEtapa.id == etapa_id, ImplEtapa.proyecto_id == proyecto_id)).first()
    texto = (texto or "").strip()
    if not et:
        return None
    if not texto:
        raise implementacion.ErrorImpl("texto", "El hito necesita un texto.")
    ultimo = s.exec(select(func.max(ImplHito.orden)).where(ImplHito.etapa_id == etapa_id)).one() or 0
    h = ImplHito(proyecto_id=proyecto_id, etapa_id=etapa_id, texto=texto, orden=ultimo + 1)
    s.add(h)
    s.flush()
    _impl_evento(s, proyecto_id, a, "hito_nuevo", detalle={"hito_id": h.id, "etapa_id": etapa_id, "texto": texto})
    s.commit()
    s.refresh(h)
    return h


def impl_tildar_hito(s: Session, proyecto_id: int, hito_id: int, actor, hecho: bool = True) -> Optional[ImplHito]:
    """Marca o desmarca un hito. Lo pueden hacer los dos lados (el avance se
    sigue juntos); queda quién y cuándo."""
    a = _impl_actor(actor)
    h = s.exec(select(ImplHito).where(ImplHito.id == hito_id, ImplHito.proyecto_id == proyecto_id)
               .with_for_update()).first()
    if not h:
        return None
    if h.hecho != bool(hecho):
        h.hecho = bool(hecho)
        h.hecho_por = a.nombre if hecho else ""
        h.hecho_en = fechas.ahora_con_segundos() if hecho else ""
        s.add(h)
        _impl_evento(s, proyecto_id, a, "hito", detalle={"hito_id": h.id, "hecho": bool(hecho), "texto": h.texto})
    s.commit()
    s.refresh(h)
    return h


def impl_avance(s: Session, proyecto_id: int) -> list:
    """Por etapa: hitos totales y hechos, y el porcentaje; más cuántas
    tarjetas abiertas tiene cada una."""
    hitos = s.exec(select(ImplHito.etapa_id, func.count(), func.sum(case((ImplHito.hecho == True, 1), else_=0)))  # noqa: E712
                   .where(ImplHito.proyecto_id == proyecto_id).group_by(ImplHito.etapa_id)).all()
    por_etapa = {e: (int(t), int(h or 0)) for e, t, h in hitos}
    abiertas = dict(s.exec(select(ImplTarjeta.etapa_id, func.count()).where(
        ImplTarjeta.proyecto_id == proyecto_id, ImplTarjeta.etapa_id.is_not(None),
        ImplTarjeta.estado.in_(implementacion.ESTADOS_ABIERTOS)).group_by(ImplTarjeta.etapa_id)).all())
    salida = []
    for et in impl_etapas(s, proyecto_id):
        total, hechos = por_etapa.get(et.id, (0, 0))
        salida.append({"etapa_id": et.id, "nombre": et.nombre, "orden": et.orden, "total": total,
                       "hechos": hechos, "porcentaje": implementacion.porcentaje(hechos, total),
                       "tarjetas_abiertas": int(abiertas.get(et.id, 0))})
    return salida


# ---------- Tarjetas ----------
def impl_crear_tarjeta(s: Session, proyecto_id: int, actor, tipo: str, titulo: str, texto: str,
                       etapa_id: int = None, hito_id: int = None, responsable: str = "",
                       responsable_lado: str = "", fecha_limite: str = "") -> ImplTarjeta:
    """Crea la tarjeta con su primer mensaje (el texto) y su evento. El número
    correlativo se toma con FOR UPDATE sobre el proyecto. None si el proyecto
    no existe; ErrorImpl si la tarjeta no valida."""
    a = _impl_actor(actor)
    v = implementacion.validar_tarjeta_nueva(tipo, titulo, texto, fecha_limite)
    if not v["ok"]:
        raise implementacion.ErrorImpl("invalida", "; ".join(v["errores"].values()))
    d = v["datos"]
    proy = s.exec(select(ImplProyecto).where(ImplProyecto.id == proyecto_id).with_for_update()).first()
    if not proy:
        return None
    if etapa_id is not None and not s.exec(select(ImplEtapa.id).where(
            ImplEtapa.id == etapa_id, ImplEtapa.proyecto_id == proyecto_id)).first():
        raise implementacion.ErrorImpl("etapa", "La etapa no es de este proyecto.")
    if hito_id is not None:
        h = s.exec(select(ImplHito).where(ImplHito.id == hito_id, ImplHito.proyecto_id == proyecto_id)).first()
        if not h:
            raise implementacion.ErrorImpl("hito", "El hito no es de este proyecto.")
        etapa_id = etapa_id or h.etapa_id
    if responsable_lado and responsable_lado not in implementacion.LADOS:
        raise implementacion.ErrorImpl("responsable", "El responsable no es válido.")
    proy.ultimo_numero += 1
    s.add(proy)
    estado = implementacion.estado_inicial(d["tipo"])
    t = ImplTarjeta(proyecto_id=proyecto_id, numero=proy.ultimo_numero, tipo=d["tipo"], titulo=d["titulo"],
                    estado=estado, lado_que_espera=implementacion.lado_inicial(d["tipo"], a.lado),
                    etapa_id=etapa_id, hito_id=hito_id, responsable_lado=responsable_lado,
                    responsable=(responsable or "").strip(), fecha_limite=d["fecha_limite"],
                    autor_lado=a.lado, autor_id=a.id, autor_nombre=a.nombre)
    s.add(t)
    s.flush()
    m = ImplMensaje(proyecto_id=proyecto_id, tarjeta_id=t.id, autor_lado=a.lado, autor_id=a.id,
                    autor_nombre=a.nombre, texto=d["texto"])
    s.add(m)
    s.flush()
    _impl_evento(s, proyecto_id, a, "crear", t.id,
                 {"numero": t.numero, "tipo": t.tipo, "titulo": t.titulo, "mensaje_id": m.id})
    s.commit()
    s.refresh(t)
    return t


def impl_tarjeta(s: Session, proyecto_id: int, tarjeta_id: int) -> Optional[ImplTarjeta]:
    return _impl_tarjeta(s, proyecto_id, tarjeta_id)


def impl_responder(s: Session, proyecto_id: int, tarjeta_id: int, actor, texto: str = "",
                   estado_nuevo: str = None, solo_equipo: bool = False) -> Optional[ImplMensaje]:
    """Responder y cambiar de estado, UN solo acto: un mensaje (si hay texto),
    el estado nuevo y UN solo evento. Devuelve el mensaje; si solo cambió el
    estado y no hubo texto, un ImplMensaje sin guardar (id None): las rutas
    releen la tarjeta con `impl_tarjeta`.

    Una nota «solo equipo» no cambia estado ni a quién le toca (el sindicato
    no debe notar nada). None si la tarjeta no es de este proyecto."""
    a = _impl_actor(actor)
    t = _impl_tarjeta(s, proyecto_id, tarjeta_id, bloquear=True)
    if not t:
        return None
    texto = (texto or "").strip()
    if len(texto) > implementacion.TOPE_TEXTO:
        raise implementacion.ErrorImpl("texto", f"El texto admite hasta {implementacion.TOPE_TEXTO} caracteres.")
    if t.tipo == implementacion.AVISO:
        raise implementacion.ErrorImpl("aviso", "Un aviso no se responde.")
    if implementacion.es_inmutable(t.tipo, t.estado):
        raise implementacion.ErrorImpl("inmutable", "La aprobación ya está resuelta y no se modifica.")
    if solo_equipo:
        if not implementacion.puede_escribir_nota_interna(a.lado):
            raise implementacion.ErrorImpl("sin_permiso", "Las notas internas son del equipo.")
        if estado_nuevo:
            raise implementacion.ErrorImpl("nota_interna", "Una nota interna no cambia el estado.")
        if not texto:
            raise implementacion.ErrorImpl("texto", "La nota está vacía.")
    if not texto and not estado_nuevo:
        raise implementacion.ErrorImpl("vacio", "Escribí algo o cambiá el estado.")
    estado_ant = t.estado
    if t.estado == implementacion.CERRADA and not (estado_nuevo == implementacion.ABIERTA):
        raise implementacion.ErrorImpl("cerrada", "Está cerrada: reabrila para seguir.")
    if estado_nuevo and estado_nuevo != t.estado:
        if not implementacion.puede_transicionar(t.tipo, t.estado, estado_nuevo):
            raise implementacion.ErrorImpl(
                "transicion", f"No se puede pasar de {implementacion.NOMBRES_ESTADO.get(t.estado)} a "
                              f"{implementacion.NOMBRES_ESTADO.get(estado_nuevo, estado_nuevo)}.")
        t.estado = estado_nuevo
    elif estado_nuevo and estado_nuevo == t.estado and not texto:
        raise implementacion.ErrorImpl("vacio", "Ya está en ese estado.")
    m = ImplMensaje(proyecto_id=proyecto_id, tarjeta_id=t.id, autor_lado=a.lado, autor_id=a.id,
                    autor_nombre=a.nombre, texto=texto, solo_equipo=bool(solo_equipo))
    if texto:
        s.add(m)
        s.flush()
    if not solo_equipo:
        t.lado_que_espera = implementacion.a_quien_le_toca(t.estado, a.lado)
        t.actualizada = fechas.ahora_con_segundos()
        s.add(t)
    _impl_evento(s, proyecto_id, a, "responder", t.id,
                 {"mensaje_id": m.id, "estado_anterior": estado_ant, "estado_nuevo": t.estado,
                  "lado_que_espera": t.lado_que_espera},
                 solo_equipo=bool(solo_equipo))
    s.commit()
    return m


def impl_reasignar(s: Session, proyecto_id: int, tarjeta_id: int, actor, responsable: str,
                   responsable_lado: str) -> Optional[ImplTarjeta]:
    a = _impl_actor(actor)
    t = _impl_tarjeta(s, proyecto_id, tarjeta_id, bloquear=True)
    if not t:
        return None
    if responsable_lado not in implementacion.LADOS:
        raise implementacion.ErrorImpl("responsable", "El responsable no es válido.")
    if implementacion.es_inmutable(t.tipo, t.estado):
        raise implementacion.ErrorImpl("inmutable", "La aprobación ya está resuelta y no se modifica.")
    antes = {"responsable": t.responsable, "responsable_lado": t.responsable_lado}
    t.responsable, t.responsable_lado = (responsable or "").strip(), responsable_lado
    t.actualizada = fechas.ahora_con_segundos()
    s.add(t)
    _impl_evento(s, proyecto_id, a, "reasignar", t.id, {"antes": antes, "despues": {
        "responsable": t.responsable, "responsable_lado": t.responsable_lado}})
    s.commit()
    s.refresh(t)
    return t


def impl_resolver_aprobacion(s: Session, proyecto_id: int, tarjeta_id: int, actor, aprobar: bool,
                             texto: str = "") -> Optional[ImplTarjeta]:
    """Aprueba o rechaza, con quién y cuándo. Resuelve el lado al que le toca
    y queda inmutable: una segunda resolución es ErrorImpl("inmutable")."""
    a = _impl_actor(actor)
    t = _impl_tarjeta(s, proyecto_id, tarjeta_id, bloquear=True)
    if not t:
        return None
    if t.tipo != implementacion.APROBACION:
        raise implementacion.ErrorImpl("tipo", "Esta tarjeta no es una aprobación.")
    if implementacion.es_inmutable(t.tipo, t.estado):
        raise implementacion.ErrorImpl("inmutable", "La aprobación ya está resuelta y no se modifica.")
    if not implementacion.puede_resolver_aprobacion(t.tipo, t.estado, t.lado_que_espera, a.lado):
        raise implementacion.ErrorImpl("sin_permiso", "Esta aprobación la resuelve la otra parte.")
    texto = (texto or "").strip()
    estado_ant = t.estado
    t.estado = implementacion.APROBADA if aprobar else implementacion.RECHAZADA
    t.lado_que_espera = ""
    t.resuelta_por_lado, t.resuelta_por_id, t.resuelta_por_nombre = a.lado, a.id, a.nombre
    t.resuelta_en = fechas.ahora_con_segundos()
    t.actualizada = t.resuelta_en
    s.add(t)
    mid = None
    if texto:
        m = ImplMensaje(proyecto_id=proyecto_id, tarjeta_id=t.id, autor_lado=a.lado, autor_id=a.id,
                        autor_nombre=a.nombre, texto=texto)
        s.add(m)
        s.flush()
        mid = m.id
    _impl_evento(s, proyecto_id, a, "resolver", t.id,
                 {"resultado": t.estado, "estado_anterior": estado_ant, "mensaje_id": mid})
    s.commit()
    s.refresh(t)
    return t


def impl_listar_tarjetas(s: Session, proyecto_id: int, lado: str, estado: str = None, tipo: str = None,
                         etapa_id: int = None, me_toca: bool = False) -> list:
    """Las tarjetas del proyecto, las más recientes primero. `me_toca` deja las
    que esperan a `lado`."""
    q = select(ImplTarjeta).where(ImplTarjeta.proyecto_id == proyecto_id)
    if estado:
        q = q.where(ImplTarjeta.estado == estado)
    if tipo:
        q = q.where(ImplTarjeta.tipo == tipo)
    if etapa_id:
        q = q.where(ImplTarjeta.etapa_id == etapa_id)
    if me_toca:
        q = q.where(ImplTarjeta.lado_que_espera == lado)
    return list(s.exec(q.order_by(ImplTarjeta.actualizada.desc(), ImplTarjeta.id.desc())).all())


def impl_contar_me_toca(s: Session, proyecto_id: int, lado: str) -> int:
    """El globo: tarjetas que esperan a ese lado."""
    return int(s.exec(select(func.count()).select_from(ImplTarjeta).where(
        ImplTarjeta.proyecto_id == proyecto_id, ImplTarjeta.lado_que_espera == lado)).one())


def impl_hilo(s: Session, proyecto_id: int, tarjeta_id: int, lado: str) -> Optional[dict]:
    """La tarjeta con su hilo, sus archivos y su traza, según quién pide. El
    filtro de lo interno va EN LA CONSULTA: para el sindicato las notas «solo
    equipo» (y los archivos y eventos de esas notas) no se traen de la base."""
    t = _impl_tarjeta(s, proyecto_id, tarjeta_id)
    if not t:
        return None
    ve_internas = implementacion.puede_ver_nota_interna(lado)
    qm = select(ImplMensaje).where(ImplMensaje.proyecto_id == proyecto_id, ImplMensaje.tarjeta_id == t.id)
    qa = select(ImplArchivo).options(*_sin_bytes(ImplArchivo)).where(
        ImplArchivo.proyecto_id == proyecto_id, ImplArchivo.tarjeta_id == t.id)
    qe = select(ImplEvento).where(ImplEvento.proyecto_id == proyecto_id, ImplEvento.tarjeta_id == t.id)
    if not ve_internas:
        qm = qm.where(ImplMensaje.solo_equipo == False)                      # noqa: E712
        internos = select(ImplMensaje.id).where(ImplMensaje.proyecto_id == proyecto_id,
                                                ImplMensaje.tarjeta_id == t.id,
                                                ImplMensaje.solo_equipo == True)   # noqa: E712
        qa = qa.where(or_(ImplArchivo.mensaje_id.is_(None), ImplArchivo.mensaje_id.not_in(internos)))
        qe = qe.where(ImplEvento.solo_equipo == False)                       # noqa: E712
    return {
        "tarjeta": t,
        "mensajes": list(s.exec(qm.order_by(ImplMensaje.id)).all()),
        "archivos": list(s.exec(qa.order_by(ImplArchivo.id)).all()),
        "eventos": list(s.exec(qe.order_by(ImplEvento.id)).all()),
    }


def impl_eventos(s: Session, proyecto_id: int, lado: str, tarjeta_id: int = None, limite: int = 200) -> list:
    q = select(ImplEvento).where(ImplEvento.proyecto_id == proyecto_id)
    if tarjeta_id is not None:
        q = q.where(ImplEvento.tarjeta_id == tarjeta_id)
    if not implementacion.puede_ver_nota_interna(lado):
        q = q.where(ImplEvento.solo_equipo == False)                          # noqa: E712
    return list(s.exec(q.order_by(ImplEvento.id.desc()).limit(limite)).all())


def impl_marcar_leido_aviso(s: Session, proyecto_id: int, tarjeta_id: int, actor) -> Optional[ImplLecturaAviso]:
    """Registra que esta persona leyó el aviso (una sola vez por persona)."""
    a = _impl_actor(actor)
    t = _impl_tarjeta(s, proyecto_id, tarjeta_id)
    if not t:
        return None
    if t.tipo != implementacion.AVISO:
        raise implementacion.ErrorImpl("tipo", "Esta tarjeta no es un aviso.")
    previa = s.exec(select(ImplLecturaAviso).where(
        ImplLecturaAviso.tarjeta_id == t.id, ImplLecturaAviso.lado == a.lado,
        ImplLecturaAviso.usuario_id == a.id)).first()
    if previa:
        return previa
    lec = ImplLecturaAviso(proyecto_id=proyecto_id, tarjeta_id=t.id, lado=a.lado, usuario_id=a.id, nombre=a.nombre)
    s.add(lec)
    _impl_evento(s, proyecto_id, a, "leer_aviso", t.id, {})
    s.commit()
    s.refresh(lec)
    return lec


def impl_lecturas_aviso(s: Session, proyecto_id: int, tarjeta_id: int) -> list:
    return list(s.exec(select(ImplLecturaAviso).where(
        ImplLecturaAviso.proyecto_id == proyecto_id, ImplLecturaAviso.tarjeta_id == tarjeta_id)
        .order_by(ImplLecturaAviso.id)).all())


# ---------- Archivos ----------
def impl_subir_archivo(s: Session, proyecto_id: int, tarjeta_id: int, actor, nombre: str, mime: str,
                       datos: bytes, datos_personales: bool = False, mensaje_id: int = None) -> Optional[ImplArchivo]:
    """Guarda el archivo (hasta 20 MB, sin pasar por `imagenes.achicar`: son
    documentos). None si la tarjeta no es de este proyecto."""
    a = _impl_actor(actor)
    t = _impl_tarjeta(s, proyecto_id, tarjeta_id)
    if not t:
        return None
    if implementacion.es_inmutable(t.tipo, t.estado):
        raise implementacion.ErrorImpl("inmutable", "La aprobación ya está resuelta y no se modifica.")
    nombre = implementacion.nombre_seguro(nombre)
    motivo = implementacion.validar_archivo(nombre, len(datos or b""))
    if motivo:
        raise implementacion.ErrorImpl("archivo", motivo)
    interno = False
    if mensaje_id is not None:
        m = s.exec(select(ImplMensaje).where(ImplMensaje.id == mensaje_id, ImplMensaje.proyecto_id == proyecto_id,
                                             ImplMensaje.tarjeta_id == t.id)).first()
        if not m:
            raise implementacion.ErrorImpl("mensaje", "El mensaje no es de esta tarjeta.")
        interno = m.solo_equipo
    arch = ImplArchivo(proyecto_id=proyecto_id, tarjeta_id=t.id, mensaje_id=mensaje_id, nombre=nombre,
                       mime=(mime or "application/octet-stream")[:120], tamano=len(datos), datos=bytes(datos),
                       datos_personales=bool(datos_personales), subido_por_lado=a.lado,
                       subido_por_id=a.id, subido_por_nombre=a.nombre)
    s.add(arch)
    s.flush()
    _impl_evento(s, proyecto_id, a, "subir", t.id,
                 {"archivo_id": arch.id, "nombre": nombre, "tamano": arch.tamano,
                  "datos_personales": bool(datos_personales)}, solo_equipo=interno)
    s.commit()
    s.refresh(arch)
    return arch


def impl_archivo(s: Session, proyecto_id: int, archivo_id: int) -> Optional[ImplArchivo]:
    """El archivo SIN sus bytes (metadatos), solo si es de ese proyecto."""
    return s.exec(select(ImplArchivo).options(*_sin_bytes(ImplArchivo)).where(
        ImplArchivo.id == archivo_id, ImplArchivo.proyecto_id == proyecto_id)).first()


def _impl_archivo_visible(s: Session, arch: ImplArchivo, lado: str) -> bool:
    """Un archivo adjunto a una nota interna no existe para el sindicato."""
    if implementacion.puede_ver_nota_interna(lado) or arch.mensaje_id is None:
        return True
    return s.exec(select(ImplMensaje.id).where(ImplMensaje.id == arch.mensaje_id,
                                               ImplMensaje.solo_equipo == False)).first() is not None   # noqa: E712


def impl_bajar_archivo(s: Session, proyecto_id: int, archivo_id: int, actor) -> Optional[tuple]:
    """(metadatos, bytes) y deja la descarga registrada. None si no existe en
    este proyecto (o es de una nota interna y pide el sindicato); ErrorImpl
    "sin_permiso" si tiene datos personales y no es del equipo ni de quien lo
    subió; "borrado" si ya no está."""
    a = _impl_actor(actor)
    arch = impl_archivo(s, proyecto_id, archivo_id)
    if not arch or not _impl_archivo_visible(s, arch, a.lado):
        return None
    if arch.borrado_en:
        raise implementacion.ErrorImpl("borrado", "El archivo fue borrado.")
    if not implementacion.puede_bajar_archivo(a.lado, a.id, arch.datos_personales, arch.subido_por_lado,
                                              arch.subido_por_id):
        raise implementacion.ErrorImpl("sin_permiso", "Este archivo tiene datos personales y no podés bajarlo.")
    datos = s.exec(select(ImplArchivo.datos).where(ImplArchivo.id == arch.id)).first()
    s.add(ImplDescarga(proyecto_id=proyecto_id, archivo_id=arch.id, tarjeta_id=arch.tarjeta_id,
                       lado=a.lado, usuario_id=a.id, nombre=a.nombre))
    _impl_evento(s, proyecto_id, a, "bajar", arch.tarjeta_id, {"archivo_id": arch.id, "nombre": arch.nombre},
                 solo_equipo=not _impl_archivo_visible(s, arch, implementacion.SINDICATO))
    s.commit()
    return arch, bytes(datos or b"")


def impl_borrar_archivo(s: Session, proyecto_id: int, archivo_id: int, actor) -> Optional[ImplArchivo]:
    """Quita los bytes y deja la constancia (nombre, tamaño, quién lo subió y
    quién lo borró). Lo borra el equipo o quien lo subió."""
    a = _impl_actor(actor)
    arch = s.exec(select(ImplArchivo).options(*_sin_bytes(ImplArchivo)).where(
        ImplArchivo.id == archivo_id, ImplArchivo.proyecto_id == proyecto_id).with_for_update()).first()
    if not arch or not _impl_archivo_visible(s, arch, a.lado):
        return None
    if arch.borrado_en:
        raise implementacion.ErrorImpl("borrado", "El archivo ya estaba borrado.")
    if not implementacion.puede_borrar_archivo(a.lado, a.id, arch.subido_por_lado, arch.subido_por_id):
        raise implementacion.ErrorImpl("sin_permiso", "Solo lo borra quien lo subió o el equipo.")
    s.exec(sa_update(ImplArchivo).where(ImplArchivo.id == arch.id).values(datos=None))
    arch.borrado_en = fechas.ahora_con_segundos()
    arch.borrado_por_lado, arch.borrado_por_id, arch.borrado_por_nombre = a.lado, a.id, a.nombre
    s.add(arch)
    _impl_evento(s, proyecto_id, a, "borrar_archivo", arch.tarjeta_id,
                 {"archivo_id": arch.id, "nombre": arch.nombre, "tamano": arch.tamano},
                 solo_equipo=not _impl_archivo_visible(s, arch, implementacion.SINDICATO))
    s.commit()
    s.refresh(arch)
    return arch


def impl_descargas(s: Session, proyecto_id: int, archivo_id: int) -> list:
    return list(s.exec(select(ImplDescarga).where(
        ImplDescarga.proyecto_id == proyecto_id, ImplDescarga.archivo_id == archivo_id)
        .order_by(ImplDescarga.id)).all())


def impl_carpetas(s: Session, proyecto_id: int, actor, sentido: str) -> list:
    """Entrada = lo que mandó el sindicato; Salida = lo que mandó el equipo.
    Son una vista de los adjuntos (no una carga aparte), ordenada por etapa de
    la tarjeta y después por fecha. Incluye los borrados (la constancia) y
    marca `puede_bajar` según quien mira. Sin bytes."""
    a = _impl_actor(actor)
    if sentido not in ("entrada", "salida"):
        raise implementacion.ErrorImpl("sentido", "La carpeta es entrada o salida.")
    lado_subio = implementacion.SINDICATO if sentido == "entrada" else implementacion.EQUIPO
    q = (select(ImplArchivo, ImplTarjeta, ImplEtapa)
         .options(*_sin_bytes(ImplArchivo))
         .join(ImplTarjeta, ImplTarjeta.id == ImplArchivo.tarjeta_id)
         .join(ImplEtapa, ImplEtapa.id == ImplTarjeta.etapa_id, isouter=True)
         .where(ImplArchivo.proyecto_id == proyecto_id, ImplArchivo.subido_por_lado == lado_subio))
    if not implementacion.puede_ver_nota_interna(a.lado):
        internos = select(ImplMensaje.id).where(ImplMensaje.proyecto_id == proyecto_id,
                                                ImplMensaje.solo_equipo == True)     # noqa: E712
        q = q.where(or_(ImplArchivo.mensaje_id.is_(None), ImplArchivo.mensaje_id.not_in(internos)))
    filas = s.exec(q.order_by(func.coalesce(ImplEtapa.orden, 999), ImplArchivo.id)).all()
    return [{
        "id": ar.id, "subido_lado": ar.subido_por_lado, "mensaje_id": ar.mensaje_id,
        "puede_borrar": (not ar.borrado_en) and implementacion.puede_borrar_archivo(
            a.lado, a.id, ar.subido_por_lado, ar.subido_por_id),
        "archivo_id": ar.id, "nombre": ar.nombre, "mime": ar.mime, "tamano": ar.tamano,
        "datos_personales": ar.datos_personales, "subido_por": ar.subido_por_nombre,
        "subido_en": ar.subido_en, "borrado": bool(ar.borrado_en), "borrado_por": ar.borrado_por_nombre,
        "borrado_en": ar.borrado_en, "tarjeta_id": tj.id, "tarjeta_numero": tj.numero,
        "tarjeta_titulo": tj.titulo, "etapa_id": et.id if et else None, "etapa": et.nombre if et else "",
        "puede_bajar": implementacion.puede_bajar_archivo(
            a.lado, a.id, ar.datos_personales, ar.subido_por_lado, ar.subido_por_id,
            borrado=bool(ar.borrado_en)),
    } for ar, tj, et in filas]


def impl_aprobaciones(s: Session, proyecto_id: int) -> list:
    """El registro: toda tarjeta de aprobación, con su resultado, quién y
    cuándo. Las pendientes salen con su estado abierto."""
    filas = s.exec(select(ImplTarjeta, ImplEtapa).join(ImplEtapa, ImplEtapa.id == ImplTarjeta.etapa_id, isouter=True)
                   .where(ImplTarjeta.proyecto_id == proyecto_id, ImplTarjeta.tipo == implementacion.APROBACION)
                   .order_by(ImplTarjeta.numero)).all()
    return [{"tarjeta_id": t.id, "numero": t.numero, "titulo": t.titulo, "estado": t.estado,
             "autor": t.autor_nombre, "creada": t.creada, "resuelta_por": t.resuelta_por_nombre,
             "resuelta_por_lado": t.resuelta_por_lado, "resuelta_en": t.resuelta_en,
             "etapa": et.nombre if et else ""} for t, et in filas]


# ---------- Usuarios del sindicato en la mesa (bloque 2: acceso, I2) ----------
# El sindicato entra con usuarios PROPIOS de la herramienta (mail + clave), que
# da de alta el equipo. La clave inicial es transitoria: no abre sesión hasta
# que la persona elige la suya. Mismas reglas que el panel del sindicato.
import correo as _correo_impl


class _AuthPerezoso:
    """`auth` exige SESSION_SECRET al importarse; db.py se importa también desde
    scripts y migraciones que no la tienen. Se carga recién al usarlo."""
    def __getattr__(self, nombre):
        import auth
        return getattr(auth, nombre)


_auth_impl = _AuthPerezoso()


def impl_proyectos(s: Session) -> list:
    return list(s.exec(select(ImplProyecto).order_by(ImplProyecto.id)).all())


def impl_usuario(s: Session, proyecto_id: int, usuario_id: int) -> Optional[ImplUsuario]:
    """El usuario SOLO si es de ese proyecto."""
    return s.exec(select(ImplUsuario).where(ImplUsuario.id == usuario_id,
                                            ImplUsuario.proyecto_id == proyecto_id)).first()


def impl_usuarios(s: Session, proyecto_id: int) -> list:
    return list(s.exec(select(ImplUsuario).where(ImplUsuario.proyecto_id == proyecto_id)
                       .order_by(ImplUsuario.id)).all())


def impl_usuario_alta(s: Session, proyecto_id: int, nombre: str, mail: str, clave_inicial: str,
                      actor) -> ImplUsuario:
    """Alta por el equipo: mail único por proyecto, clave transitoria."""
    nombre, mail = (nombre or "").strip(), (mail or "").strip().lower()
    clave = (clave_inicial or "").strip()
    if not nombre:
        raise implementacion.ErrorImpl("nombre", "El usuario necesita un nombre.")
    if not _correo_impl.destino_valido(mail):
        raise implementacion.ErrorImpl("mail", "El mail no es válido.")
    if len(clave) < implementacion.CLAVE_INICIAL_MINIMA:
        raise implementacion.ErrorImpl(
            "clave", f"La clave inicial tiene que tener al menos {implementacion.CLAVE_INICIAL_MINIMA} caracteres.")
    if not s.get(ImplProyecto, proyecto_id):
        raise implementacion.ErrorImpl("proyecto", "El proyecto no existe.")
    if s.exec(select(ImplUsuario.id).where(ImplUsuario.proyecto_id == proyecto_id,
                                           ImplUsuario.mail == mail)).first() is not None:
        raise implementacion.ErrorImpl("mail_repetido", "Ya hay un usuario con ese mail en el proyecto.")
    u = ImplUsuario(proyecto_id=proyecto_id, nombre=nombre, mail=mail,
                    clave_hash=_auth_impl.hashear_clave(clave), debe_cambiar_clave=True, activo=True)
    s.add(u)
    try:
        s.flush()
    except IntegrityError:
        s.rollback()
        raise implementacion.ErrorImpl("mail_repetido", "Ya hay un usuario con ese mail en el proyecto.")
    _impl_evento(s, proyecto_id, actor, "usuario_alta", detalle={"usuario_id": u.id, "mail": mail},
                 solo_equipo=True)
    s.commit()
    s.refresh(u)
    return u


# Hash de relleno: con un mail que no existe se verifica igual contra algo, así
# el tiempo de respuesta no dice si la cuenta existe.
_IMPL_HASH_RELLENO = ""


def _impl_relleno() -> str:
    global _IMPL_HASH_RELLENO
    if not _IMPL_HASH_RELLENO:
        _IMPL_HASH_RELLENO = _auth_impl.hashear_clave(secrets.token_hex(8))
    return _IMPL_HASH_RELLENO


def impl_login(s: Session, mail: str, clave: str) -> Optional[ImplUsuario]:
    """Mail + clave. El mail es único por proyecto, no entre proyectos: si hay
    varios con el mismo mail, entra el primero cuya clave coincide. Devuelve el
    usuario activo (aunque deba cambiar la clave: quien llama decide), o None.
    Re-hashea si el costo del hash quedó viejo."""
    mail = (mail or "").strip().lower()
    clave = (clave or "").strip()
    filas = list(s.exec(select(ImplUsuario).where(ImplUsuario.mail == mail)
                        .order_by(ImplUsuario.id)).all()) if mail else []
    if not filas:
        _auth_impl.verificar_clave(clave, _impl_relleno())
        return None
    for u in filas:
        proyecto = s.get(ImplProyecto, u.proyecto_id)
        if _auth_impl.verificar_clave(clave, u.clave_hash) and u.activo and proyecto and proyecto.activo:
            if _auth_impl.necesita_rehash(u.clave_hash):
                u.clave_hash = _auth_impl.hashear_clave(clave)
                s.add(u)
                s.commit()
                s.refresh(u)
            return u
    return None


def impl_usuario_cambiar_clave(s: Session, usuario_id: int, clave_actual: str, clave_nueva: str) -> Optional[ImplUsuario]:
    """Primer ingreso o cambio propio: verifica la actual, exige la nueva de 8+
    y distinta, y apaga la bandera. None si el usuario no existe / está inactivo
    / la clave actual no es la suya (quien llama distingue con impl_login)."""
    u = s.get(ImplUsuario, usuario_id)
    if not u or not u.activo or not _auth_impl.verificar_clave((clave_actual or "").strip(), u.clave_hash):
        return None
    nueva = (clave_nueva or "").strip()
    if len(nueva) < implementacion.CLAVE_MINIMA:
        raise implementacion.ErrorImpl(
            "clave", f"La clave nueva tiene que tener al menos {implementacion.CLAVE_MINIMA} caracteres.")
    if nueva == (clave_actual or "").strip():
        raise implementacion.ErrorImpl("clave_igual", "Elegí una clave distinta de la actual.")
    u.clave_hash, u.debe_cambiar_clave = _auth_impl.hashear_clave(nueva), False
    s.add(u)
    s.commit()
    s.refresh(u)
    return u


def impl_usuario_restablecer(s: Session, proyecto_id: int, usuario_id: int, actor):
    """Clave transitoria al azar: se devuelve UNA vez junto al usuario y el
    próximo ingreso obliga a elegir una propia. None si no es de ese proyecto."""
    u = impl_usuario(s, proyecto_id, usuario_id)
    if not u:
        return None
    clave = secrets.token_urlsafe(8)
    u.clave_hash, u.debe_cambiar_clave = _auth_impl.hashear_clave(clave), True
    s.add(u)
    _impl_evento(s, proyecto_id, actor, "usuario_clave", detalle={"usuario_id": u.id}, solo_equipo=True)
    s.commit()
    s.refresh(u)
    return u, clave


def impl_usuario_activar(s: Session, proyecto_id: int, usuario_id: int, activo: bool, actor) -> Optional[ImplUsuario]:
    u = impl_usuario(s, proyecto_id, usuario_id)
    if not u:
        return None
    if u.activo != bool(activo):
        u.activo = bool(activo)
        s.add(u)
        _impl_evento(s, proyecto_id, actor, "usuario_estado",
                     detalle={"usuario_id": u.id, "activo": bool(activo)}, solo_equipo=True)
    s.commit()
    s.refresh(u)
    return u


# =====================================================================
# Mesa de implementación: bloques 3 y 4 (vistas, plan editable, exportación)
# =====================================================================
def _impl_like(texto: str) -> str:
    """El patrón de un LIKE con los comodines del usuario neutralizados."""
    limpio = texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{limpio}%"


def impl_buscar_tarjetas(s: Session, proyecto_id: int, lado: str, vista: str = "todas", estado: str = None,
                         tipo: str = None, etapa_id: int = None, q: str = "") -> list:
    """Las tarjetas del proyecto para una vista. `vista="pendientes"` deja las
    que esperan a `lado`. `q` busca en el título, en el número (#12) y en el
    texto de los mensajes: el sindicato SOLO busca en los mensajes que ve (una
    palabra de una nota interna no puede delatar que existe)."""
    consulta = select(ImplTarjeta).where(ImplTarjeta.proyecto_id == proyecto_id)
    if vista == "pendientes":
        consulta = consulta.where(ImplTarjeta.lado_que_espera == lado)
    if estado:
        consulta = consulta.where(ImplTarjeta.estado == estado)
    if tipo:
        consulta = consulta.where(ImplTarjeta.tipo == tipo)
    if etapa_id:
        consulta = consulta.where(ImplTarjeta.etapa_id == etapa_id)
    q = (q or "").strip()[:100]
    if q:
        patron = _impl_like(q)
        condiciones = [ImplTarjeta.titulo.ilike(patron, escape="\\")]
        if q.lstrip("#").isdigit():
            condiciones.append(ImplTarjeta.numero == int(q.lstrip("#")))
        en_mensajes = select(ImplMensaje.tarjeta_id).where(
            ImplMensaje.proyecto_id == proyecto_id, ImplMensaje.texto.ilike(patron, escape="\\"))
        if not implementacion.puede_ver_nota_interna(lado):
            en_mensajes = en_mensajes.where(ImplMensaje.solo_equipo == False)         # noqa: E712
        condiciones.append(ImplTarjeta.id.in_(en_mensajes))
        consulta = consulta.where(or_(*condiciones))
    return list(s.exec(consulta.order_by(ImplTarjeta.actualizada.desc(), ImplTarjeta.id.desc())).all())


def impl_conteos(s: Session, proyecto_id: int, lado: str, tarjeta_ids: list) -> tuple:
    """({tarjeta_id: mensajes}, {tarjeta_id: archivos vigentes}) según quién
    mira: el sindicato no cuenta lo interno."""
    if not tarjeta_ids:
        return {}, {}
    ve = implementacion.puede_ver_nota_interna(lado)
    qm = select(ImplMensaje.tarjeta_id, func.count()).where(
        ImplMensaje.proyecto_id == proyecto_id, ImplMensaje.tarjeta_id.in_(tarjeta_ids))
    qa = select(ImplArchivo.tarjeta_id, func.count()).where(
        ImplArchivo.proyecto_id == proyecto_id, ImplArchivo.tarjeta_id.in_(tarjeta_ids),
        ImplArchivo.borrado_en == "")
    if not ve:
        internos = select(ImplMensaje.id).where(ImplMensaje.proyecto_id == proyecto_id,
                                                ImplMensaje.solo_equipo == True)      # noqa: E712
        qm = qm.where(ImplMensaje.solo_equipo == False)                              # noqa: E712
        qa = qa.where(or_(ImplArchivo.mensaje_id.is_(None), ImplArchivo.mensaje_id.not_in(internos)))
    return (dict(s.exec(qm.group_by(ImplMensaje.tarjeta_id)).all()),
            dict(s.exec(qa.group_by(ImplArchivo.tarjeta_id)).all()))


def impl_resumen(s: Session, proyecto_id: int, lado: str) -> dict:
    """Los indicadores de arriba: pendientes (me tocan), esperan al otro lado,
    con fecha límite y vencidas (solo tarjetas abiertas) y el avance del plan."""
    abiertas = implementacion.ESTADOS_ABIERTOS
    hoy = fechas.hoy_texto()

    def contar(*condiciones) -> int:
        return int(s.exec(select(func.count()).select_from(ImplTarjeta).where(
            ImplTarjeta.proyecto_id == proyecto_id, ImplTarjeta.estado.in_(abiertas), *condiciones)).one())

    etapas = impl_avance(s, proyecto_id)
    total = sum(e["total"] for e in etapas)
    hechos = sum(e["hechos"] for e in etapas)
    return {
        "pendientes": contar(ImplTarjeta.lado_que_espera == lado),
        "esperan_otro": contar(ImplTarjeta.lado_que_espera == implementacion.otro_lado(lado)),
        "con_fecha": contar(ImplTarjeta.fecha_limite != ""),
        "vencidas": contar(ImplTarjeta.fecha_limite != "", ImplTarjeta.fecha_limite < hoy),
        "plan_pct": implementacion.porcentaje(hechos, total),
        "etapas": [{"id": e["etapa_id"], "nombre": e["nombre"], "orden": e["orden"], "total": e["total"],
                    "hechos": e["hechos"], "pct": e["porcentaje"], "tarjetas_abiertas": e["tarjetas_abiertas"]}
                   for e in etapas],
    }


def impl_plan(s: Session, proyecto_id: int) -> list:
    """Etapas con sus hitos y las tarjetas que cuelgan de cada hito."""
    hitos = list(s.exec(select(ImplHito).where(ImplHito.proyecto_id == proyecto_id)
                        .order_by(ImplHito.etapa_id, ImplHito.orden, ImplHito.id)).all())
    tarjetas = {}
    for t in s.exec(select(ImplTarjeta).where(ImplTarjeta.proyecto_id == proyecto_id,
                                              ImplTarjeta.hito_id.is_not(None))
                    .order_by(ImplTarjeta.numero)).all():
        tarjetas.setdefault(t.hito_id, []).append({"numero": t.numero, "titulo": t.titulo, "estado": t.estado})
    por_etapa = {}
    for h in hitos:
        por_etapa.setdefault(h.etapa_id, []).append({
            "id": h.id, "texto": h.texto, "orden": h.orden, "hecho": h.hecho, "hecho_por": h.hecho_por,
            "hecho_en": h.hecho_en, "tarjetas": tarjetas.get(h.id, [])})
    salida = []
    for e in impl_etapas(s, proyecto_id):
        lista = por_etapa.get(e.id, [])
        salida.append({"id": e.id, "nombre": e.nombre, "orden": e.orden,
                       "pct": implementacion.porcentaje(sum(1 for h in lista if h["hecho"]), len(lista)),
                       "hitos": lista})
    return salida


def _impl_exigir_equipo(actor) -> "implementacion.Actor":
    a = _impl_actor(actor)
    if a.lado != implementacion.EQUIPO:
        raise implementacion.ErrorImpl("sin_permiso", "El plan lo edita el equipo.")
    return a


def _impl_hito(s: Session, proyecto_id: int, hito_id: int, bloquear: bool = True) -> Optional[ImplHito]:
    q = select(ImplHito).where(ImplHito.id == hito_id, ImplHito.proyecto_id == proyecto_id)
    return s.exec(q.with_for_update() if bloquear else q).first()


def impl_editar_hito(s: Session, proyecto_id: int, hito_id: int, actor, texto: str = None,
                     orden: int = None) -> Optional[ImplHito]:
    """Cambia el texto y/o la posición (1..n dentro de su etapa). Solo equipo."""
    a = _impl_exigir_equipo(actor)
    h = _impl_hito(s, proyecto_id, hito_id)
    if not h:
        return None
    if texto is not None:
        texto = texto.strip()
        if not texto:
            raise implementacion.ErrorImpl("texto", "El hito necesita un texto.")
        if texto != h.texto:
            h.texto = texto
            s.add(h)
            _impl_evento(s, proyecto_id, a, "hito_editar", detalle={"hito_id": h.id, "texto": texto})
    if orden is not None:
        hermanos = list(s.exec(select(ImplHito).where(ImplHito.proyecto_id == proyecto_id,
                                                      ImplHito.etapa_id == h.etapa_id)
                               .order_by(ImplHito.orden, ImplHito.id)).all())
        hermanos = [x for x in hermanos if x.id != h.id]
        pos = max(1, min(int(orden), len(hermanos) + 1))
        hermanos.insert(pos - 1, h)
        for i, x in enumerate(hermanos, start=1):
            if x.orden != i:
                x.orden = i
                s.add(x)
    s.commit()
    s.refresh(h)
    return h


def impl_borrar_hito(s: Session, proyecto_id: int, hito_id: int, actor) -> bool:
    """Quita el hito (las tarjetas que lo nombraban quedan sin hito) y deja el
    evento con su texto. False si no es de este proyecto."""
    a = _impl_exigir_equipo(actor)
    h = _impl_hito(s, proyecto_id, hito_id)
    if not h:
        return False
    s.exec(sa_update(ImplTarjeta).where(ImplTarjeta.proyecto_id == proyecto_id,
                                        ImplTarjeta.hito_id == h.id).values(hito_id=None))
    _impl_evento(s, proyecto_id, a, "hito_borrar", detalle={"hito_id": h.id, "texto": h.texto})
    s.delete(h)
    s.commit()
    return True


def impl_renombrar_etapa(s: Session, proyecto_id: int, etapa_id: int, actor, nombre: str) -> Optional[ImplEtapa]:
    a = _impl_exigir_equipo(actor)
    et = s.exec(select(ImplEtapa).where(ImplEtapa.id == etapa_id, ImplEtapa.proyecto_id == proyecto_id)
                .with_for_update()).first()
    if not et:
        return None
    nombre = (nombre or "").strip()
    if not nombre or len(nombre) > 80:
        raise implementacion.ErrorImpl("nombre", "La etapa necesita un nombre de hasta 80 caracteres.")
    if nombre != et.nombre:
        _impl_evento(s, proyecto_id, a, "etapa_renombrar", detalle={"etapa_id": et.id, "antes": et.nombre,
                                                                    "despues": nombre})
        et.nombre = nombre
        s.add(et)
    s.commit()
    s.refresh(et)
    return et


def impl_cargar_hitos_semilla(s: Session, proyecto_id: int, actor, fases: list) -> Optional[int]:
    """Carga los hitos de `fases` [(etapa, [textos])] en un proyecto SIN hitos
    (las etapas se emparejan por nombre; una que no existe se crea al final).
    Devuelve cuántos cargó; None si el proyecto no existe."""
    a = _impl_exigir_equipo(actor)
    if not s.exec(select(ImplProyecto).where(ImplProyecto.id == proyecto_id).with_for_update()).first():
        return None
    if s.exec(select(func.count()).select_from(ImplHito).where(ImplHito.proyecto_id == proyecto_id)).one():
        raise implementacion.ErrorImpl("con_hitos", "El proyecto ya tiene hitos: no se pisan.")
    etapas = {e.nombre.strip().lower(): e for e in impl_etapas(s, proyecto_id)}
    cantidad = 0
    for nombre, textos in fases:
        et = etapas.get(nombre.strip().lower())
        if et is None:
            et = ImplEtapa(proyecto_id=proyecto_id, nombre=nombre, orden=len(etapas) + 1)
            s.add(et)
            s.flush()
            etapas[nombre.strip().lower()] = et
        for orden, texto in enumerate(textos, start=1):
            s.add(ImplHito(proyecto_id=proyecto_id, etapa_id=et.id, texto=texto, orden=orden))
            cantidad += 1
    _impl_evento(s, proyecto_id, a, "hitos_semilla", detalle={"cantidad": cantidad})
    s.commit()
    return cantidad


def impl_aprobaciones_registro(s: Session, proyecto_id: int) -> list:
    """`impl_aprobaciones` más el texto con que se resolvió (el mensaje que
    acompañó la aprobación o el rechazo; nunca una nota interna)."""
    filas = impl_aprobaciones(s, proyecto_id)
    ids = [f["tarjeta_id"] for f in filas if f["resuelta_en"]]
    textos = {}
    if ids:
        for ev in s.exec(select(ImplEvento).where(ImplEvento.proyecto_id == proyecto_id,
                                                  ImplEvento.tarjeta_id.in_(ids),
                                                  ImplEvento.accion == "resolver")
                         .order_by(ImplEvento.id)).all():
            mid = (ev.detalle or {}).get("mensaje_id")
            if mid:
                m = s.exec(select(ImplMensaje).where(ImplMensaje.id == mid, ImplMensaje.proyecto_id == proyecto_id,
                                                     ImplMensaje.solo_equipo == False)).first()   # noqa: E712
                if m:
                    textos[ev.tarjeta_id] = m.texto
    for f in filas:
        f["texto"] = textos.get(f["tarjeta_id"], "")
    return filas


def impl_exportacion(s: Session, proyecto_id: int, actor) -> Optional[dict]:
    """Todo lo del proyecto para la exportación (solo equipo): proyecto, etapas,
    hitos, tarjetas, mensajes (internos incluidos), eventos, descargas y la
    lista de archivos SIN bytes. Deja el evento «exportar». None si no existe."""
    a = _impl_exigir_equipo(actor)
    proy = impl_proyecto(s, proyecto_id)
    if not proy:
        return None
    def todo(modelo, orden):
        q = select(modelo).where(modelo.proyecto_id == proyecto_id)
        if modelo is ImplArchivo:
            q = q.options(*_sin_bytes(ImplArchivo))
        return list(s.exec(q.order_by(orden)).all())
    datos = {
        "proyecto": proy, "etapas": impl_etapas(s, proyecto_id),
        "hitos": todo(ImplHito, ImplHito.id), "tarjetas": todo(ImplTarjeta, ImplTarjeta.numero),
        "mensajes": todo(ImplMensaje, ImplMensaje.id), "eventos": todo(ImplEvento, ImplEvento.id),
        "descargas": todo(ImplDescarga, ImplDescarga.id), "archivos": todo(ImplArchivo, ImplArchivo.id),
        "lecturas": todo(ImplLecturaAviso, ImplLecturaAviso.id),
        "aprobaciones": impl_aprobaciones_registro(s, proyecto_id),
    }
    _impl_evento(s, proyecto_id, a, "exportar", detalle={"tarjetas": len(datos["tarjetas"]),
                                                         "archivos": len(datos["archivos"])}, solo_equipo=True)
    s.commit()
    return datos


def impl_bytes_archivo(s: Session, proyecto_id: int, archivo_id: int) -> bytes:
    """Los bytes de un archivo del proyecto (para la exportación; no registra
    una descarga: la exportación entera deja su propio evento)."""
    return bytes(s.exec(select(ImplArchivo.datos).where(
        ImplArchivo.id == archivo_id, ImplArchivo.proyecto_id == proyecto_id)).first() or b"")
