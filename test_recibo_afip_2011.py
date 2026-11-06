"""Recibo real de AFIP, septiembre 2011 (SDN, Pruebas 2026-11-05): lo que la IA
leyó se confirmó en la app y `POST /api/validar` terminó en un 502 que el
navegador no supo mostrar (HISTORIAL.md, "El 502 del recibo de AFIP 2011").

Estos tests fijan lo que SÍ se pudo verificar en local: con el JSON que
`extractor.extraer()` devolvería para ese recibo (y con las variantes razonables
de lo que una IA puede devolver) la ruta contesta 200 con JSON, y la pantalla
del trabajador ya no depende de que cada respuesta sea JSON. Un 502 de Render
no es una excepción de Python: es la instancia que no contestó.

Correr con: .venv/Scripts/python.exe -m pytest test_recibo_afip_2011.py -q
"""
import copy
import json
import re
from pathlib import Path

import db
from db import Sindicato, Trabajador, Concepto, Formula
import main
import auth
from fastapi.testclient import TestClient

CUIL = "20202790411"
db.crear_tablas()
with db.get_session() as s:
    sind = Sindicato(nombre="AEFIP test 2011", slug="aefip-test-2011")
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(Trabajador(sindicato_id=SID, cuil=CUIL, activo=True, registrado=True))
    db.guardar_datos_personales(s, CUIL, nombre="Sdn")
    s.commit()
# El catálogo y las fórmulas de AEFIP (seed histórico) más los aportes de ley.
seed = json.loads(Path("data/seed_aefip.json").read_text(encoding="utf-8"))
with db.get_session() as s:
    for c in seed["conceptos"]:
        s.add(Concepto(sindicato_id=SID, **c))
    for f in seed["formulas"]:
        s.add(Formula(sindicato_id=SID, **f))
    s.commit()
db.crear_conceptos_universales(SID)

client = TestClient(main.app, raise_server_exceptions=False)
client.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", ident=CUIL))
client.cookies.set("cuil_trab", CUIL)


def _l(cod, desc, cant, uni, imp, tipo, sec, cat=None):
    return {"codigo": cod, "descripcion": desc, "cantidad": cant, "unidad": uni,
            "importe": imp, "tipo": tipo, "seccion": sec, "categoria_universal": cat}


# Lo que extractor.extraer() devuelve para el recibo (líneas tal cual impresas).
RECIBO = {
    "formato": "clasico",
    "empleado": {"apellido_nombre": "SDN", "cuil": CUIL, "legajo": "032949/91",
                 "categoria": "PL:1 - GR:25 - DIRECTOR (ASESOR MAYOR)", "fecha_ingreso": "1994-07-28"},
    "empleador": {"nombre": "AFIP", "cuit": "33-69345023-9"},
    "periodo": "2011-09",
    "fecha_pago": "2011-10-05",
    "lineas": [
        _l("1-026", "SUELDO BASICO", 1.0, "$", 2180.00, "remuneracion", "haberes"),
        _l("4-001", "ADICIONAL TECNICO - A.1", 65.0, "%", 3543.15, "remuneracion", "haberes"),
        _l("6-026", "BONIFICACION ESPECIAL", 1.0, "$", 3271.00, "remuneracion", "haberes"),
        _l("20-024", "REFRIGERIO", 1.0, "$", 905.00, "remuneracion", "haberes"),
        _l("37-025", "PERMANENCIA EN EL GRUPO", 1.0, "$", 1393.00, "remuneracion", "haberes"),
        _l("100-001", "ADICIONAL POR JEFATURA", 1.0, "$", 4580.00, "remuneracion", "haberes"),
        _l("108-001", "ANTIGUEDAD LAUDO 15/91", 17.0, "A", 296.14, "remuneracion", "haberes"),
        _l("126-001", "TITULO UNIV/TERC.LAUDO15/91 - INCISO A)", 1.0, "$", 563.00, "remuneracion", "haberes"),
        _l("704-001", "INCREMENTO SALARIAL - SUMA FIJA", 1.0, "$", 1069.00, "remuneracion", "haberes"),
        _l("707-001", "ADICIONAL POR SERV. ACREDITADO", 17.0, "A", 872.27, "remuneracion", "haberes"),
        _l("795-019", "COMP. P/DEDICACION ESPECIAL", 1.0, "$", 9220.00, "remuneracion", "haberes"),
        _l("38-001", "APORTE PERSONAL I.N.S.S.J.Y P.", 3.0, "%", -486.41, "aporte_trabajador", "descuentos", "pami"),
        _l("42-001", "AP. PERS. JUB. ANSES", 11.0, "%", -1783.51, "aporte_trabajador", "descuentos", "jubilacion"),
        _l("44-001", "SEGURO OBLIGATORIO - DGI", 1.0, "$", -3.80, "otro", "descuentos"),
        _l("85-117", "O.S. DE COMISARIOS NAVALES", 3.0, "%", -486.41, "aporte_trabajador", "descuentos", "obra_social"),
        _l("161-001", "IMPUESTO A LAS GANANCIAS", 1.0, "$", -6773.26, "otro", "descuentos"),
        _l("258-001", "MUTUAL FED.EMP.AFIP CTA.SOCIAL", 1.0, "$", -48.00, "otro", "descuentos"),
        _l("309-004", "SEGURO FAMILIAR - DGI", 1.0, "$", -16.50, "otro", "descuentos"),
        _l("623-001", "BANCO NAC.ARGENTINA-CREDITOS", 1.0, "$", -2056.53, "otro", "descuentos"),
    ],
    "totales_impresos": {"remuneraciones": 27892.56, "descuentos": -11654.42, "neto": 16238.14},
    "contribuciones_patronales": [],
    "costo_laboral_total": None,
    "ultimo_deposito": {"fecha": "2011-09-13", "periodo": "2011-08", "banco": "NACION"},
    "confianza": "alta",
    "observaciones": None,
    "alerta_adulteracion": {"detectada": False, "motivo": None},
}


