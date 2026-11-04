"""Recursos del plan de pruebas de La Bancaria (PLAN_PRUEBAS_BANCARIA.md, §5):
el lote de recibos, la alta de sus 50 empleados, la clasificación de una
corrida contra el manifiesto, el análisis del corte al cambiar de plan y los
archivos al límite. Nada de esto llama a la app real ni a la IA.

Correr con: python -m pytest test_lote_bancaria.py -q
"""
import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "carga"))

import db  # noqa: E402
import lote_bancaria as L  # noqa: E402
import probar_lote_bancaria as P  # noqa: E402
import analizar_corte as A  # noqa: E402
import archivos_limite as AL  # noqa: E402

db.crear_tablas()


@pytest.fixture(scope="module")
def lote(tmp_path_factory):
    """El lote extraído en una carpeta temporal, con el módulo apuntando ahí."""
    destino = tmp_path_factory.mktemp("lote")
    L.extraer(destino)
    viejos = (L.DESTINO, L.MANIFIESTO, L.EMPLEADOS)
    L.DESTINO, L.MANIFIESTO, L.EMPLEADOS = destino, destino / "manifest.csv", destino / "empleados.csv"
    yield destino
    L.DESTINO, L.MANIFIESTO, L.EMPLEADOS = viejos


# ------------------------------------------------------------- el lote ----
def test_el_lote_esta_completo(lote):
    assert L.verificar() == []
    filas = L.manifiesto()
    assert len(filas) == 600
    assert len({f["cuil"] for f in filas}) == 50
    assert {f["archivo"].split("/")[0] for f in filas} == {"bbva", "galicia", "nacion", "santander", "industrial"}
    k6 = json.loads((lote / "k6.json").read_text(encoding="utf-8"))
    assert len(k6) == 600 and all(r["cuil"].isdigit() for r in k6)


def test_los_errores_a_proposito_y_lo_que_se_espera(lote):
    errores = {f["error_intencional"]: f for f in L.manifiesto() if f["error_intencional"]}
    assert set(errores) == {"NETO_INCORRECTO", "CUIL_DV_INVALIDO"}
    assert L.esperado(errores["NETO_INCORRECTO"]) == "CON_DISCREPANCIAS"
    # Hoy la app corta un CUIL impreso con el DV mal (decisión pendiente).
    assert L.esperado(errores["CUIL_DV_INVALIDO"]) == "E-RECIBO-04"


def test_los_recibos_que_superan_el_tope_se_esperan_con_diferencias(lote):
    """El generador del lote no aplicó el tope de aportes: la app lo marca, con
    razón (prueba piloto del 2026-11-03, 5 de 10). 271 de los 600."""
    filas = L.manifiesto()
    sobre = [f for f in filas if L.supera_tope(f)]
    assert len(sobre) == 271
    assert all(L.esperado(f) == "CON_DISCREPANCIAS" for f in sobre if not f["error_intencional"])
    debajo = next(f for f in filas if not L.supera_tope(f) and not f["error_intencional"])
    assert L.esperado(debajo) == "OK"


def test_la_muestra_es_siempre_la_misma_reparte_y_lleva_los_errores(lote):
    filas = L.manifiesto()
    a, b = L.muestra(filas, 60), L.muestra(filas, 60)
    assert [f["archivo"] for f in a] == [f["archivo"] for f in b]
    assert len(a) == 60
    assert sum(1 for f in a if f["error_intencional"]) == 2
    por_banco = {}
    for f in a:
        por_banco[f["archivo"].split("/")[0]] = por_banco.get(f["archivo"].split("/")[0], 0) + 1
    assert set(por_banco) == {"bbva", "galicia", "nacion", "santander", "industrial"}
    assert max(por_banco.values()) - min(por_banco.values()) <= 2
    assert len({f["periodo"] for f in a}) >= 6          # recorre meses distintos
    assert L.muestra(filas, 0) == filas


def test_extraer_no_escribe_fuera_de_la_carpeta(tmp_path, monkeypatch):
    import zipfile
    z = tmp_path / "parte9.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../afuera.txt", "x")
    monkeypatch.setattr(L, "ZIPS", [z])
    with pytest.raises(SystemExit):
        L.extraer(tmp_path / "dest")
    assert not (tmp_path / "afuera.txt").exists()


