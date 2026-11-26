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
    assert estado(t, hechos({"D": OK, "X": MEDIO}), "X").estado == "esperando"
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


def test_camino_de_codigo_inexistente():
    t = armar()
    with pytest.raises(KeyError):
        consulta.camino_hasta(t, tablero(t, {}), "ZZ")


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