def _post(recibo, nuevos=None):
    # Igual que la pantalla: los conceptos nuevos los calcula el servidor al
    # leer (/api/leer) y el cliente los devuelve junto con el recibo.
    if nuevos is None:
        nuevos = main.detectar_nuevos(db.conceptos_como_dicts(SID), recibo["lineas"], "33693450239")
    return client.post("/api/validar", json={"recibo": recibo, "conceptos_nuevos": nuevos})


def _con(**cambios):
    r = copy.deepcopy(RECIBO)
    r.update(cambios)
    return r


def test_recibo_afip_2011_valida_de_punta_a_punta():
    # Los topes de la seguridad social sembrados como en Pruebas (init_db):
    # no tienen vigencia para 2011, y eso tiene que ser un aviso, no un error.
    db.sembrar_topes_si_vacio()
    r = _post(copy.deepcopy(RECIBO))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["periodo"] == "2011-09" and d["cuil"] == CUIL
    assert d["estado"] in ("OK", "CON_DISCREPANCIAS"), d["estado"]
    assert d["totales"]["ingresos"] == 27892.56
    assert d["totales"]["descuentos"] == 11654.42
    assert d["totales"]["neto"] == 16238.14
    assert d["recibo_verificado_id"]
    # Sin tope cargado para 2011-09 el sistema lo dice y sigue.
    assert "tope_no_verificable" in {a["tipo"] for a in d["alertas"]}, d["alertas"]
    # Queda en el historial del trabajador.
    with db.get_session() as s:
        reg = s.get(db.ReciboVerificado, d["recibo_verificado_id"])
        assert reg.periodo == "2011-09" and reg.cuil == CUIL
    print("OK  test_recibo_afip_2011_valida_de_punta_a_punta")


def test_el_mismo_recibo_otra_vez_con_los_conceptos_ya_cargados():
    # SDN ya lo había subido antes: los conceptos nuevos de la primera vez
    # quedaron como pendientes y la segunda ya no los trae como nuevos.
    primero = _post(copy.deepcopy(RECIBO))
    segundo = _post(copy.deepcopy(RECIBO))
    assert primero.status_code == 200 and segundo.status_code == 200, segundo.text
    assert segundo.json()["recibo_verificado_id"] != primero.json()["recibo_verificado_id"]
    print("OK  test_el_mismo_recibo_otra_vez_con_los_conceptos_ya_cargados")


def _importes_como_texto_ar(r):
    for ln in r["lineas"]:
        ln["importe"] = f"{ln['importe']:.2f}".replace(".", ",")


def _importes_con_pesos_y_miles(r):
    for ln in r["lineas"]:
        ln["importe"] = "$ " + f"{ln['importe']:,.2f}"


def _importes_nulos(r):
    for ln in r["lineas"][::2]:
        ln["importe"] = None


def _cantidades_texto(r):
    for ln in r["lineas"]:
        ln["cantidad"] = "1,00"


def _importe_nan_texto(r):
    r["lineas"][0]["importe"] = "NaN"


def _importe_desmedido(r):
    r["lineas"][0]["importe"] = "1e999"


def _codigos_numericos(r):
    for ln in r["lineas"]:
        ln["codigo"] = int(ln["codigo"].split("-")[0])


def _sin_codigo_ni_descripcion(r):
    for ln in r["lineas"][:3]:
        ln["codigo"] = None
        ln["descripcion"] = None


VARIANTES = {
    "importes_texto_ar": _importes_como_texto_ar,
    "importes_pesos_y_miles": _importes_con_pesos_y_miles,
    "importes_nulos": _importes_nulos,
    "cantidades_texto": _cantidades_texto,
    "importe_nan_texto": _importe_nan_texto,
    "importe_desmedido": _importe_desmedido,
    "codigos_numericos": _codigos_numericos,
    "sin_codigo_ni_descripcion": _sin_codigo_ni_descripcion,
}

