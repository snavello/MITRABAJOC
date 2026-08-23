"""Capa de datos con SQLModel (SQLite).

Todo lo que la aplicación lee o modifica vive acá: conceptos, fórmulas,
reportes. El archivo de base se ubica en la ruta que indique DB_PATH
(por defecto data/validador.db). En Render, DB_PATH apunta al disco
persistente para que los datos sobrevivan a los reinicios.

La primera vez que arranca, si la base está vacía, se cargan los conceptos
y fórmulas iniciales desde data/seed_aefip.json (solo como semilla).
"""
import os
import csv
import json
from pathlib import Path
from typing import Optional
from datetime import datetime

from dotenv import load_dotenv
from typing import Any
from sqlmodel import SQLModel, Field, create_engine, Session, select, Column, JSON
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
# Si hay DATABASE_URL (Render Postgres), se usa Postgres.
# Si no, cae a SQLite en DB_PATH (desarrollo local, sin cambios).
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if DATABASE_URL:
    # Render entrega la URL como postgres://; SQLAlchemy/psycopg3 espera postgresql+psycopg://
    url = DATABASE_URL
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://") and "+psycopg" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(
        url,
        pool_pre_ping=True,   # descarta conexiones muertas antes de usarlas (clave con base remota)
        pool_recycle=300,     # recicla conexiones cada 5 min (Render duerme el servicio en plan free)
        pool_size=5,
        max_overflow=5,
        connect_args={
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
        },
    )
    USANDO_POSTGRES = True
else:
    DB_PATH = os.getenv("DB_PATH", "data/validador.db")
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{DB_PATH}",
        connect_args={"check_same_thread": False},
    )
    USANDO_POSTGRES = False


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
    modulos_habilitados: list = Field(default=[], sa_column=Column(JSON))
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
    admin las da de alta y las asigna a trabajadores en el alta/edición --
    es un dato descriptivo, no afecta validación de recibos ni aislamiento."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(foreign_key="sindicato.id", index=True)
    nombre: str
    direccion: str = ""


