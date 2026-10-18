"""Validaciones de fuente `funcion` en Trámites (PLAN_LISTAS_VALIDACIONES.md,
bloque 3): contra una lista del sindicato o contra el padrón, con fórmulas
escritas como las Reglas de control, requisitos para iniciar y campos
calculados.

Cubre el motor puro (nombres, fórmulas, saneo, evaluación con un contexto
simulado), el alta del tipo por la ruta real, el banco de pruebas con CUIL
de prueba y el envío del afiliado (rechazado por la lista, frenado por un
requisito, aceptado con el calculado guardado por el servidor).

Correr con: python -m pytest test_validaciones_funcion.py -q
"""
import io
import json
from datetime import timedelta

import auth
import cuit
from sqlmodel import select
import db
import fechas
import main
import validaciones_tramite as vt
from db import Area, Seccional, Sindicato, Trabajador, UsuarioSindicato
from fastapi.testclient import TestClient
from modulos import MODULOS_INICIALES

db.crear_tablas()

JUAN = cuit.corregir("20300000010")      # en la lista, afiliado desde 2019
ANA = cuit.corregir("27300000020")       # afiliada hace dos meses, sin familia cargada
AJENO = cuit.corregir("20300000030")     # no está en el padrón
ADMIN = cuit.corregir("20300000040")
HOY = fechas.hoy()

with db.get_session() as s:
    sind = Sindicato(nombre="Gremio Función", slug="gremio-funcion",
                     modulos_habilitados=list(MODULOS_INICIALES) + ["tramites"])
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=ADMIN, nombre="Admin Función",
                           clave_hash=auth.hashear_clave("admin-demo"),
                           debe_cambiar_clave=False, es_super_admin=True))
    sec = Seccional(sindicato_id=SID, nombre="Sede Central", ve_todas=True)
    s.add(sec); s.commit(); s.refresh(sec)
    mesa = Area(sindicato_id=SID, seccional_id=sec.id, nombre="Mesa de Entradas")
    s.add(mesa); s.commit(); s.refresh(mesa)
    AREA, SEC = mesa.id, sec.id
    s.add(Trabajador(sindicato_id=SID, cuil=JUAN, activo=True, registrado=True,
                     seccional_id=SEC, fecha_afiliacion="2019-05-02"))
    db.guardar_datos_personales(s, JUAN, nombre="Juan Pérez", fecha_nacimiento="1988-07-15")
    db.asegurar_cuenta(s, JUAN).clave_hash = auth.hashear_clave("clave-larga-123")
    s.add(Trabajador(sindicato_id=SID, cuil=ANA, activo=True, registrado=True,
                     fecha_afiliacion=(HOY - timedelta(days=60)).isoformat()))
    db.guardar_datos_personales(s, ANA, nombre="Ana López")
    db.asegurar_cuenta(s, ANA).clave_hash = auth.hashear_clave("clave-larga-123")
    s.commit()

admin = TestClient(main.app)
admin.post("/admin/login", data={"usuario": ADMIN, "clave": "admin-demo"})


def _trab(cuil):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident=cuil))
    c.cookies.set("cuil_trab", cuil)
    c.cookies.set("sind_elegido", str(SID))
    return c


CAMPOS = [
    {"etiqueta": "DNI del chico", "tipo_dato": "texto", "obligatorio": True, "validaciones": [
        {"fuente": "funcion", "origen": "lista", "lista": "grupo_familiar", "clave2": 0,
         "trae": "existe", "mensaje": "Ese DNI no figura en tu grupo familiar.", "bloquea": True, "en_vivo": True},
        {"fuente": "funcion", "origen": "lista", "lista": "grupo_familiar", "clave2": 0,
         "formula": "anios_entre(lista.fecha_nacimiento, hoy()) <= 12",
         "mensaje": "El kit es hasta los 12 años.", "bloquea": False},
    ]},
    {"etiqueta": "Grado", "tipo_dato": "seleccion", "opciones": "1º, 2º, 3º", "obligatorio": True, "validaciones": []},
    {"etiqueta": "Edad del chico", "tipo_dato": "calculado", "validaciones": [
        {"fuente": "funcion", "origen": "lista", "lista": "grupo_familiar", "clave2": 0,
         "formula": "anios_entre(lista.fecha_nacimiento, hoy())"}]},
    {"etiqueta": "Antigüedad (meses)", "tipo_dato": "calculado", "validaciones": [
        {"fuente": "funcion", "origen": "sistema", "formula": "meses_entre(sistema.fecha_afiliacion, hoy())"}]},
]
REQUISITOS = [
    {"origen": "sistema", "formula": "meses_entre(sistema.fecha_afiliacion, hoy()) >= 6",
     "mensaje": "Necesitás seis meses de antigüedad para pedir el kit."},
]


