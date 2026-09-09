"""Pestaña "Tests" de /entornos: dispara el test de estrés (carga/) como
un Job de Render aparte -- ver main.py "Tests: pestaña de test de estrés"
y render_admin.py. Acá se cubre la tabla TestCarga (db.py) y el gate de
acceso de las rutas; NO se prueba contra la API real de Render (se
monkeypatchea render_admin.crear_job).

Correr con: .venv/Scripts/python.exe test_tests_carga.py
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE
os.environ["ENTORNO"] = "pruebas"
os.environ["PIN_ENTORNOS"] = "13571357"

import db
import main
import render_admin
from fastapi.testclient import TestClient

db.crear_tablas()
client = TestClient(main.app)
assert client.post("/entornos/pin", data={"pin": "13571357"}, follow_redirects=False).status_code == 303


def test_modelo_test_carga_alta_actualizacion_y_lectura():
    tid = db.crear_test_carga("lecturas", {"escalones": [50, 100], "duracion_seg": 120})
    fila = db.test_carga_por_id(tid)
    assert fila["estado"] == "pendiente"
    assert fila["parametros"]["escalones"] == [50, 100]

    db.fijar_job_test_carga(tid, "job-abc123")
    fila = db.test_carga_por_id(tid)
    assert fila["estado"] == "corriendo"
    assert fila["render_job_id"] == "job-abc123"

    db.actualizar_test_carga(tid, avance="escalón 50 listo")
    assert db.test_carga_por_id(tid)["avance"] == "escalón 50 listo"

    resumen = [{"escalon": 50, "p95": 300, "errores_pct": 0}]
    db.actualizar_test_carga(tid, estado="listo", resumen=resumen, terminado_en="2026-09-09 12:00:00")
    fila = db.test_carga_por_id(tid)
    assert fila["estado"] == "listo"
    assert fila["resumen"] == resumen

    recientes = db.tests_carga_recientes(5)
    assert any(f["id"] == tid for f in recientes)
    print("OK  test_modelo_test_carga_alta_actualizacion_y_lectura")


def test_sin_pase_no_se_puede_correr_ni_listar():
    c = TestClient(main.app)
    r = c.post("/entornos/tests/correr", data={"tipo": "lecturas"}, follow_redirects=False)
    assert r.status_code == 403
    r = c.get("/api/entornos/tests")
    assert r.status_code == 403
    print("OK  test_sin_pase_no_se_puede_correr_ni_listar")


def test_correr_crea_test_y_llama_a_render(monkeypatch):
    llamados = []

    def crear_job_fake(start_command):
        llamados.append(start_command)
        return {"id": "job-xyz", "status": "pending"}

    monkeypatch.setattr(render_admin, "crear_job", crear_job_fake)
    antes = len(db.tests_carga_recientes(50))
    r = client.post("/entornos/tests/correr",
                     data={"tipo": "lecturas", "escalones": "10,20", "duracion_seg": 60},
                     follow_redirects=False)
    assert r.status_code == 303
    assert "aviso=test_lanzado" in r.headers["location"]
    despues = db.tests_carga_recientes(50)
    assert len(despues) == antes + 1
    nuevo = despues[0]  # orden desc por id
    assert nuevo["estado"] == "corriendo"
    assert nuevo["render_job_id"] == "job-xyz"
    assert nuevo["parametros"]["escalones"] == [10, 20]
    assert nuevo["parametros"]["duracion_seg"] == 60
    assert len(llamados) == 1 and str(nuevo["id"]) in llamados[0]
    print("OK  test_correr_crea_test_y_llama_a_render")


def test_correr_sin_configuracion_de_render_queda_en_error(monkeypatch):
    monkeypatch.setattr(render_admin, "crear_job",
                         lambda start_command: {"error": "Falta RENDER_API_KEY"})
    r = client.post("/entornos/tests/correr", data={"tipo": "recibos"}, follow_redirects=False)
    assert r.status_code == 303
    nuevo = db.tests_carga_recientes(1)[0]
    assert nuevo["estado"] == "error"
    assert "RENDER_API_KEY" in nuevo["error_detalle"]
    print("OK  test_correr_sin_configuracion_de_render_queda_en_error")


def test_escalones_invalidos_caen_al_default():
    from main import _parsear_escalones, ESCALONES_DEFAULT_LECTURAS
    assert _parsear_escalones("50,100,abc", ESCALONES_DEFAULT_LECTURAS) == ESCALONES_DEFAULT_LECTURAS
    assert _parsear_escalones("10, 20 ,30", []) == [10, 20, 30]
    assert _parsear_escalones("", ESCALONES_DEFAULT_LECTURAS) == ESCALONES_DEFAULT_LECTURAS
    print("OK  test_escalones_invalidos_caen_al_default")


def test_api_detalle_404_si_no_existe():
    r = client.get("/api/entornos/tests/999999")
    assert r.status_code == 404
    print("OK  test_api_detalle_404_si_no_existe")


def test_entornos_renderiza_la_pestana_tests_con_datos_reales():
    """El path que ningún otro test ejercita: la plantilla Jinja iterando
    t.resumen (lista de dicts) y mostrando t.parametros -- si algo ahí
    tiene una key que no existe, esto revienta con un 500."""
    tid = db.crear_test_carga("lecturas", {"escalones": [50, 100], "duracion_seg": 90})
    db.actualizar_test_carga(
        tid, estado="listo", terminado_en="2026-09-09 12:00:00",
        resumen=[{"escalon": 50, "p50": 210.5, "p95": 480.2, "p99": 610.0, "errores_pct": 0.0, "rps": 12.3},
                 {"escalon": 100, "p50": 900.1, "p95": 1500.0, "p99": 1800.0, "errores_pct": 2.5, "rps": 15.0}])
    r = client.get("/entornos")
    assert r.status_code == 200
    assert f'data-test-id="{tid}"' in r.text
    assert "test-tabla" in r.text and "Escalón" in r.text
    assert "Tests en Pruebas" in r.text and "Tests en Demo" in r.text
    print("OK  test_entornos_renderiza_la_pestana_tests_con_datos_reales")


if __name__ == "__main__":
    test_modelo_test_carga_alta_actualizacion_y_lectura()
    test_sin_pase_no_se_puede_correr_ni_listar()

    class _MP:
        def setattr(self, obj, name, value):
            setattr(obj, name, value)

    test_correr_crea_test_y_llama_a_render(_MP())
    test_entornos_renderiza_la_pestana_tests_con_datos_reales()
    test_correr_sin_configuracion_de_render_queda_en_error(_MP())
    test_escalones_invalidos_caen_al_default()
    test_api_detalle_404_si_no_existe()
    print("Todo OK")