class UsuarioSindicato(SQLModel, table=True):
    """Administrador de un sindicato. Lo da de alta el admin de plataforma."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(foreign_key="sindicato.id", index=True)
    usuario: str = Field(index=True)            # mail o nombre de usuario
    nombre: str = ""
    clave_hash: str = ""
    debe_cambiar_clave: bool = True             # la primera clave la pone el admin de plataforma
    activo: bool = True


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
    El mismo CUIL puede tener varias filas (una por sindicato donde está afiliado)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(foreign_key="sindicato.id", index=True)
    cuil: str = Field(index=True)          # obligatorio
    nombre: str = ""                       # obligatorio
    # Datos de contacto / domicilio (opcionales)
    calle: str = ""
    numero: str = ""
    piso: str = ""
    ciudad: str = ""
    provincia: str = ""
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
    # CUIT del empleador (opcional, lo carga el admin en el alta/edición
    # manual -- NO está en el alta masiva, mismo criterio que seccional_id).
    # Permite dirigir una Notificacion "por empresa" (ver Notificacion).
    cuit_empleador: Optional[str] = Field(default=None, index=True)
    # Último semáforo de ARCA calculado (POST /api/aportes) -- antes se
    # perdía apenas se navegaba o se recargaba la página, porque nunca se
    # guardaba. Es el mismo dict que devuelve semaforo.calcular_semaforo().
    semaforo_datos: dict = Field(default={}, sa_column=Column(JSON))
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
    alias: list = Field(default=[], sa_column=Column(JSON))
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
    # Destino: lista de Seccional.id a la(s) que se dirige. Lista vacía (el
    # default) = todas las seccionales, incluidos los trabajadores sin
    # seccional asignada.
    destino_seccionales: list = Field(default=[], sa_column=Column(JSON))


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
    # Destino: lista de Seccional.id a la(s) que se dirige. Lista vacía (el
    # default) = todas las seccionales, mismo criterio que Noticia.
    destino_seccionales: list = Field(default=[], sa_column=Column(JSON))


class Reporte(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(default=1, foreign_key="sindicato.id", index=True)
    fecha: str
    cuil: str = ""
    periodo: str = ""
    estado: str = "nuevo"          # "nuevo" | "en_revision" | "resuelto"
    detalle: dict = Field(default={}, sa_column=Column(JSON))


class UsoIA(SQLModel, table=True):
    """Consumo de la API de Anthropic, una fila por llamada -- sindicato_id
    NULL cuando no se puede resolver (no debería pasar en los 3 puntos donde
    se registra hoy, pero no se descarta la fila por eso). Pensado para medir
    costo real (tokens crudos, sin precio -- cambia según el plan/modelo) por
    sindicato y por tipo de llamada en el panel de plataforma."""
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: Optional[int] = Field(default=None, foreign_key="sindicato.id", index=True)
    cuil: str = ""  # vacío en "aprendizaje": lo dispara el admin, no es de un trabajador puntual
    tipo: str = ""  # "recibo" | "aportes" | "aprendizaje"
    modelo: str = ""
    tokens_entrada: int = 0
    tokens_salida: int = 0
    fecha: str = ""  # "AAAA-MM-DD HH:MM"


class ConfiguracionPlataforma(SQLModel, table=True):
    """Parámetros globales de plataforma (no por sindicato). Fila única, id=1."""
    id: Optional[int] = Field(default=None, primary_key=True)
    # Ley 27.802 art. 133 / Dto 407/2026: tope global a las cargas sindicales de
    # convenio, en % de la remuneración. Editable SOLO por el admin de plataforma.
    tope_sindical_pct: float = 2.0
    # Marca de la plataforma "Mi Trabajo" (pantallas de login y panel de
    # plataforma, antes de entrar a un sindicato en particular). Mismo patrón
    # que Sindicato: logo en la base (Opción B), colores editables. Si no se
    # cargó nada, se usan los valores de siempre (ver marca_plataforma()).
    color_primario: str = "#152238"
    color_secundario: str = "#1a7a6b"
    color_acento: str = "#b23a2e"
    logo: str = ""
    logo_datos: Optional[bytes] = Field(default=None)
    logo_mime: str = ""
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
    detalle: dict = Field(default={}, sa_column=Column(JSON))


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
    detalle: dict = Field(default={}, sa_column=Column(JSON))


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
    criterio_valores: list = Field(default=[], sa_column=Column(JSON))
    # "manual" = la compuso el admin desde /admin. "sistema" = la disparó
    # automáticamente un cambio de trámite (Fase 3, main._notificar_cambio_tramite).
    origen: str = "manual"
    enviado_en: str = ""           # fecha/hora de envío ("AAAA-MM-DD HH:MM")
    cantidad_destinatarios: int = 0  # snapshot: cuántos matchearon al enviar


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
    criterio_valores: list = Field(default=[], sa_column=Column(JSON))
    origen: str = "manual"          # "manual" | "sistema" (Fase 5: cambio de trámite externo)
    enviado_en: str = ""
    cantidad_destinatarios: int = 0


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
    creado: str = ""
    actualizado: str = ""


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
    adjunto_datos: Optional[bytes] = Field(default=None)
    adjunto_mime: str = ""
    adjunto_nombre: str = ""
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


class TramiteEmpleadorLog(SQLModel, table=True):
    """Mirror de TramiteLog."""
    id: Optional[int] = Field(default=None, primary_key=True)
    tramite_id: int = Field(foreign_key="tramiteempleador.id", index=True)
    evento: str
    detalle: str = ""
    creado: str = ""


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
    fragmentos_usados: list = Field(default=[], sa_column=Column(JSON))
    creado: str = ""



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
                     creado=datetime.now().strftime("%Y-%m-%d %H:%M"))
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
            creado=datetime.now().strftime("%Y-%m-%d %H:%M"))
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
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M")
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
    SQLModel.metadata.create_all(engine)


def cargar_seed_si_vacio():
    """Si no hay conceptos, carga los iniciales desde el JSON semilla."""
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
    """Pone el contador de autoincremento de Postgres por encima del id máximo.
    En SQLite no hace nada (no tiene secuencias con nombre)."""
    if not USANDO_POSTGRES:
        return
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

    - En SQLite (desarrollo): crea las tablas con create_all, como siempre.
    - En Postgres (producción): NO crea tablas; el esquema lo administra Alembic
      (`alembic upgrade head` corre en el deploy). Si las tablas aún no existen,
      cargar_seed_si_vacio no encontrará nada y no romperá.
    El seed se carga si la base está vacía, en ambos motores.
    """
    if not USANDO_POSTGRES:
        crear_tablas()
    cargar_seed_si_vacio()
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


def marca_plataforma() -> dict:
    """Marca de 'Mi Trabajo' para las pantallas sin sindicato (logins, panel de
    plataforma): degrada a los colores/logo de siempre si no se configuró nada."""
    with Session(engine) as s:
        cfg = s.get(ConfiguracionPlataforma, 1)
        if not cfg:
            return {"logo": "", "color_primario": "#152238",
                    "color_secundario": "#1a7a6b", "color_acento": "#b23a2e",
                    "portada_clara": False}
        return {
            "logo": cfg.logo,
            "color_primario": cfg.color_primario or "#152238",
            "color_secundario": cfg.color_secundario or "#1a7a6b",
            "color_acento": cfg.color_acento or "#b23a2e",
            "portada_clara": cfg.portada_clara,
        }


