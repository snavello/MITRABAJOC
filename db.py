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
import csv
import json
from pathlib import Path
from typing import Optional
from datetime import date, datetime, timedelta

from dotenv import load_dotenv
from typing import Any
from sqlmodel import SQLModel, Field, create_engine, Session, select, Column, JSON, text
from sqlalchemy import or_, bindparam
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

import encuestas
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
    # Portada del trabajador: oscura (default, regla histórica) o clara.
    # El encabezado (.enc) sigue siendo oscuro en las dos variantes -- lo
    # que cambia es el fondo del cuerpo y las tarjetas. Default False =
    # ningún sindicato existente cambia de aspecto el día del deploy.
    portada_clara: bool = Field(default=False)
    # Portada de /admin (ver admin_portada.html): independiente de la del
    # trabajador -- un sindicato puede querer, por ejemplo, oscura para el
    # trabajador y clara para el admin. Mismo criterio visual, elegida aparte.
    admin_portada_clara: bool = Field(default=False)


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
    clave_hash: str = ""
    debe_cambiar_clave: bool = True             # la primera clave la pone el admin de plataforma
    activo: bool = True
    # Default False a propósito: si alguna alta se olvida de setearlo, el
    # usuario nace SIN poder, no con todo. Los tres lugares que crean Super
    # Admins de verdad (alta desde plataforma, alta desde el propio
    # sindicato, cargar_demo) lo pasan explícito.
    es_super_admin: bool = False
    es_admin_seccional: bool = False
    area_id: Optional[int] = Field(default=None, foreign_key="area.id", index=True)
    seccional_id: Optional[int] = Field(default=None, foreign_key="seccional.id", index=True)


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


class CuentaTrabajador(SQLModel, table=True):
    """La identidad única del trabajador en toda la plataforma: CUIL + clave.
    Con esto entra, sin importar en cuántos sindicatos esté empadronado.
    La foto de perfil vive acá (no en Trabajador, que es por sindicato) --
    es una sola por persona, la misma se ve sin importar el sindicato
    activo. Bytes en la base, mismo patrón que el logo del sindicato."""
    id: Optional[int] = Field(default=None, primary_key=True)
    cuil: str = Field(index=True, unique=True)
    clave_hash: str = ""
    nombre: str = ""
    foto_datos: Optional[bytes] = Field(default=None)
    foto_mime: str = ""


