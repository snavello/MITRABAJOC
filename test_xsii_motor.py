"""XSII, motor genérico (xsii/motor): validación del catálogo, estados,
precedencia, consultas. Sin base de datos ni nada de la app.

Correr con: python -m pytest test_xsii_motor.py -q
"""
import ast
import sys
from pathlib import Path

import pytest

from xsii.motor import catalogo, consulta, estados
from xsii.motor.catalogo import Tarea
from xsii.motor.estados import Control

GRUPOS = ("A", "B")


def T(codigo, necesita=(), mejora_con=(), insumos=(), aplica_si=None, grupo="A", modo="manual"):
    return Tarea(codigo, f"Tarea {codigo}", grupo, modo, necesita=tuple(necesita),
                 mejora_con=tuple(mejora_con), insumos=tuple(insumos),
                 aplica_si=aplica_si, control="c_" + codigo)


OK = Control("completa", "ok")
OBS = Control("observaciones", "ok con avisos", faltan=["un aviso"])
NO = Control("incompleta", "falta", faltan=["algo"])
MEDIO = Control("incompleta", "a medias", en_curso=True)


def hechos(controles=None, **resto):
    h = {"controles": controles or {}, "aplica": {}, "insumos": {}, "decisiones": {},
         "ensayos_abiertos": set()}
    h.update(resto)
    return h


# ---- catálogo ----------------------------------------------------------------

def test_catalogo_valido():
    assert catalogo.validar([T("A1"), T("A2", ["A1"])], GRUPOS) == []


def test_catalogo_errores():
    tareas = [
        T("A1"), T("A1"),                                   # repetido
        T("A2", necesita=["ZZ"]),                           # dependencia inexistente
        Tarea("A3", "x", "A", "inventado", control="c"),    # modo inválido
        Tarea("A4", "x", "Z", "manual", control="c"),       # grupo inválido
        Tarea("A5", "x", "A", "manual"),                    # sin control
        T("A6", mejora_con=["ZZ"]),
        T("A7", necesita=["A7"]),
    ]
    texto = "\n".join(catalogo.validar(tareas, GRUPOS))
    assert "A1: el código está repetido" in texto
    assert "A2: necesita ZZ, que no existe" in texto
    assert "A3: modo inválido" in texto
    assert "A4: grupo inválido" in texto
    assert "A5: la tarea no tiene control" in texto
    assert "A6: mejora con ZZ, que no existe" in texto
    assert "A7: se necesita a sí misma" in texto


def test_catalogo_ciclo_de_duras_es_error():
    tareas = [T("A1", ["A3"]), T("A2", ["A1"]), T("A3", ["A2"])]
    errores = catalogo.validar(tareas, GRUPOS)
    assert any(e.startswith("Ciclo de dependencias duras") for e in errores)


def test_catalogo_ciclo_de_blandas_se_informa_aparte():
    tareas = [T("A1", mejora_con=["A2"]), T("A2", mejora_con=["A1"])]
    errores = catalogo.validar(tareas, GRUPOS)
    assert any(e.startswith("Ciclo de dependencias blandas") for e in errores)
    assert not any("duras" in e for e in errores)


def test_una_dura_y_una_blanda_cruzadas_no_son_ciclo():
    tareas = [T("A1", necesita=["A2"]), T("A2", mejora_con=["A1"])]
    assert catalogo.validar(tareas, GRUPOS) == []


def test_control_valida_su_estado():
    with pytest.raises(ValueError):
        Control("casi")


# ---- estados -----------------------------------------------------------------

def estado(tareas, h, codigo):
    return estados.resolver(tareas, h)[codigo]


def test_lista_sin_nada_que_la_frene():
    t = [T("A1")]
    assert estado(t, hechos({"A1": NO}), "A1").estado == "lista"


def test_hecha_y_con_observaciones():
    t = [T("A1"), T("A2")]
    r = estados.resolver(t, hechos({"A1": OK, "A2": OBS}))
    assert r["A1"].estado == "hecha" and not r["A1"].con_observaciones
    assert r["A2"].estado == "hecha" and r["A2"].con_observaciones
    assert r["A2"].control is OBS