def set_marca_plataforma(color_primario: str, color_secundario: str, color_acento: str,
                          logo_datos: bytes = None, logo_mime: str = "", logo_flag: str = "",
                          portada_clara: bool = False):
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
            "calle": t.calle, "numero": t.numero, "piso": t.piso,
            "ciudad": t.ciudad, "provincia": t.provincia,
            "telefono": t.telefono, "mail": t.mail,
        }


def actualizar_perfil_trabajador(cuil: str, sindicato_id: int, nombre: str, calle: str, numero: str,
                                  piso: str, ciudad: str, provincia: str, telefono: str, mail: str) -> bool:
    """El trabajador edita sus propios datos -- todo menos el CUIL (identidad,
    no se toca acá) y los campos de gestión del sindicato (seccional,
    vigencia de credencial, etc.), que siguen siendo resorte del admin.
    Actualiza SOLO el empadronamiento del sindicato activo -- Trabajador es
    por sindicato (pluriempleo), no hay un domicilio único de la persona en
    este modelo."""
    with Session(engine) as s:
        t = s.exec(select(Trabajador).where(
            Trabajador.cuil == cuil, Trabajador.sindicato_id == sindicato_id)).first()
        if not t:
            return False
        t.nombre = (nombre or "").strip()[:200] or t.nombre
        t.calle, t.numero, t.piso = calle.strip()[:200], numero.strip()[:20], piso.strip()[:20]
        t.ciudad, t.provincia = ciudad.strip()[:100], provincia.strip()[:60]
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
        t.semaforo_actualizado = datetime.now().strftime("%Y-%m-%d")
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
    }


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
    hoy = datetime.now().strftime("%Y-%m-%d")
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
    hoy = datetime.now().strftime("%Y-%m-%d")
    todos = beneficios_del_sindicato(sindicato_id)
    return [b for b in todos if beneficio_vigente(b, hoy)
            and visible_para_seccional(b["destino_seccionales"], seccional_id)]


def beneficio_por_id(beneficio_id: int) -> Optional[dict]:
    with Session(engine) as s:
        b = s.get(Beneficio, beneficio_id)
        return _beneficio_a_dict(b) if b else None


def seccionales_del_sindicato(sindicato_id: int) -> list:
    """Todas las seccionales del sindicato, para el CRUD de admin y el
    <select> del alta/edición de trabajador."""
    with Session(engine) as s:
        seccionales = s.exec(select(Seccional).where(
            Seccional.sindicato_id == sindicato_id).order_by(Seccional.nombre)).all()
        return [{"id": sec.id, "nombre": sec.nombre, "direccion": sec.direccion} for sec in seccionales]


def seccional_de_trabajador(cuil: str, sindicato_id: int) -> Optional[int]:
    """seccional_id del trabajador en ESE sindicato (None si no tiene
    asignada) -- para filtrar Noticias/Beneficios por destino."""
    with Session(engine) as s:
        t = s.exec(select(Trabajador).where(
            Trabajador.cuil == cuil, Trabajador.sindicato_id == sindicato_id)).first()
        return t.seccional_id if t else None


def registrar_uso_ia(sindicato_id: Optional[int], cuil: str, tipo: str,
                      modelo: str, tokens_entrada: int, tokens_salida: int) -> None:
    """Guarda una fila de consumo de la API por cada llamada real -- se llama
    en el mismo request que hace la llamada (extraer/extraer_aportes), nunca
    se re-arma después, para que el conteo no dependa de que el trabajador
    confirme o reporte nada."""
    with Session(engine) as s:
        s.add(UsoIA(
            sindicato_id=sindicato_id, cuil=cuil, tipo=tipo, modelo=modelo,
            tokens_entrada=tokens_entrada, tokens_salida=tokens_salida,
            fecha=datetime.now().strftime("%Y-%m-%d %H:%M"),
        ))
        s.commit()


def uso_ia_listado() -> list:
    """Todo el consumo de IA de TODOS los sindicatos, más reciente primero,
    con el nombre del sindicato ya resuelto (para el panel de plataforma)."""
    with Session(engine) as s:
        filas = s.exec(select(UsoIA).order_by(UsoIA.id.desc())).all()
        nombres = {sind.id: sind.nombre for sind in s.exec(select(Sindicato)).all()}
        return [{
            "id": f.id, "sindicato": nombres.get(f.sindicato_id, "—"),
            "sindicato_id": f.sindicato_id, "cuil": f.cuil, "tipo": f.tipo,
            "modelo": f.modelo, "tokens_entrada": f.tokens_entrada,
            "tokens_salida": f.tokens_salida, "fecha": f.fecha,
        } for f in filas]


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
            fecha=datetime.now().strftime("%Y-%m-%d %H:%M"),
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