# ------------------------------------------------------------- motor puro

def test_los_nombres_de_los_campos_salen_de_la_etiqueta():
    campos = [{"etiqueta": "DNI del chico", "tipo_dato": "texto"}, {"etiqueta": "Fecha desde", "tipo_dato": "fecha"},
              {"etiqueta": "", "tipo_dato": "separador"}, {"etiqueta": "Fecha desde", "tipo_dato": "fecha"},
              {"etiqueta": "1er hijo", "tipo_dato": "texto"}]
    assert vt.nombres_de_campos(campos) == ["dni_del_chico", "fecha_desde", "", "fecha_desde_2", "c_1er_hijo"]


def test_la_formula_se_escribe_como_las_reglas_y_falla_al_guardar():
    campos = [{"etiqueta": "Días", "tipo_dato": "numero"}, {"etiqueta": "Desde", "tipo_dato": "fecha"}]
    assert vt.error_de_formula("campo.dias * 2 >= 10 y no (campo.desde < hoy())", campos) is None
    assert vt.error_de_formula("lista.vinculo == 'Hijo' o lista.vinculo == 'Hija'", campos, "grupo_familiar") is None
    assert "campo.dias_x" in vt.error_de_formula("campo.dias_x > 1", campos)
    assert "sistema.nada" in vt.error_de_formula("sistema.nada > 1", campos)
    assert "fórmula válida" in vt.error_de_formula("campo.dias ** 2", campos)
    assert "divide por cero" in vt.error_de_formula("campo.dias / 0", campos)
    assert vt.error_de_formula("__import__('os')", campos)
    assert vt.error_de_formula("", campos) == "La fórmula está vacía."


def test_las_funciones_de_fecha_cuentan_unidades_cumplidas():
    ns = {"campo": {}, "lista": {}, "sistema": {"desde": "2020-01-15"}}
    assert vt.evaluar_formula("meses_entre('2020-01-15', '2020-03-14')", ns) == 1
    assert vt.evaluar_formula("meses_entre('2020-01-15', '2020-03-15')", ns) == 2
    assert vt.evaluar_formula("anios_entre('1988-07-15', '2026-07-14')", ns) == 37
    assert vt.evaluar_formula("anios_entre('1988-07-15', '2026-07-15')", ns) == 38
    assert vt.evaluar_formula("dias_entre('2026-01-01', '2026-01-31')", ns) == 30
    assert vt.evaluar_formula("hoy()", ns) == HOY.isoformat()
    assert vt.evaluar_formula("'HIJA' == 'hija' y existe(sistema.desde) y no existe(sistema.nada)", {
        "campo": {}, "lista": {}, "sistema": {"desde": "2020-01-15", "nada": None}}) is True
    assert vt.evaluar_formula("redondear(max(1, 2.5) / 3, 2)", ns) == 0.83
    assert vt.evaluar_formula("largo('abc') + 1", ns) == 4


