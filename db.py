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


class Concepto(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(default=1, foreign_key="sindicato.id", index=True)
    codigo: str = Field(index=True)
    nombre: str
    tipo: str                      # "ingreso" | "descuento"
    remunerativo: bool = True
    alias: list = Field(default=[], sa_column=Column(JSON))
    pendiente_revision: bool = False


class Formula(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(default=1, foreign_key="sindicato.id", index=True)
    target: str                    # código del concepto que controla
    descripcion: str
    expr: str                      # ej: "0.015 * base_remunerativa"
    tolerancia: float = 1.0
    activa: bool = True


class Reporte(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    sindicato_id: int = Field(default=1, foreign_key="sindicato.id", index=True)
    fecha: str
    cuil: str = ""
    periodo: str = ""
    estado: str = "nuevo"          # "nuevo" | "en_revision" | "resuelto"
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
             "expr": f.expr, "tolerancia": f.tolerancia}
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
        }


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