def resolver_destinatarios(sindicato_id: int, criterio: str, valores: list) -> list:
    """CUILs de trabajadores ACTIVOS de este sindicato que matchean el
    criterio -- usado tanto por el preview (solo cuenta) como por el envío
    real (que además fija la lista, ver crear_notificacion). El sindicato
    solo puede targetear su propia gente: un valor que no matchea ningún
    trabajador de ESTE sindicato_id simplemente no suma destinatarios."""
    valores = [str(v).strip() for v in (valores or []) if str(v).strip()]
    if not valores:
        return []
    with Session(engine) as s:
        trabajadores = s.exec(select(Trabajador).where(
            Trabajador.sindicato_id == sindicato_id, Trabajador.activo == True)).all()
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
                        origen: str = "manual") -> dict:
    """Resuelve los destinatarios y los FIJA en el momento de enviar (snapshot,
    ver Notificacion). Devuelve id y cantidad real, para la confirmación."""
    cuils = resolver_destinatarios(sindicato_id, criterio, valores)
    with Session(engine) as s:
        n = Notificacion(
            sindicato_id=sindicato_id, remitente=remitente or "", usuario_id=usuario_id,
            texto=texto or "", adjunto_datos=adjunto_datos, adjunto_mime=adjunto_mime or "",
            adjunto_nombre=adjunto_nombre or "", criterio=criterio, criterio_valores=list(valores or []),
            origen=origen, enviado_en=datetime.now().strftime("%Y-%m-%d %H:%M"),
            cantidad_destinatarios=len(cuils),
        )
        s.add(n); s.commit(); s.refresh(n)
        for cuil in cuils:
            s.add(NotificacionDestinatario(notificacion_id=n.id, cuil=cuil))
        s.commit()
        return {"id": n.id, "cantidad_destinatarios": len(cuils)}


def notificaciones_del_sindicato(sindicato_id: int) -> list:
    """Todas las notificaciones enviadas por este sindicato, con el resumen
    leídos/total, más recientes primero -- para el listado de admin."""
    with Session(engine) as s:
        filas = s.exec(select(Notificacion).where(Notificacion.sindicato_id == sindicato_id)
                       .order_by(Notificacion.id.desc())).all()
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


