"""Recursos de la landing /entornos (recursos.py + rutas /recursos/* de
main.py): el catálogo mezcla los del repositorio con los subidos, ordenado
por fecha; abrir, subir y quitar exigen el pase de la landing (el PIN de
entorno.PIN_LANDING, cookie de 30 días) o una sesión de plataforma; nada de
esto existe en la demo. La puerta del PIN en sí se prueba en
test_entornos.py.

Correr con: .venv/Scripts/python.exe test_recursos.py
"""
import os
import tempfile
from datetime import date

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE
os.environ["ENTORNO"] = "pruebas"            # antes de importar main
os.environ["PIN_ENTORNOS"] = "12345678"      # antes de importar entorno
os.environ["PLATAFORMA_PASSWORD"] = "clave-de-prueba"   # antes de importar auth

import entorno
import recursos
import db
import auth
import main
from fastapi.testclient import TestClient

db.crear_tablas()
sin_pase = TestClient(main.app)

# Un <form> de página completa manda este Accept; el fetch del JS, no.
NAVEGADOR = {"Accept": "text/html,application/xhtml+xml"}


def _cliente_con_pase():
    c = TestClient(main.app)
    r = c.post("/entornos/pin", data={"pin": "12345678"}, follow_redirects=False)
    assert r.status_code == 303 and recursos.COOKIE_PASE in r.cookies
    return c


def test_catalogo_del_repositorio_ordenado_por_fecha():
    r = _cliente_con_pase().get("/entornos")
    assert r.status_code == 200
    assert 'id="recursos"' in r.text
    # Los dos documentos versionados, con su miniatura, su ancla y su fecha.
    assert 'href="/recursos/plan-maestro/archivo"' in r.text
    assert 'href="/recursos/plan-implementacion-sindicato/archivo#estrategia"' in r.text
    assert "/recursos/plan-maestro/miniatura?v=" in r.text
    assert "7 sep 2026" in r.text and "4 sep 2026" in r.text
    # Del más nuevo al más viejo: el plan maestro (7 sep) antes que el de
    # implementación (4 sep).
    assert r.text.index("Plan Maestro Colm3na") < r.text.index("Plan de implementación en el sindicato")
    # Con el pase, el formulario de alta está ahí; el de clave, ya no existe.
    assert 'id="form-recurso"' in r.text
    assert "Clave de plataforma" not in r.text
    assert "supera los 30 MB" in _cliente_con_pase().get("/entornos?aviso=tamanio").text
    print("OK  test_catalogo_del_repositorio_ordenado_por_fecha")


