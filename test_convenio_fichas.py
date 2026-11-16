"""Convenio en fichas (PLAN_CONVENIO_ESCALAS.md, Bloque 4, D11/D21).

Puro: lee `data/convenios/cct-18-75.json` y la grilla de agosto 2026.
Correr con: .venv/bin/python -m pytest test_convenio_fichas.py -q
"""
import json
import re
from pathlib import Path

import convenio_fichas as cf

RAIZ = Path(__file__).resolve().parent
GRILLA = json.loads((RAIZ / "data" / "grillas_bancarias" / "2026-08.json").read_text(encoding="utf-8"))
CONV = cf.cargar()


def test_estan_los_62_articulos_en_orden_y_con_texto():
    nums = [a["numero"] for a in CONV["articulos"]]
    assert nums == list(range(1, 63))
    for a in CONV["articulos"]:
        assert a["texto"].strip(), a["numero"]
        assert a["titulo"].strip(), a["numero"]
        assert "<<<" not in a["texto"], a["numero"]


def test_estan_las_ocho_disposiciones_transitorias():
    nums = [t["numero"] for t in CONV["transitorias"]]
    assert nums == ["I", "II", "III", "IV", "V", "VI", "VII", "VIII"]
    for t in CONV["transitorias"]:
        assert t["texto"].strip()
    assert cf.articulo("iii")["numero"] == "III"
    assert cf.articulo(22)["numero"] == 22
    assert cf.articulo(63) is None


def test_ningun_articulo_arrastra_el_encabezado_del_siguiente():
    # Los tres epígrafes del convenio son títulos de los artículos 1 a 3 y no
    # deben quedar pegados al final del texto del artículo anterior.
    for a in CONV["articulos"]:
        assert not a["texto"].rstrip().endswith(("Vigencia temporal", "Ambito de aplicación", "Personal comprendido"))
    assert CONV["articulos"][0]["titulo"] == "Vigencia temporal"


def test_cada_situacion_apunta_a_articulos_que_existen():
    assert len(CONV["situaciones"]) == 6
    titulos = {s["titulo"] for s in CONV["situaciones"]}
    assert titulos == {"Voy a ser madre o padre", "Me caso", "Estudio o me recibí",
                       "Trabajo en caja", "Trabajo en zona alejada", "Falleció un familiar"}
    for s in cf.situaciones():
        assert s["articulos"], s["id"]
        assert len(s["fichas"]) == len(s["articulos"])


def test_el_indice_cubre_cada_ficha_una_sola_vez():
    vistos = [r["numero"] for g in cf.indice() for r in g["articulos"]]
    esperados = [a["numero"] for a in CONV["articulos"]] + [t["numero"] for t in CONV["transitorias"]]
    assert sorted(map(str, vistos)) == sorted(map(str, esperados))


def test_todo_importe_grilla_resuelve_contra_la_grilla_de_agosto():
    con_importe = [a for a in CONV["articulos"] if a["importe_grilla"]]
    assert {a["numero"] for a in con_importe} >= {10, 22, 25}
    for a in con_importe:
        filas = cf.importe_vigente(a, GRILLA)
        assert filas, a["numero"]
        for f in filas:
            assert isinstance(f["importe"], (int, float)) and f["rotulo"]


def test_importe_vigente_no_inventa():
    art_sin = cf.articulo(1)
    assert cf.importe_vigente(art_sin, GRILLA) is None
    assert cf.importe_vigente(cf.articulo(22), {}) is None
    assert cf.importe_vigente(cf.articulo(22), {"adicionales": {"funcion_cajero": 1.0}}) is None
    assert cf.importe_vigente(None, GRILLA) is None
    titulos = cf.importe_vigente(cf.articulo(10), GRILLA)
    assert [f["rotulo"] for f in titulos] == ["secundario", "terciario", "universitario"]


