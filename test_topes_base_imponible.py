"""Topes de base imponible de la seguridad social (jubilación, INSSJP,
obra social) -- Fase 1: modelo de datos, semilla desde data/topes_ss.csv y
la marca `sujeto_a_tope` en Formula. La Fase 2 (lógica en validador.py) se
prueba en la sección de más abajo del mismo archivo.

Correr con: .venv/Scripts/python.exe test_topes_base_imponible.py
"""
import os
import tempfile
from datetime import datetime, timedelta

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE
os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
from db import Sindicato, TopeBaseImponible, Formula
import validador
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()

with db.get_session() as s:
    sind = Sindicato(nombre="Sindicato Test Topes", color_base="#0f1b2d")
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id

plataforma_client = TestClient(main.app)
plataforma_client.post("/plataforma/login", data={"cuit": "20000000000", "clave": "test-plataforma"})


# ---------- Fase 1: semilla + CRUD ----------

def test_sembrado_carga_59_filas_respetando_estado():
    db.sembrar_topes_si_vacio()
    topes = db.topes_como_dicts()
    assert len(topes) == 59
    sospechosos = [t for t in topes if t["estado"] == "SOSPECHOSO"]
    assert len(sospechosos) == 14
    marzo_2026 = next(t for t in topes if t["vigencia_desde"] == "2026-03")
    assert marzo_2026["estado"] == "verificado"
    assert marzo_2026["tope_maximo"] == 4045590.45
    print("OK  test_sembrado_carga_59_filas_respetando_estado")


def test_sembrado_no_duplica_si_ya_hay_datos():
    db.sembrar_topes_si_vacio()  # ya corrió arriba, esto no debería agregar nada más
    assert len(db.topes_como_dicts()) == 59
    print("OK  test_sembrado_no_duplica_si_ya_hay_datos")


def test_crear_tope_rechaza_vigencia_duplicada():
    assert db.crear_tope("2030-01", 1000, 100, "por_verificar", "test") is True
    assert db.crear_tope("2030-01", 2000, 200, "por_verificar", "test") is False
    print("OK  test_crear_tope_rechaza_vigencia_duplicada")


def test_tope_anterior_a():
    anterior = db.tope_anterior_a("2026-08")
    assert anterior["vigencia_desde"] == "2026-07"
    assert db.tope_anterior_a("2015-01") is None  # no hay ninguno antes del primero
    print("OK  test_tope_anterior_a")


def test_editar_tope():
    with Session(db.engine) as s:
        t = s.exec(select(TopeBaseImponible).where(TopeBaseImponible.vigencia_desde == "2030-01")).first()
        tid = t.id
    assert db.editar_tope(tid, 5000, 500, "verificado", "corregido a mano")
    with Session(db.engine) as s:
        t = s.get(TopeBaseImponible, tid)
        assert t.tope_maximo == 5000 and t.estado == "verificado"
    print("OK  test_editar_tope")


def test_borrar_tope():
    with Session(db.engine) as s:
        t = s.exec(select(TopeBaseImponible).where(TopeBaseImponible.vigencia_desde == "2030-01")).first()
        tid = t.id
    db.borrar_tope(tid)
    with Session(db.engine) as s:
        assert s.get(TopeBaseImponible, tid) is None
    print("OK  test_borrar_tope")


def test_orden_prioridad_sospechosos_recientes_primero():
    listado = db.topes_listado()
    hace_12 = (datetime.now().replace(day=1) - timedelta(days=365)).strftime("%Y-%m")
    urgentes_esperados = {t.vigencia_desde for t in listado
                           if t.estado in ("SOSPECHOSO", "por_verificar") and t.vigencia_desde >= hace_12}
    cantidad_urgentes = len(urgentes_esperados)
    primeros = {t.vigencia_desde for t in listado[:cantidad_urgentes]}
    assert primeros == urgentes_esperados, (primeros, urgentes_esperados)
    # dentro del grupo urgente, el más reciente va primero
    if cantidad_urgentes >= 2:
        assert listado[0].vigencia_desde > listado[1].vigencia_desde
    print("OK  test_orden_prioridad_sospechosos_recientes_primero")