class Trabajador(SQLModel, table=True):
    """Empadronamiento de un CUIL en un sindicato, con sus datos propios de ese gremio.
    El mismo CUIL puede tener varias filas (una por sindicato donde está afiliado).

    **El domicilio usa el MISMO bloque de campos que `Seccional`** (mismos
    nombres, mismos tipos, misma pantalla de carga guiada, misma función de
    geocodificación). Antes del 2026-09-12 eran parecidos pero no iguales:
    acá `piso` y `ciudad`, en la seccional nada. Dos nombres para lo mismo es
    lo que hace que una pantalla arme la dirección distinto que la otra, así
    que se unificaron a `piso_depto` y `localidad` -- un rename, los datos se
    conservan. `test_seccional_geo.py` verifica que el bloque siga siendo
    idéntico en las dos tablas.

    Las coordenadas del domicilio son dato del padrón, del mismo nivel de
    sensibilidad que la dirección que el sindicato ya tenía. No salen nunca
    en un endpoint que no sea del propio afiliado o del padrón de su
    sindicato; en particular NO van al Panel Sindical."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(foreign_key="sindicato.id", index=True)
    cuil: str = Field(index=True)          # obligatorio
    nombre: str = ""                       # obligatorio
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
    mail: str = ""
    # Estado
    registrado: bool = False               # True cuando el CUIL ya creó su cuenta
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
    mail: str = ""
    registrado: bool = False               # True cuando el CUIT ya creó su CuentaEmpleador
    activo: bool = True                    # baja lógica: False = dado de baja (recuperable)


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
    # Hasta 2 imágenes, mismo patrón que el logo del sindicato (bytes en la
    # base, Opción B -- ver Sindicato.logo_datos).
    imagen1_datos: Optional[bytes] = Field(default=None)
    imagen1_mime: str = ""
    imagen2_datos: Optional[bytes] = Field(default=None)
    imagen2_mime: str = ""
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
    cuil: str = ""  # vacío en "aprendizaje" y "prueba": no son de un trabajador puntual
    tipo: str = ""  # "recibo" | "aportes" | "aprendizaje" | "prueba"
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
    # Portada de /plataforma (ver plataforma_portada.html): oscura (default)
    # o clara, mismo criterio que Sindicato.portada_clara -- pero acá NO hay
    # un color_base aparte validado como oscuro, se reusa color_primario tal
    # cual (a diferencia de Sindicato: la plataforma es una única instancia,
    # no multi-tenant, así que no hace falta la misma red de seguridad).
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
    cuit_empleador: str = ""                            # solo dígitos (validador._norm_cuil)
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
    """El recurso entero, bytes incluidos: solo para servirlo."""
    with Session(engine) as s:
        return s.get(Recurso, recurso_id)


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
            sind = s.get(Sindicato, e.sindicato_id)
            if sind and sind.activo:
                resultado.append({"id": sind.id, "nombre": sind.nombre, "slug": sind.slug})
        return resultado


def importar_cuits_de_conceptos(sindicato_id: int) -> int:
    """CUITs distintos de Concepto.cuit_empleador de ESTE sindicato que
    todavía no tienen fila en Empleador -- crea una fila mínima (solo
    cuit) por cada uno, registrado=False, activo=True. Idempotente: se
    puede volver a correr cuando aparezcan CUITs nuevos en Conceptos
    (botón "Importar CUITs de conceptos" en el CRUD). Devuelve cuántos
    se agregaron."""
    with Session(engine) as s:
        conceptos = s.exec(select(Concepto).where(
            Concepto.sindicato_id == sindicato_id)).all()
        cuits_concepto = {
            c.cuit_empleador.strip() for c in conceptos if (c.cuit_empleador or "").strip()
        }
        existentes = {e.cuit for e in s.exec(select(Empleador).where(
            Empleador.sindicato_id == sindicato_id)).all()}
        nuevos = cuits_concepto - existentes
        for cuit in nuevos:
            s.add(Empleador(sindicato_id=sindicato_id, cuit=cuit))
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
    with Session(engine) as s:
        sind = s.get(Sindicato, sindicato_id)
        if not sind:
            return {}
        return {
            "id": sind.id, "nombre": sind.nombre, "logo": sind.logo,
            # Sello de versión (largo del binario) para romper el cache del
            # navegador cuando se reemplaza el logo/firma -- sin esto, /logo/{id}
            # y /firma/{id} son la MISMA url antes y después de subir uno nuevo,
            # y el Cache-Control:max-age=3600 de esas rutas seguía sirviendo la
            # imagen vieja hasta que expiraba solo.
            "logo_v": len(sind.logo_datos or b""), "firma_v": len(sind.firma_datos or b""),
            "color_primario": sind.color_primario,
            "color_secundario": sind.color_secundario,
            "color_acento": sind.color_acento,
            "color_base": sind.color_base,
            "color_destacado": sind.color_destacado or "#E5188F",
            "portada_clara": sind.portada_clara,
            "admin_portada_clara": sind.admin_portada_clara,
            # Para la credencial sindical del trabajador
            "autoridad": sind.autoridad, "cargo_autoridad": sind.cargo_autoridad,
            "firma": sind.firma,
            "direccion": sind.direccion, "telefonos": sind.telefonos,
        }


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
    from permisos import calcular_efectivos, secciones_de_modulos
    with Session(engine) as s:
        u = s.get(UsuarioSindicato, usuario_id)
        if not u or not u.activo:
            return set()
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
            return set(secciones_de_modulos(mods))
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
        return calcular_efectivos(del_area, agregados, bloqueados, mods)


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
    """{uso: modelo_id} para los tres usos de precios_ia.USOS, ya resuelto:
    lo que eligió plataforma o, si no eligió nada, el default del módulo.
    Quien llama nunca tiene que preguntarse si hay configuración."""
    with Session(engine) as s:
        cfg = s.get(ConfiguracionPlataforma, 1)
        elegidos = {
            "recibos": (cfg.modelo_recibos if cfg else "") or "",
            "convenio": (cfg.modelo_convenio if cfg else "") or "",
            "asistente": (cfg.modelo_asistente if cfg else "") or "",
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
                             ("asistente", "modelo_asistente")):
            valor = (elegidos.get(uso) or "").strip()
            if valor and precios_ia.modelo_valido(valor):
                setattr(cfg, columna, valor)
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
        cfg = s.get(ConfiguracionPlataforma, 1)
        if not cfg:
            return {"logo": "", "logo_oscuro": "", "color_primario": "#152238",
                    "color_secundario": "#1a7a6b", "color_acento": "#b23a2e",
                    "portada_clara": False}
        return {
            "logo": cfg.logo,
            "logo_oscuro": cfg.logo_oscuro,
            "color_primario": cfg.color_primario or "#152238",
            "color_secundario": cfg.color_secundario or "#1a7a6b",
            "color_acento": cfg.color_acento or "#b23a2e",
            "portada_clara": cfg.portada_clara,
        }


def set_marca_plataforma(color_primario: str, color_secundario: str, color_acento: str,
                          logo_datos: bytes = None, logo_mime: str = "", logo_flag: str = "",
                          portada_clara: bool = False,
                          logo_datos_oscuro: bytes = None, logo_mime_oscuro: str = "",
                          logo_oscuro_flag: str = ""):
    with Session(engine) as s:
        cfg = s.get(ConfiguracionPlataforma, 1)
        if not cfg:
            cfg = ConfiguracionPlataforma(id=1)
        cfg.color_primario = color_primario or "#152238"
        cfg.color_secundario = color_secundario or "#1a7a6b"
        cfg.color_acento = color_acento or "#b23a2e"
        cfg.portada_clara = portada_clara
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


def nombre_trabajador(cuil: str, sindicato_id: int) -> str:
    """Devuelve el nombre del trabajador en ese sindicato (o cadena vacía)."""
    with Session(engine) as s:
        t = s.exec(select(Trabajador).where(
            Trabajador.cuil == cuil, Trabajador.sindicato_id == sindicato_id)).first()
        return t.nombre if t else ""


def perfil_trabajador(cuil: str, sindicato_id: int) -> Optional[dict]:
    """Datos propios del trabajador para mostrarle su perfil. Editable desde
    /api/perfil (ver actualizar_perfil_trabajador) -- todo menos el CUIL."""
    with Session(engine) as s:
        t = s.exec(select(Trabajador).where(
            Trabajador.cuil == cuil, Trabajador.sindicato_id == sindicato_id)).first()
        if not t:
            return None
        return {
            "nombre": t.nombre, "cuil": t.cuil,
            "calle": t.calle, "numero": t.numero, "piso_depto": t.piso_depto,
            "localidad": t.localidad, "provincia": t.provincia,
            "codigo_postal": t.codigo_postal, "direccion_texto": t.direccion_texto,
            "latitud": t.latitud, "longitud": t.longitud,
            "precision_geo": t.precision_geo, "geo_actualizado": t.geo_actualizado,
            "telefono": t.telefono, "mail": t.mail,
        }


def actualizar_perfil_trabajador(cuil: str, sindicato_id: int, nombre: str,
                                  domicilio: dict, telefono: str, mail: str) -> bool:
    """El trabajador edita sus propios datos -- todo menos el CUIL (identidad,
    no se toca acá) y los campos de gestión del sindicato (seccional,
    vigencia de credencial, etc.), que siguen siendo resorte del admin.
    Actualiza SOLO el empadronamiento del sindicato activo -- Trabajador es
    por sindicato (pluriempleo), no hay un domicilio único de la persona en
    este modelo.

    `domicilio` llega ya armado por `geo.campos_para_guardar()`, que es la
    única función que decide qué se escribe en el bloque de domicilio: antes
    esta firma tenía un parámetro por campo y sumarle el CP y las
    coordenadas la habría dejado en once posicionales, donde equivocarse de
    orden no da error, da datos mal."""
    with Session(engine) as s:
        t = s.exec(select(Trabajador).where(
            Trabajador.cuil == cuil, Trabajador.sindicato_id == sindicato_id)).first()
        if not t:
            return False
        t.nombre = (nombre or "").strip()[:200] or t.nombre
        for campo, valor in (domicilio or {}).items():
            if campo in geo.CAMPOS_DOMICILIO:
                setattr(t, campo, valor)
        t.telefono, t.mail = telefono.strip()[:40], mail.strip()[:200]
        s.add(t)
        s.commit()
        return True


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
        return {
            "sindicato": sind.nombre, "sindicato_id": sind.id,
            "logo": sind.logo, "color_primario": sind.color_primario,
            "nombre": t.nombre, "cuil": t.cuil,
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


def _noticia_a_dict(n: "Noticia") -> dict:
    return {
        "id": n.id, "sindicato_id": n.sindicato_id, "titulo": n.titulo,
        "bajada": n.bajada, "texto_completo": n.texto_completo,
        "fecha_desde": n.fecha_desde, "fecha_hasta": n.fecha_hasta, "creada": n.creada,
        "tiene_imagen1": bool(n.imagen1_datos), "tiene_imagen2": bool(n.imagen2_datos),
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


def noticias_del_sindicato(sindicato_id: int) -> list:
    """Todas las noticias del sindicato (para el panel de admin), más
    recientes primero."""
    with Session(engine) as s:
        noticias = s.exec(select(Noticia).where(Noticia.sindicato_id == sindicato_id)
                          .order_by(Noticia.creada.desc(), Noticia.id.desc())).all()
        return [_noticia_a_dict(n) for n in noticias]


def noticias_vigentes(sindicato_id: int, seccional_id: Optional[int] = None, limite: int = None) -> list:
    """Noticias vigentes HOY de un sindicato, dirigidas a la seccional del
    trabajador (o a todas), más recientes primero."""
    hoy = fechas.hoy_texto()
    todas = noticias_del_sindicato(sindicato_id)
    vigentes = [n for n in todas if noticia_vigente(n, hoy)
                and visible_para_seccional(n["destino_seccionales"], seccional_id)]
    return vigentes[:limite] if limite else vigentes


def noticia_por_id(noticia_id: int) -> Optional[dict]:
    with Session(engine) as s:
        n = s.get(Noticia, noticia_id)
        return _noticia_a_dict(n) if n else None


def beneficio_vigente(b: "Beneficio | dict", hoy: str) -> bool:
    """Mismo criterio que noticia_vigente: hoy en AAAA-MM-DD, vigente =
    fecha_desde <= hoy <= fecha_hasta."""
    desde = b["fecha_desde"] if isinstance(b, dict) else b.fecha_desde
    hasta = b["fecha_hasta"] if isinstance(b, dict) else b.fecha_hasta
    return bool(desde) and bool(hasta) and desde <= hoy <= hasta


def _beneficio_a_dict(b: "Beneficio") -> dict:
    return {
        "id": b.id, "sindicato_id": b.sindicato_id, "rubro": b.rubro,
        "descripcion": b.descripcion, "link": b.link,
        "fecha_desde": b.fecha_desde, "fecha_hasta": b.fecha_hasta, "creada": b.creada,
        "tiene_imagen": bool(b.imagen_datos),
        "destino_seccionales": b.destino_seccionales or [],
        "formulario_id": b.formulario_id,
    }


def beneficios_del_sindicato(sindicato_id: int) -> list:
    """Todos los beneficios del sindicato (para el panel de admin), más
    recientes primero."""
    with Session(engine) as s:
        beneficios = s.exec(select(Beneficio).where(Beneficio.sindicato_id == sindicato_id)
                            .order_by(Beneficio.creada.desc(), Beneficio.id.desc())).all()
        return [_beneficio_a_dict(b) for b in beneficios]


def beneficios_vigentes(sindicato_id: int, seccional_id: Optional[int] = None) -> list:
    """Beneficios vigentes HOY de un sindicato, dirigidos a la seccional del
    trabajador (o a todos), más recientes primero."""
    hoy = fechas.hoy_texto()
    todos = beneficios_del_sindicato(sindicato_id)
    return [b for b in todos if beneficio_vigente(b, hoy)
            and visible_para_seccional(b["destino_seccionales"], seccional_id)]


def beneficio_por_id(beneficio_id: int) -> Optional[dict]:
    with Session(engine) as s:
        b = s.get(Beneficio, beneficio_id)
        return _beneficio_a_dict(b) if b else None


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
    """(id, domicilio) de los afiliados activos sin coordenadas y CON localidad.

    Sin localidad no hay nada que preguntarle a Georef, así que esas filas
    no se cuentan ni se intentan: gastarían un pedido para devolver siempre
    lo mismo. El alcance de seccional se aplica EN la consulta."""
    conds = ["sindicato_id = :sid", "activo", "latitud IS NULL", "localidad != ''"]
    params = {"sid": sindicato_id, "limite": limite}
    if alcance is not None:
        if not alcance:
            return []
        conds.append("seccional_id IN :secs")
        params["secs"] = list(alcance)
    sql = (f"SELECT id, calle, numero, piso_depto, localidad, provincia, codigo_postal "
           f"FROM trabajador WHERE {' AND '.join(conds)} ORDER BY id LIMIT :limite")
    stmt = text(sql)
    if alcance is not None:
        stmt = stmt.bindparams(bindparam("secs", expanding=True))
    with Session(engine) as s:
        filas = s.execute(stmt, params).all()
    return [(f[0], {"calle": f[1], "numero": f[2], "piso_depto": f[3],
                    "localidad": f[4], "provincia": f[5], "codigo_postal": f[6]})
            for f in filas]


def guardar_geo_trabajador(sindicato_id: int, trabajador_id: int, domicilio: dict) -> None:
    """Escribe el bloque de domicilio de UN afiliado. El `sindicato_id` va en
    el WHERE aunque el id ya sea único: una función que escribe por id suelto
    es la que un día se llama con el id equivocado."""
    with Session(engine) as s:
        t = s.exec(select(Trabajador).where(
            Trabajador.id == trabajador_id,
            Trabajador.sindicato_id == sindicato_id)).first()
        if not t:
            return
        for campo, valor in (domicilio or {}).items():
            if campo in geo.CAMPOS_DOMICILIO:
                setattr(t, campo, valor)
        s.add(t); s.commit()


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
        salida = []
        for u in usuarios:
            ind = permisos_individuales(u.id)
            salida.append({
                "id": u.id, "usuario": u.usuario, "nombre": u.nombre, "activo": u.activo,
                "cuil": u.cuil, "trabajador_id": u.trabajador_id,
                "es_afiliado": bool(u.trabajador_id),
                "debe_cambiar_clave": u.debe_cambiar_clave,
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


def registrar_uso_ia(sindicato_id: Optional[int], cuil: str, tipo: str,
                      modelo: str, tokens_entrada: int, tokens_salida: int,
                      duracion_ms: int = 0) -> None:
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
                                 f.precio_entrada, f.precio_salida)
        exacto = True
    else:
        costo = precios_ia.costo_estimado(f.modelo, f.tokens_entrada, f.tokens_salida)
        exacto = False
    return {
        "id": f.id, "sindicato": nombres.get(f.sindicato_id, "—"),
        "sindicato_id": f.sindicato_id, "cuil": f.cuil, "tipo": f.tipo,
        "modelo": f.modelo, "modelo_nombre": precios_ia.nombre(f.modelo),
        "tokens_entrada": f.tokens_entrada,
        "tokens_salida": f.tokens_salida, "fecha": f.fecha,
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
        q = select(Trabajador).where(
            Trabajador.sindicato_id == sindicato_id, Trabajador.activo == True)
        if alcance is not None:
            q = q.where(Trabajador.seccional_id.in_(list(alcance)))
        trabajadores = s.exec(q).all()
    if criterio == "todos":
        return sorted({t.cuil for t in trabajadores})
    if criterio == "cuil":
        objetivo = set(valores)
        return sorted({t.cuil for t in trabajadores if t.cuil in objetivo})
    if criterio == "cuit_empleador":
        objetivo = set(valores)
        return sorted({t.cuil for t in trabajadores if t.cuit_empleador in objetivo})
    if criterio == "seccional":
        objetivo = {int(v) for v in valores if v.isdigit()}
        return sorted({t.cuil for t in trabajadores if t.seccional_id in objetivo})
    if criterio == "provincia":
        objetivo = set(valores)
        return sorted({t.cuil for t in trabajadores if t.provincia in objetivo})
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
        for n in filas:
            dests = s.exec(select(NotificacionDestinatario).where(
                NotificacionDestinatario.notificacion_id == n.id)).all()
            leidos = sum(1 for d in dests if d.leida_en)
            resultado.append({
                "id": n.id, "remitente": n.remitente, "texto": n.texto,
                "tiene_adjunto": bool(n.adjunto_datos), "adjunto_nombre": n.adjunto_nombre,
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
        nombres = {t.cuil: t.nombre for t in s.exec(select(Trabajador)).all()}
        return [{
            "cuil": d.cuil, "nombre": nombres.get(d.cuil, ""), "leida_en": d.leida_en,
        } for d in dests]


def notificaciones_de_trabajador(cuil: str, sindicato_id: int) -> list:
    """Notificaciones que le llegaron a este CUIL en este sindicato, más
    nuevas primero -- para el modal de la portada."""
    with Session(engine) as s:
        dests = s.exec(select(NotificacionDestinatario).where(
            NotificacionDestinatario.cuil == cuil)).all()
        if not dests:
            return []
        por_id = {d.notificacion_id: d for d in dests}
        notifs = s.exec(select(Notificacion).where(
            Notificacion.id.in_(por_id.keys()), Notificacion.sindicato_id == sindicato_id)
            .order_by(Notificacion.id.desc())).all()
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
        return [{
            "id": n.id, "remitente": n.remitente, "texto": n.texto,
            "tiene_adjunto": bool(n.adjunto_datos), "adjunto_nombre": n.adjunto_nombre,
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
        objetivo = set(valores)
        return sorted({e.cuit for e in empleadores if e.cuit in objetivo})
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
        for n in filas:
            dests = s.exec(select(NotificacionEmpleadorDestinatario).where(
                NotificacionEmpleadorDestinatario.notificacion_empleador_id == n.id)).all()
            leidos = sum(1 for d in dests if d.leida_en)
            resultado.append({
                "id": n.id, "remitente": n.remitente, "texto": n.texto,
                "tiene_adjunto": bool(n.adjunto_datos), "adjunto_nombre": n.adjunto_nombre,
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
        return [{
            "id": n.id, "remitente": n.remitente, "texto": n.texto,
            "tiene_adjunto": bool(n.adjunto_datos), "adjunto_nombre": n.adjunto_nombre,
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
                        seccional_id: int = None, permite_pase: bool = False) -> int:
    """Crea el tipo y sus campos en un solo alta. `campos` es una lista de
    dicts con las claves de CampoTramite (sin id/tipo_tramite_id); `reglas`
    son las reglas de consistencia ya saneadas
    (validaciones_tramite.reglas_saneadas)."""
    with Session(engine) as s:
        t = TipoTramite(sindicato_id=sindicato_id, titulo=titulo, codigo=codigo,
                         reglas_consistencia=reglas or [],
                         area_destino_default_id=area_destino_default_id,
                         seccional_id=seccional_id, permite_pase=permite_pase,
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
                         permite_pase: Optional[bool] = None) -> bool:
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
        # La SECCIONAL de un formulario no se edita: cambiarla le sacaría
        # el trámite de la vista a los trabajadores que ya lo tenían
        # disponible. El destino, en cambio, sí -- es la configuración
        # que el sindicato va a querer ajustar con el uso.
        if area_destino_default_id is not None:
            t.area_destino_default_id = area_destino_default_id
        if permite_pase is not None:
            t.permite_pase = permite_pase
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
                                 seccional_id: Optional[int] = "todas") -> list:
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
        tipos = s.exec(q.order_by(TipoTramite.creado.desc())).all()
        resultado = []
        for t in tipos:
            campos = s.exec(select(CampoTramite)
                            .where(CampoTramite.tipo_tramite_id == t.id,
                                   CampoTramite.retirado == False)  # noqa: E712
                            .order_by(CampoTramite.orden)).all()
            resultado.append({
                "id": t.id, "titulo": t.titulo, "codigo": t.codigo, "activo": t.activo,
                "creado": t.creado, "campos": [_campo_tramite_a_dict(c) for c in campos],
                "reglas_consistencia": t.reglas_consistencia or [],
                "seccional_id": t.seccional_id,
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
            "activo": t.activo, "creado": t.creado, "campos": [_campo_tramite_a_dict(c) for c in campos],
            "reglas_consistencia": t.reglas_consistencia or [],
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
        prefijo = "".join(ch for ch in tipo.codigo.upper() if ch.isalnum()) or "TRAM"
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
                     ultimas_notas: Optional[dict] = None) -> dict:
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
            "tiene_adjunto": bool(ultima.adjunto_datos), "formulario_id": ultima.formulario_id,
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
        return [_tramite_resumen(s, tr, titulos_tipo) for tr in tramites]


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


def tramites_de_trabajador(cuil: str, sindicato_id: int) -> list:
    """Los trámites que presentó ESTE trabajador en ESTE sindicato, más
    recientes primero -- para "Mis trámites"."""
    with Session(engine) as s:
        tramites = s.exec(select(Tramite).where(
            Tramite.cuil == cuil, Tramite.sindicato_id == sindicato_id).order_by(Tramite.id.desc())).all()
        titulos_tipo = {t.id: t.titulo for t in s.exec(
            select(TipoTramite).where(TipoTramite.sindicato_id == sindicato_id)).all()}
        # último mensaje de cada hilo, en una sola consulta (ordenada por id:
        # la última fila que se asigna por tramite_id es la más nueva)
        ultimas: dict = {}
        if tramites:
            for n in s.exec(select(NotaTramite).where(
                    NotaTramite.tramite_id.in_([t.id for t in tramites])).order_by(NotaTramite.id)).all():
                ultimas[n.tramite_id] = n
        return [_tramite_resumen(s, tr, titulos_tipo, ultimas) for tr in tramites]


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
            "valor_texto": r.valor_texto, "tiene_archivo": bool(r.archivo_datos),
            "archivo_nombre": r.archivo_nombre, "respuesta_id": r.id,
        } for r in respuestas],
        "notas": [{
            "id": n.id, "autor": n.autor, "texto": n.texto, "creado": n.creado,
            "orden": orden_de_nota.get(n.id, 0),
            "tiene_adjunto": bool(n.adjunto_datos), "adjunto_nombre": n.adjunto_nombre,
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
        tr = s.exec(select(Tramite).where(Tramite.numero_expediente == numero_expediente)).first()
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
        prefijo = "".join(ch for ch in tipo.codigo.upper() if ch.isalnum()) or "TRAM"
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
            "valor_texto": r.valor_texto, "tiene_archivo": bool(r.archivo_datos),
            "archivo_nombre": r.archivo_nombre, "respuesta_id": r.id,
        } for r in respuestas],
        "notas": [{
            "id": n.id, "autor": n.autor, "texto": n.texto, "creado": n.creado,
            "orden": orden_de_nota.get(n.id, 0),
            "tiene_adjunto": bool(n.adjunto_datos), "adjunto_nombre": n.adjunto_nombre,
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
        tr = s.exec(select(TramiteEmpleador).where(
            TramiteEmpleador.numero_expediente == numero_expediente)).first()
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
            t = s.exec(select(Trabajador).where(
                Trabajador.sindicato_id == sindicato_id, Trabajador.cuil == cuil)).first()
            if t:
                if "seccional" in cortes:
                    datos_corte["seccional_id"] = t.seccional_id
                if "provincia" in cortes:
                    datos_corte["provincia"] = t.provincia or ""
                if "empleador" in cortes:
                    datos_corte["cuit_empleador"] = t.cuit_empleador or ""

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
                      creada=fechas.ahora_texto(), encuesta_id=encuesta_id))
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