def test_bloqueada_dice_cual():
    t = [T("A1"), T("A2"), T("A3", ["A1", "A2"])]
    e = estado(t, hechos({"A1": OK, "A2": NO, "A3": NO}), "A3")
    assert e.estado == "bloqueada" and e.frenada_por == ["A2"]


def test_hecha_aunque_la_dependencia_no_lo_este():
    """El estado se calcula de la realidad: si el control pasa, está hecha."""
    t = [T("A1"), T("A2", ["A1"])]
    assert estado(t, hechos({"A1": NO, "A2": OK}), "A2").estado == "hecha"


def test_esperando_un_dato_y_en_curso():
    t = [T("A1", insumos=["planilla"]), T("A2")]
    h = hechos({"A1": NO, "A2": NO})
    e = estado(t, h, "A1")
    assert e.estado == "esperando" and e.insumos_faltantes == ["planilla"]
    h["insumos"]["planilla"] = True
    assert estado(t, h, "A1").estado == "lista"
    assert estado(t, hechos({"A1": NO, "A2": MEDIO}, insumos={"planilla": True}), "A2").estado == "en_curso"
    assert estado(t, hechos({"A1": NO, "A2": NO}, ensayos_abiertos={"A2"}), "A2").estado == "en_curso"


def test_no_aplica_por_condicion_y_por_decision():
    t = [T("A1", aplica_si="modulo"), T("A2")]
    h = hechos({"A1": NO, "A2": NO}, aplica={"modulo": False})
    assert estado(t, h, "A1").estado == "no_aplica"
    h = hechos({"A1": NO, "A2": NO}, aplica={"modulo": True},
               decisiones={"A1": {"tipo": "no_aplica", "motivo": "x"}})
    assert estado(t, h, "A1").estado == "no_aplica"


def test_condicion_sin_informar_es_error():
    with pytest.raises(ValueError, match="modulo"):
        estados.resolver([T("A1", aplica_si="modulo")], hechos({"A1": NO}))


def test_precedencia_completo():
    """no_aplica > hecha > bloqueada > esperando > en_curso > lista."""
    t = [T("D"), T("X", ["D"], insumos=["i"])]
    # Bloqueada gana a esperando y a en_curso.
    assert estado(t, hechos({"D": NO, "X": MEDIO}), "X").estado == "bloqueada"
    # Sin la dependencia, esperando gana a en_curso.
    assert estado(t, hechos({"D": OK, "X": NO}), "X").estado == "esperando"
    # Con el insumo, en_curso gana a lista.
    assert estado(t, hechos({"D": OK, "X": MEDIO}, insumos={"i": True}), "X").estado == "en_curso"
    # Hecha gana a bloqueada.
    assert estado(t, hechos({"D": NO, "X": OK}), "X").estado == "hecha"
    # no_aplica gana a hecha.
    t2 = [T("X", aplica_si="m")]
    assert estado(t2, hechos({"X": OK}, aplica={"m": False}), "X").estado == "no_aplica"


def test_completada_a_mano_destraba_y_conserva_el_control():
    t = [T("A1"), T("A2", ["A1"])]
    dec = {"A1": {"tipo": "completada_a_mano", "quien": "ana", "cuando": "2026-11-26", "motivo": "m"}}
    r = estados.resolver(t, hechos({"A1": NO, "A2": NO}, decisiones=dec))
    assert r["A1"].estado == "hecha" and r["A1"].a_mano
    assert r["A1"].control is NO and r["A1"].decision["quien"] == "ana"
    assert r["A2"].estado == "lista"


def test_completada_a_mano_con_el_control_pasando_no_se_marca_a_mano():
    t = [T("A1")]
    dec = {"A1": {"tipo": "completada_a_mano", "motivo": "m"}}
    assert not estado(t, hechos({"A1": OK}, decisiones=dec), "A1").a_mano


def test_no_aplica_destraba():
    t = [T("A1"), T("A2", ["A1"])]
    dec = {"A1": {"tipo": "no_aplica", "motivo": "m"}}
    assert estado(t, hechos({"A1": NO, "A2": NO}, decisiones=dec), "A2").estado == "lista"


