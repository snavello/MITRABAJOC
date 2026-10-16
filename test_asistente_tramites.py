"""Asistente de trámites, el motor puro (asistente_tramites.py,
PLAN_ASISTENTE_TRAMITES.md bloque 1).

Lo que se prueba: que el catálogo del asistente sea el del constructor real
(fail-closed), que el kit escolar de La Bancaria salga IGUAL que el JSON del
prototipo (caso dorado), que cada campo exportado tenga la forma exacta que
acepta main._campos_tramite_validos, y que el saneo descarte lo que no está
en el catálogo.

Correr con: python -m pytest test_asistente_tramites.py -q
"""
import copy
import json
from datetime import date
from pathlib import Path

import pytest

import asistente_tramites as at
import db
import main
import validaciones_tramite

DORADO = Path("docs/chat/2026-10-16-ejemplo-kit-escolar.colm3na.json")
HOY = date(2026, 10, 16)


def _ejemplo():
    return at.sanear_propuesta(at.EJEMPLO_PROPUESTA, relato=at.EJEMPLO_RELATO)


# ---------------------------------------------------------------- catálogo
def test_el_catalogo_es_el_del_constructor():
    """Fail-closed: un tipo de campo, un ancho o un estado nuevo en Colm3na
    hace fallar esto hasta que el asistente sepa qué decir de él."""
    assert tuple(at.TIPOS) == main.TIPOS_DATO_TRAMITE
    assert at.ANCHOS == main.ANCHOS_CAMPO_TRAMITE
    assert set(at.ANCHO_POR_TIPO) == set(at.TIPOS) and set(at.ANCHO_POR_TIPO.values()) <= set(at.ANCHOS)
    assert set(at.ESTADOS) == set(db.ESTADOS_TRAMITE)   # el orden de acá es el cronológico de la pantalla
    assert set(at.CON_OPCIONES) <= set(at.TIPOS)
    # Las validaciones fijas que el asistente escribe usan operadores reales.
    for c in at.campos_colm3na(_ejemplo()["campos"]):
        for v in c["validaciones"]:
            assert v["operador"] in validaciones_tramite.OPERADORES


def test_cada_brecha_esta_completa():
    for k, b in at.BRECHAS.items():
        assert b["nivel"] in ("ajuste", "desarrollo"), k
        assert b["tam"] in ("chico", "mediano", "grande"), k
        assert b["titulo"] and b["hoy"] and b["rec"], k
    assert set(at.CONTROL_BRECHA.values()) <= set(at.BRECHAS)
    assert set(at.CONTROL_BRECHA) <= set(at.CONTROLES)


def test_las_preguntas_viajan_como_datos():
    """`cuando` es un dict (no una función): la pantalla lo evalúa igual."""
    claves = [p["clave"] for p in at.PREGUNTAS]
    assert len(claves) == len(set(claves)) == 14
    for p in at.PREGUNTAS:
        if "cuando" in p:
            assert set(p["cuando"]) == {"clave", "en"} and p["cuando"]["clave"] in claves
        for t in ("texto", "texto2"):
            if t in p:
                assert p[t]["clave"] in at.CLAVES_TEXTO
    json.dumps(at.catalogo(), ensure_ascii=False)   # serializable entero


# ---------------------------------------------------------------- caso dorado
def test_el_kit_escolar_sale_igual_que_el_prototipo():
    """El JSON que generó el prototipo de Chat para el kit escolar es el caso
    dorado: el motor tiene que reproducirlo exacto (misma fecha de
    generación). Si una diferencia es a propósito, se anota acá."""
    esperado = json.loads(DORADO.read_text(encoding="utf-8"))
    generado = at.resolver(_ejemplo(), hoy=HOY)["json"]
    assert generado == esperado


def test_resolver_es_determinista():
    e = _ejemplo()
    assert at.resolver(e, hoy=HOY) == at.resolver(copy.deepcopy(e), hoy=HOY)


# ---------------------------------------------------------------- forma del campo
def test_cada_campo_tiene_la_forma_que_acepta_el_constructor():
    """Lo exportado ya es importable: pasar los campos por el saneo real del
    constructor no cambia nada (salvo `id`, que agrega, y `x_pendiente`, que
    el importador ignora)."""
    for f in at.resolver(_ejemplo(), hoy=HOY)["formularios"]:
        campos = f["campos"]
        saneados = main._campos_tramite_validos(copy.deepcopy(campos))
        assert len(saneados) == len(campos)
        for c, s in zip(campos, saneados):
            assert {k: v for k, v in s.items() if k != "id"} == {k: v for k, v in c.items() if k != "x_pendiente"}
            assert validaciones_tramite.validaciones_saneadas(c["validaciones"], c["tipo_dato"]) == c["validaciones"]


