"""Punto 2 (pedido 2026-08-18): el comprobante de aportes de ARCA puede
mostrar "INFORMADO" en vez de PAGO -- significa que el aporte está en
regla pero se hizo a una Caja previsional u organismo provincial (ej.
empleados de la Provincia de Buenos Aires), no directamente a ARCA. No
cambia la lógica del semáforo (sigue siendo pagado/parcial/impago/
no_presentada/no_declarado): "INFORMADO" tiene que mapear a "pagado"
(verde) y "NO INFORMADO" a "impago" (rojo) -- ver ESQUEMA_APORTES en
extractor.py, que es la instrucción que le da esa aclaración a la IA.

No llama a la API real: mockea extractor.client.messages.create, mismo
criterio que test_extractor_bi_formato.py.
Correr con: .venv/Scripts/python.exe test_aportes_informado.py
"""
import json
from types import SimpleNamespace

import extractor
import semaforo


def _mock_response(payload: dict):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps(payload))],
        usage=SimpleNamespace(input_tokens=111, output_tokens=22),
    )


def _run_extraer_aportes_con_mock(payload: dict) -> dict:
    original = extractor.client.messages.create
    extractor.client.messages.create = lambda **kw: _mock_response(payload)
    try:
        datos, uso = extractor.extraer_aportes(b"fake-bytes", "image/png")
        return datos
    finally:
        extractor.client.messages.create = original


def test_esquema_aclara_informado_a_la_ia():
    # Guard: si se pierde esta aclaración del prompt (ej. al reescribirlo),
    # la IA vuelve a clasificar mal "INFORMADO" -- el bug real reportado.
    assert "INFORMADO" in extractor.ESQUEMA_APORTES
    assert "NO INFORMADO" in extractor.ESQUEMA_APORTES
    assert "Caja previsional" in extractor.ESQUEMA_APORTES or "organismo provincial" in extractor.ESQUEMA_APORTES
    print("OK  test_esquema_aclara_informado_a_la_ia")


def test_informado_mapeado_a_pagado_da_semaforo_verde():
    # Simula lo que la IA debería devolver para un mes en "INFORMADO"
    # (aporte en regla vía Caja provincial) -- mapeado a "pagado".
    datos = _run_extraer_aportes_con_mock({
        "cuil": "20111111119", "desde": "01/2026", "hasta": "01/2026",
        "meses": [{"periodo": "01/2026", "jubilacion": "pagado", "obra_social": "pagado"}],
        "confianza": "alta",
    })
    resultado = semaforo.calcular_semaforo(datos)
    assert resultado["color"] == "verde", resultado
    print("OK  test_informado_mapeado_a_pagado_da_semaforo_verde")


def test_no_informado_mapeado_a_impago_da_semaforo_rojo():
    datos = _run_extraer_aportes_con_mock({
        "cuil": "20111111119", "desde": "01/2026", "hasta": "01/2026",
        "meses": [{"periodo": "01/2026", "jubilacion": "impago", "obra_social": "pagado"}],
        "confianza": "alta",
    })
    resultado = semaforo.calcular_semaforo(datos)
    assert resultado["color"] == "rojo", resultado
    print("OK  test_no_informado_mapeado_a_impago_da_semaforo_rojo")


if __name__ == "__main__":
    test_esquema_aclara_informado_a_la_ia()
    test_informado_mapeado_a_pagado_da_semaforo_verde()
    test_no_informado_mapeado_a_impago_da_semaforo_rojo()
    print("\nTodo OK — estado INFORMADO/NO INFORMADO de ARCA.")