def test_blandas_avisan_y_no_frenan():
    t = [T("A1"), T("A2", mejora_con=["A1"])]
    e = estado(t, hechos({"A1": NO, "A2": NO}), "A2")
    assert e.estado == "lista" and e.avisos == ["A1"]
    assert estado(t, hechos({"A1": OK, "A2": NO}), "A2").avisos == []


def test_pospuesta_no_cambia_el_estado():
    t = [T("A1")]
    e = estado(t, hechos({"A1": NO}, decisiones={"A1": {"tipo": "pospuesta"}}), "A1")
    assert e.estado == "lista" and e.pospuesta


def test_decision_invalida_es_error():
    with pytest.raises(ValueError):
        estados.resolver([T("A1")], hechos({"A1": NO}, decisiones={"A1": {"tipo": "xx"}}))


def test_sin_control_calculado_cuenta_como_incompleta():
    assert estado([T("A1")], hechos({}), "A1").estado == "lista"


# ---- consultas ---------------------------------------------------------------

def armar():
    """A1 → A2 → A4 ; A1 → A3 ; A5 suelta."""
    return [T("A1"), T("A2", ["A1"]), T("A3", ["A1"]), T("A4", ["A2"]), T("A5")]


def tablero(tareas, controles, **resto):
    return estados.resolver(tareas, hechos(controles, **resto))


def test_resumen():
    t = armar()
    tb = tablero(t, {"A1": OK, "A2": OBS, "A3": NO, "A4": NO, "A5": NO},
                 decisiones={"A5": {"tipo": "no_aplica"}})
    r = consulta.resumen(tb)
    assert r["total"] == 5 and r["aplican"] == 4 and r["resueltas"] == 2
    assert r["porcentaje"] == 50 and r["por_estado"]["no_aplica"] == 1
    assert r["con_observaciones"] == 1


def test_recomendada_la_que_mas_destraba():
    t = armar()
    tb = tablero(t, {c.codigo: NO for c in t})
    # A1 destraba A2, A3 y A4 (3); A5 no destraba nada.
    assert consulta.recomendada(t, tb) == "A1"
    assert consulta.alternativas(t, tb) == ["A5"]


def test_recomendada_la_en_curso_gana():
    t = armar()
    tb = tablero(t, {"A1": NO, "A2": NO, "A3": NO, "A4": NO, "A5": MEDIO})
    assert consulta.recomendada(t, tb) == "A5"


def test_recomendada_empate_por_orden_y_pospuesta_se_saltea():
    t = [T("B1"), T("B2")]
    tb = tablero(t, {"B1": NO, "B2": NO})
    assert consulta.recomendada(t, tb) == "B1"
    tb = tablero(t, {"B1": NO, "B2": NO}, decisiones={"B1": {"tipo": "pospuesta"}})
    assert consulta.recomendada(t, tb) == "B2"


def test_recomendada_ninguna():
    t = [T("B1")]
    tb = tablero(t, {"B1": OK})
    assert consulta.recomendada(t, tb) is None
    assert consulta.alternativas(t, tb) == []


def test_que_destraba_directo_y_transitivo_sin_resueltas():
    t = armar()
    tb = tablero(t, {"A1": NO, "A2": NO, "A3": OK, "A4": NO, "A5": NO})
    d = consulta.que_destraba(t, tb, "A1")
    assert d["directo"] == ["A2"]                   # A3 ya está hecha
    assert d["transitivo"] == ["A2", "A4"]


def test_que_frena_y_camino():
    t = armar()
    tb = tablero(t, {c.codigo: NO for c in t})
    assert consulta.que_frena(t, tb, "A4") == ["A1", "A2"]
    assert consulta.camino_hasta(t, tb, "A4") == ["A1", "A2"]
    assert consulta.camino_hasta(t, tb, "A1") == []
    tb = tablero(t, {"A1": OK, "A2": NO, "A3": NO, "A4": NO, "A5": NO})
    assert consulta.camino_hasta(t, tb, "A4") == ["A2"]    # A1 resuelta corta la rama


def test_camino_orden_topologico_con_desempate_de_catalogo():
    t = [T("C1"), T("C2"), T("C3", ["C2", "C1"]), T("C4", ["C3"])]
    tb = tablero(t, {c.codigo: NO for c in t})
    assert consulta.camino_hasta(t, tb, "C4") == ["C1", "C2", "C3"]


