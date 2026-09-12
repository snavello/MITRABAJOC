"""Marca de la plataforma (colores + logo), configurable desde /plataforma,
con el mismo patrón que la marca de un sindicato.

Correr con: .venv/Scripts/python.exe -m pytest test_marca_plataforma.py -q
"""
import os

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
import main
from fastapi.testclient import TestClient

db.crear_tablas()
client = TestClient(main.app)
client.post("/plataforma/login", data={"cuit": "20000000000", "clave": "test-plataforma"})


def test_marca_por_defecto_sin_configurar():
    m = db.marca_plataforma()
    assert m["color_primario"] == "#152238"
    assert m["color_secundario"] == "#1a7a6b"
    assert m["logo"] == ""
    print("OK  test_marca_por_defecto_sin_configurar")


def test_actualizar_colores_sin_logo():
    r = client.post("/plataforma/marca", data={
        "color_primario": "#0a0a0a", "color_secundario": "#00ff00", "color_acento": "#ff00ff",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert "marca=ok" in r.headers.get("location", "")
    m = db.marca_plataforma()
    assert m["color_primario"] == "#0a0a0a"
    assert m["color_secundario"] == "#00ff00"
    assert m["color_acento"] == "#ff00ff"
    assert m["logo"] == "", "no se subió logo, no debe tener uno"
    print("OK  test_actualizar_colores_sin_logo")


def test_subir_logo():
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>'
    r = client.post("/plataforma/marca", data={
        "color_primario": "#0a0a0a", "color_secundario": "#00ff00", "color_acento": "#ff00ff",
    }, files={"logo": ("logo.svg", svg, "image/svg+xml")}, follow_redirects=False)
    assert r.status_code == 303
    m = db.marca_plataforma()
    assert m["logo"] == "logo.svg"

    r2 = client.get("/logo-plataforma")
    assert r2.status_code == 200
    assert r2.content == svg
    assert r2.headers["content-type"] == "image/svg+xml"
    print("OK  test_subir_logo")


def test_editar_colores_preserva_logo_si_no_se_sube_uno_nuevo():
    client.post("/plataforma/marca", data={
        "color_primario": "#111111", "color_secundario": "#222222", "color_acento": "#333333",
    })
    m = db.marca_plataforma()
    assert m["color_primario"] == "#111111"
    assert m["logo"] == "logo.svg", "editar colores no debe borrar el logo ya cargado"
    print("OK  test_editar_colores_preserva_logo_si_no_se_sube_uno_nuevo")


def test_logo_plataforma_404_sin_configurar():
    # Vaciar el logo (sin recrear la app: mismo motor, solo borra el binario)
    # para probar el caso "no hay logo cargado" sin depender del orden de tests.
    from sqlmodel import Session
    from db import ConfiguracionPlataforma, engine
    with Session(engine) as s:
        cfg = s.get(ConfiguracionPlataforma, 1)
        cfg.logo_datos, cfg.logo_mime, cfg.logo = None, "", ""
        s.add(cfg); s.commit()
    r = client.get("/logo-plataforma")
    assert r.status_code == 404
    print("OK  test_logo_plataforma_404_sin_configurar")


def test_no_autorizado_sin_sesion_de_plataforma():
    client_sin_sesion = TestClient(main.app)
    r = client_sin_sesion.post("/plataforma/marca", data={"color_primario": "#000000"})
    assert r.status_code == 403
    print("OK  test_no_autorizado_sin_sesion_de_plataforma")


def test_subir_logo_oscuro_no_toca_el_claro():
    svg_claro = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10" fill="navy"/></svg>'
    svg_oscuro = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10" fill="white"/></svg>'
    client.post("/plataforma/marca", data={
        "color_primario": "#0a0a0a", "color_secundario": "#00ff00", "color_acento": "#ff00ff",
    }, files={"logo": ("claro.svg", svg_claro, "image/svg+xml")}, follow_redirects=False)
    r = client.post("/plataforma/marca", data={
        "color_primario": "#0a0a0a", "color_secundario": "#00ff00", "color_acento": "#ff00ff",
    }, files={"logo_oscuro": ("oscuro.svg", svg_oscuro, "image/svg+xml")}, follow_redirects=False)
    assert r.status_code == 303
    m = db.marca_plataforma()
    # _leer_logo deriva el flag de la extensión, no del nombre real del
    # archivo (mismo criterio que test_subir_logo) -- lo que importa acá es
    # que subir el oscuro no haya tocado el binario del claro, verificado
    # abajo por contenido servido, no por el nombre del flag.
    assert m["logo"], "subir el oscuro no debe borrar el claro"
    assert m["logo_oscuro"]

    r_claro = client.get("/logo-plataforma")
    assert r_claro.content == svg_claro
    r_oscuro = client.get("/logo-plataforma-oscuro")
    assert r_oscuro.status_code == 200
    assert r_oscuro.content == svg_oscuro
    print("OK  test_subir_logo_oscuro_no_toca_el_claro")


def test_logo_oscuro_404_sin_configurar():
    from sqlmodel import Session
    from db import ConfiguracionPlataforma, engine
    with Session(engine) as s:
        cfg = s.get(ConfiguracionPlataforma, 1)
        cfg.logo_datos_oscuro, cfg.logo_mime_oscuro, cfg.logo_oscuro = None, "", ""
        s.add(cfg); s.commit()
    r = client.get("/logo-plataforma-oscuro")
    assert r.status_code == 404
    print("OK  test_logo_oscuro_404_sin_configurar")


if __name__ == "__main__":
    test_marca_por_defecto_sin_configurar()
    test_actualizar_colores_sin_logo()
    test_subir_logo()
    test_editar_colores_preserva_logo_si_no_se_sube_uno_nuevo()
    test_no_autorizado_sin_sesion_de_plataforma()
    test_subir_logo_oscuro_no_toca_el_claro()
    test_logo_oscuro_404_sin_configurar()
    test_logo_plataforma_404_sin_configurar()
    print("\nTodo OK — marca de la plataforma (colores + logo).")