def notificacion_destinatarios(notificacion_id: int) -> list:
    """Detalle fila por fila (CUIL + si leyó y cuándo) de una notificación."""
    with Session(engine) as s:
        dests = s.exec(select(NotificacionDestinatario).where(
            NotificacionDestinatario.notificacion_id == notificacion_id).order_by(
            NotificacionDestinatario.cuil)).all()
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
        return [{
            "id": n.id, "remitente": n.remitente, "texto": n.texto,
            "tiene_adjunto": bool(n.adjunto_datos), "adjunto_nombre": n.adjunto_nombre,
            "enviado_en": n.enviado_en, "leida_en": por_id[n.id].leida_en,
        } for n in notifs]


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
            d.leida_en = datetime.now().strftime("%Y-%m-%d %H:%M")
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
                                  origen: str = "manual") -> dict:
    """Resuelve los destinatarios y los FIJA en el momento de enviar
    (snapshot, mismo criterio que crear_notificacion)."""
    cuits = resolver_destinatarios_empleador(sindicato_id, criterio, valores)
    with Session(engine) as s:
        n = NotificacionEmpleador(
            sindicato_id=sindicato_id, remitente=remitente or "", usuario_id=usuario_id,
            texto=texto or "", adjunto_datos=adjunto_datos, adjunto_mime=adjunto_mime or "",
            adjunto_nombre=adjunto_nombre or "", criterio=criterio, criterio_valores=list(valores or []),
            origen=origen, enviado_en=datetime.now().strftime("%Y-%m-%d %H:%M"),
            cantidad_destinatarios=len(cuits),
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
        return [{
            "id": n.id, "remitente": n.remitente, "texto": n.texto,
            "tiene_adjunto": bool(n.adjunto_datos), "adjunto_nombre": n.adjunto_nombre,
            "enviado_en": n.enviado_en, "leida_en": por_id[n.id].leida_en,
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
            d.leida_en = datetime.now().strftime("%Y-%m-%d %H:%M")
            s.add(d); s.commit()
        return True


# ---------- Trámites (Fase 3 de Módulos + Notificaciones + Trámites) ----------

def _campo_tramite_a_dict(c: "CampoTramite") -> dict:
    return {
        "id": c.id, "orden": c.orden, "etiqueta": c.etiqueta, "tipo_dato": c.tipo_dato,
        "longitud_maxima": c.longitud_maxima, "longitud_exacta": c.longitud_exacta,
        "decimales": c.decimales, "tipos_archivo_permitidos": c.tipos_archivo_permitidos,
        "opciones": c.opciones, "ancho": c.ancho, "obligatorio": c.obligatorio,
    }


def crear_tipo_tramite(sindicato_id: int, titulo: str, codigo: str, campos: list) -> int:
    """Crea el tipo y sus campos en un solo alta. `campos` es una lista de
    dicts con las claves de CampoTramite (sin id/tipo_tramite_id)."""
    with Session(engine) as s:
        t = TipoTramite(sindicato_id=sindicato_id, titulo=titulo, codigo=codigo,
                         creado=datetime.now().strftime("%Y-%m-%d %H:%M"))
        s.add(t); s.commit(); s.refresh(t)
        for i, c in enumerate(campos):
            s.add(CampoTramite(
                tipo_tramite_id=t.id, orden=i, etiqueta=c["etiqueta"], tipo_dato=c["tipo_dato"],
                longitud_maxima=c.get("longitud_maxima"), longitud_exacta=c.get("longitud_exacta"),
                decimales=c.get("decimales"), tipos_archivo_permitidos=c.get("tipos_archivo_permitidos", ""),
                opciones=c.get("opciones", ""), ancho=c.get("ancho") or "completo",
                obligatorio=c.get("obligatorio", True),
            ))
        s.commit()
        return t.id


def editar_tipo_tramite(tipo_id: int, sindicato_id: int, titulo: str, codigo: str,
                         activo: bool, campos: list) -> bool:
    """Actualiza título/código/activo y REEMPLAZA los campos por los
    enviados -- el constructor de campos en admin es "lo que ves es lo que
    queda", como editar un formulario, no un merge campo por campo."""
    with Session(engine) as s:
        t = s.get(TipoTramite, tipo_id)
        if not t or t.sindicato_id != sindicato_id:
            return False
        t.titulo, t.codigo, t.activo = titulo, codigo, activo
        s.add(t)
        for viejo in s.exec(select(CampoTramite).where(CampoTramite.tipo_tramite_id == tipo_id)).all():
            s.delete(viejo)
        s.commit()
        for i, c in enumerate(campos):
            s.add(CampoTramite(
                tipo_tramite_id=tipo_id, orden=i, etiqueta=c["etiqueta"], tipo_dato=c["tipo_dato"],
                longitud_maxima=c.get("longitud_maxima"), longitud_exacta=c.get("longitud_exacta"),
                decimales=c.get("decimales"), tipos_archivo_permitidos=c.get("tipos_archivo_permitidos", ""),
                opciones=c.get("opciones", ""), ancho=c.get("ancho") or "completo",
                obligatorio=c.get("obligatorio", True),
            ))
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


def tipos_tramite_del_sindicato(sindicato_id: int, solo_activos: bool = False) -> list:
    """Tipos de trámite del sindicato con sus campos, para el constructor de
    admin y el listado que ve el trabajador (con solo_activos=True)."""
    with Session(engine) as s:
        q = select(TipoTramite).where(TipoTramite.sindicato_id == sindicato_id)
        if solo_activos:
            q = q.where(TipoTramite.activo == True)
        tipos = s.exec(q.order_by(TipoTramite.creado.desc())).all()
        resultado = []
        for t in tipos:
            campos = s.exec(select(CampoTramite).where(CampoTramite.tipo_tramite_id == t.id)
                            .order_by(CampoTramite.orden)).all()
            resultado.append({
                "id": t.id, "titulo": t.titulo, "codigo": t.codigo, "activo": t.activo,
                "creado": t.creado, "campos": [_campo_tramite_a_dict(c) for c in campos],
            })
        return resultado


def tipo_tramite_por_id(tipo_id: int) -> Optional[dict]:
    with Session(engine) as s:
        t = s.get(TipoTramite, tipo_id)
        if not t:
            return None
        campos = s.exec(select(CampoTramite).where(CampoTramite.tipo_tramite_id == tipo_id)
                        .order_by(CampoTramite.orden)).all()
        return {
            "id": t.id, "sindicato_id": t.sindicato_id, "titulo": t.titulo, "codigo": t.codigo,
            "activo": t.activo, "creado": t.creado, "campos": [_campo_tramite_a_dict(c) for c in campos],
        }


def _log_tramite(s: Session, tramite_id: int, evento: str, detalle: str) -> None:
    """Único punto que escribe en TramiteLog -- recibe la sesión abierta del
    llamador para que el evento quede en la MISMA transacción que el cambio
    que lo generó (alta, cambio de estado, nota)."""
    s.add(TramiteLog(
        tramite_id=tramite_id, evento=evento, detalle=detalle,
        creado=datetime.now().strftime("%Y-%m-%d %H:%M"),
    ))


def crear_tramite(sindicato_id: int, tipo_tramite_id: int, cuil: str, respuestas: list) -> Optional[dict]:
    """Genera el número de expediente (correlativo por tipo, reintenta ante
    colisión igual que generar_codigo_credencial) y persiste el trámite con
    sus respuestas en una sola operación. `respuestas` es una lista de dicts
    con campo_tramite_id/valor_texto/archivo_datos/archivo_mime/archivo_nombre,
    ya validada por el llamador (ver main.api_enviar_tramite)."""
    with Session(engine) as s:
        tipo = s.get(TipoTramite, tipo_tramite_id)
        if not tipo or tipo.sindicato_id != sindicato_id or not tipo.activo:
            return None
        prefijo = "".join(ch for ch in tipo.codigo.upper() if ch.isalnum()) or "TRAM"
        anio = datetime.now().strftime("%Y")
        ahora = datetime.now().strftime("%Y-%m-%d %H:%M")
        existentes = len(s.exec(select(Tramite).where(Tramite.tipo_tramite_id == tipo_tramite_id)).all())
        numero = None
        for intento in range(25):
            candidato = f"{prefijo}-{anio}-{(existentes + 1 + intento):06d}"
            if not s.exec(select(Tramite).where(Tramite.numero_expediente == candidato)).first():
                numero = candidato
                break
        if not numero:
            raise RuntimeError("No se pudo generar un número de expediente único, reintentá.")
        tr = Tramite(sindicato_id=sindicato_id, tipo_tramite_id=tipo_tramite_id, cuil=cuil,
                     numero_expediente=numero, estado="iniciado", creado=ahora, actualizado=ahora)
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
    """False si el estado no es válido, el trámite no es de ese sindicato, o
    el trámite YA está terminado -- un trámite terminado queda bloqueado,
    no se puede reabrir ni cambiar de estado (ver también agregar_nota_tramite)."""
    if nuevo_estado not in ESTADOS_TRAMITE:
        return False
    with Session(engine) as s:
        tr = s.get(Tramite, tramite_id)
        if not tr or tr.sindicato_id != sindicato_id or tr.estado == "terminado":
            return False
        anterior = tr.estado
        tr.estado = nuevo_estado
        tr.actualizado = datetime.now().strftime("%Y-%m-%d %H:%M")
        s.add(tr)
        _log_tramite(s, tramite_id, "cambio_estado",
                     f"{ESTADOS_TRAMITE_LABEL.get(anterior, anterior)} → {ESTADOS_TRAMITE_LABEL.get(nuevo_estado, nuevo_estado)}")
        s.commit()
        return True


def agregar_nota_tramite(tramite_id: int, autor: str, texto: str,
                          adjunto_datos: Optional[bytes] = None, adjunto_mime: str = "",
                          adjunto_nombre: str = "") -> bool:
    """`autor` es "admin" o "trabajador" -- la verificación de que quien
    escribe tiene permiso sobre ESTE trámite la hace el caller (main.py).
    Un trámite terminado queda bloqueado para notas nuevas de cualquier lado."""
    with Session(engine) as s:
        tr = s.get(Tramite, tramite_id)
        if not tr or tr.estado == "terminado":
            return False
        s.add(NotaTramite(
            tramite_id=tramite_id, autor=autor, texto=texto or "",
            adjunto_datos=adjunto_datos, adjunto_mime=adjunto_mime or "",
            adjunto_nombre=adjunto_nombre or "", creado=datetime.now().strftime("%Y-%m-%d %H:%M"),
        ))
        tr.actualizado = datetime.now().strftime("%Y-%m-%d %H:%M")
        s.add(tr)
        _log_tramite(s, tramite_id, f"nota_{autor}", texto[:120] if texto else "(sin texto, con adjunto)")
        s.commit()
        return True


def _tramite_resumen(s: Session, tr: "Tramite", titulos_tipo: dict) -> dict:
    return {
        "id": tr.id, "numero_expediente": tr.numero_expediente, "cuil": tr.cuil,
        "tipo_tramite_id": tr.tipo_tramite_id, "tipo_titulo": titulos_tipo.get(tr.tipo_tramite_id, "—"),
        "estado": tr.estado, "estado_label": ESTADOS_TRAMITE_LABEL.get(tr.estado, tr.estado),
        "creado": tr.creado, "actualizado": tr.actualizado,
    }


def tramites_del_sindicato(sindicato_id: int, estado: str = None, tipo_tramite_id: int = None,
                            cuil: str = None) -> list:
    """Listado filtrable para el panel de admin, más recientes primero."""
    with Session(engine) as s:
        q = select(Tramite).where(Tramite.sindicato_id == sindicato_id)
        if estado:
            q = q.where(Tramite.estado == estado)
        if tipo_tramite_id:
            q = q.where(Tramite.tipo_tramite_id == tipo_tramite_id)
        if cuil:
            q = q.where(Tramite.cuil == cuil)
        tramites = s.exec(q.order_by(Tramite.id.desc())).all()
        titulos_tipo = {t.id: t.titulo for t in s.exec(
            select(TipoTramite).where(TipoTramite.sindicato_id == sindicato_id)).all()}
        return [_tramite_resumen(s, tr, titulos_tipo) for tr in tramites]


def contar_tramites_nuevos(sindicato_id: int) -> int:
    """Trámites recién presentados (estado "iniciado", el admin todavía no
    los tocó) -- para el globo de notificación de la portada de admin y de
    la pestaña "Ver trámites" dentro de /admin."""
    with Session(engine) as s:
        return len(s.exec(select(Tramite).where(
            Tramite.sindicato_id == sindicato_id, Tramite.estado == "iniciado")).all())


def tramites_de_trabajador(cuil: str, sindicato_id: int) -> list:
    """Los trámites que presentó ESTE trabajador en ESTE sindicato, más
    recientes primero -- para "Mis trámites"."""
    with Session(engine) as s:
        tramites = s.exec(select(Tramite).where(
            Tramite.cuil == cuil, Tramite.sindicato_id == sindicato_id).order_by(Tramite.id.desc())).all()
        titulos_tipo = {t.id: t.titulo for t in s.exec(
            select(TipoTramite).where(TipoTramite.sindicato_id == sindicato_id)).all()}
        return [_tramite_resumen(s, tr, titulos_tipo) for tr in tramites]


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
    return {
        "id": tr.id, "numero_expediente": tr.numero_expediente, "cuil": tr.cuil,
        "sindicato_id": tr.sindicato_id, "estado": tr.estado,
        "estado_label": ESTADOS_TRAMITE_LABEL.get(tr.estado, tr.estado),
        "creado": tr.creado, "actualizado": tr.actualizado,
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
            "tiene_adjunto": bool(n.adjunto_datos), "adjunto_nombre": n.adjunto_nombre,
        } for n in notas],
        "log": [{"evento": l.evento, "detalle": l.detalle, "creado": l.creado} for l in log],
    }


def tramite_detalle(tramite_id: int) -> Optional[dict]:
    with Session(engine) as s:
        tr = s.get(Tramite, tramite_id)
        return _tramite_detalle_completo(s, tr) if tr else None


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
    }


