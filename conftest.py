"""Conftest global de la suite: cada proceso de pytest corre contra su
propia base POSTGRES, creada al empezar y borrada al terminar.

Los tests corrían en un SQLite temporal por archivo. Era rápido, pero
validaba un motor que el proyecto NO USA -- y eso se pagó el 2026-09-11 con
tres defectos que la suite daba por buenos: un `sindicato_id` que no existía
(SQLite no valida claves foráneas por defecto), un test que suponía la base
recién nacida y una consulta sin acotar que devolvía varias filas. Los tres
pasaban en verde y los tres hubieran roto en producción.

Cómo funciona:

- `DATABASE_URL` (del entorno o del `.env`) apunta al servidor de Postgres
  de desarrollo, el del `docker-compose.yml`. De ahí se toma el SERVIDOR,
  no la base: la base de trabajo no se toca nunca.
- Se crea `mitrabajo_test_<pid>_<azar>`, se le instala la extensión
  `vector` (la necesita FragmentoConvenio, del RAG) y se le arma el esquema
  completo con `create_all`. Recién ahí se importan los test_*.py.
- Al terminar el proceso, la base se borra. Si pytest muere de una forma
  que no deja correr esto, quedan bases `mitrabajo_test_*` sueltas: se
  limpian con `python chequeo.py --limpiar-bases-de-test`.

El nombre lleva el PID porque la convención del proyecto es correr UN
ARCHIVO POR PROCESO (ver "Comandos útiles" en CLAUDE.md): así dos archivos
corriendo a la vez nunca comparten base, igual que antes no compartían
archivo de SQLite.
"""
import os
import uuid
from urllib.parse import urlsplit, urlunsplit

import psycopg
from dotenv import load_dotenv

load_dotenv()

_URL_BASE = os.getenv("DATABASE_URL", "").strip()
if not _URL_BASE:
    raise RuntimeError(
        "La suite necesita Postgres y no hay DATABASE_URL.\n"
        "Levantá el Postgres de desarrollo con `docker compose up -d` y "
        "poné DATABASE_URL en el .env (ver .env.example).\n"
        "SQLite ya no se usa en este proyecto.")


def _url_con_base(url: str, base: str) -> str:
    partes = urlsplit(url)
    return urlunsplit((partes.scheme, partes.netloc, "/" + base,
                       partes.query, partes.fragment))


def _url_psycopg(url: str) -> str:
    """psycopg no entiende el prefijo +psycopg de SQLAlchemy."""
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


NOMBRE_BASE = f"mitrabajo_test_{os.getpid()}_{uuid.uuid4().hex[:6]}"
_URL_ADMIN = _url_psycopg(_url_con_base(_URL_BASE, "postgres"))
_URL_TEST = _url_con_base(_URL_BASE, NOMBRE_BASE)

with psycopg.connect(_URL_ADMIN, autocommit=True) as _c:
    _c.execute(f'CREATE DATABASE "{NOMBRE_BASE}"')
with psycopg.connect(_url_psycopg(_URL_TEST), autocommit=True) as _c:
    _c.execute("CREATE EXTENSION IF NOT EXISTS vector")

# Antes de cualquier "import db" de los test_*.py.
os.environ["DATABASE_URL"] = _URL_TEST

# Si db ya estaba importado, este conftest llegó tarde: pasa cuando alguien
# corre `python test_x.py` en vez de `python -m pytest test_x.py`. El módulo
# se importa como __main__ ANTES de que pytest.main() cargue este archivo,
# así que el engine ya quedó apuntando a la base del .env -- la de
# desarrollo, con datos de verdad, que el test estaría por llenar de basura.
# Mejor cortar acá que descubrirlo después.
import sys  # noqa: E402

if "db" in sys.modules:
    raise RuntimeError(
        "Los tests se corren con `python -m pytest test_x.py`, no con "
        "`python test_x.py`: así este conftest levanta una base descartable "
        "ANTES de que se importe db. Tal como lo corriste, el test "
        "escribiría en tu base de desarrollo.")

import db  # noqa: E402

# El esquema lo arma create_all y no Alembic: correr 59 migraciones por
# archivo de test multiplicaría por diez lo que tarda la suite. Que el
# esquema de las migraciones coincida con el de los modelos es otra cosa, y
# se verifica aparte (test_migraciones.py).
db.crear_tablas()


def pytest_sessionfinish(session, exitstatus):
    db.engine.dispose()
    try:
        with psycopg.connect(_URL_ADMIN, autocommit=True) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{NOMBRE_BASE}" WITH (FORCE)')
    except Exception as e:      # que un error limpiando no tape el resultado
        print(f"\n[conftest] no se pudo borrar {NOMBRE_BASE}: {e}")