def test_codigo_inexistente_se_trata_igual_en_las_tres_consultas():
    t = armar()
    tb = tablero(t, {})
    for f in (consulta.camino_hasta, consulta.que_frena, consulta.que_destraba):
        with pytest.raises(ValueError, match="ZZ"):
            f(t, tb, "ZZ")


def test_a_json_es_serializable():
    import json
    t = armar()
    tb = tablero(t, {"A1": OK, "A2": NO, "A3": NO, "A4": NO, "A5": NO},
                 decisiones={"A5": {"tipo": "completada_a_mano", "quien": "x", "motivo": "m"}})
    datos = consulta.a_json(t, tb)
    json.dumps(datos)
    assert datos["recomendada"] == "A2"
    assert {x["codigo"]: x["estado"] for x in datos["tareas"]}["A5"] == "hecha"
    assert datos["resumen"]["a_mano"] == 1


# ---- pureza ------------------------------------------------------------------

def test_el_motor_no_importa_nada_de_la_app():
    """El motor es genérico: solo stdlib y sus propios módulos."""
    carpeta = Path(__file__).parent / "xsii" / "motor"
    archivos = sorted(carpeta.glob("*.py"))
    assert len(archivos) >= 4
    permitidos = set(sys.stdlib_module_names) | {"__future__"}
    for archivo in archivos:
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Import):
                nombres = [a.name.split(".")[0] for a in nodo.names]
            elif isinstance(nodo, ast.ImportFrom):
                if nodo.level:          # relativo: es del propio paquete
                    continue
                nombres = [(nodo.module or "").split(".")[0]]
            else:
                continue
            for n in nombres:
                assert n in permitidos, f"{archivo.name} importa {n}, que no es stdlib"


# ---- confirmaciones (B) --------------------------------------------------------

def C(codigo, necesita=(), solo=False):
    return Tarea(codigo, codigo, "A", "manual", necesita=tuple(necesita), control="c_" + codigo,
                 confirmacion="Está bien", solo_confirmacion=solo)


CONFIRMADA = {"tipo": "confirmada", "quien": "ana", "cuando": "2026-11-26", "motivo": ""}


def test_control_que_pasa_sin_confirmar_queda_en_curso_y_no_destraba():
    t = [C("A1"), T("A2", ["A1"])]
    r = estados.resolver(t, hechos({"A1": OK, "A2": NO}))
    assert r["A1"].estado == "en_curso" and r["A1"].falta_confirmar
    assert r["A1"].confirmacion == "Está bien"
    assert r["A2"].estado == "bloqueada" and r["A2"].frenada_por == ["A1"]
    assert consulta.que_destraba(t, r, "A1")["directo"] == ["A2"]


def test_con_la_decision_confirmada_esta_hecha_y_destraba():
    t = [C("A1"), T("A2", ["A1"])]
    r = estados.resolver(t, hechos({"A1": OBS, "A2": NO}, decisiones={"A1": CONFIRMADA}))
    assert r["A1"].estado == "hecha" and r["A1"].con_observaciones and not r["A1"].falta_confirmar
    assert r["A2"].estado == "lista"


def test_confirmada_no_alcanza_si_el_control_no_pasa():
    t = [C("A1")]
    r = estados.resolver(t, hechos({"A1": NO}, decisiones={"A1": CONFIRMADA}))
    assert r["A1"].estado == "lista" and not r["A1"].falta_confirmar


def test_completada_a_mano_reemplaza_a_la_confirmacion():
    t = [C("A1"), T("A2", ["A1"])]
    d = {"A1": {"tipo": "completada_a_mano", "quien": "q", "cuando": "c", "motivo": "m"}}
    r = estados.resolver(t, hechos({"A1": OK, "A2": NO}, decisiones=d))
    assert r["A1"].estado == "hecha" and r["A1"].a_mano and r["A2"].estado == "lista"


def test_solo_confirmacion_queda_lista_y_no_en_curso():
    t = [C("A1", solo=True)]
    r = estados.resolver(t, hechos({"A1": OK}))
    assert r["A1"].estado == "lista" and r["A1"].falta_confirmar
    assert consulta.recomendada(t, r) == "A1"
    r = estados.resolver(t, hechos({"A1": OK}, decisiones={"A1": CONFIRMADA}))
    assert r["A1"].estado == "hecha"