def crear_tipo_tramite_empleador(sindicato_id: int, titulo: str, codigo: str, campos: list) -> int:
    with Session(engine) as s:
        t = TipoTramiteEmpleador(sindicato_id=sindicato_id, titulo=titulo, codigo=codigo,
                                  creado=datetime.now().strftime("%Y-%m-%d %H:%M"))
        s.add(t); s.commit(); s.refresh(t)
        for i, c in enumerate(campos):
            s.add(CampoTramiteEmpleador(
                tipo_tramite_id=t.id, orden=i, etiqueta=c["etiqueta"], tipo_dato=c["tipo_dato"],
                longitud_maxima=c.get("longitud_maxima"), longitud_exacta=c.get("longitud_exacta"),
                decimales=c.get("decimales"), tipos_archivo_permitidos=c.get("tipos_archivo_permitidos", ""),
                opciones=c.get("opciones", ""), ancho=c.get("ancho") or "completo",
                obligatorio=c.get("obligatorio", True),
            ))
        s.commit()
        return t.id


def editar_tipo_tramite_empleador(tipo_id: int, sindicato_id: int, titulo: str, codigo: str,
                                   activo: bool, campos: list) -> bool:
    with Session(engine) as s:
        t = s.get(TipoTramiteEmpleador, tipo_id)
        if not t or t.sindicato_id != sindicato_id:
            return False
        t.titulo, t.codigo, t.activo = titulo, codigo, activo
        s.add(t)
        for viejo in s.exec(select(CampoTramiteEmpleador).where(
                CampoTramiteEmpleador.tipo_tramite_id == tipo_id)).all():
            s.delete(viejo)
        s.commit()
        for i, c in enumerate(campos):
            s.add(CampoTramiteEmpleador(
                tipo_tramite_id=tipo_id, orden=i, etiqueta=c["etiqueta"], tipo_dato=c["tipo_dato"],
                longitud_maxima=c.get("longitud_maxima"), longitud_exacta=c.get("longitud_exacta"),
                decimales=c.get("decimales"), tipos_archivo_permitidos=c.get("tipos_archivo_permitidos", ""),
                opciones=c.get("opciones", ""), ancho=c.get("ancho") or "completo",
                obligatorio=c.get("obligatorio", True),
            ))
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
            campos = s.exec(select(CampoTramiteEmpleador).where(CampoTramiteEmpleador.tipo_tramite_id == t.id)
                            .order_by(CampoTramiteEmpleador.orden)).all()
            resultado.append({
                "id": t.id, "titulo": t.titulo, "codigo": t.codigo, "activo": t.activo,
                "creado": t.creado, "campos": [_campo_tramite_empleador_a_dict(c) for c in campos],
            })
        return resultado