def test_los_resumenes_nacen_sin_revisar():
    for a in list(CONV["articulos"]) + list(CONV["transitorias"]):
        assert a["resumen"].strip()
        assert a["resumen_estado"] == "sin_revisar", a["numero"]


def test_ningun_resumen_contiene_un_importe_en_pesos():
    for a in list(CONV["articulos"]) + list(CONV["transitorias"]):
        r = a["resumen"]
        assert "$" not in r and not re.search(r"\bpesos\b", r, re.I), a["numero"]


def test_el_buscador_encuentra_titulo_y_licencia():
    assert 10 in [a["numero"] for a in cf.buscar("título")]
    assert 10 in [a["numero"] for a in cf.buscar("TITULO")]  # sin acentos ni mayúsculas
    assert 48 in [a["numero"] for a in cf.buscar("licencia")]
    assert cf.buscar("") == []
    assert cf.buscar("xyzzy-no-existe") == []
    # los que coinciden en el título van primero
    assert cf.buscar("licencias")[0]["numero"] == 48


def test_el_convenio_no_sale_de_su_carpeta():
    try:
        cf.cargar("../grillas_bancarias/2026-08")
    except FileNotFoundError:
        return
    raise AssertionError("debía rechazar un nombre que sale de la carpeta")


def test_importe_vigente_exige_importes_finitos_y_positivos():
    for malo in (float("nan"), float("inf"), float("-inf"), 0, -5):
        g = {"adicionales": {"funcion_cajero": malo, "falla_caja": 10.0}}
        assert cf.importe_vigente(cf.articulo(22), g) is None, malo
    ok = {"adicionales": {"funcion_cajero": 5.0, "falla_caja": 10.0}}
    assert len(cf.importe_vigente(cf.articulo(22), ok)) == 2


def test_importe_grilla_que_no_es_texto_devuelve_none():
    for raro in (5, 1.5, {"a": 1}, [1, 2], ["adicionales.titulos", 3]):
        assert cf.importe_vigente({"importe_grilla": raro}, GRILLA) is None, raro


def test_las_escalas_por_antiguedad_no_traen_las_jerarquicas():
    for n, rama in ((5, "administrativa"), (33, "maestranza"), (35, "ordenanza")):
        filas = cf.importe_vigente(cf.articulo(n), GRILLA)
        con_anios = [c for c in GRILLA["ramas"][rama]["categorias"] if c["anios"] is not None]
        assert [f["rotulo"] for f in filas] == [c["nombre"] for c in con_anios], n
        assert [f["importe"] for f in filas] == [c["basico"] for c in con_anios], n


def test_las_escalas_jerarquicas_resuelven_a_las_jerarquicas_de_su_rama():
    esperado = {6: ("administrativa", 6), 34: ("maestranza", 14), 36: ("ordenanza", 14)}
    for n, (rama, cuantas) in esperado.items():
        filas = cf.importe_vigente(cf.articulo(n), GRILLA)
        jer = [c for c in GRILLA["ramas"][rama]["categorias"] if c["anios"] is None]
        assert len(filas) == cuantas, n
        assert {f["rotulo"] for f in filas} <= {c["nombre"] for c in jer}, n
    assert all("Div." in f["rotulo"] for f in cf.importe_vigente(cf.articulo(6), GRILLA))
    assert cf.importe_vigente({"importe_grilla": "ramas.administrativa.jerarquias.otra"}, GRILLA) is None


def test_titulo_del_convenio_solo_en_los_articulos_1_a_3():
    for a in list(CONV["articulos"]) + list(CONV["transitorias"]):
        assert isinstance(a["titulo_del_convenio"], bool), a["numero"]
        assert a["titulo_del_convenio"] == (a["numero"] in (1, 2, 3)), a["numero"]


def test_zona_alejada_incluye_la_transitoria_viii():
    zona = next(s for s in cf.situaciones() if s["id"] == "zona")
    assert [f["numero"] for f in zona["fichas"]] == [25, "VIII"]