def test_confirmacion_pendiente_con_dependencia_sin_resolver_sigue_bloqueada():
    t = [T("D"), C("A1", ["D"])]
    r = estados.resolver(t, hechos({"D": NO, "A1": OK}))
    assert r["A1"].estado == "bloqueada"


def test_solo_confirmacion_exige_texto_y_el_resumen_cuenta_las_pendientes():
    mala = Tarea("A1", "A1", "A", "manual", control="c", solo_confirmacion=True)
    assert any("no dice qué confirmar" in e for e in catalogo.validar([mala], GRUPOS))
    t = [C("A1")]
    assert consulta.resumen(estados.resolver(t, hechos({"A1": OK})))["por_confirmar"] == 1


# ---- los 9 del QA, en el motor ---------------------------------------------------

def test_porcentaje_nunca_100_con_algo_sin_hacer():
    t = [T(f"T{i}") for i in range(200)]
    cs = {x.codigo: OK for x in t}
    cs["T0"] = NO
    assert consulta.resumen(estados.resolver(t, hechos(cs)))["porcentaje"] == 99
    cs["T0"] = OK
    assert consulta.resumen(estados.resolver(t, hechos(cs)))["porcentaje"] == 100


def test_una_pospuesta_en_curso_no_se_recomienda():
    t = [T("A"), T("B")]
    r = estados.resolver(t, hechos({"A": MEDIO, "B": NO}, decisiones={"A": {"tipo": "pospuesta"}}))
    assert consulta.recomendada(t, r) == "B"


def test_no_aplica_expone_su_porque():
    t = [T("A", aplica_si="m"), T("B")]
    r = estados.resolver(t, hechos({"A": NO, "B": NO}, aplica={"m": False},
                                   decisiones={"B": {"tipo": "no_aplica", "quien": "q", "motivo": "x"}}))
    assert r["A"].no_aplica_por == "condicion" and r["B"].no_aplica_por == "decision"


# ---- bloque 1: varias decisiones por tarea e insumo sin registrar ---------------

def D(tipo, **resto):
    return {"tipo": tipo, "quien": "ana", "cuando": "2026-11-26", "motivo": "porque sí", **resto}


def test_varias_decisiones_a_la_vez_se_guardan_todas():
    t = [T("A1")]
    ds = [D("pospuesta"), D("completada_a_mano")]
    e = estado(t, hechos({"A1": NO}, decisiones={"A1": ds}), "A1")
    assert e.estado == "hecha" and e.a_mano and e.pospuesta
    assert [d["tipo"] for d in e.decisiones] == ["pospuesta", "completada_a_mano"]
    assert e.decision["tipo"] == "completada_a_mano"


def test_un_dict_suelto_se_toma_como_lista_de_una():
    t = [T("A1")]
    e = estado(t, hechos({"A1": NO}, decisiones={"A1": D("pospuesta")}), "A1")
    assert e.pospuesta and len(e.decisiones) == 1 and e.decision is None


def test_confirmada_y_pospuesta_conviven_y_decision_es_la_confirmada():
    t = [C("A1")]
    r = estados.resolver(t, hechos({"A1": OK}, decisiones={"A1": [D("pospuesta"), D("confirmada")]}))
    assert r["A1"].estado == "hecha" and r["A1"].pospuesta
    assert r["A1"].decision["tipo"] == "confirmada" and len(r["A1"].decisiones) == 2


def test_no_aplica_declarada_gana_a_las_otras():
    t = [T("A1")]
    ds = [D("completada_a_mano"), D("no_aplica")]
    e = estado(t, hechos({"A1": OK}, decisiones={"A1": ds}), "A1")
    assert e.estado == "no_aplica" and e.no_aplica_por == "decision" and e.decision["tipo"] == "no_aplica"


def test_pospuesta_saca_de_recomendada_y_alternativas_aunque_haya_otra_decision():
    t = [T("A1"), T("A2")]
    tb = estados.resolver(t, hechos({"A1": NO, "A2": NO}, decisiones={"A1": [D("pospuesta")]}))
    assert consulta.recomendada(t, tb) == "A2" and consulta.alternativas(t, tb) == []