def test_el_saneo_de_una_funcion_descarta_lo_mal_formado():
    campos = [{"etiqueta": "DNI", "tipo_dato": "texto"}, {"etiqueta": "Edad", "tipo_dato": "numero"},
              {"etiqueta": "Foto", "tipo_dato": "archivo"}]
    ok = vt.funcion_saneada({"origen": "lista", "lista": "grupo_familiar", "clave2": "0"}, campos, indice=1)
    assert ok["trae"] == "existe" and ok["operador"] == "==" and ok["valor"] == "si" and ok["clave2"] == 0
    assert "grupo familiar" in ok["mensaje"] and ok["bloquea"] is True and ok["en_vivo"] is False
    assert vt.funcion_saneada({"origen": "lista", "lista": "marciana"}, campos) is None
    assert vt.funcion_saneada({"origen": "lista", "lista": "simple", "clave2": 0}, campos, indice=0)["clave2"] == 0, "la segunda clave puede ser el mismo campo"
    assert vt.funcion_saneada({"origen": "lista", "lista": "simple", "clave2": 7}, campos, indice=0) is None
    assert vt.funcion_saneada({"origen": "lista", "lista": "simple", "clave2": 2}, campos, indice=0) is None, "ni un archivo"
    assert vt.funcion_saneada({"origen": "lista", "lista": "simple", "trae": "vinculo"}, campos) is None, "columna que la plantilla no tiene"
    assert vt.funcion_saneada({"origen": "lista", "lista": "simple", "formula": "campo.nada > 1"}, campos) is None
    assert vt.funcion_saneada({"origen": "sistema"}, campos) is None, "sin dato ni fórmula no afirma nada"
    assert vt.funcion_saneada({"origen": "sistema", "trae": "recibos_verificados"}, campos) is None, "un dato sin operador no afirma nada"
    con_op = vt.funcion_saneada({"origen": "sistema", "trae": "recibos_verificados", "operador": ">=", "valor": "3"}, campos)
    assert con_op["mensaje"] == "sistema.recibos_verificados tiene que ser mayor o igual a 3."
    req = vt.requisitos_saneados([{"origen": "sistema", "formula": "sistema.en_padron", "bloquea": False, "clave2": 0, "en_vivo": True}], campos)
    assert req[0]["bloquea"] is True and req[0]["clave2"] is None and req[0]["en_vivo"] is False
    calc = vt.validaciones_saneadas([{"fuente": "funcion", "origen": "sistema", "formula": "sistema.recibos_verificados * 2",
                                      "operador": ">=", "valor": "1"}], "calculado", campos=campos, indice=1)
    assert calc[0]["operador"] is None and calc[0]["valor"] == ""
    assert vt.validaciones_saneadas([{"fuente": "funcion", "origen": "sistema", "formula": "sistema.en_padron"}], "archivo",
                                    campos=campos, indice=2) == []
    assert vt.validaciones_saneadas([{"fuente": "funcion", "origen": "sistema", "formula": "sistema.en_padron"}], "texto") == [], "sin la lista de campos no se sanea"


def _contexto(fila=None, **sistema):
    base = {"en_padron": True, "activo": True, "registrado": True, "seccional": "Sede Central",
            "provincia": None, "localidad": None, "nivel_fiabilidad": 2.0, "recibos_verificados": 3.0,
            "semaforo": "verde", "fecha_afiliacion": "2019-05-02", "fecha_nacimiento": "1988-07-15"}
    base.update(sistema)
    return {"sistema": base, "buscar": lambda plantilla, clave2: fila}


def test_evaluar_envio_con_lista_sistema_requisitos_y_calculados():
    campos = main._campos_tramite_validos(json.loads(json.dumps(CAMPOS)))
    for i, c in enumerate(campos):
        c["id"] = 100 + i
    requisitos = vt.requisitos_saneados(REQUISITOS, campos)
    martina = {"cuil": JUAN, "dni": "55123456", "apellido_nombre": "Pérez, Martina", "vinculo": "Hija",
               "fecha_nacimiento": (HOY - timedelta(days=365 * 9)).isoformat()}
    v = vt.evaluar_envio(campos, [], {100: "55.123.456", 101: "1º"}, _contexto(fila=martina), requisitos)
    assert v["errores"] == [] and v["advertencias"] == [] and v["sin_contexto"] == 0
    assert v["calculados"][102] in ("8", "9") and v["calculados"][103] == str(vt._meses_entre("2019-05-02", HOY.isoformat()))
    # El DNI no está: bloquea con el mensaje del admin, y el calculado queda vacío con aviso.
    v = vt.evaluar_envio(campos, [], {100: "1", 101: "1º"}, _contexto(fila=None), requisitos)
    assert v["errores"] == ['"DNI del chico": Ese DNI no figura en tu grupo familiar.']
    assert v["errores_campos"][100] == "Ese DNI no figura en tu grupo familiar."
    assert v["calculados"][102] == "" and any("no se pudo calcular" in a for a in v["advertencias"])
    # Un familiar de 15: la de "avisa" no frena, queda como advertencia.
    grande = dict(martina, fecha_nacimiento=(HOY - timedelta(days=365 * 15 + 10)).isoformat())
    v = vt.evaluar_envio(campos, [], {100: "55123456", 101: "1º"}, _contexto(fila=grande), requisitos)
    assert v["errores"] == [] and v["advertencias"] == ['"DNI del chico": El kit es hasta los 12 años.']
    # El requisito de antigüedad: dos meses no alcanzan.
    v = vt.evaluar_envio(campos, [], {100: "55123456", 101: "1º"},
                         _contexto(fila=martina, fecha_afiliacion=(HOY - timedelta(days=60)).isoformat()), requisitos)
    assert v["errores"] == ["Necesitás seis meses de antigüedad para pedir el kit."]
    # Sin fecha de afiliación cargada el requisito tampoco pasa (falta el dato, no vale 0).
    v = vt.evaluar_envio(campos, [], {100: "55123456", 101: "1º"}, _contexto(fila=martina, fecha_afiliacion=None), requisitos)
    assert v["errores"] == ["Necesitás seis meses de antigüedad para pedir el kit."]
    # Sin contexto no se evalúa nada de esto y se dice cuánto quedó sin evaluar.
    v = vt.evaluar_envio(campos, [], {100: "1", 101: "1º"}, None, requisitos)
    assert v["errores"] == [] and v["sin_contexto"] == 5
    # Un campo vacío no dispara las validaciones del campo (de eso se encarga "obligatorio").
    v = vt.evaluar_envio(campos, [], {100: "", 101: "1º"}, _contexto(fila=None), [])
    assert v["errores"] == []