# -------------------------------------------------- alta de los 50 ------
@pytest.fixture
def bancaria(lote):
    from db import Seccional, Sindicato
    with db.get_session() as s:
        sind = Sindicato(nombre="Bancaria Pruebas Lote", slug="bancaria-lote-test")
        s.add(sind)
        s.commit()
        s.refresh(sind)
        for n in ("Sede Central", "Lomas de Zamora"):
            s.add(Seccional(sindicato_id=sind.id, nombre=n))
        s.commit()
        return sind.id


def test_preparar_sin_si_no_escribe_y_con_si_empadrona(bancaria, monkeypatch, tmp_path):
    import preparar_bancaria as PB
    from sqlmodel import select
    from db import CuentaTrabajador, Trabajador
    import auth
    monkeypatch.setattr(PB, "CSV_SALIDA", tmp_path / "usuarios.csv")
    # Uno de los 50 ya tiene cuenta con clave propia: no se toca.
    ajeno = L.solo_digitos(L.empleados()[0]["cuil"])
    with db.get_session() as s:
        c = db.asegurar_cuenta(s, ajeno)
        c.clave_hash = auth.hashear_clave("suya-propia")
        s.add(c)
        s.commit()

    PB.main(["--sindicato", "bancaria pruebas lote"])
    with db.get_session() as s:
        assert s.exec(select(Trabajador).where(Trabajador.sindicato_id == bancaria)).all() == []
    assert not (tmp_path / "usuarios.csv").exists()

    PB.main(["--sindicato", "Bancaria Pruebas Lote", "--si"])
    filas = list(csv.DictReader(open(tmp_path / "usuarios.csv", encoding="utf-8")))
    assert len(filas) == 50
    fila_ajena = next(f for f in filas if f["cuil"] == ajeno)
    assert fila_ajena["estado"] == "cuenta_ajena" and fila_ajena["clave"] == ""
    with db.get_session() as s:
        trabs = s.exec(select(Trabajador).where(Trabajador.sindicato_id == bancaria)).all()
        assert len(trabs) == 49
        assert len({t.seccional_id for t in trabs}) == 2          # repartidos
        uno = next(f for f in filas if f["clave"])
        cuenta = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == uno["cuil"])).first()
        assert auth.verificar_clave(uno["clave"], cuenta.clave_hash)
        assert cuenta.nombre
        ajena = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == ajeno)).first()
        assert auth.verificar_clave("suya-propia", ajena.clave_hash)

    # Correrlo de nuevo no duplica.
    PB.main(["--sindicato", "Bancaria Pruebas Lote", "--si"])
    with db.get_session() as s:
        assert len(s.exec(select(Trabajador).where(Trabajador.sindicato_id == bancaria)).all()) == 49

    # Limpiar: ensayo no borra, con --si sí; la cuenta ajena queda (no la creó el lote... pero
    # tampoco está en otro sindicato: se borra solo si nadie más la tiene empadronada).
    assert PB.limpiar("Bancaria Pruebas Lote", escribir=False)["Trabajador"] == 49
    PB.limpiar("Bancaria Pruebas Lote", escribir=True)
    with db.get_session() as s:
        assert s.exec(select(Trabajador).where(Trabajador.sindicato_id == bancaria)).all() == []


def test_preparar_se_niega_en_demo(monkeypatch):
    import preparar_bancaria as PB
    monkeypatch.setenv("ENTORNO", "demo")
    with pytest.raises(SystemExit):
        PB.main([])


# ------------------------------------------- clasificar una corrida -----
def _fila(error=""):
    return {"archivo": "bbva/20111111112_2026-01.pdf", "formato": "pdf", "cuil": "20-11111111-2",
            "periodo": "2026-01", "error_intencional": error, "total_haberes": "1000.0",
            "total_descuentos": "200.0", "neto_impreso": "800.0"}


def _leer(neto=-800.0, periodo="2026-01"):
    return {"recibo": {"periodo": periodo, "empleado": {"cuil": "20111111112"},
                       "totales_impresos": {"neto": neto}},
            "totales_leidos": {"ingresos": 1000.0, "descuentos": -200.0}}


