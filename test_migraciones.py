"""El esquema de las migraciones tiene que ser el de los modelos.

`conftest.py` promete este archivo desde que la suite pasó a Postgres ("que
el esquema de las migraciones coincida con el de los modelos es otra cosa, y
se verifica aparte") pero nunca existió. Este es.

**Por qué importa.** La suite arma su base con `create_all`, o sea con los
MODELOS; producción la arma Alembic. Si los dos no dicen lo mismo, los tests
pasan contra un esquema que no es el que corre — que es exactamente el
defecto por el que se sacó SQLite el 2026-09-11, solo que adentro del mismo
motor y por eso mucho más difícil de ver.

Pasó de verdad: quince columnas JSON estaban declaradas `JSON` en los modelos
y `JSONB` en las migraciones. Para leer y escribir un dict entero los dos
tipos se comportan igual, así que nada falló nunca; pero `json` no tiene
operador de igualdad ni se puede indexar, así que la primera consulta que
usara eso habría andado en la suite y roto en producción.

Correr con: .venv/bin/python -m pytest test_migraciones.py -q
"""
import os
import uuid
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

import db

# Alembic tarda ~1,5 s en levantar el esquema entero desde cero, así que se
# hace UNA vez por archivo y se comparan todas las tablas con eso.
NOMBRE = f"mitrabajo_mig_{os.getpid()}_{uuid.uuid4().hex[:6]}"


def _url_con_base(url: str, base: str) -> str:
    partes = urlsplit(url)
    return urlunsplit((partes.scheme, partes.netloc, "/" + base, partes.query, partes.fragment))


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture(scope="module")
def esquema_alembic():
    """Una base levantada SOLO con `alembic upgrade head`, y sus columnas.

    Alembic corre en un SUBPROCESO y no con `command.upgrade` acá adentro:
    `migrations/env.py` usa `db.engine` directamente (a propósito, para leer
    DATABASE_URL igual que la app) y no la URL de `alembic.ini`, así que
    llamarlo en este proceso levantaría las migraciones sobre la base de la
    suite -- que `create_all` ya llenó. Con el subproceso se corre igual que
    lo corre una persona: una variable de entorno y nada más.

    No hace falta crear la extensión `vector` a mano: la crea la migración
    del RAG (f4d1a7c39e02), que es parte de lo que se está verificando.
    """
    import subprocess
    import sys

    base_url = str(db.engine.url.render_as_string(hide_password=False))
    url_admin = _psycopg(_url_con_base(base_url, "postgres"))
    url_mig = _url_con_base(base_url, NOMBRE)

    with psycopg.connect(url_admin, autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{NOMBRE}"')
    try:
        r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                           env={**os.environ, "DATABASE_URL": url_mig},
                           capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, ("`alembic upgrade head` falló sobre una base "
                                   f"limpia:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
        yield _columnas(_psycopg(url_mig))
    finally:
        with psycopg.connect(url_admin, autocommit=True) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{NOMBRE}" WITH (FORCE)')


def _columnas(url: str) -> dict:
    """{(tabla, columna): (tipo, admite_nulos)} de una base."""
    with psycopg.connect(url) as c:
        filas = c.execute(
            "SELECT table_name, column_name, data_type, is_nullable "
            "FROM information_schema.columns WHERE table_schema = 'public'").fetchall()
    return {(t, col): (tipo, nulos) for t, col, tipo, nulos in filas
            if t != "alembic_version"}


@pytest.fixture(scope="module")
def esquema_modelos():
    """Las columnas de la base de la suite, que `conftest.py` armó con
    `create_all` a partir de los modelos."""
    return _columnas(_psycopg(str(db.engine.url.render_as_string(hide_password=False))))


def test_las_mismas_tablas(esquema_modelos, esquema_alembic):
    tablas_modelos = {t for t, _ in esquema_modelos}
    tablas_alembic = {t for t, _ in esquema_alembic}
    faltan = tablas_modelos - tablas_alembic
    sobran = tablas_alembic - tablas_modelos
    assert not faltan, f"hay modelos sin migración: {sorted(faltan)}"
    assert not sobran, f"hay tablas que ninguna migración borró: {sorted(sobran)}"
    print(f"OK  test_las_mismas_tablas ({len(tablas_modelos)} tablas)")


def test_las_mismas_columnas(esquema_modelos, esquema_alembic):
    faltan = esquema_modelos.keys() - esquema_alembic.keys()
    sobran = esquema_alembic.keys() - esquema_modelos.keys()
    assert not faltan, f"columnas del modelo que ninguna migración crea: {sorted(faltan)}"
    assert not sobran, f"columnas que la migración crea y el modelo no tiene: {sorted(sobran)}"
    print(f"OK  test_las_mismas_columnas ({len(esquema_modelos)} columnas)")


def test_los_mismos_tipos(esquema_modelos, esquema_alembic):
    """El que encontró las quince columnas `json` contra `jsonb`."""
    dif = {k: (esquema_modelos[k][0], esquema_alembic[k][0])
           for k in esquema_modelos.keys() & esquema_alembic.keys()
           if esquema_modelos[k][0] != esquema_alembic[k][0]}
    detalle = "\n".join(f"    {t}.{c}: modelo={a}  migración={b}"
                        for (t, c), (a, b) in sorted(dif.items()))
    assert not dif, ("el modelo y la migración declaran tipos distintos:\n" + detalle)
    print("OK  test_los_mismos_tipos")


def test_la_misma_obligatoriedad(esquema_modelos, esquema_alembic):
    """Una columna NOT NULL en el modelo y nullable en la base (o al revés)
    deja pasar en la suite filas que producción rechaza, o al revés."""
    dif = {k: (esquema_modelos[k][1], esquema_alembic[k][1])
           for k in esquema_modelos.keys() & esquema_alembic.keys()
           if esquema_modelos[k][1] != esquema_alembic[k][1]}
    detalle = "\n".join(f"    {t}.{c}: modelo admite nulos={a}  migración={b}"
                        for (t, c), (a, b) in sorted(dif.items()))
    assert not dif, ("el modelo y la migración no coinciden en qué es obligatorio:\n"
                     + detalle)
    print("OK  test_la_misma_obligatoriedad")
