"""Costo en dólares de cada llamada a la IA, y el modelo elegido por uso.

Lo que se verifica acá, en orden de importancia:

1. El PRECIO se congela en la fila y el costo se deriva. Cambiar la lista de
   precios no puede reescribir el gasto de los meses anteriores.
2. Los defaults del catálogo (precios_ia.USOS) son los mismos que las
   constantes de los módulos. Si alguien mueve una y no la otra, el panel
   mostraría "el de origen" al lado del modelo equivocado.
3. El modelo que elige plataforma es el que de verdad viaja a la API.
4. El banco de pruebas corre el mismo archivo con varios modelos, registra
   el gasto que genera y marca lo que leyeron distinto.

Correr con: .venv/Scripts/python.exe -m pytest test_precios_ia.py -q
"""
import json
import os
from types import SimpleNamespace

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
import auth
import extractor
import precios_ia
import rag
import asistente
from db import Sindicato, Trabajador, UsoIA
from modulos import MODULOS_INICIALES
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()
with db.get_session() as s:
    sind = Sindicato(nombre="UOM Precios", slug="uom-precios",
                     modulos_habilitados=list(MODULOS_INICIALES))
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(Trabajador(sindicato_id=SID, cuil="20111111119", nombre="Juan",
                     activo=True, registrado=True))
    s.commit()

trab_client = TestClient(main.app)
trab_client.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0))
trab_client.cookies.set("cuil_trab", "20111111119")

plataforma_client = TestClient(main.app)
plataforma_client.post("/plataforma/login", data={"cuit": "20000000000", "clave": "test-plataforma"})

anonimo = TestClient(main.app)

RECIBO = {
    "formato": "clasico", "confianza": "alta",
    "empleado": {"cuil": "20111111119"}, "empleador": {"nombre": "Acme", "cuit": "30111111113"},
    "periodo": "2026-08", "lineas": [], "totales_impresos": {"neto": 500000},
}


def _mock_msg(payload: dict, entrada=1000, salida=200):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps(payload))],
        usage=SimpleNamespace(input_tokens=entrada, output_tokens=salida),
    )


def _fila_con(tokens_entrada: int) -> dict:
    return next(f for f in db.uso_ia_listado() if f["tokens_entrada"] == tokens_entrada)


# ---------------- 1. el catálogo y las cuentas ----------------
def test_costo_es_tokens_por_precio_sobre_un_millon():
    # Un millón de cada uno a 3 y 15 -> exactamente 18 dólares.
    assert abs(precios_ia.costo(1_000_000, 1_000_000, 3.0, 15.0) - 18.0) < 1e-9
    assert precios_ia.costo(0, 0, 3.0, 15.0) == 0.0


def test_un_modelo_fuera_del_catalogo_no_vale_cero_sino_desconocido():
    """La diferencia importa: cero es "salió gratis" y eso sería mentira."""
    assert precios_ia.precios("un-modelo-que-no-existe") is None
    assert precios_ia.costo_estimado("un-modelo-que-no-existe", 1000, 100) is None
    assert precios_ia.usd(None) == "—"
    assert precios_ia.segundos(0) == "—"


def test_los_cuatro_precios_del_catalogo_son_positivos():
    modelos = precios_ia.modelos()
    assert modelos, "sin data/precios_ia.json no se puede calcular ningún costo"
    for m in modelos:
        assert float(m["entrada"]) > 0 and float(m["salida"]) > 0, m
        assert float(m["salida"]) >= float(m["entrada"]), f"{m['id']}: la salida nunca es más barata"
    assert precios_ia.catalogo().get("leido"), "un precio sin fecha de lectura no se puede auditar"


def test_los_defaults_son_las_constantes_de_los_modulos():
    """Fail-closed: el panel muestra "el de origen" al lado de uno de estos
    ids. Si alguien cambia la constante de un módulo y no el catálogo, la
    pantalla mentiría sin que falle nada más."""
    assert precios_ia.USOS["recibos"]["default"] == extractor.MODELO
    assert precios_ia.USOS["convenio"]["default"] == rag.MODELO_RESPUESTA
    assert precios_ia.USOS["asistente"]["default"] == asistente.MODELO
    for uso in precios_ia.USOS:
        assert precios_ia.modelo_valido(precios_ia.default_de(uso)), uso