def test_el_catalogo_sale_del_codigo():
    cat = vt.catalogo_funcion()
    assert {x["clave"] for x in cat["sistema"]} == set(vt.DATOS_SISTEMA)
    assert {x["nombre"] for x in cat["funciones"]} == set(vt.FUNCIONES_FORMULA)
    assert [x["clave"] for x in cat["listas"]] == ["grupo_familiar", "datos_afiliado", "simple"]
    assert cat["operadores"] == list(vt.OPERADORES)


# ------------------------------------------------------------------ rutas

def _archivo(texto, nombre="familia.csv"):
    return {"archivo": (nombre, io.BytesIO(texto.encode("utf-8")), "text/csv")}


def test_el_admin_carga_la_lista_y_crea_el_tipo_con_funciones():
    csv = "cuil;dni;apellido_nombre;vinculo;fecha_nacimiento\n" \
          f"{JUAN};55123456;Pérez, Martina;Hija;{(HOY - timedelta(days=365 * 9)).isoformat()}\n" \
          f"{JUAN};58765432;Pérez, Tomás;Hijo;{(HOY - timedelta(days=365 * 15 + 10)).isoformat()}\n"
    r = admin.post("/admin/lista/cargar", data={"plantilla": "grupo_familiar", "nombre": "Familias", "seccional_id": "", "confirmar": "1"},
                   files=_archivo(csv))
    assert r.status_code == 200 and r.json()["validas"] == 2, r.text
    r = admin.post("/admin/tramite-tipo", data={
        "titulo": "Kit escolar", "codigo": "KIT GF", "campos_json": json.dumps(CAMPOS),
        "requisitos_json": json.dumps(REQUISITOS), "area_destino_default_id": str(AREA),
    }, follow_redirects=False)
    assert r.status_code == 303 and "error=" not in r.headers["location"]
    tipo = next(t for t in db.tipos_tramite_del_sindicato(SID) if t["codigo"] == "KIT GF")
    global TIPO
    TIPO = db.tipo_tramite_por_id(tipo["id"])
    dni = TIPO["campos"][0]
    assert [v["fuente"] for v in dni["validaciones"]] == ["funcion", "funcion"]
    assert dni["validaciones"][0]["clave2"] == 0 and dni["validaciones"][0]["en_vivo"] is True
    assert TIPO["campos"][2]["tipo_dato"] == "calculado" and TIPO["campos"][2]["validaciones"][0]["operador"] is None
    assert TIPO["requisitos"][0]["bloquea"] is True and TIPO["requisitos"][0]["origen"] == "sistema"
    # Y una fórmula rota no se guarda: la validación desaparece, el campo queda.
    r = admin.post("/admin/tramite-tipo", data={
        "titulo": "Roto", "codigo": "KIT ROTO",
        "campos_json": json.dumps([{"etiqueta": "Días", "tipo_dato": "numero", "validaciones": [
            {"fuente": "funcion", "origen": "sistema", "formula": "sistema.nada > 1", "mensaje": "x"}]}]),
        "area_destino_default_id": str(AREA)}, follow_redirects=False)
    roto = next(t for t in db.tipos_tramite_del_sindicato(SID) if t["codigo"] == "KIT ROTO")
    assert db.tipo_tramite_por_id(roto["id"])["campos"][0]["validaciones"] == []