def test_sin_pase_nada_se_abre():
    # Un clic (navegación) vuelve a la landing, que pide el PIN; un fetch
    # recibe 403. La miniatura tampoco: está detrás del mismo pase.
    r = sin_pase.get("/recursos/plan-maestro/archivo", headers=NAVEGADOR, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/entornos"
    assert sin_pase.get("/recursos/plan-maestro/archivo").status_code == 403
    assert sin_pase.get("/recursos/plan-maestro/miniatura").status_code == 403
    assert sin_pase.post("/recursos", data={"titulo": "x"}).status_code == 403
    assert sin_pase.post("/recursos/1/quitar").status_code == 403
    r = sin_pase.get("/entornos")
    assert r.status_code == 200 and 'action="/entornos/pin"' in r.text
    assert "Plan Maestro Colm3na" not in r.text and "/recursos/" not in r.text
    print("OK  test_sin_pase_nada_se_abre")


def test_con_pase_se_sirven_los_del_repositorio():
    c = _cliente_con_pase()
    r = c.get("/recursos/plan-maestro/archivo")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "Plan maestro: primer sindicato, primer equipo" in r.text
    r = c.get("/recursos/plan-implementacion-sindicato/archivo")
    assert r.status_code == 200 and "Implementación en el sindicato" in r.text
    r = c.get("/recursos/plan-maestro/miniatura")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    # El video versionado: se sirve como MP4 y acepta rangos (FileResponse),
    # que es lo que el reproductor necesita para adelantar.
    r = c.get("/recursos/video-recibos-tramites/archivo", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and r.headers["content-type"] == "video/mp4"
    assert r.headers["content-range"].startswith("bytes 0-99/") and len(r.content) == 100
    assert c.get("/recursos/video-recibos-tramites/miniatura").status_code == 200
    assert '/recursos/video-recibos-tramites/archivo"' in c.get("/entornos").text
    assert c.get("/recursos/no-existe/miniatura").status_code == 404
    assert c.get("/recursos/no-existe/archivo").status_code == 404
    # El pase es un token propio, no una sesión de rol.
    assert recursos.pase_valido(c.cookies[recursos.COOKIE_PASE])
    assert not recursos.pase_valido("basura.firma")
    assert not recursos.pase_valido(auth.crear_sesion("plataforma"))
    print("OK  test_con_pase_se_sirven_los_del_repositorio")


def test_sesion_de_plataforma_tambien_abre():
    c = TestClient(main.app)
    r = c.post("/plataforma/login", data={"cuit": auth.CUIT_PLATAFORMA, "clave": "clave-de-prueba"},
               follow_redirects=False)
    assert r.status_code == 303 and main.COOKIE_PLATAFORMA in r.cookies
    assert c.get("/recursos/plan-maestro/archivo").status_code == 200
    assert 'id="recursos"' in c.get("/entornos").text
    print("OK  test_sesion_de_plataforma_tambien_abre")


def test_subir_catalogar_abrir_y_quitar():
    c = _cliente_con_pase()
    html = b"<!doctype html><title>Guia</title><h1>Gu\xc3\xada del administrador</h1>"
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    r = c.post("/recursos", data={
        "titulo": "  Guía del 'administrador'  ", "descripcion": "Cómo operar el panel.",
        "fecha": "2026-09-20", "fragmento": "padron",
    }, files={"archivo": ("guia-admin.html", html, "text/html"),
              "miniatura": ("miniatura.jpg", png, "image/png")})
    assert r.status_code == 200, r.text       # fetch: JSON con adónde ir
    j = r.json()
    assert j["ok"] and j["ir"] == f"/entornos?aviso=agregado&n={j['id']}#recurso-{j['id']}"
    rid = j["id"]

    # Aparece primero (20 sep es más nuevo que los del repositorio), con
    # su ancla normalizada, su miniatura y el botón de quitar.
    r = c.get("/entornos")
    assert r.text.index("Guía del") < r.text.index("Plan Maestro Colm3na")
    assert f'href="/recursos/{rid}/archivo#padron"' in r.text
    assert f'src="/recursos/{rid}/miniatura"' in r.text
    assert f'action="/recursos/{rid}/quitar"' in r.text
    # El título con comillas no rompe el confirm() del botón Quitar.
    assert "confirm(\"\\u00bfQuitar \\u00abGu\\u00eda del \\u0027administrador\\u0027\\u00bb" in r.text
    assert "20 sep 2026" in r.text
    # La lista no carga los bytes.
    fila = db.listar_recursos()[0]
    assert fila["titulo"] == "Guía del 'administrador'" and fila["tipo"] == "html"
    assert fila["fecha"] == date(2026, 9, 20) and "archivo_datos" not in fila

    r = c.get(f"/recursos/{rid}/archivo")
    assert r.status_code == 200 and r.content == html
    assert r.headers["content-type"] == "text/html; charset=utf-8"
    assert r.headers["accept-ranges"] == "bytes"
    r = c.get(f"/recursos/{rid}/miniatura")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content == png
    # Un rango, como el que pide el reproductor de video para adelantar.
    r = c.get(f"/recursos/{rid}/archivo", headers={"Range": "bytes=0-9"})
    assert r.status_code == 206 and r.content == html[:10]
    assert r.headers["content-range"] == f"bytes 0-9/{len(html)}"
    r = c.get(f"/recursos/{rid}/archivo", headers={"Range": f"bytes={len(html) + 5}-"})
    assert r.status_code == 416

    # Sin pase no se quita; con pase, desaparece.
    assert sin_pase.post(f"/recursos/{rid}/quitar").status_code == 403
    r = c.post(f"/recursos/{rid}/quitar", headers=NAVEGADOR, follow_redirects=False)
    assert r.status_code == 303 and "aviso=quitado" in r.headers["location"]
    assert "Guía del" not in c.get("/entornos").text
    assert c.get(f"/recursos/{rid}/archivo").status_code == 404
    assert c.post(f"/recursos/{rid}/quitar").status_code == 404
    print("OK  test_subir_catalogar_abrir_y_quitar")


def test_enlace_sin_archivo_redirige():
    c = _cliente_con_pase()
    r = c.post("/recursos", data={"titulo": "Video de difusión", "url": "https://youtu.be/abc",
                                   "fecha": "2026-08-30"})
    rid = r.json()["id"]
    assert [x for x in db.listar_recursos() if x["id"] == rid][0]["tipo"] == "enlace"
    r = c.get(f"/recursos/{rid}/archivo", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "https://youtu.be/abc"
    # En la tarjeta: sin miniatura, va la portada dibujada con el host.
    r = c.get("/entornos")
    assert 'ic-tipo-enlace' in r.text and f'id="recurso-{rid}"' in r.text
    assert '<span>youtu.be</span>' in r.text
    assert recursos.texto_portada("archivo", "", "Presupuesto.xlsx") == "XLSX"
    assert recursos.texto_portada("pdf", "", "") == "PDF"
    assert recursos.texto_portada("enlace", "https://www.claude.ai/code/x", "") == "claude.ai"
    # El enlace no se abre sin pase (misma regla que los archivos).
    assert sin_pase.get(f"/recursos/{rid}/archivo").status_code == 403
    db.borrar_recurso(rid)
    print("OK  test_enlace_sin_archivo_redirige")


def test_validaciones_del_alta(monkeypatch):
    c = _cliente_con_pase()
    # fetch: JSON 400 con código; <form>: vuelve a la landing con el aviso.
    r = c.post("/recursos", data={"titulo": ""}, files={"archivo": ("a.txt", b"x", "text/plain")})
    assert r.status_code == 400 and r.json()["codigo"] == "titulo"
    r = c.post("/recursos", data={"titulo": "Sin nada"})
    assert r.status_code == 400 and r.json()["codigo"] == "archivo"
    r = c.post("/recursos", data={"titulo": "Sin nada"}, headers=NAVEGADOR, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/entornos?aviso=archivo#alta"
    r = c.post("/recursos", data={"titulo": "Mal enlace", "url": "ftp://x"})
    assert r.json()["codigo"] == "enlace"
    r = c.post("/recursos", data={"titulo": "Vacío"}, files={"archivo": ("a.txt", b"", "text/plain")})
    assert r.json()["codigo"] == "vacio"
    r = c.post("/recursos", data={"titulo": "Mini"}, files={"archivo": ("a.txt", b"x", "text/plain"),
                                                            "miniatura": ("m.txt", b"no", "text/plain")})
    assert r.json()["codigo"] == "miniatura"
    monkeypatch.setattr(recursos, "TAMANIO_MAX", 10)
    r = c.post("/recursos", data={"titulo": "Grande"}, files={"archivo": ("a.bin", b"x" * 11, "application/octet-stream")})
    assert r.json()["codigo"] == "tamanio"
    assert db.listar_recursos() == []
    # La fecha inválida no rompe: cae en hoy; la ancla se normaliza.
    assert recursos.leer_fecha("no-es-fecha") == date.today()
    assert recursos.normalizar_fragmento("estrategia") == "#estrategia"
    assert recursos.normalizar_fragmento(" #plan ") == "#plan"
    print("OK  test_validaciones_del_alta")


def test_tipos():
    assert recursos.tipo_de("text/html", "a.html") == "html"
    assert recursos.tipo_de("text/html; charset=utf-8", "a.html") == "html"
    assert recursos.tipo_de("application/octet-stream", "Plan.HTML") == "html"
    assert recursos.tipo_de("application/pdf", "a.pdf") == "pdf"
    assert recursos.tipo_de("", "foto.jpg") == "imagen"
    assert recursos.tipo_de("video/mp4", "v.mp4") == "video"
    assert recursos.tipo_de("audio/mpeg", "a.mp3") == "audio"
    assert recursos.tipo_de("", "", "https://x") == "enlace"
    assert recursos.tipo_de("application/vnd.ms-excel", "a.xls") == "archivo"
    assert recursos.mime_de("", "a.html") == "text/html; charset=utf-8"
    assert recursos.tamanio_legible(73_000) == "71 KB"
    assert recursos.tamanio_legible(12_968_751) == "12.4 MB"
    print("OK  test_tipos")


def test_en_la_demo_nada_de_esto_existe(monkeypatch):
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", False)
    c = _cliente_con_pase() if False else TestClient(main.app)
    assert c.get("/recursos/plan-maestro/archivo").status_code == 404
    assert c.get("/recursos/plan-maestro/miniatura").status_code == 404
    assert c.post("/entornos/pin", data={"pin": "12345678"}).status_code == 404
    assert c.post("/recursos", data={"titulo": "x"}).status_code == 404
    assert c.post("/recursos/1/quitar").status_code == 404
    print("OK  test_en_la_demo_nada_de_esto_existe")


if __name__ == "__main__":
    import pytest, sys
    sys.exit(pytest.main([__file__, "-q"]))
