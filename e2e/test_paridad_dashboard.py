# -*- coding: utf-8 -*-
"""Paridad del Panel Sindical v1 / v2 (PLAN_DASHBOARD_V2.md, bloques 0 y 7).

Necesita el entorno levantado, como todo `e2e/`:

    docker compose up -d
    uvicorn main:app --reload           # en otra terminal
    python cargar_lote_sindicato.py --sindicato "Unión Obrera Metalúrgica"

Y se corre con:

    .venv/Scripts/python.exe -m pytest e2e/test_paridad_dashboard.py -q

Tres tests:

- `test_linea_de_base_v1` abre la v1 con cada combinación de filtros de
  `paridad.NOMBRES` y verifica que esté sana: ningún panel en error, ningún
  pedido rechazado y **nunca más de 4 pedidos en vuelo**, medido en el
  navegador. Deja la lectura en JSON y una captura en
  `e2e/resultados/paridad/`.
- `test_la_lectura_es_estable` abre la v1 dos veces con los mismos filtros y
  exige que las dos lecturas sean iguales. Es la baranda del robot: si leer
  dos veces lo mismo diera distinto, la comparación con la v2 fallaría por
  el robot y no por la v2.
- `test_paridad_v1_v2` lee las dos versiones con cada combinación y exige
  los mismos datos y los mismos pedidos al servidor. Se saltea, diciendo por
  qué, hasta que exista la v2 y su lector (bloque 7 del plan).
"""
import pytest

import fechas
import paridad


def _preparar(page, nombre):
    paridad.entrar_como_admin(page)
    params = paridad.parametros(nombre, fechas.hoy(), paridad.catalogo(page))
    return params


@pytest.mark.parametrize("nombre", paridad.NOMBRES)
def test_linea_de_base_v1(page, informe, nombre):
    params = _preparar(page, nombre)
    lectura = paridad.leer(page, "v1", params)
    destino = paridad.guardar(page, "v1", nombre, lectura)
    informe.paso(f"Abrió la v1 con «{nombre}» ({lectura['url'] or 'sin filtros'})")

    assert not lectura["paneles_con_error"], lectura["paneles_con_error"]
    assert not lectura["aviso"], f"el servidor rechazó los filtros: {lectura['aviso']}"
    assert not lectura["pedidos_fallidos"], lectura["pedidos_fallidos"]
    assert lectura["pedidos"], "el panel no le pidió nada al servidor"
    assert lectura["max_en_vuelo"] <= 4, (
        f"{lectura['max_en_vuelo']} pedidos en vuelo a la vez; el cupo del servidor es de 4")
    assert paridad.numeros(lectura["kpis"].get("recibos")), lectura["kpis"]

    if nombre == "url-con-fecha-futura":
        # Descartada la URL, el panel abre en "Hoy": desde y hasta son hoy.
        hoy = fechas.hoy().isoformat()
        assert f"desde={hoy}" in lectura["url"] and f"hasta={hoy}" in lectura["url"], lectura["url"]

    informe.dato(f"{nombre}: recibos analizados", lectura["kpis"]["recibos"])
    informe.dato(f"{nombre}: pedidos distintos / máximo en vuelo",
                 f"{len(lectura['pedidos'])} / {lectura['max_en_vuelo']}")
    informe.dato(f"{nombre}: lectura y captura", destino.name + ".json / .png")


def test_la_lectura_es_estable(page, informe):
    params = _preparar(page, "90-dias-seccional-salario")
    primera = paridad.leer(page, "v1", params)
    segunda = paridad.leer(page, "v1", params)
    diferencias = paridad.comparar(primera, segunda)
    assert not diferencias, "dos lecturas de la v1 no coinciden:\n" + "\n".join(diferencias)
    informe.paso("Dos lecturas seguidas de la v1 con los mismos filtros dieron lo mismo")


@pytest.mark.parametrize("nombre", paridad.NOMBRES)
def test_paridad_v1_v2(page, informe, nombre):
    params = _preparar(page, nombre)
    if not paridad.existe(page, "v2"):
        pytest.skip("La v2 todavía no existe en este entorno (PLAN_DASHBOARD_V2.md, bloque 1).")
    if "v2" not in paridad.LECTORES:
        pytest.skip("Falta el lector de la v2 en e2e/paridad.py (PLAN_DASHBOARD_V2.md, bloque 7).")
    v1 = paridad.leer(page, "v1", params)
    v2 = paridad.leer(page, "v2", params)
    paridad.guardar(page, "v2", nombre, v2)
    diferencias = paridad.comparar(v1, v2)
    assert not diferencias, f"«{nombre}»: la v2 no muestra lo mismo que la v1:\n" + "\n".join(diferencias)
    assert v2["max_en_vuelo"] <= 4, v2["max_en_vuelo"]
    informe.paso(f"«{nombre}»: la v1 y la v2 muestran los mismos datos")
