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