def test_clasificar_recibo_correcto_y_error_detectado():
    r = P.clasificar(_fila(), _leer(), None, {"estado": "OK", "discrepancias": []})
    assert r["acierto"] and r["lectura_ok"] and r["obtenido"] == "OK"
    r = P.clasificar(_fila("NETO_INCORRECTO"), _leer(), None,
                     {"estado": "CON_DISCREPANCIAS", "discrepancias": [{"tipo": "total_inconsistente"}]})
    assert r["acierto"] and r["discrepancias"] == "total_inconsistente"
    # Leyó otro período: la lectura no es exacta aunque la validación diga OK.
    r = P.clasificar(_fila(), _leer(periodo="2026-02"), None, {"estado": "OK"})
    assert r["acierto"] and not r["lectura_ok"]
    # Un falso positivo: el recibo correcto sale con diferencias.
    assert not P.clasificar(_fila(), _leer(), None, {"estado": "CON_DISCREPANCIAS"})["acierto"]


def test_clasificar_errores_de_la_app():
    assert P.clasificar(_fila("CUIL_DV_INVALIDO"), None, "E-RECIBO-04", None)["acierto"]
    r = P.clasificar(_fila(), None, "E-RECIBO-01", None)
    assert not r["acierto"] and not r["lectura_ok"]


def test_resumir_y_comparar_dos_modelos(tmp_path):
    a = [dict(P.clasificar(_fila(), _leer(), None, {"estado": "OK"}), ms_leer=9000, etiqueta="sonnet-5-5"),
         dict(P.clasificar(_fila("NETO_INCORRECTO"), _leer(), None, {"estado": "CON_DISCREPANCIAS"}),
              ms_leer=11000, etiqueta="sonnet-5-5")]
    b = [dict(P.clasificar(_fila(), _leer(), None, {"estado": "OK"}), ms_leer=4000, etiqueta="haiku-5-5"),
         dict(P.clasificar(_fila("NETO_INCORRECTO"), _leer(), None, {"estado": "OK"}),
              ms_leer=5000, etiqueta="haiku-5-5")]
    r = P.resumir(a)
    assert r["aciertos"] == 2 and r["errores_lote_detectados"] == 1 and r["ms_leer_p50"] == 10000
    rutas = []
    for nombre, filas in (("s", a), ("h", b)):
        ruta = tmp_path / f"{nombre}.csv"
        with open(ruta, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=P.CAMPOS, extrasaction="ignore")
            w.writeheader()
            w.writerows(filas)
        rutas.append(str(ruta))
    tabla = P.comparar(rutas)
    assert "| sonnet-5-5 | 2 | 2 |" in tabla and "| haiku-5-5 | 2 | 1 |" in tabla
    assert "no coinciden: 1" in tabla


def test_probar_lote_se_niega_contra_la_demo():
    with pytest.raises(SystemExit):
        P.main(["--base-url", "https://mitrabajo.onrender.com", "--etiqueta", "x"])


def test_costo_estimado_sale_del_catalogo():
    assert P.costo_estimado(100, "claude-sonnet-5-5") > P.costo_estimado(100, "claude-haiku-5-5") > 0
    assert P.costo_estimado(100, "modelo-que-no-existe") is None


# --------------------------------------------- corte al cambiar de plan --
def _punto(seg, status):
    return json.dumps({"type": "Point", "metric": "http_reqs",
                       "data": {"time": f"2026-11-03T15:00:{seg:02d}.5-03:00", "value": 1,
                                "tags": {"status": str(status)}}})


def test_analizar_corte_encuentra_la_racha_y_el_500():
    lineas = [_punto(s, 200) for s in range(0, 5)]
    lineas += [_punto(s, 503) for s in range(5, 9)] + [_punto(7, 0)]
    lineas += [_punto(s, 200) for s in range(9, 12)]
    lineas += [_punto(12, 500), _punto(12, 500), _punto(12, 200)]
    lineas.append('{"type":"Metric","metric":"http_reqs","data":{}}')
    rs = A.cortes(A.linea_de_tiempo(lineas))
    assert len(rs) == 2
    assert rs[0]["segundos"] == 4 and rs[0]["codigos"] == {"503": 4, "0": 1} and not rs[0]["hubo_500"]
    assert rs[1]["hubo_500"]