def test_crear_conceptos_universales_marca_sujeto_a_tope():
    db.crear_conceptos_universales(SID)
    formulas = {f["target"]: f for f in db.formulas_como_dicts(SID)}
    assert formulas["JUBILACION"]["sujeto_a_tope"] is True
    assert formulas["PAMI"]["sujeto_a_tope"] is True
    assert formulas["OBRASOCIAL"]["sujeto_a_tope"] is True
    print("OK  test_crear_conceptos_universales_marca_sujeto_a_tope")


def test_formula_nueva_sin_tope_por_defecto():
    from db import Formula
    with db.get_session() as s:
        s.add(Formula(sindicato_id=SID, target="SINDMET", descripcion="Cuota sindical",
                       expr="0.02 * base_remunerativa"))
        s.commit()
    formulas = {f["target"]: f for f in db.formulas_como_dicts(SID)}
    assert formulas["SINDMET"]["sujeto_a_tope"] is False
    print("OK  test_formula_nueva_sin_tope_por_defecto")


# ---------- Fase 2: lógica en validador.py ----------

CONCEPTOS_TOPE = [
    {"codigo": "SUELDO", "nombre": "Sueldo básico", "tipo": "ingreso", "remunerativo": True, "alias": []},
    {"codigo": "JUBILACION", "nombre": "Aporte jubilatorio (SIPA)", "tipo": "descuento", "remunerativo": True, "alias": []},
    {"codigo": "PAMI", "nombre": "Ley 19.032 (PAMI)", "tipo": "descuento", "remunerativo": True, "alias": []},
    {"codigo": "OBRASOCIAL", "nombre": "Obra Social", "tipo": "descuento", "remunerativo": True, "alias": []},
    {"codigo": "SINDMET", "nombre": "Cuota sindical", "tipo": "descuento", "remunerativo": True, "alias": []},
]

FORMULAS_TOPE = [
    {"target": "JUBILACION", "descripcion": "Aporte jubilatorio (SIPA)", "expr": "0.11 * base_remunerativa", "tolerancia": 1.0, "sujeto_a_tope": True},
    {"target": "PAMI", "descripcion": "Ley 19.032 (PAMI)", "expr": "0.03 * base_remunerativa", "tolerancia": 1.0, "sujeto_a_tope": True},
    {"target": "OBRASOCIAL", "descripcion": "Obra Social", "expr": "0.03 * base_remunerativa", "tolerancia": 1.0, "sujeto_a_tope": True},
]
FORMULA_SINDMET = {"target": "SINDMET", "descripcion": "Cuota sindical", "expr": "0.02 * base_remunerativa", "tolerancia": 1.0, "sujeto_a_tope": False}

TOPE_MAY_2015 = {"vigencia_desde": "2015-03", "tope_maximo": 43202.17, "base_minima": 1329.31, "estado": "verificado", "fuente": "test"}
TOPE_AGO_2026 = {"vigencia_desde": "2026-08", "tope_maximo": 4594798.23, "base_minima": 141380.42, "estado": "verificado", "fuente": "test"}
TOPE_AGO_2026_SOSPECHOSO = {**TOPE_AGO_2026, "estado": "SOSPECHOSO"}


def _recibo(periodo, sueldo, jub=None, pami=None, os_=None, sindmet=None):
    lineas = [{"codigo": "SUELDO", "descripcion": "Sueldo básico", "importe": sueldo, "tipo": "remuneracion"}]
    if jub is not None:
        lineas.append({"codigo": "JUBILACION", "descripcion": "Aporte jubilatorio", "importe": -jub, "tipo": "aporte_trabajador"})
    if pami is not None:
        lineas.append({"codigo": "PAMI", "descripcion": "PAMI", "importe": -pami, "tipo": "aporte_trabajador"})
    if os_ is not None:
        lineas.append({"codigo": "OBRASOCIAL", "descripcion": "Obra social", "importe": -os_, "tipo": "aporte_trabajador"})
    if sindmet is not None:
        lineas.append({"codigo": "SINDMET", "descripcion": "Cuota sindical", "importe": -sindmet, "tipo": "aporte_trabajador"})
    return {
        "empleado": {"cuil": "20111111119"}, "periodo": periodo,
        "lineas": lineas, "totales_impresos": {},
    }


