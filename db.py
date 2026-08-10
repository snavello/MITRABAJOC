"""Capa de datos con SQLModel (SQLite).

Todo lo que la aplicación lee o modifica vive acá: conceptos, fórmulas,
reportes. El archivo de base se ubica en la ruta que indique DB_PATH
(por defecto data/validador.db). En Render, DB_PATH apunta al disco
persistente para que los datos sobrevivan a los reinicios.

La primera vez que arranca, si la base está vacía, se cargan los conceptos
y fórmulas iniciales desde data/seed_aefip.json (solo como semilla).
"""
import os
import json
from pathlib import Path
from typing import Optional
from datetime import datetime

from sqlmodel import SQLModel, Field, create_engine, Session, select, Column, JSON


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
    # Firma digitalizada de la autoridad, para la credencial sindical del
    # trabajador. Misma estrategia que el logo: el binario va en la base y se
    # sirve por /firma/{id}; `firma` es el flag "tiene firma cargada".
    firma: str = ""
    firma_datos: Optional[bytes] = Field(default=None)
    firma_mime: str = ""
    activo: bool = True


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
    Con esto entra, sin importar en cuántos sindicatos esté empadronado."""
    id: Optional[int] = Field(default=None, primary_key=True)
    cuil: str = Field(index=True, unique=True)
    clave_hash: str = ""
    nombre: str = ""


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


class Reporte(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(default=1, foreign_key="sindicato.id", index=True)
    fecha: str
    cuil: str = ""
    periodo: str = ""
    estado: str = "nuevo"          # "nuevo" | "en_revision" | "resuelto"
    detalle: dict = Field(default={}, sa_column=Column(JSON))


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


# ---------- Inicialización ----------
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
             "fecha_desde": f.fecha_desde, "fecha_hasta": f.fecha_hasta}
            for f in s.exec(q).all() if f.activa
        ]


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


def marca_sindicato(sindicato_id: int) -> dict:
    """Devuelve la marca (nombre, logo, colores) de un sindicato para pintar la app."""
    with Session(engine) as s:
        sind = s.get(Sindicato, sindicato_id)
        if not sind:
            return {}
        return {
            "id": sind.id, "nombre": sind.nombre, "logo": sind.logo,
            "color_primario": sind.color_primario,
            "color_secundario": sind.color_secundario,
            "color_acento": sind.color_acento,
            # Para la credencial sindical del trabajador
            "autoridad": sind.autoridad, "cargo_autoridad": sind.cargo_autoridad,
            "firma": sind.firma,
            "direccion": sind.direccion, "telefonos": sind.telefonos,
        }


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
                    "color_secundario": "#1a7a6b", "color_acento": "#b23a2e"}
        return {
            "logo": cfg.logo,
            "color_primario": cfg.color_primario or "#152238",
            "color_secundario": cfg.color_secundario or "#1a7a6b",
            "color_acento": cfg.color_acento or "#b23a2e",
        }


def set_marca_plataforma(color_primario: str, color_secundario: str, color_acento: str,
                          logo_datos: bytes = None, logo_mime: str = "", logo_flag: str = ""):
    with Session(engine) as s:
        cfg = s.get(ConfiguracionPlataforma, 1)
        if not cfg:
            cfg = ConfiguracionPlataforma(id=1)
        cfg.color_primario = color_primario or "#152238"
        cfg.color_secundario = color_secundario or "#1a7a6b"
        cfg.color_acento = color_acento or "#b23a2e"
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
