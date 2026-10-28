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
    claves = [p["clave"] for p in at.PREGUNTAS_TODAS]
    assert len(claves) == len(set(claves)) == 14
    assert len(at.PREGUNTAS) == 6 and len(at.INFERIDAS) == 8, "seis se preguntan, ocho se infieren (previo y pago_colm3na desde 2026-10-28)"
    assert not any("cuando" in p for p in at.PREGUNTAS), "las que se preguntan se preguntan siempre"
    for p in at.PREGUNTAS_TODAS:
        validas = [k for k, _ in p["opciones"]]
        rec = p["recomendada"]
        assert (set(rec) <= set(validas)) if p.get("multiple") else rec in validas, p["clave"]
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
    generación). Si una diferencia es a propósito, se anota acá.

    Diferencias a propósito respecto del prototipo de Chat (2026-10-16,
    bloque 5 de PLAN_LISTAS_VALIDACIONES.md): el formulario trae
    `requisitos` (ser titular sale como requisito sobre `sistema.en_padron`),
    y `requisitos` y `lista` dejaron de ser brechas porque existen; el
    archivo dorado se regeneró con el motor ese día. Y el 2026-10-28
    (PLAN_ASISTENTE_TRAMITES_V2.md): `respuestas.previo` (el formulario
    previo de Colm3na) y `pendientes.aclaraciones` (lo que el analista
    contestó con texto), y los dos campos del solicitante (nombre y CUIL
    extraídos del padrón) adelante del formulario; regenerado otra vez."""
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
            # las de fuente `funcion` necesitan la lista entera (la segunda clave va por orden)
            assert validaciones_tramite.validaciones_saneadas(c["validaciones"], c["tipo_dato"], campos=campos, indice=campos.index(c)) == c["validaciones"]


def test_un_control_sin_soporte_marca_pendiente_y_no_inventa_validacion():
    campos = at.campos_colm3na([
        at.sanear_campo({"etiqueta": "DNI", "tipo": "numero", "control": "unico"}),
        at.sanear_campo({"etiqueta": "Nacimiento", "tipo": "fecha", "control": "no_futura"}),
        at.sanear_campo({"etiqueta": "Mail", "tipo": "texto", "control": "formato"}),
    ])
    assert campos[0]["x_pendiente"] == "No repetir entre pedidos" and campos[0]["validaciones"] == []
    assert campos[1]["validaciones"][0]["operador"] == "<=" and "x_pendiente" not in campos[1]
    assert campos[2]["x_pendiente"] == "Formato (mail, teléfono)"


def test_el_control_contra_una_lista_exporta_una_validacion_real():
    """Desde el bloque 3 de Listas y validaciones, «contra una lista del
    sindicato» no es una brecha: sale como validación por función (el dato
    tiene que estar en el grupo familiar, buscado por este mismo campo) y
    pasa entera por el saneo real del constructor."""
    campos = at.campos_colm3na([
        at.sanear_campo({"etiqueta": "", "tipo": "separador"}),          # no se exporta: el índice lo saltea
        at.sanear_campo({"etiqueta": "Grado", "tipo": "seleccion", "opciones": "1º,2º"}),
        at.sanear_campo({"etiqueta": "DNI del chico", "tipo": "texto", "control": "lista"}),
    ])
    v = campos[-1]["validaciones"][0]
    assert v["fuente"] == "funcion" and v["lista"] == "grupo_familiar" and v["clave2"] == len(campos) - 1
    assert v["trae"] == "existe" and v["en_vivo"] is True and "x_pendiente" not in campos[-1]
    saneados = main._campos_tramite_validos(copy.deepcopy(campos))
    assert saneados[-1]["validaciones"] == [v]
    reqs = at.requisitos_colm3na({"requisitos": ["antiguedad", "titular", "edad"], "frecuencia": "unica"})
    assert [q.get("trae") or q["formula"][:11] for q in reqs] == ["meses_entre", "en_padron", "tramites_de_este_tipo"]
    assert len(validaciones_tramite.requisitos_saneados(reqs, campos)) == 3, "los tres pasan el saneo real"


# ---------------------------------------------------------------- saneo
def test_sanear_descarta_lo_que_no_esta_en_el_catalogo():
    e = at.sanear_propuesta({
        "nombre": "Ayuda por nacimiento", "codigo": "ayú-da nac!",
        "respuestas": {"quien": "marciano", "fin": "pago", "requisitos": ["titular", "inventado", "ninguno"],
                       "area": "  Acción Social  ", "enc_datos": "x" * 500},
        "campos": [{"etiqueta": "Partida", "tipo": "pdf", "control": "mágico"}, "basura",
                   {"etiqueta": "Foto", "tipo": "archivo", "opciones": "jpg"}, {"tipo": "separador", "obligatorio": True}],
        "dudas": ["¿Y los mellizos?", "", 42, {"pregunta": "¿Quién aprueba?", "sobre": "aprueba", "opciones": ["ignoradas"]},
                  {"pregunta": "¿Plazo?", "sobre": "inventada", "opciones": ["30 días", "60 días", "", "30 días"]}, {"sobre": "fin"}],
        "aclaraciones": [{"pregunta": "¿Plazo?", "respuesta": "60 días"}, {"pregunta": "sin respuesta"}, "basura"],
    }, de_ia=True)
    assert e["codigo"] == "AYUDAN"          # sigla("ayú-da nac!") recortada a seis
    # Un valor fuera del catálogo se descarta y queda la RECOMENDADA: siempre hay una.
    assert e["respuestas"]["quien"] == "afiliado" and "quien" in e["recomendadas"] and e["respuestas"]["fin"] == "pago"
    assert e["respuestas"]["requisitos"] == ["ninguno"], "lo excluyente desmarca lo demás"
    assert e["respuestas"]["area"] == "Acción Social" and len(e["respuestas"]["enc_datos"]) == 400
    assert e["de_ia"] == ["requisitos", "fin"] and "fin" not in e["recomendadas"]
    assert e["respuestas"]["ventana"] == "no" and "ventana" in e["recomendadas"], "las inferidas también traen su valor"
    assert e["campos"][0]["aclaracion"] == "" and e["campos"][0]["formula"] == ""
    assert [c["tipo"] for c in e["campos"]] == ["texto", "archivo", "separador"]
    assert e["campos"][0]["control"] == "" and e["campos"][1]["opciones"] == "jpg,jpeg"
    assert e["campos"][2]["obligatorio"] is False
    # Las dudas (V3): un texto suelto queda sin opciones; sobre una pregunta
    # del catálogo lleva LAS opciones de esa pregunta; si no, las suyas, sin
    # repetir; sin pregunta no es una duda.
    assert [d["pregunta"] for d in e["dudas"]] == ["¿Y los mellizos?", "42", "¿Quién aprueba?", "¿Plazo?"]
    assert e["dudas"][0]["opciones"] == [] and e["dudas"][2]["sobre"] == "aprueba"
    assert e["dudas"][2]["opciones"][0] == ["misma", "Sí, la misma área que lo revisa"]
    assert e["dudas"][3]["sobre"] == "" and e["dudas"][3]["opciones"] == [["30 días", "30 días"], ["60 días", "60 días"]]
    assert e["aclaraciones"] == [{"pregunta": "¿Plazo?", "respuesta": "60 días"}]


def test_normalizar_extensiones():
    assert at.normalizar_extensiones("") == at.EXTENSIONES_DEFAULT
    assert at.normalizar_extensiones("PDF, .jpeg") == "pdf,jpeg,jpg"
    assert at.normalizar_extensiones("pdf,jpg,jpg") == "pdf,jpg,jpeg"


def test_codigo_desde_el_nombre():
    assert at.codigo_de("Kit escolar 2027") == "KE27"
    assert at.codigo_de("") == "NUEVO"
    assert at.sigla("Ñandú 7") == "NANDU7"


def test_preguntas_vigentes_dependen_de_las_respuestas():
    """Las inferidas con `cuando` solo valen si la respuesta de la que
    dependen las habilita; las seis preguntadas, siempre."""
    sin = [p["clave"] for p in at.INFERIDAS if at.pregunta_vigente(p, {"aprueba": "no", "fin": "pago"})]
    assert "segundo" not in sin and "entrega" not in sin and "cupo" not in sin
    con = [p["clave"] for p in at.INFERIDAS if at.pregunta_vigente(p, {"aprueba": "otra", "fin": "entrega"})]
    assert {"segundo", "entrega", "cupo"} <= set(con)
    assert [p["clave"] for p in at.preguntas_vigentes({})] == [p["clave"] for p in at.PREGUNTAS]


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
    assert [x["clave"] for x in r["preparar"]["ajuste"]] == ["ventana", "duplicados", "entrega", "dependencia"]
    assert "exportar" not in at.BRECHAS, "el listado con las respuestas existe desde 2026-10-28"
    assert "listado" in [p["clave"] for p in r["instruccion"]["pasos"]]
    assert [x["clave"] for x in r["preparar"]["desarrollo"]] == ["familia", "cupo"]
    assert "requisitos" not in at.BRECHAS and "lista" not in at.BRECHAS, "existen desde el bloque 3: no son brechas"
    assert "requisitos" in [p["clave"] for p in r["instruccion"]["pasos"]]


def test_las_pendientes_son_solo_las_dudas_y_el_resto_va_al_prompt():
    """Sin segundo cuestionario (SDN, 2026-10-18): lo pendiente son las
    dudas de la IA; las notas libres y las brechas viven en el prompt."""
    e = at.sanear_propuesta({"nombre": "X", "respuestas": {"ventana": "si", "nota_fin": "Se entrega en la obra social"},
                             "dudas": ["¿Plazo?"]})
    r = at.resolver(e, hoy=HOY)
    assert r["pendientes"] == [{"pregunta": "¿Plazo?", "sobre": "", "opciones": []}]
    assert r["json"]["pendientes"]["preguntas"] == ["¿Plazo?"]
    assert "## A confirmar con el sindicato" in r["prompt"] and "- ¿Plazo?" in r["prompt"]
    assert "¿Cómo termina? Se entrega en la obra social" in r["prompt"]
    assert "Abrir y cerrar el formulario por fechas" in r["prompt"] and "salida provisoria" in r["prompt"]


def test_el_prompt_dice_que_funcion_usar_y_cual_desarrollar():
    """Una regla escrita con el catálogo sale como validación real; una que
    no compila queda «a controlar»; una función nueva, «a desarrollar»."""
    e = at.sanear_propuesta({"nombre": "Préstamo", "respuestas": {"requisitos": ["credencial"]}, "campos": [
        {"etiqueta": "DNI del chico", "tipo": "texto", "aclaracion": "Sin puntos", "regla": "Hasta 12 años",
         "formula": "anios_entre(lista.fecha_nacimiento, hoy()) <= 12"},
        {"etiqueta": "Monto", "tipo": "numero", "regla": "Hasta el 30% del bruto", "formula": "campo.monto <= sistema.ultimo_recibo_bruto * 0.3"},
        {"etiqueta": "Sucursal", "tipo": "texto", "regla": "Una sucursal del banco", "funcion_nueva": "sucursal_valida: si está en la lista de sucursales"},
        {"etiqueta": "Mal", "tipo": "texto", "formula": "sistema.inventado > 1"}]})
    r = at.resolver(e, hoy=HOY)
    f = r["formularios"][0]
    nombre, cuil, dni, monto, suc, mal = f["campos"]
    assert nombre["tipo_dato"] == "calculado" and nombre["validaciones"][0]["ingreso"] and cuil["validaciones"][0]["trae"] == "cuil"
    assert dni["x_aclaracion"] == "Sin puntos" and dni["validaciones"][0]["origen"] == "lista" and dni["validaciones"][0]["clave2"] == 2
    assert dni["validaciones"][0]["mensaje"] == "Hasta 12 años" and dni["validaciones"][0]["en_vivo"] is True
    assert monto["validaciones"][0]["origen"] == "sistema" and monto["validaciones"][0]["en_vivo"] is False
    assert suc["validaciones"] == [] and suc["x_funcion_nueva"].startswith("sucursal_valida")
    assert "no se pudo guardar" in mal["x_regla"] and mal["validaciones"] == []
    assert f["requisitos"][0]["trae"] == "credencial_vigente"
    # Y lo exportado pasa entero por el saneo real del constructor.
    saneados = main._campos_tramite_validos(copy.deepcopy(f["campos"]))
    assert [len(c["validaciones"]) for c in saneados] == [1, 1, 1, 1, 0, 0]
    p = r["prompt"]
    assert "## Validaciones: usar lo que existe" in p and "`campo.monto <= sistema.ultimo_recibo_bruto * 0.3`" in p
    assert "`sistema.credencial_vigente == si`" in p
    assert "## Funciones a desarrollar" in p and "sucursal_valida" in p
    assert "## A controlar sin función todavía" in p and "«Sucursal»: Una sucursal del banco" in p
    assert "Aclaración: Sin puntos" in p
    assert "Extraer de `sistema.afiliado.nombre`" in p and "Se completa con" not in p.split("## Validaciones")[1]


def test_el_pago_fuera_de_colm3na_no_es_brecha_y_el_solicitante_no_se_pide_dos_veces():
    """Prueba de SDN (2026-10-28) con un subsidio por matrimonio: terminar con
    un pago no significa pagar DESDE Colm3na; solo eso es la brecha. Y el
    nombre o el CUIL que la IA pida de más se descartan: ya vienen."""
    e = at.sanear_propuesta({"nombre": "Subsidio por matrimonio", "respuestas": {"fin": "pago"},
                             "campos": [{"etiqueta": "Nombre y apellido", "tipo": "texto"}, {"etiqueta": "DNI", "tipo": "numero"},
                                        {"etiqueta": "Acta de matrimonio", "tipo": "archivo"}]})
    r = at.resolver(e, hoy=HOY)
    assert "pago" not in r["brechas"] and r["veredicto"]["complejidad"] == "ninguna"
    assert [c["etiqueta"] for c in r["formularios"][0]["campos"]] == ["Apellido y nombre", "CUIL", "Acta de matrimonio"]
    assert "pago_colm3na" in r["json"]["respuestas"] and r["json"]["respuestas"]["pago_colm3na"] == "no"
    e["respuestas"]["pago_colm3na"] = "si"
    assert "pago" in at.resolver(e, hoy=HOY)["brechas"]


def test_la_instruccion_y_los_estados_siguen_a_las_respuestas():
    r = at.resolver(_ejemplo(), hoy=HOY)
    claves = [p["clave"] for p in r["instruccion"]["pasos"]]
    assert claves == ["crear", "destino", "pase", "requisitos", "listado", "probar", "anunciar"]
    assert "en «Requisitos para iniciar»" in r["instruccion"]["pasos"][3]["texto"] and "grupo familiar" in r["instruccion"]["pasos"][3]["texto"]
    assert "Sin pase entre áreas." in r["instruccion"]["pasos"][2]["texto"]
    assert "15. Lugar de retiro — Lista desplegable, obligatorio — Sede de la seccional" in r["instruccion"]["texto"]
    assert "1. Apellido y nombre — Extraído del padrón (sistema.afiliado.nombre), obligatorio" in r["instruccion"]["texto"]
    assert [x["estado"] for x in r["estados"]] == ["iniciado", "en_tratamiento", "espera_info", "respondido", "terminado"]
    assert "Retiralo en Sede, delegación o comisión gremial del banco" in r["estados"][3]["mensaje"]
    assert [q["actor"] for q in r["quien_hace_que"]] == ["Afiliado", "Acción Social", "Delegado de la comisión gremial", "Proveedor de kits"]
    assert r["quien_hace_que"][2]["necesita"] == "Acordar el canal fuera de Colm3na"