def test_caso_real_mayo_2015_remuneracion_sobre_el_tope_sin_discrepancia():
    # Caso documentado: remunerativo 44.975,40, aportes calculados
    # correctamente sobre el tope vigente (43.202,17), no sobre el sueldo real.
    jub = round(0.11 * 43202.17, 2)
    pami = round(0.03 * 43202.17, 2)
    os_ = round(0.03 * 43202.17, 2)
    recibo = _recibo("2015-05", 44975.40, jub=jub, pami=pami, os_=os_)
    r = validador.validar(CONCEPTOS_TOPE, FORMULAS_TOPE, recibo, topes=[TOPE_MAY_2015], cuil_sesion="20111111119")
    assert r["estado"] == "OK", r["discrepancias"]
    print("OK  test_caso_real_mayo_2015_remuneracion_sobre_el_tope_sin_discrepancia")


def test_remuneracion_por_debajo_del_tope_sin_cambios():
    sueldo = 20000.0
    jub, pami, os_ = round(0.11 * sueldo, 2), round(0.03 * sueldo, 2), round(0.03 * sueldo, 2)
    recibo = _recibo("2015-05", sueldo, jub=jub, pami=pami, os_=os_)
    r = validador.validar(CONCEPTOS_TOPE, FORMULAS_TOPE, recibo, topes=[TOPE_MAY_2015], cuil_sesion="20111111119")
    assert r["estado"] == "OK", r["discrepancias"]
    print("OK  test_remuneracion_por_debajo_del_tope_sin_cambios")


def test_remuneracion_por_debajo_del_piso_minimo_usa_el_minimo():
    # Mismo ejemplo del documento de contexto: remuneración 80.000, mínimo
    # agosto 2026 = 141.380,42 -> retención total 24.034,67.
    minima = TOPE_AGO_2026["base_minima"]
    jub, pami, os_ = round(0.11 * minima, 2), round(0.03 * minima, 2), round(0.03 * minima, 2)
    assert round(jub + pami + os_, 2) == 24034.67
    recibo = _recibo("2026-08", 80000.0, jub=jub, pami=pami, os_=os_)
    r = validador.validar(CONCEPTOS_TOPE, FORMULAS_TOPE, recibo, topes=[TOPE_AGO_2026], cuil_sesion="20111111119")
    assert r["estado"] == "OK", r["discrepancias"]
    print("OK  test_remuneracion_por_debajo_del_piso_minimo_usa_el_minimo")


def test_periodo_sin_tope_cargado_evalua_igual_y_avisa():
    sueldo = 20000.0
    jub, pami, os_ = round(0.11 * sueldo, 2), round(0.03 * sueldo, 2), round(0.03 * sueldo, 2)
    recibo = _recibo("2010-01", sueldo, jub=jub, pami=pami, os_=os_)
    r = validador.validar(CONCEPTOS_TOPE, FORMULAS_TOPE, recibo, topes=[TOPE_MAY_2015], cuil_sesion="20111111119")
    assert r["estado"] == "OK"  # se evaluó igual, sin topear (no había tope <= 2010-01)
    alertas = [a for a in r["alertas"] if a["tipo"] == "tope_no_verificable"]
    assert len(alertas) == 1, r["alertas"]
    assert "2010-01" in alertas[0]["detalle"]
    print("OK  test_periodo_sin_tope_cargado_evalua_igual_y_avisa")