def test_los_nombres_los_arma_el_servidor():
    r = admin.post("/admin/tramite-tipo/nombres", json={"campos": CAMPOS})
    assert r.json()["nombres"] == ["dni_del_chico", "grado", "edad_del_chico", "antiguedad_meses"]


def test_el_banco_de_pruebas_evalua_con_un_cuil_de_prueba():
    cuerpo = {"campos": CAMPOS, "reglas": [], "requisitos": REQUISITOS, "valores": {"0": "55123456", "1": "1º"}}
    r = admin.post("/admin/tramite-tipo/probar", json=cuerpo)
    assert r.status_code == 200 and r.json()["sin_contexto"] == 5 and r.json()["errores"] == []
    r = admin.post("/admin/tramite-tipo/probar", json={**cuerpo, "cuil": JUAN})
    d = r.json()
    assert d["errores"] == [] and d["sin_contexto"] == 0 and d["cuil"] == JUAN
    assert d["calculados"]["2"] in ("8", "9") and d["nombres"][0] == "dni_del_chico"
    r = admin.post("/admin/tramite-tipo/probar", json={**cuerpo, "cuil": JUAN, "valores": {"0": "99999999", "1": "1º"}})
    assert r.json()["errores_campos"]["0"] == "Ese DNI no figura en tu grupo familiar."
    r = admin.post("/admin/tramite-tipo/probar", json={**cuerpo, "cuil": ANA})
    assert "seis meses" in r.json()["errores"][0]
    r = admin.post("/admin/tramite-tipo/probar", json={**cuerpo, "cuil": AJENO})
    assert r.json()["errores"], "un CUIL que no está en el padrón no pasa nada: falta todo dato"


def test_el_envio_del_afiliado_se_frena_o_se_guarda_con_el_calculado():
    ids = {c["etiqueta"]: c["id"] for c in TIPO["campos"]}
    juan = _trab(JUAN)
    r = juan.post("/api/tramite", data={"tipo_tramite_id": TIPO["id"], f'campo_{ids["DNI del chico"]}': "99999999",
                                        f'campo_{ids["Grado"]}': "1º"})
    assert r.status_code == 422
    assert r.json()["errores_campos"][str(ids["DNI del chico"])] == "Ese DNI no figura en tu grupo familiar."
    r = juan.post("/api/tramite", data={"tipo_tramite_id": TIPO["id"], f'campo_{ids["DNI del chico"]}': "58.765.432",
                                        f'campo_{ids["Grado"]}': "1º",
                                        f'campo_{ids["Edad del chico"]}': "3"})     # lo que mande el cliente se ignora
    assert r.status_code == 200, r.text
    detalle = db.tramite_detalle(r.json()["id"])
    respuestas = {x["etiqueta"]: x["valor_texto"] for x in detalle["respuestas"]}
    assert respuestas["Edad del chico"] == "15" and respuestas["Antigüedad (meses)"] == str(vt._meses_entre("2019-05-02", HOY.isoformat()))
    assert detalle["advertencias"] == ['"DNI del chico": El kit es hasta los 12 años.']
    ana = _trab(ANA)
    r = ana.post("/api/tramite", data={"tipo_tramite_id": TIPO["id"], f'campo_{ids["DNI del chico"]}': "55123456",
                                       f'campo_{ids["Grado"]}': "1º"})
    assert r.status_code == 422 and "seis meses" in r.json()["errores"][0]
    # El CUIL de la lista es SIEMPRE el de la sesión: Ana no puede usar la familia de Juan.
    assert all("grupo familiar" in e or "seis meses" in e for e in r.json()["errores"])


def test_el_contexto_del_sistema_sale_del_padron():
    ctx = db.contexto_validaciones(SID, JUAN, TIPO, {})
    s = ctx["sistema"]
    assert s["en_padron"] and s["registrado"] and s["seccional"] == "Sede Central"
    assert s["fecha_afiliacion"] == "2019-05-02" and s["fecha_nacimiento"] == "1988-07-15"
    assert s["recibos_verificados"] == 0 and s["semaforo"] is None and s["nivel_fiabilidad"] == 1
    assert db.contexto_validaciones(SID, AJENO, TIPO, {})["sistema"]["en_padron"] is False
    assert ctx["buscar"]("grupo_familiar", "55123456") is None, "sin valores no se buscó nada"
    ctx = db.contexto_validaciones(SID, JUAN, TIPO, {TIPO["campos"][0]["id"]: "55.123.456"})
    assert ctx["buscar"]("grupo_familiar", "55123456")["apellido_nombre"] == "Pérez, Martina"