def test_decision_invalida_en_una_lista_es_error():
    with pytest.raises(ValueError):
        estados.resolver([T("A1")], hechos({"A1": NO}, decisiones={"A1": [D("pospuesta"), D("xx")]}))


def test_insumo_sin_registrar_con_control_en_curso_no_deja_esperando():
    t = [T("A1", insumos=["i"])]
    e = estado(t, hechos({"A1": MEDIO}), "A1")
    assert e.estado == "en_curso" and e.insumos_sin_registrar == ["i"] and e.insumos_faltantes == []


def test_insumo_sin_registrar_con_control_que_pasa_y_confirmacion_no_deja_esperando():
    t = [Tarea("A1", "x", "A", "manual", insumos=("i",), control="c", confirmacion="ok")]
    e = estados.resolver(t, hechos({"A1": OK}))["A1"]
    assert e.estado == "en_curso" and e.falta_confirmar and e.insumos_sin_registrar == ["i"]


def test_insumo_sin_registrar_y_sin_datos_sigue_esperando():
    t = [T("A1", insumos=["i"])]
    e = estado(t, hechos({"A1": NO}), "A1")
    assert e.estado == "esperando" and e.insumos_faltantes == ["i"] and e.insumos_sin_registrar == []


def test_solo_confirmacion_sin_insumo_registrado_sigue_esperando():
    t = [Tarea("A1", "x", "A", "manual", insumos=("i",), control="c", confirmacion="ok",
               solo_confirmacion=True)]
    e = estados.resolver(t, hechos({"A1": OK}))["A1"]
    assert e.estado == "esperando" and e.insumos_faltantes == ["i"] and e.insumos_sin_registrar == []


def test_insumo_registrado_no_aparece_como_sin_registrar():
    t = [T("A1", insumos=["i"])]
    e = estado(t, hechos({"A1": MEDIO}, insumos={"i": True}), "A1")
    assert e.estado == "en_curso" and e.insumos_sin_registrar == []


def test_a_json_trae_decisiones_e_insumos_sin_registrar():
    t = [T("A1", insumos=["i"])]
    tb = estados.resolver(t, hechos({"A1": MEDIO}, decisiones={"A1": [D("pospuesta")]}))
    item = consulta.a_json(t, tb)["tareas"][0]
    assert item["decisiones"][0]["tipo"] == "pospuesta" and item["insumos_sin_registrar"] == ["i"]


# ---- confirmación sin el insumo ------------------------------------------------

def CI(codigo, solo=False):
    return Tarea(codigo, codigo, "A", "manual", insumos=("planilla",), control="c_" + codigo,
                 confirmacion="Está bien", solo_confirmacion=solo)


def test_solo_confirmacion_con_el_insumo_faltante_no_queda_hecha_aunque_este_confirmada():
    t = [CI("A1", solo=True)]
    r = estados.resolver(t, hechos({"A1": OK}, decisiones={"A1": CONFIRMADA}))
    assert r["A1"].estado == "esperando" and r["A1"].insumos_faltantes == ["planilla"]
    assert not r["A1"].falta_confirmar          # ya está confirmada: falta el insumo, no la confirmación
    r = estados.resolver(t, hechos({"A1": OK}, insumos={"planilla": True}, decisiones={"A1": CONFIRMADA}))
    assert r["A1"].estado == "hecha"


def test_con_datos_cargados_la_confirmacion_vale_sin_el_insumo_registrado():
    t = [CI("A1")]                              # no es solo_confirmacion: el control calcula
    r = estados.resolver(t, hechos({"A1": OK}, decisiones={"A1": CONFIRMADA}))
    assert r["A1"].estado == "hecha" and r["A1"].insumos_sin_registrar == []


def test_completada_a_mano_sigue_valiendo_sin_el_insumo():
    t = [CI("A1", solo=True)]
    d = {"A1": {"tipo": "completada_a_mano", "quien": "q", "cuando": "c", "motivo": "m"}}
    assert estados.resolver(t, hechos({"A1": OK}, decisiones=d))["A1"].estado == "hecha"
