"""Verificación del Punto 3 del Sprint A (alerta temprana de último depósito).

Sin dependencias externas. Correr con: .venv/Scripts/python.exe test_alerta_deposito.py
"""
import semaforo


def test_deposito_reciente_no_alerta():
    recibo = {"periodo": "2026-06", "ultimo_deposito": {"fecha": "10/06/2026"}}
    assert semaforo.advertencia_ultimo_deposito(recibo) is None
    print("OK  test_deposito_reciente_no_alerta")


def test_deposito_3_meses_atras_alerta():
    recibo = {"periodo": "2026-06", "ultimo_deposito": {"fecha": "15/03/2026"}}
    r = semaforo.advertencia_ultimo_deposito(recibo)
    assert r is not None and r["meses_atraso"] == 3, r
    print("OK  test_deposito_3_meses_atras_alerta")


def test_deposito_2_meses_atras_no_alerta():
    recibo = {"periodo": "2026-06", "ultimo_deposito": {"fecha": "15/04/2026"}}
    assert semaforo.advertencia_ultimo_deposito(recibo) is None
    print("OK  test_deposito_2_meses_atras_no_alerta")


def test_sin_ultimo_deposito_no_rompe():
    assert semaforo.advertencia_ultimo_deposito({"periodo": "2026-06", "ultimo_deposito": None}) is None
    assert semaforo.advertencia_ultimo_deposito({"periodo": "2026-06"}) is None
    assert semaforo.advertencia_ultimo_deposito({"periodo": None, "ultimo_deposito": {"fecha": "15/01/2026"}}) is None
    print("OK  test_sin_ultimo_deposito_no_rompe")


def test_arca_no_se_toca():
    # calcular_semaforo() no cambia su forma: la señal temprana vive aparte y el
    # front-end solo la muestra mientras no haya datos reales de ARCA (semArcaCargado).
    datos = {"cuil": "1", "meses": [{"periodo": "01/2026", "jubilacion": "pagado", "obra_social": "pagado"}]}
    r = semaforo.calcular_semaforo(datos)
    assert "advertencia" not in r and r["color"] == "verde"
    print("OK  test_arca_no_se_toca")


if __name__ == "__main__":
    test_deposito_reciente_no_alerta()
    test_deposito_3_meses_atras_alerta()
    test_deposito_2_meses_atras_no_alerta()
    test_sin_ultimo_deposito_no_rompe()
    test_arca_no_se_toca()
    print("\nTodo OK — Punto 3 (alerta de último depósito) pasa sus criterios de aceptación.")