def tipo_tramite_empleador_por_id(tipo_id: int) -> Optional[dict]:
    with Session(engine) as s:
        t = s.get(TipoTramiteEmpleador, tipo_id)
        if not t:
            return None
        campos = s.exec(select(CampoTramiteEmpleador).where(CampoTramiteEmpleador.tipo_tramite_id == tipo_id)
                        .order_by(CampoTramiteEmpleador.orden)).all()
        return {
            "id": t.id, "sindicato_id": t.sindicato_id, "titulo": t.titulo, "codigo": t.codigo,
            "activo": t.activo, "creado": t.creado,
            "campos": [_campo_tramite_empleador_a_dict(c) for c in campos],
        }


def _log_tramite_empleador(s: Session, tramite_id: int, evento: str, detalle: str) -> None:
    s.add(TramiteEmpleadorLog(
        tramite_id=tramite_id, evento=evento, detalle=detalle,
        creado=datetime.now().strftime("%Y-%m-%d %H:%M"),
    ))


def crear_tramite_empleador(sindicato_id: int, tipo_tramite_id: int, cuit: str, respuestas: list) -> Optional[dict]:
    with Session(engine) as s:
        tipo = s.get(TipoTramiteEmpleador, tipo_tramite_id)
        if not tipo or tipo.sindicato_id != sindicato_id or not tipo.activo:
            return None
        prefijo = "".join(ch for ch in tipo.codigo.upper() if ch.isalnum()) or "TRAM"
        anio = datetime.now().strftime("%Y")
        ahora = datetime.now().strftime("%Y-%m-%d %H:%M")
        existentes = len(s.exec(select(TramiteEmpleador).where(
            TramiteEmpleador.tipo_tramite_id == tipo_tramite_id)).all())
        numero = None
        for intento in range(25):
            candidato = f"{prefijo}-{anio}-{(existentes + 1 + intento):06d}"
            if not s.exec(select(TramiteEmpleador).where(TramiteEmpleador.numero_expediente == candidato)).first():
                numero = candidato
                break
        if not numero:
            raise RuntimeError("No se pudo generar un número de expediente único, reintentá.")
        tr = TramiteEmpleador(sindicato_id=sindicato_id, tipo_tramite_id=tipo_tramite_id, cuit=cuit,
                               numero_expediente=numero, estado="iniciado", creado=ahora, actualizado=ahora)
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
        tr.actualizado = datetime.now().strftime("%Y-%m-%d %H:%M")
        s.add(tr)
        _log_tramite_empleador(s, tramite_id, "cambio_estado",
                     f"{ESTADOS_TRAMITE_LABEL.get(anterior, anterior)} → {ESTADOS_TRAMITE_LABEL.get(nuevo_estado, nuevo_estado)}")
        s.commit()
        return True