def test_un_control_sin_soporte_marca_pendiente_y_no_inventa_validacion():
    campos = at.campos_colm3na([
        at.sanear_campo({"etiqueta": "DNI", "tipo": "numero", "control": "unico"}),
        at.sanear_campo({"etiqueta": "Nacimiento", "tipo": "fecha", "control": "no_futura"}),
        at.sanear_campo({"etiqueta": "Mail", "tipo": "texto", "control": "formato"}),
    ])
    assert campos[0]["x_pendiente"] == "No repetir entre pedidos" and campos[0]["validaciones"] == []
    assert campos[1]["validaciones"][0]["operador"] == "<=" and "x_pendiente" not in campos[1]
    assert campos[2]["x_pendiente"] == "Formato (mail, teléfono)"


# ---------------------------------------------------------------- saneo
def test_sanear_descarta_lo_que_no_esta_en_el_catalogo():
    e = at.sanear_propuesta({
        "nombre": "Ayuda por nacimiento", "codigo": "ayú-da nac!",
        "respuestas": {"quien": "marciano", "fin": "pago", "requisitos": ["titular", "inventado", "ninguno"],
                       "area": "  Acción Social  ", "enc_datos": "x" * 500},
        "campos": [{"etiqueta": "Partida", "tipo": "pdf", "control": "mágico"}, "basura",
                   {"etiqueta": "Foto", "tipo": "archivo", "opciones": "jpg"}, {"tipo": "separador", "obligatorio": True}],
        "dudas": ["¿Y los mellizos?", "", 42],
    }, de_ia=True)
    assert e["codigo"] == "AYUDAN"          # sigla("ayú-da nac!") recortada a seis
    assert "quien" not in e["respuestas"] and e["respuestas"]["fin"] == "pago"
    assert e["respuestas"]["requisitos"] == ["ninguno"], "lo excluyente desmarca lo demás"
    assert e["respuestas"]["area"] == "Acción Social" and len(e["respuestas"]["enc_datos"]) == 400
    assert e["de_ia"] == ["requisitos", "fin"]
    assert [c["tipo"] for c in e["campos"]] == ["texto", "archivo", "separador"]
    assert e["campos"][0]["control"] == "" and e["campos"][1]["opciones"] == "jpg,jpeg"
    assert e["campos"][2]["obligatorio"] is False
    assert e["dudas"] == ["¿Y los mellizos?", "42"]


def test_normalizar_extensiones():
    assert at.normalizar_extensiones("") == at.EXTENSIONES_DEFAULT
    assert at.normalizar_extensiones("PDF, .jpeg") == "pdf,jpeg,jpg"
    assert at.normalizar_extensiones("pdf,jpg,jpg") == "pdf,jpg,jpeg"


def test_codigo_desde_el_nombre():
    assert at.codigo_de("Kit escolar 2027") == "KE27"
    assert at.codigo_de("") == "NUEVO"
    assert at.sigla("Ñandú 7") == "NANDU7"


def test_preguntas_vigentes_dependen_de_las_respuestas():
    sin = [p["clave"] for p in at.preguntas_vigentes({"aprueba": "no", "fin": "pago"})]
    assert "segundo" not in sin and "entrega" not in sin and "cupo" not in sin
    con = [p["clave"] for p in at.preguntas_vigentes({"aprueba": "otra", "fin": "entrega"})]
    assert {"segundo", "entrega", "cupo"} <= set(con)


# ---------------------------------------------------------------- circuito
@pytest.mark.parametrize("fin", ["entrega", "respuesta", "turno", "pago"])
@pytest.mark.parametrize("aprueba", ["misma", "otra", "no"])
@pytest.mark.parametrize("entrega", ["area", "delegado_panel", "delegado", "proveedor"])
def test_todo_circuito_cierra(fin, aprueba, entrega):
    """Cualquier combinación de respuestas da un circuito con inicio, un
    cierre, fin, y flujos que apuntan a nodos que existen."""
    e = at.sanear_propuesta({"nombre": "X", "respuestas": {
        "quien": "afiliado", "atiende": "central", "area": "Mesa", "aprueba": aprueba, "area_aprueba": "Secretaría",
        "segundo": "si", "enc_nombre": "Registro", "enc_datos": "Nombre, DNI, Fecha de nacimiento, Constancia",
        "fin": fin, "entrega": entrega, "entrega_quien": "Delegado", "tercero": "si", "tercero_nombre": "Hotel",
        "listado": "si"}, "campos": [{"etiqueta": "Dato", "tipo": "texto"}]})
    c = at.circuito(e)
    ids = {n["id"] for n in c["nodos"]}
    assert {"ini", "env", "rev", "cierra", "fin"} <= ids
    assert all(f["de"] in ids and f["a"] in ids for f in c["flujos"])
    assert all(n["carril"] in {l["k"] for l in c["carriles"]} for n in c["nodos"])
    assert c["cols"] == max(n["col"] for n in c["nodos"]) + 1
    if aprueba != "no":
        assert c["encadenados"] and c["encadenados"][0]["campos"][2]["tipo"] == "fecha"
        assert "encadenado" in at.brechas_de(e, c)
    else:
        assert not c["encadenados"]