# ---------------- 2. el precio se congela, el costo se deriva ----------------
def test_el_precio_se_congela_en_la_fila(monkeypatch):
    db.registrar_uso_ia(SID, "20111111119", "recibo", "claude-sonnet-4-6",
                        1_000_000, 1_000_000, 4321)
    fila = _fila_con(1_000_000)
    assert fila["costo_exacto"] is True
    assert abs(fila["costo"] - 18.0) < 1e-9
    assert fila["duracion_ms"] == 4321 and fila["duracion_txt"] == "4,3 s"

    # Ahora "Anthropic cambia la lista de precios": la fila vieja no se mueve.
    caro = {"fuente": "test", "leido": "2026-09-13", "modelos": [
        {"id": "claude-sonnet-4-6", "nombre": "Sonnet 4.6", "entrada": 300.0, "salida": 1500.0}]}
    monkeypatch.setattr(precios_ia, "catalogo", lambda: caro)
    assert abs(_fila_con(1_000_000)["costo"] - 18.0) < 1e-9, \
        "cambiar la lista de precios no puede reescribir el gasto de ayer"


def test_una_fila_sin_precio_congelado_se_estima_y_se_avisa():
    """Todo lo registrado antes de que existieran las columnas. Se muestra
    con los precios de hoy, pero marcado: un número sin decir de dónde sale
    es peor que no tenerlo."""
    with Session(db.engine) as s:
        s.add(UsoIA(sindicato_id=SID, cuil="", tipo="recibo", modelo="claude-sonnet-4-6",
                    tokens_entrada=2_000_000, tokens_salida=0, fecha="2026-01-01 10:00"))
        s.commit()
    fila = _fila_con(2_000_000)
    assert fila["costo_exacto"] is False
    assert abs(fila["costo"] - 6.0) < 1e-9          # 2M de entrada a US$ 3 el millón


def test_el_nombre_de_un_modelo_desconocido_no_se_esconde():
    db.registrar_uso_ia(SID, "", "recibo", "claude-viejisimo-1", 77, 7)
    fila = _fila_con(77)
    assert fila["modelo_nombre"] == "claude-viejisimo-1"
    assert fila["costo"] is None and fila["costo_txt"] == "—"


# ---------------- 3. el modelo que elige plataforma es el que corre ----------------
def test_sin_configuracion_corre_el_default_del_modulo():
    assert db.modelos_ia() == {uso: precios_ia.default_de(uso) for uso in precios_ia.USOS}


def test_un_modelo_fuera_del_catalogo_no_se_guarda():
    """Un id mal escrito no falla acá: falla con un 400 de la API en la
    pantalla del trabajador que sube el recibo."""
    antes = db.modelo_ia("convenio")
    db.set_modelos_ia({"convenio": "claude-inventado-9"})
    assert db.modelo_ia("convenio") == antes


def test_api_leer_usa_el_modelo_que_eligio_plataforma():
    db.set_modelos_ia({"recibos": "claude-haiku-4-5"})
    pedidos = []
    original = extractor.client.messages.create
    extractor.client.messages.create = lambda **kw: (pedidos.append(kw["model"]),
                                                     _mock_msg(RECIBO, 3333, 111))[1]
    try:
        r = trab_client.post("/api/leer", files={"archivo": ("r.png", b"fake", "image/png")})
    finally:
        extractor.client.messages.create = original
        db.set_modelos_ia({"recibos": extractor.MODELO})
    assert r.status_code == 200, r.text
    assert pedidos == ["claude-haiku-4-5"], pedidos
    fila = _fila_con(3333)
    assert fila["modelo"] == "claude-haiku-4-5"
    # Haiku: 1 y 5 por millón. 3333 de entrada + 111 de salida.
    assert abs(fila["costo"] - (3333 * 1.0 + 111 * 5.0) / 1e6) < 1e-12
    assert fila["duracion_ms"] >= 0


def test_guardar_los_modelos_desde_el_panel():
    r = plataforma_client.post("/plataforma/modelos-ia", data={
        "modelo_recibos": "claude-sonnet-5", "modelo_convenio": "claude-opus-5",
        "modelo_asistente": "claude-haiku-4-5"}, follow_redirects=False)
    assert r.status_code == 303
    assert db.modelos_ia() == {"recibos": "claude-sonnet-5", "convenio": "claude-opus-5",
                               "asistente": "claude-haiku-4-5"}
    # Dejarlo como estaba para no contaminar los tests de abajo.
    db.set_modelos_ia({uso: precios_ia.default_de(uso) for uso in precios_ia.USOS})


def test_los_modelos_solo_los_cambia_plataforma():
    r = anonimo.post("/plataforma/modelos-ia", data={"modelo_recibos": "claude-haiku-4-5"},
                     follow_redirects=False)
    assert r.status_code == 403