def agregar_nota_tramite_empleador(tramite_id: int, autor: str, texto: str,
                                    adjunto_datos: Optional[bytes] = None, adjunto_mime: str = "",
                                    adjunto_nombre: str = "") -> bool:
    with Session(engine) as s:
        tr = s.get(TramiteEmpleador, tramite_id)
        if not tr or tr.estado == "terminado":
            return False
        s.add(NotaTramiteEmpleador(
            tramite_id=tramite_id, autor=autor, texto=texto or "",
            adjunto_datos=adjunto_datos, adjunto_mime=adjunto_mime or "",
            adjunto_nombre=adjunto_nombre or "", creado=datetime.now().strftime("%Y-%m-%d %H:%M"),
        ))
        tr.actualizado = datetime.now().strftime("%Y-%m-%d %H:%M")
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
    }


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
    return {
        "id": tr.id, "numero_expediente": tr.numero_expediente, "cuit": tr.cuit,
        "sindicato_id": tr.sindicato_id, "estado": tr.estado,
        "estado_label": ESTADOS_TRAMITE_LABEL.get(tr.estado, tr.estado),
        "creado": tr.creado, "actualizado": tr.actualizado,
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
            "tiene_adjunto": bool(n.adjunto_datos), "adjunto_nombre": n.adjunto_nombre,
        } for n in notas],
        "log": [{"evento": l.evento, "detalle": l.detalle, "creado": l.creado} for l in log],
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