def test_tope_sospechoso_se_aplica_igual_y_avisa():
    minima = TOPE_AGO_2026["base_minima"]
    sueldo = 80000.0
    jub, pami, os_ = round(0.11 * minima, 2), round(0.03 * minima, 2), round(0.03 * minima, 2)
    recibo = _recibo("2026-08", sueldo, jub=jub, pami=pami, os_=os_)
    r = validador.validar(CONCEPTOS_TOPE, FORMULAS_TOPE, recibo, topes=[TOPE_AGO_2026_SOSPECHOSO], cuil_sesion="20111111119")
    assert r["estado"] == "OK", r["discrepancias"]  # el tope se aplicó igual (SOSPECHOSO no bloquea)
    alertas = [a for a in r["alertas"] if a["tipo"] == "tope_sospechoso"]
    assert len(alertas) == 1, r["alertas"]
    print("OK  test_tope_sospechoso_se_aplica_igual_y_avisa")


def test_discrepancia_real_incluye_aclaracion_de_liquidaciones_multiples():
    # JUB figura muy por debajo de lo esperado sobre el tope -> discrepancia real,
    # pero con la aclaración de que puede deberse a liquidaciones múltiples.
    recibo = _recibo("2015-05", 44975.40, jub=100.0, pami=1296.07, os_=1296.07)
    r = validador.validar(CONCEPTOS_TOPE, FORMULAS_TOPE, recibo, topes=[TOPE_MAY_2015], cuil_sesion="20111111119")
    assert r["estado"] == "CON_DISCREPANCIAS"
    disc_jub = next(d for d in r["discrepancias"] if d["codigo"] == "JUBILACION")
    assert "tope máximo mensual" in disc_jub["detalle"]
    assert "jornada parcial" not in disc_jub["detalle"]  # no se aplicó el piso acá
    print("OK  test_discrepancia_real_incluye_aclaracion_de_liquidaciones_multiples")


def test_discrepancia_con_piso_aplicado_incluye_las_dos_aclaraciones():
    minima = TOPE_AGO_2026["base_minima"]
    recibo = _recibo("2026-08", 80000.0, jub=100.0, pami=4241.41, os_=4241.41)
    r = validador.validar(CONCEPTOS_TOPE, FORMULAS_TOPE, recibo, topes=[TOPE_AGO_2026], cuil_sesion="20111111119")
    disc_jub = next(d for d in r["discrepancias"] if d["codigo"] == "JUBILACION")
    assert "tope máximo mensual" in disc_jub["detalle"]
    assert "jornada parcial" in disc_jub["detalle"]
    print("OK  test_discrepancia_con_piso_aplicado_incluye_las_dos_aclaraciones")


def test_concepto_faltante_sujeto_a_tope_incluye_aclaracion():
    recibo = _recibo("2015-05", 44975.40, pami=1296.07, os_=1296.07)  # sin línea de JUBILACION
    r = validador.validar(CONCEPTOS_TOPE, FORMULAS_TOPE, recibo, topes=[TOPE_MAY_2015], cuil_sesion="20111111119")
    disc_jub = next(d for d in r["discrepancias"] if d["codigo"] == "JUBILACION")
    assert disc_jub["tipo"] == "concepto_faltante"
    assert "tope máximo mensual" in disc_jub["detalle"]
    print("OK  test_concepto_faltante_sujeto_a_tope_incluye_aclaracion")


def test_formula_no_sujeta_a_tope_sigue_sobre_base_completa():
    # SINDMET no está sujeta a tope: aunque el sueldo supere el tope, se
    # sigue calculando sobre el remunerativo completo, no sobre el topeado.
    sueldo = 44975.40
    jub = round(0.11 * 43202.17, 2)
    pami = round(0.03 * 43202.17, 2)
    os_ = round(0.03 * 43202.17, 2)
    sindmet = round(0.02 * sueldo, 2)  # sobre el sueldo REAL, no el tope
    recibo = _recibo("2015-05", sueldo, jub=jub, pami=pami, os_=os_, sindmet=sindmet)
    r = validador.validar(CONCEPTOS_TOPE, FORMULAS_TOPE + [FORMULA_SINDMET], recibo,
                           topes=[TOPE_MAY_2015], cuil_sesion="20111111119")
    assert r["estado"] == "OK", r["discrepancias"]
    print("OK  test_formula_no_sujeta_a_tope_sigue_sobre_base_completa")