# ---------------- 4. el banco de pruebas ----------------
def test_resumen_comparable_marca_lo_que_leyo_distinto():
    a = extractor.resumen_comparable("recibo", dict(RECIBO, periodo="2026-08"))
    b = extractor.resumen_comparable("recibo", dict(RECIBO, periodo="2026-09"))
    assert dict(a)["Período"] == "2026-08" and dict(b)["Período"] == "2026-09"
    assert dict(a)["Neto"] == "500.000,00"
    # Un campo que el modelo no leyó no es un cero.
    assert dict(extractor.resumen_comparable("recibo", {}))["Neto"] == "—"


def test_banco_de_pruebas_compara_dos_modelos_y_registra_el_gasto():
    def responder(**kw):
        # Haiku lee otro período: es exactamente lo que la pantalla tiene que
        # mostrar en rojo.
        if kw["model"] == "claude-haiku-4-5":
            return _mock_msg(dict(RECIBO, periodo="2026-09"), 4444, 44)
        return _mock_msg(RECIBO, 5555, 55)

    original = extractor.client.messages.create
    extractor.client.messages.create = responder
    try:
        r = plataforma_client.post(
            "/plataforma/probar-modelos",
            data={"tipo": "recibo", "modelos": ["claude-sonnet-4-6", "claude-haiku-4-5"]},
            files={"archivo": ("r.png", b"fake", "image/png")})
    finally:
        extractor.client.messages.create = original

    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert [m["modelo"] for m in cuerpo["modelos"]] == ["claude-sonnet-4-6", "claude-haiku-4-5"]
    assert all(m["ok"] for m in cuerpo["modelos"])
    periodo_haiku = next(c for c in cuerpo["modelos"][1]["resumen"] if c["etiqueta"] == "Período")
    assert periodo_haiku["igual"] is False, "leyó otro período: tiene que salir marcado"
    cuil_haiku = next(c for c in cuerpo["modelos"][1]["resumen"] if c["etiqueta"] == "CUIL")
    assert cuil_haiku["igual"] is True

    # Gasta créditos de verdad: tiene que quedar en el consumo, y filtrable aparte.
    assert _fila_con(4444)["tipo"] == "prueba"
    assert _fila_con(5555)["tipo"] == "prueba"
    assert _fila_con(4444)["sindicato_id"] is None


def test_banco_de_pruebas_no_tumba_la_comparacion_si_un_modelo_falla():
    def responder(**kw):
        if kw["model"] == "claude-haiku-4-5":
            raise RuntimeError("modelo no disponible")
        return _mock_msg(RECIBO, 6666, 66)

    original = extractor.client.messages.create
    extractor.client.messages.create = responder
    try:
        r = plataforma_client.post(
            "/plataforma/probar-modelos",
            data={"tipo": "recibo", "modelos": ["claude-sonnet-4-6", "claude-haiku-4-5"]},
            files={"archivo": ("r.png", b"fake", "image/png")})
    finally:
        extractor.client.messages.create = original
    assert r.status_code == 200, r.text
    ok, fallo = r.json()["modelos"]
    assert ok["ok"] is True
    assert fallo["ok"] is False and "modelo no disponible" in fallo["error"]
    # El que sí contestó igual gastó: se registra.
    assert _fila_con(6666)["tipo"] == "prueba"


def test_banco_de_pruebas_rechaza_lo_que_no_es_del_catalogo():
    r = plataforma_client.post("/plataforma/probar-modelos",
                               data={"tipo": "recibo", "modelos": ["gpt-lo-que-sea"]},
                               files={"archivo": ("r.png", b"fake", "image/png")})
    assert r.status_code == 422
    r = plataforma_client.post("/plataforma/probar-modelos",
                               data={"tipo": "otra-cosa", "modelos": ["claude-haiku-4-5"]},
                               files={"archivo": ("r.png", b"fake", "image/png")})
    assert r.status_code == 422


def test_el_banco_de_pruebas_es_solo_de_plataforma():
    r = anonimo.post("/plataforma/probar-modelos",
                     data={"tipo": "recibo", "modelos": ["claude-haiku-4-5"]},
                     files={"archivo": ("r.png", b"fake", "image/png")})
    assert r.status_code == 403


# ---------------- 5. la pantalla ----------------
def test_la_pantalla_muestra_costo_modelos_y_banco():
    r = plataforma_client.get("/plataforma")
    assert r.status_code == 200
    for marca in ("Uso de la API de IA", "Consumo y costo", "Banco de pruebas",
                  "usoia-por-modelo", "/plataforma/modelos-ia", "/plataforma/probar-modelos"):
        assert marca in r.text, marca
    # El precio y la fecha de lectura del catálogo, a la vista.
    assert precios_ia.catalogo()["leido"] in r.text