def test_los_datos_del_sistema_nuevos_salen_del_padron_y_de_los_recibos():
    """Las funciones pedidas el 2026-10-18: credencial, edad, antigüedad,
    último recibo, empleador y pedidos abiertos. Todo del CUIL de la sesión."""
    from db import Empleador, ReciboVerificado, Trabajador
    cuil = cuit.corregir("20300000060")
    with db.get_session() as s:
        s.add(Trabajador(sindicato_id=SID, cuil=cuil, activo=True, registrado=True, fecha_afiliacion="2019-05-02",
                         codigo_credencial="GREMI1234ABCD", vigencia_credencial="2030-12-31",
                         cuit_empleador="30999888778"))
        db.guardar_datos_personales(s, cuil, nombre="Credencial", fecha_nacimiento="1988-07-15")
        s.add(Empleador(sindicato_id=SID, cuit="30999888778", razon_social="Banco Humo S.A."))
        s.add(ReciboVerificado(sindicato_id=SID, cuil=cuil, periodo="2026-06", estado="OK", bruto=1500000.0))
        s.add(ReciboVerificado(sindicato_id=SID, cuil=cuil, periodo="2026-08", estado="OK", bruto=1650000.5))
        s.commit()
    sis = db.contexto_validaciones(SID, cuil, {"campos": [], "requisitos": []}, {})["sistema"]
    assert sis["credencial_vigente"] is True and sis["numero_credencial"] == "GREMI1234ABCD"
    assert sis["edad"] == vt.anios_cumplidos("1988-07-15") and sis["antiguedad_meses"] == vt.meses_cumplidos("2019-05-02")
    assert sis["ultimo_recibo_periodo"] == "2026-08" and sis["ultimo_recibo_bruto"] == 1650000.5
    assert sis["meses_sin_recibo"] == vt.meses_cumplidos("2026-08")
    assert sis["empleador_cuit"] == "30999888778" and sis["empleador_nombre"] == "Banco Humo S.A."
    assert sis["tramites_abiertos"] == 0 and sis["dias_desde_ultimo_pedido_de_este_tipo"] is None
    # Credencial vencida, o sin generar: no vigente. Sin fecha: vigente.
    with db.get_session() as s:
        t = s.exec(select(Trabajador).where(Trabajador.cuil == cuil, Trabajador.sindicato_id == SID)).first()
        t.vigencia_credencial = "2020-01-01"; s.add(t); s.commit()
    assert db.contexto_validaciones(SID, cuil, {"campos": [], "requisitos": []}, {})["sistema"]["credencial_vigente"] is False
    with db.get_session() as s:
        t = s.exec(select(Trabajador).where(Trabajador.cuil == cuil, Trabajador.sindicato_id == SID)).first()
        t.vigencia_credencial = None; s.add(t); s.commit()
    assert db.contexto_validaciones(SID, cuil, {"campos": [], "requisitos": []}, {})["sistema"]["credencial_vigente"] is True
    # Y en una fórmula se usan como cualquier dato: la credencial frena, la edad compara.
    campos = [{"id": 1, "etiqueta": "Nada", "tipo_dato": "texto", "validaciones": []}]
    req = vt.requisitos_saneados([{"origen": "sistema", "formula": "sistema.credencial_vigente y sistema.edad >= 18",
                                   "mensaje": "Necesitás credencial vigente y ser mayor."}], campos)
    ctx = db.contexto_validaciones(SID, cuil, {"campos": campos, "requisitos": req}, {})
    assert vt.evaluar_envio(campos, [], {}, ctx, req)["errores"] == []
    assert vt.evaluar_envio(campos, [], {}, db.contexto_validaciones(SID, ANA, {"campos": campos, "requisitos": req}, {}), req)["errores"] == [
        "Necesitás credencial vigente y ser mayor."]
    # Alguien que no está en el padrón: todo vacío, nada revienta.
    vacio = db.contexto_validaciones(SID, AJENO, {"campos": [], "requisitos": []}, {})["sistema"]
    assert vacio["credencial_vigente"] is False and vacio["edad"] is None and vacio["ultimo_recibo_periodo"] is None
