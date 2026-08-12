"""Filigrana determinística y generación del código de credencial persistido.
Correr con: .venv/Scripts/python.exe test_credencial_v2.py
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE

from filigrana import filigrana_svg
import db
from db import Sindicato, Trabajador

db.crear_tablas()
with db.get_session() as s:
    sind = Sindicato(nombre="Unión Obrera Metalúrgica", slug="union-obrera-metalurgica")
    s.add(sind); s.commit(); s.refresh(sind)
    trab = Trabajador(sindicato_id=sind.id, cuil="20111111119", nombre="Juan")
    s.add(trab)
    s.commit()
    s.refresh(trab)
    SID = sind.id
    TRAB_ID = trab.id


def test_filigrana_es_determinista():
    a = filigrana_svg("Unión Obrera Metalúrgica", "#2fa88f", "#e8b84b")
    b = filigrana_svg("Unión Obrera Metalúrgica", "#2fa88f", "#e8b84b")
    assert a == b
    print("OK  test_filigrana_es_determinista")


def test_filigrana_varia_por_sindicato():
    a = filigrana_svg("Unión Obrera Metalúrgica", "#2fa88f", "#e8b84b")
    b = filigrana_svg("Federación Gastronómica", "#c9a227", "#2f6b3d")
    assert a != b
    print("OK  test_filigrana_varia_por_sindicato")


def test_filigrana_es_svg_valido_y_usa_los_colores():
    # Son 3 rosetones con tono levemente variado (no el color exacto): se
    # verifica que los 3 stroke queden CERCA de secundario o acento, no que
    # coincidan al pixel.
    import re

    def _dist(hex_a, hex_b):
        a = [int(hex_a.lstrip("#")[i:i+2], 16) for i in (0, 2, 4)]
        b = [int(hex_b.lstrip("#")[i:i+2], 16) for i in (0, 2, 4)]
        return sum(abs(x - y) for x, y in zip(a, b))

    secundario, acento = "#3f8fd4", "#8ab4d8"
    svg = filigrana_svg("AEFIP", secundario, acento)
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    strokes = re.findall(r'stroke="(#[0-9a-f]{6})"', svg)
    assert len(strokes) == 3, strokes
    for color in strokes:
        # tono va de -0.35 a -0.05 (variación +-0.15 de siempre, más un
        # oscurecimiento fijo de -0.20 pedido por el usuario): en el peor
        # caso 255*3*0.35 = 267.75. 290 da margen sin ser tan ancho como
        # para no detectar un color realmente distinto.
        assert min(_dist(color, secundario), _dist(color, acento)) < 290, color
    print("OK  test_filigrana_es_svg_valido_y_usa_los_colores")


def test_filigrana_tiene_tres_rosetones_en_posiciones_distintas():
    svg = filigrana_svg("Unión Obrera Metalúrgica", "#2fa88f", "#e8b84b")
    assert svg.count("<g transform=") == 3
    import re
    traslados = re.findall(r'translate\(([-\d.]+),([-\d.]+)\)', svg)
    assert len(traslados) == 3
    assert len(set(traslados)) == 3, "los 3 rosetones deben quedar en posiciones distintas"
    print("OK  test_filigrana_tiene_tres_rosetones_en_posiciones_distintas")


def test_filigrana_no_rompe_con_nombre_vacio():
    svg = filigrana_svg("", "#000000", "#ffffff")
    assert svg.startswith("<svg")
    print("OK  test_filigrana_no_rompe_con_nombre_vacio")


def test_generar_codigo_credencial_formato():
    codigo = db.generar_codigo_credencial(TRAB_ID, SID, "Unión Obrera Metalúrgica")
    assert len(codigo) == 13, codigo  # 5 letras del sindicato + 8 alfanuméricos
    prefijo, sufijo = codigo[:5], codigo[5:]
    assert prefijo == "UNIÓN", prefijo  # primeros 5 caracteres alfanuméricos del nombre, en mayúsculas
    assert sufijo.isalnum() and sufijo == sufijo.upper(), codigo
    print(f"OK  test_generar_codigo_credencial_formato ({codigo})")


def test_generar_codigo_credencial_persiste_y_regenera():
    c1 = db.generar_codigo_credencial(TRAB_ID, SID, "Unión Obrera Metalúrgica")
    datos = db.credencial_de("20111111119", SID)
    assert datos["codigo"] == c1
    c2 = db.generar_codigo_credencial(TRAB_ID, SID, "Unión Obrera Metalúrgica")
    assert c2 != c1, "regenerar tiene que dar un código nuevo"
    assert db.credencial_de("20111111119", SID)["codigo"] == c2
    print("OK  test_generar_codigo_credencial_persiste_y_regenera")


def test_credencial_de_sin_generar_es_none():
    with db.get_session() as s:
        otro = Trabajador(sindicato_id=SID, cuil="20999999999", nombre="Sin Generar")
        s.add(otro); s.commit()
    assert db.credencial_de("20999999999", SID)["codigo"] is None
    print("OK  test_credencial_de_sin_generar_es_none")


def test_credencial_de_sin_empadronamiento_es_none():
    assert db.credencial_de("20888888888", SID) is None
    print("OK  test_credencial_de_sin_empadronamiento_es_none")


if __name__ == "__main__":
    test_filigrana_es_determinista()
    test_filigrana_varia_por_sindicato()
    test_filigrana_es_svg_valido_y_usa_los_colores()
    test_filigrana_tiene_tres_rosetones_en_posiciones_distintas()
    test_filigrana_no_rompe_con_nombre_vacio()
    test_generar_codigo_credencial_formato()
    test_generar_codigo_credencial_persiste_y_regenera()
    test_credencial_de_sin_generar_es_none()
    test_credencial_de_sin_empadronamiento_es_none()
    print("\nTodo OK — filigrana y código de credencial.")