# ------------------------------------------------ archivos al límite ----
def test_archivos_limite_se_generan_y_se_evaluan(lote, tmp_path):
    casos = AL.generar(tmp_path)
    assert len(casos) == 9
    assert all((tmp_path / c["archivo"]).exists() for c in casos)
    assert AL.evaluar(200, {}) == "ok"
    assert AL.evaluar(400, {"codigo": "E-RECIBO-01"}) == "codigo"
    assert AL.evaluar(503, {"codigo": "E-SERVIDOR-01"}) == "codigo"
    assert AL.evaluar(422, {"detail": "x"}) == "FALLA"
    assert AL.evaluar(500, {"codigo": "E-INTERNO-00"}) == "FALLA"


# ------------------------------------------- tirada al azar por el panel --
def test_la_muestra_al_azar_se_repite_con_la_misma_semilla(lote):
    filas = L.manifiesto()
    a, b = L.muestra_azar(filas, 10, 20261103), L.muestra_azar(filas, 10, 20261103)
    assert [f["archivo"] for f in a] == [f["archivo"] for f in b] and len(a) == 10
    assert [f["archivo"] for f in L.muestra_azar(filas, 10, 7)] != [f["archivo"] for f in a]


def test_las_claves_cumplen_la_minima_de_la_app():
    import alta_por_panel as AP
    import preparar_bancaria as PB
    import main
    assert len(AP.clave_de("20-18533142-4")) == len(PB.clave_de("20185331424")) == main.CLAVE_MINIMA


def test_alta_por_panel_agrega_al_csv_sin_pisar(tmp_path):
    import alta_por_panel as AP
    ruta = tmp_path / "u.csv"
    AP.guardar([{"cuil": "1", "clave": "a", "banco": "x", "seccional_id": "", "estado": "registrado"}], ruta)
    AP.guardar([{"cuil": "2", "clave": "b", "banco": "y", "seccional_id": "", "estado": "registrado"},
                {"cuil": "1", "clave": "c", "banco": "x", "seccional_id": "", "estado": "ya_entraba"}], ruta)
    filas = {r["cuil"]: r for r in csv.DictReader(open(ruta, encoding="utf-8"))}
    assert set(filas) == {"1", "2"} and filas["1"]["clave"] == "c"


def test_alta_por_panel_se_niega_contra_la_demo():
    import alta_por_panel as AP
    with pytest.raises(SystemExit):
        AP.main(["--base-url", "https://mitrabajo.onrender.com", "--admin-clave", "x",
                 "--azar", "1", "--semilla", "1"])


def test_publicar_exactitud_arma_las_tres_pruebas(lote):
    import publicar_exactitud as PE
    pagos = [PE.payload_de(p, PE._recalculo()) for p in json.loads(PE.REGISTRO.read_text(encoding="utf-8"))]
    assert [len(p["resumen"]) for p in pagos] == [10, 10, 20]
    for p in pagos:
        assert p["tipo"] == "exactitud" and p["causas"] and p["totales"]
        assert all(f["archivo"] for f in p["resumen"])
        assert {c["origen"] for c in p["causas"]} <= {"app", "recibos", "configuracion"}
    assert pagos[0]["totales"]["Con las correcciones"] == "10 de 10"
    assert pagos[2]["totales"]["Dieron lo esperado"] == "19 de 20"


def test_asignar_uso_pone_modelo_tiempo_y_costo_por_recibo(lote):
    import publicar_exactitud as PE
    pago = PE.armar()[1]                      # variantes: 8 lecturas de un mismo CUIL, 10 filas
    usos = [{"cuil": pago["resumen"][0]["cuil"], "modelo": "claude-sonnet-5-5", "tokens_entrada": 4000,
             "tokens_salida": 1500, "precio_entrada": 2.0, "precio_salida": 10.0}] * 8
    assert PE.asignar_uso(pago, usos)
    con_costo = [f for f in pago["resumen"] if f.get("costo_usd")]
    assert len(con_costo) == 8 and all(f["costo_usd"] == 0.023 for f in con_costo)
    assert all(f["modelo"] == "Sonnet 5.5" for f in pago["resumen"])
    assert pago["totales"]["Costo total"] == "US$ 0,1840" and "Costo" not in pago["totales"]
    # Si las cuentas no cierran, no se inventa nada.
    otro = PE.armar()[1]
    assert not PE.asignar_uso(otro, usos[:5])
    assert not any("costo_usd" in f for f in otro["resumen"])