def test_tope_vigente_en_con_vigencias_no_contiguas():
    topes = [
        {"vigencia_desde": "2015-01", "tope_maximo": 100, "base_minima": 10, "estado": "verificado"},
        {"vigencia_desde": "2015-03", "tope_maximo": 200, "base_minima": 20, "estado": "verificado"},
    ]
    # Febrero no tiene fila propia -> rige la de enero (huecos como el CSV real).
    t = validador.tope_vigente_en(topes, "2015-02")
    assert t["vigencia_desde"] == "2015-01"
    assert validador.tope_vigente_en(topes, "2015-03")["vigencia_desde"] == "2015-03"
    assert validador.tope_vigente_en(topes, "2014-12") is None  # nada antes del primero
    assert validador.tope_vigente_en(topes, "2020-01")["vigencia_desde"] == "2015-03"  # el más reciente
    print("OK  test_tope_vigente_en_con_vigencias_no_contiguas")


def test_sin_topes_pasados_no_rompe_y_avisa():
    # topes=None (default) no debe romper -- llamadas existentes sin este
    # parámetro (como el test bloqueado por CUIL) siguen funcionando. Se
    # evalúa sin topear (como no había topes[]) y avisa que no se pudo
    # verificar, mismo criterio que "período sin tope cargado".
    sueldo = 20000.0
    jub, pami, os_ = round(0.11 * sueldo, 2), round(0.03 * sueldo, 2), round(0.03 * sueldo, 2)
    recibo = _recibo("2015-05", sueldo, jub=jub, pami=pami, os_=os_)
    r = validador.validar(CONCEPTOS_TOPE, FORMULAS_TOPE, recibo, cuil_sesion="20111111119")
    assert r["estado"] == "OK", r["discrepancias"]
    assert any(a["tipo"] == "tope_no_verificable" for a in r["alertas"])
    print("OK  test_sin_topes_pasados_no_rompe_y_avisa")


# ---------- Fase 3: rutas de plataforma ----------