def test_un_actor_extra_entra_despues_del_paso_elegido():
    e = _ejemplo()
    e["extras"] = at.sanear_extras([{"nombre": "Auditoría", "hace": "Controla el padrón", "despues": "dec", "dato": "Listado", "colm3na": True},
                                    {"nombre": "", "hace": "nada"}])
    c = at.circuito(e)
    extra = next(n for n in c["nodos"] if n["id"] == "x0n")
    ref = next(n for n in c["nodos"] if n["id"] == "dec")
    assert extra["col"] == ref["col"] and c["carriles"][-1]["nombre"] == "Auditoría"
    assert any(d["dato"] == "Listado" and d["a"] == "Auditoría" for d in c["datos"])
    assert sum(1 for l in c["carriles"] if l["k"].startswith("x")) == 1


# ---------------------------------------------------------------- preparar
def test_preparar_dice_que_existe_y_que_falta_con_el_sindicato_elegido():
    e = _ejemplo()
    r = at.resolver(e, sindicato={
        "nombre": "La Bancaria", "modulos": ["tramites", "noticias"],
        "seccionales": ["Sede Central", "Rosario", "Córdoba"],
        "areas": [{"nombre": "Acción Social", "seccional": "Sede Central"}, {"nombre": "Acción Social", "seccional": "Rosario"}],
    }, hoy=HOY)
    cfg = {x["clave"]: x for x in r["preparar"]["configurar"]}
    assert cfg["modulos"]["estado"] == "falta" and "Notificaciones" in cfg["modulos"]["detalle"]
    assert cfg["area"]["estado"] == "falta" and "Córdoba" in cfg["area"]["detalle"]
    sin = at.resolver(e, hoy=HOY)["preparar"]
    assert {x["estado"] for x in sin["configurar"]} == {"sin_verificar"}
    assert [x["clave"] for x in r["preparar"]["ajuste"]] == ["ventana", "duplicados", "exportar", "entrega", "dependencia"]
    assert [x["clave"] for x in r["preparar"]["desarrollo"]] == ["requisitos", "familia", "cupo"]


def test_las_pendientes_incluyen_dudas_preguntas_sin_responder_y_brechas():
    e = at.sanear_propuesta({"nombre": "X", "respuestas": {"ventana": "si"}, "dudas": ["¿Plazo?"]})
    pend = at.resolver(e, hoy=HOY)["pendientes"]
    assert pend[0] == "¿Plazo?"
    assert "¿Quién inicia el pedido?" in pend and "¿Estos son los datos que se piden?" in pend
    assert pend[-1].startswith("¿Aceptan arrancar así mientras tanto? Abrir y cerrar el formulario por fechas")


def test_la_instruccion_y_los_estados_siguen_a_las_respuestas():
    r = at.resolver(_ejemplo(), hoy=HOY)
    claves = [p["clave"] for p in r["instruccion"]["pasos"]]
    assert claves == ["crear", "destino", "pase", "probar", "anunciar"]
    assert "Sin pase entre áreas." in r["instruccion"]["pasos"][2]["texto"]
    assert "13. Lugar de retiro — Lista desplegable, obligatorio — Sede de la seccional" in r["instruccion"]["texto"]
    assert [x["estado"] for x in r["estados"]] == ["iniciado", "en_tratamiento", "espera_info", "respondido", "terminado"]
    assert "Retiralo en Sede, delegación o comisión gremial del banco" in r["estados"][3]["mensaje"]
    assert [q["actor"] for q in r["quien_hace_que"]] == ["Afiliado", "Acción Social", "Delegado de la comisión gremial", "Proveedor de kits"]
    assert r["quien_hace_que"][2]["necesita"] == "Acordar el canal fuera de Colm3na"
