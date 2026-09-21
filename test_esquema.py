"""Sala de mando (GET /entornos/esquema + GET /api/entornos/esquema): el
esquema físico de la plataforma con los indicadores reales del entorno
(esquema.py). Mismo gate que la landing: existe solo donde hay distintivo,
pide pase, y en la demo responde 404.

Correr con: .venv/Scripts/python.exe -m pytest test_esquema.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"          # antes de importar main
os.environ["PIN_ENTORNOS"] = "24681357"    # antes de importar entorno
os.environ["PIN_ENTORNOS_HABILITADO"] = "1"

from datetime import datetime

import db
import entorno
import esquema
import fechas
import main
import recursos
from fastapi.testclient import TestClient
from sqlmodel import select

db.crear_tablas()


def _sindicato() -> int:
    with db.get_session() as s:
        sd = s.exec(select(db.Sindicato).where(db.Sindicato.nombre == "Gremio Esquema")).first()
        if not sd:
            sd = db.Sindicato(nombre="Gremio Esquema", cuit="30777777770", activo=True)
            s.add(sd)
            s.commit()
            s.refresh(sd)
        return sd.id


def test_kpis_en_un_dia_sin_movimiento_dan_cero():
    with db.get_session() as s:
        k = esquema.kpis(s, ahora=datetime(2031, 1, 1, 10, 0))
    assert k["recibos_hoy"] == 0 and k["lecturas_hoy"] == 0 and k["costo_hoy_usd"] == 0.0
    assert k["en_linea_total"] == 0 and k["en_linea"] == {}
    assert k["minutos_en_linea"] == 15
    print("OK  test_kpis_en_un_dia_sin_movimiento_dan_cero")


def test_kpis_cuentan_lo_de_hoy_y_los_ingresos_recientes():
    sid = _sindicato()
    ahora = fechas.ahora()
    hoy = ahora.strftime("%Y-%m-%d %H:%M")
    with db.get_session() as s:
        s.add(db.ReciboVerificado(sindicato_id=sid, cuil="20111111119", fecha=hoy[:10],
                                  estado="OK", procesado_en=hoy))
        s.add(db.ReciboVerificado(sindicato_id=sid, cuil="20111111119", fecha="2020-01-01",
                                  estado="OK", procesado_en="2020-01-01 10:00"))
        s.add(db.UsoIA(sindicato_id=sid, tipo="recibo", modelo="claude-sonnet-4-6",
                       tokens_entrada=1000, tokens_salida=500, fecha=hoy,
                       precio_entrada=3.0, precio_salida=15.0))
        s.add(db.UsoIA(sindicato_id=sid, tipo="prueba", modelo="claude-sonnet-4-6",
                       tokens_entrada=1000, tokens_salida=500, fecha=hoy,
                       precio_entrada=3.0, precio_salida=15.0))   # "prueba" no es gasto de recibos
        s.add(db.AccesoLog(rol="trabajador", sindicato_id=sid, fecha=hoy))
        s.add(db.AccesoLog(rol="admin", sindicato_id=sid, fecha="2020-01-01 10:00"))  # viejo: no cuenta
        s.add(db.Trabajador(sindicato_id=sid, cuil="20111111119", nombre="Ana", registrado=True))
        s.add(db.Trabajador(sindicato_id=sid, cuil="27222222224", nombre="Bea", registrado=False))
        s.commit()
        k = esquema.kpis(s, ahora=ahora)
    assert k["recibos_hoy"] == 1 and k["recibos_total"] >= 2
    assert k["lecturas_hoy"] == 1
    assert k["costo_hoy_usd"] == round(1000 / 1e6 * 3.0 + 500 / 1e6 * 15.0, 2)
    assert k["en_linea"] == {"trabajador": 1} and k["en_linea_total"] == 1
    assert "Gremio Esquema" in k["sindicatos"]
    assert k["padron"] >= 2 and k["registrados"] >= 1
    print("OK  test_kpis_cuentan_lo_de_hoy_y_los_ingresos_recientes")


def test_sin_pase_no_se_ve_y_con_pase_dibuja_con_datos():
    c = TestClient(main.app)
    navegador = {"Accept": "text/html,application/xhtml+xml"}
    r = c.get("/entornos/esquema", headers=navegador, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/entornos")
    assert c.get("/entornos/esquema").status_code == 403        # un fetch sin pase: 403, no redirección
    assert c.get("/api/entornos/esquema").status_code == 403
    assert c.post("/entornos/pin", data={"pin": "24681357"}, follow_redirects=False).status_code == 303
    r = c.get("/entornos/esquema")
    assert r.status_code == 200 and "Sala de mando" in r.text and 'id="datos-vivos"' in r.text
    assert "{% raw %}" not in r.text        # Jinja procesó la plantilla entera
    assert 'className = "burbuja"' in r.text and "dataset.detalle" in r.text   # detalle largo en burbuja, no en la tarjeta
    d = c.get("/api/entornos/esquema").json()
    assert d["entorno"] == "pruebas" and "kpis" in d and "versiones" in d
    assert d["seguridad"] is not None and "bloquean" in d["seguridad"]
    assert d["semaforo"] is None           # sin GRAFANA_URL en la suite: "sin dato", no inventado
    print("OK  test_sin_pase_no_se_ve_y_con_pase_dibuja_con_datos")


def test_esta_en_el_catalogo_de_recursos_como_enlace():
    fichas = [f for f in recursos.catalogo() if f["ref"] == "sala-de-mando"]
    assert fichas and fichas[0]["tipo"] == "enlace" and fichas[0]["href"] == "/entornos/esquema"
    assert recursos.del_repositorio_por_clave("sala-de-mando") is None   # no es un archivo
    print("OK  test_esta_en_el_catalogo_de_recursos_como_enlace")


def test_en_la_demo_no_existe(monkeypatch):
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", False)
    c = TestClient(main.app)
    assert c.get("/entornos/esquema").status_code == 404
    assert c.get("/api/entornos/esquema").status_code == 404
    print("OK  test_en_la_demo_no_existe")


def test_logos_vendoreados_y_cada_marca_del_esquema_esta_en_el_sprite():
    import re
    from pathlib import Path
    raiz = Path(main.__file__).parent
    sprite = (raiz / "static" / "marcas.svg").read_text(encoding="utf-8")
    plantilla = (raiz / "templates" / "esquema.html").read_text(encoding="utf-8")
    assert "jsdelivr" not in plantilla and "unpkg" not in plantilla        # jamás CDN
    assert "sello_static('marcas.svg')" in plantilla and "sello_static('marcas/arca.png')" in plantilla
    marcas = set(re.findall(r'marca:"([a-z]+)"', plantilla)) - {"arca"}
    assert marcas, "la plantilla tiene que declarar marcas"
    for m in marcas:
        assert f'id="m-{m}"' in sprite, f"falta el logo de {m} en static/marcas.svg"
    c = TestClient(main.app)
    assert c.get("/static/marcas.svg").status_code == 200
    assert c.get("/static/marcas/arca.png").status_code == 200
    print("OK  test_logos_vendoreados_y_cada_marca_del_esquema_esta_en_el_sprite")


def test_pestana_observabilidad_con_dos_pastillas_y_sala_de_mando_por_defecto():
    c = TestClient(main.app)
    assert c.post("/entornos/pin", data={"pin": "24681357"}, follow_redirects=False).status_code == 303
    t = c.get("/entornos").text
    assert 'data-obs="sala"' in t and 'data-obs="tecnica"' in t
    assert 'class="obs-pastilla activa" role="tab" aria-selected="true" data-obs="sala"' in t
    assert 'data-src="/entornos/esquema?embebida=1"' in t and 'data-tab="actividad"' not in t
    # la Sala se abre a pantalla completa: capa fija con el logo y el botón de volver
    assert 'id="sala-full"' in t and 'id="sala-cerrar"' in t and 'id="sala-abrir"' in t
    assert 'class="sala-barra"' not in t       # la cápsula de la landing se fue
    # la Sala trae su logo y su botón circular de volver; la bajada larga ya no está
    s = c.get("/entornos/esquema").text
    assert 'id="volver"' in s and 'alt="Colm3na"' in s and "Todo lo que corre entre" not in s
    assert 'window.parent.postMessage({sala:"cerrar"}' in s
    assert "ev.data.sala === 'cerrar'" in t    # y la landing lo escucha
    print("OK  test_pestana_observabilidad_con_dos_pastillas_y_sala_de_mando_por_defecto")


def test_embebida_permite_el_marco_desde_el_mismo_origen_y_suelta_no():
    c = TestClient(main.app)
    assert c.post("/entornos/pin", data={"pin": "24681357"}, follow_redirects=False).status_code == 303
    r = c.get("/entornos/esquema?embebida=1")
    assert r.headers["x-frame-options"] == "SAMEORIGIN"
    assert "frame-ancestors 'self'" in r.headers["content-security-policy"]
    r = c.get("/entornos/esquema")
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    print("OK  test_embebida_permite_el_marco_desde_el_mismo_origen_y_suelta_no")