def test_ruta_alta_tope_ok():
    r = plataforma_client.post("/plataforma/tope", data={
        "id": "", "vigencia_desde": "2027-01", "tope_maximo": 5000000, "base_minima": 150000,
        "estado": "verificado", "fuente": "test ruta",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert "error" not in r.headers["location"]
    with Session(db.engine) as s:
        t = s.exec(select(TopeBaseImponible).where(TopeBaseImponible.vigencia_desde == "2027-01")).first()
        assert t is not None and t.tope_maximo == 5000000
    print("OK  test_ruta_alta_tope_ok")


def test_ruta_alta_tope_duplicado_rechaza():
    r = plataforma_client.post("/plataforma/tope", data={
        "id": "", "vigencia_desde": "2027-01", "tope_maximo": 6000000, "base_minima": 160000,
        "estado": "verificado", "fuente": "test dup",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert "error=topeduplicado" in r.headers["location"]
    print("OK  test_ruta_alta_tope_duplicado_rechaza")


def test_ruta_alta_menor_al_anterior_sin_confirmar_rechaza():
    r = plataforma_client.post("/plataforma/tope", data={
        "id": "", "vigencia_desde": "2027-02", "tope_maximo": 100, "base_minima": 10,
        "estado": "por_verificar", "fuente": "test bajo",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert "error=topebajo" in r.headers["location"]
    with Session(db.engine) as s:
        assert s.exec(select(TopeBaseImponible).where(TopeBaseImponible.vigencia_desde == "2027-02")).first() is None
    print("OK  test_ruta_alta_menor_al_anterior_sin_confirmar_rechaza")


def test_ruta_alta_menor_al_anterior_confirmado_guarda():
    r = plataforma_client.post("/plataforma/tope", data={
        "id": "", "vigencia_desde": "2027-02", "tope_maximo": 100, "base_minima": 10,
        "estado": "por_verificar", "fuente": "test bajo confirmado", "confirmado": "1",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert "error" not in r.headers["location"]
    with Session(db.engine) as s:
        assert s.exec(select(TopeBaseImponible).where(TopeBaseImponible.vigencia_desde == "2027-02")).first() is not None
    print("OK  test_ruta_alta_menor_al_anterior_confirmado_guarda")


def test_ruta_edicion_no_se_compara_consigo_misma():
    # Editar 2027-01 SIN cambiar el valor no debe disparar "menor al anterior"
    # comparándose contra sí misma.
    with Session(db.engine) as s:
        t = s.exec(select(TopeBaseImponible).where(TopeBaseImponible.vigencia_desde == "2027-01")).first()
        tid = t.id
    r = plataforma_client.post("/plataforma/tope", data={
        "id": str(tid), "vigencia_desde": "2027-01", "tope_maximo": 5000000, "base_minima": 150000,
        "estado": "SOSPECHOSO", "fuente": "editado",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert "error" not in r.headers["location"]
    with Session(db.engine) as s:
        t = s.get(TopeBaseImponible, tid)
        assert t.estado == "SOSPECHOSO"
    print("OK  test_ruta_edicion_no_se_compara_consigo_misma")


def test_ruta_borrar_tope():
    with Session(db.engine) as s:
        t = s.exec(select(TopeBaseImponible).where(TopeBaseImponible.vigencia_desde == "2027-02")).first()
        tid = t.id
    r = plataforma_client.post("/plataforma/tope/borrar", data={"id": tid}, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        assert s.get(TopeBaseImponible, tid) is None
    print("OK  test_ruta_borrar_tope")

    # limpiar el otro tope de prueba (2027-01) para no ensuciar el resto de la corrida
    with Session(db.engine) as s:
        t = s.exec(select(TopeBaseImponible).where(TopeBaseImponible.vigencia_desde == "2027-01")).first()
        if t:
            s.delete(t); s.commit()


if __name__ == "__main__":
    test_sembrado_carga_59_filas_respetando_estado()
    test_sembrado_no_duplica_si_ya_hay_datos()
    test_crear_tope_rechaza_vigencia_duplicada()
    test_tope_anterior_a()
    test_editar_tope()
    test_borrar_tope()
    test_orden_prioridad_sospechosos_recientes_primero()
    test_crear_conceptos_universales_marca_sujeto_a_tope()
    test_formula_nueva_sin_tope_por_defecto()
    print("\nTests de Fase 1 (modelo de datos) pasaron.")

    test_caso_real_mayo_2015_remuneracion_sobre_el_tope_sin_discrepancia()
    test_remuneracion_por_debajo_del_tope_sin_cambios()
    test_remuneracion_por_debajo_del_piso_minimo_usa_el_minimo()
    test_periodo_sin_tope_cargado_evalua_igual_y_avisa()
    test_tope_sospechoso_se_aplica_igual_y_avisa()
    test_discrepancia_real_incluye_aclaracion_de_liquidaciones_multiples()
    test_discrepancia_con_piso_aplicado_incluye_las_dos_aclaraciones()
    test_concepto_faltante_sujeto_a_tope_incluye_aclaracion()
    test_formula_no_sujeta_a_tope_sigue_sobre_base_completa()
    test_tope_vigente_en_con_vigencias_no_contiguas()
    test_sin_topes_pasados_no_rompe_y_avisa()
    print("Tests de Fase 2 (motor de validación) pasaron.")

    test_ruta_alta_tope_ok()
    test_ruta_alta_tope_duplicado_rechaza()
    test_ruta_alta_menor_al_anterior_sin_confirmar_rechaza()
    test_ruta_alta_menor_al_anterior_confirmado_guarda()
    test_ruta_edicion_no_se_compara_consigo_misma()
    test_ruta_borrar_tope()
    print("Tests de Fase 3 (rutas de plataforma) pasaron.")

    print("\nTodos los tests de topes pasaron.")