CAMBIOS = {
    "periodo_en_letras": dict(periodo="SEPTIEMBRE 2011"),
    "periodo_mes_anio": dict(periodo="09/2011"),
    "periodo_nulo": dict(periodo=None),
    "periodo_un_digito": dict(periodo="2011-9"),
    "periodo_mes_13": dict(periodo="2011-13"),
    "deposito_con_barras": dict(ultimo_deposito={"fecha": "13/09/2011", "periodo": "08/2011", "banco": "NACION"}),
    "deposito_nulo": dict(ultimo_deposito=None),
    "deposito_en_texto": dict(ultimo_deposito="NACION 13/09/2011"),
    "fecha_pago_con_barras": dict(fecha_pago="05/10/2011"),
    "totales_en_texto": dict(totales_impresos={"remuneraciones": "27.892,56", "descuentos": "-11.654,42",
                                               "neto": "16.238,14"}),
    "totales_nulos": dict(totales_impresos=None),
    "empleador_nulo": dict(empleador=None),
    "empleado_nulo": dict(empleado=None),
    "cuit_numerico": dict(empleador={"nombre": "AFIP", "cuit": 33693450239}),
    "legajo_numerico": dict(empleado={"cuil": CUIL, "legajo": 32949, "fecha_ingreso": "28/07/1994"}),
    "campo_extra_del_cliente": dict(cuil_impreso_invalido=CUIL),
}


def test_variantes_de_lo_que_puede_devolver_la_ia_no_dan_5xx():
    malas = []
    for nombre, fn in VARIANTES.items():
        r = copy.deepcopy(RECIBO)
        fn(r)
        resp = _post(r)
        if resp.status_code != 200:
            malas.append((nombre, resp.status_code, resp.text[:120]))
    for nombre, cambios in CAMBIOS.items():
        resp = _post(_con(**copy.deepcopy(cambios)))
        if resp.status_code != 200:
            malas.append((nombre, resp.status_code, resp.text[:120]))
    assert not malas, malas
    print("OK  test_variantes_de_lo_que_puede_devolver_la_ia_no_dan_5xx")


def test_un_payload_roto_contesta_json_y_no_cuelga_nada():
    # Lo que el navegador espera de un fallo propio de la app: JSON con
    # `detail` de texto. Nunca HTML ni un cuerpo vacío.
    for cuerpo in ({}, {"recibo": "no soy un dict"}, {"recibo": None},
                   {"recibo": {"empleado": {"cuil": CUIL}, "periodo": "2011-09"}}):
        r = client.post("/api/validar", json=cuerpo)
        assert r.status_code in (200, 400, 422, 500), (cuerpo, r.status_code)
        if r.status_code != 200:
            assert r.headers["content-type"].startswith("application/json"), r.text[:100]
            if r.status_code == 500:
                j = r.json()
                assert isinstance(j["detail"], str) and j["codigo"], j
    print("OK  test_un_payload_roto_contesta_json_y_no_cuelga_nada")


def test_la_pantalla_del_trabajador_no_lee_json_a_ciegas():
    """El 502 de Render trae HTML: `await r.json()` reventaba con "Unexpected
    token '<'" y el trabajador veía un error crudo. Los fetch del flujo del
    recibo pasan por `pedirJson`, que convierte cualquier respuesta que no sea
    JSON de la app en un mensaje claro con el código de estado."""
    html = Path("templates/trabajador.html").read_text(encoding="utf-8")
    for ruta in ("/api/leer", "/api/validar", "/api/aportes", "/api/reportar",
                 "/api/enviar-sindicato", "/api/mis-recibos"):
        assert f"pedirJson('{ruta}'" in html, f"{ruta} no pasa por pedirJson"
        assert f"fetch('{ruta}'" not in html, f"{ruta} vuelve a usar fetch a pelo"
    assert "function textoErrorHttp" in html and "Código HTTP" in html
    assert "El servidor no respondió" in html
    # Ningún catch de esos pasos puede pintar el mensaje crudo del navegador.
    assert not re.search(r"panelError\(\[[^\]]*\],\s*err\.message", html)
    print("OK  test_la_pantalla_del_trabajador_no_lee_json_a_ciegas")


if __name__ == "__main__":
    test_recibo_afip_2011_valida_de_punta_a_punta()
    test_el_mismo_recibo_otra_vez_con_los_conceptos_ya_cargados()
    test_variantes_de_lo_que_puede_devolver_la_ia_no_dan_5xx()
    test_un_payload_roto_contesta_json_y_no_cuelga_nada()
    test_la_pantalla_del_trabajador_no_lee_json_a_ciegas()
    print("\nTodo OK -- recibo de AFIP 2011 y respuestas que no son JSON.")
