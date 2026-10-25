"""«Portada clara», retirada (auditoría R2-03, 2026-10-25).

Fue una opción por sindicato (portada del trabajador y del admin) y de la
plataforma. Con los dos modelos de diseño (PLAN_TEMAS.md) la portada la
define el modelo que elige cada persona y la casilla no cambiaba nada, así
que se sacó. Las columnas quedan en la base (sin migración), pero:

- plataforma ya no ofrece las casillas (alta, edición y Marca);
- ninguna ruta las escribe: un POST armado a mano con el campo no cambia nada,
  ni para prender ni para apagar lo que ya estuviera guardado;
- marca_sindicato() y marca_plataforma() no las exponen, así que ninguna
  plantilla puede depender de ellas;
- la portada de plataforma va siempre con el cuerpo «oscuro» (el modelo la
  pinta) y sus hojas no tienen variante clara.

Correr con: python -m pytest test_portada_clara.py -q
"""
import os
import re
from pathlib import Path

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
from db import Sindicato
import main
import temas
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()

plataforma_client = TestClient(main.app)
plataforma_client.post("/plataforma/login", data={"cuit": "20000000000", "clave": "test-plataforma"})


def _datos_base(**overrides):
    datos = {
        "nombre": "Sindicato Test Portada Clara", "descripcion": "", "cuit": "",
        "direccion": "", "mail": "", "telefonos": "", "autoridad": "", "cargo_autoridad": "",
        "color_primario": "#152238", "color_secundario": "#1a7a6b", "color_acento": "#b23a2e",
        "color_base": "#0f1b2d",
    }
    datos.update(overrides)
    return datos


def _sindicato(nombre):
    with Session(db.engine) as s:
        return s.exec(select(Sindicato).where(Sindicato.nombre == nombre)).first()


def test_la_pantalla_no_ofrece_las_casillas():
    html = plataforma_client.get("/plataforma").text
    for nombre in ("portada_clara", "admin_portada_clara"):
        assert f'name="{nombre}"' not in html, nombre
    assert "sind-portada-clara" not in html and "sind-admin-portada-clara" not in html
    assert "Portada clara" not in html
    # el JSON de «Editar» tampoco las lleva
    assert '"portada_clara"' not in html and "portada_clara" not in html
    # en su lugar, una línea que dice quién define la portada
    assert "La portada la define el modelo de diseño (Laguna o Noticiero)" in html


def test_el_alta_ignora_el_campo():
    r = plataforma_client.post("/plataforma/sindicato", data=_datos_base(
        nombre="Sindicato Retiro Portada 1", portada_clara="true", admin_portada_clara="true",
    ), follow_redirects=False)
    assert r.status_code == 303
    sind = _sindicato("Sindicato Retiro Portada 1")
    assert sind is not None
    assert sind.portada_clara is False and sind.admin_portada_clara is False


def test_la_edicion_no_toca_lo_guardado():
    """Ni prende ni apaga: un valor viejo queda como estaba (la columna no se
    usa), y un POST con el campo no lo cambia."""
    r = plataforma_client.post("/plataforma/sindicato", data=_datos_base(
        nombre="Sindicato Retiro Portada 2"), follow_redirects=False)
    assert r.status_code == 303
    sid = _sindicato("Sindicato Retiro Portada 2").id
    with Session(db.engine) as s:
        sind = s.get(Sindicato, sid)
        sind.portada_clara, sind.admin_portada_clara = True, True
        s.add(sind); s.commit()
    r = plataforma_client.post("/plataforma/sindicato/editar", data=_datos_base(
        id=sid, nombre="Sindicato Retiro Portada 2"), follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        sind = s.get(Sindicato, sid)
        assert sind.portada_clara is True and sind.admin_portada_clara is True


def test_la_marca_no_la_expone():
    sid = _sindicato("Sindicato Retiro Portada 2").id     # tiene las dos en True
    marca = db.marca_sindicato(sid)
    assert "portada_clara" not in marca and "admin_portada_clara" not in marca
    assert "portada_clara" not in db.marca_plataforma()


def test_la_marca_de_plataforma_ignora_el_campo():
    r = plataforma_client.post("/plataforma/marca", data={
        "color_primario": "#152238", "color_secundario": "#1a7a6b",
        "color_acento": "#b23a2e", "portada_clara": "true",
    }, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        cfg = s.get(db.ConfiguracionPlataforma, 1)
        assert cfg.portada_clara is False


def test_la_portada_de_plataforma_va_siempre_con_el_modelo():
    with Session(db.engine) as s:
        cfg = s.get(db.ConfiguracionPlataforma, 1) or db.ConfiguracionPlataforma(id=1)
        cfg.portada_clara = True                     # un valor viejo en la base
        s.add(cfg); s.commit()
    try:
        html = plataforma_client.get("/plataforma/inicio").text
        assert '<body class="oscuro">' in html
    finally:
        with Session(db.engine) as s:
            cfg = s.get(db.ConfiguracionPlataforma, 1)
            cfg.portada_clara = False
            s.add(cfg); s.commit()
    for modelo in temas.TEMAS:
        css = Path(f"static/temas/{modelo}-plataforma-portada.css").read_text(encoding="utf-8")
        assert not re.search(r"body\.claro", re.sub(r"/\*.*?\*/", "", css, flags=re.S)), modelo


def test_ningun_codigo_escribe_ni_lee_la_opcion():
    """Fuera de la declaración de las columnas (db.py) y de este test, nada
    de Python ni de las plantillas de plataforma nombra la opción."""
    for archivo in ("main.py", "cargar_marca_plataforma.py", "templates/plataforma.html",
                    "templates/plataforma_portada.html", "templates/portada.html",
                    "templates/admin_portada.html"):
        assert "portada_clara" not in Path(archivo).read_text(encoding="utf-8"), archivo
    db_py = Path("db.py").read_text(encoding="utf-8")
    usos = [l.strip() for l in db_py.splitlines() if "portada_clara" in l and not l.strip().startswith("#")]
    assert usos == ["portada_clara: bool = Field(default=False)",
                    "admin_portada_clara: bool = Field(default=False)",
                    "portada_clara: bool = Field(default=False)"], usos


def test_no_quedan_estilos_de_la_portada_clara():
    """Ninguna hoja ni plantilla conserva reglas para `body.claro`: sin la
    opción, nadie pone esa clase y serían reglas muertas."""
    archivos = [*Path("static").glob("*.css"), *Path("static/temas").glob("*.css"),
                *Path("templates").glob("*.html")]
    for f in archivos:
        texto = re.sub(r"/\*.*?\*/", "", f.read_text(encoding="utf-8"), flags=re.S)
        assert not re.search(r"body\.claro\b", texto), f
    for nombre in ("portada", "admin_portada"):
        html = Path(f"templates/{nombre}.html").read_text(encoding="utf-8")
        assert '<body class="oscuro grano grano-osc">' in html, nombre
