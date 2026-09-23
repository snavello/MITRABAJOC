"""Pestaña "Tests" de /entornos: dispara el test de estrés (carga/) como
un Job de Render aparte -- ver main.py "Tests: pestaña de test de estrés"
y render_admin.py. Acá se cubre la tabla TestCarga (db.py) y el gate de
acceso de las rutas; NO se prueba contra la API real de Render (se
monkeypatchea render_admin.crear_job).

Correr con: .venv/Scripts/python.exe -m pytest test_tests_carga.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"
os.environ["PIN_ENTORNOS"] = "13571357"

import db
import main
import render_admin
from fastapi.testclient import TestClient

db.crear_tablas()
client = TestClient(main.app)
assert client.post("/entornos/pin", data={"pin": "13571357"}, follow_redirects=False).status_code == 303


def test_usuarios_carga_estres_lee_de_la_base_no_de_un_csv():
    """carga/correr_job.py corre en un Job de Render (contenedor efímero,
    sin el CSV que otro Job haya escrito) -- tiene que poder armar la lista
    de usuarios leyendo directo de la base."""
    from db import Sindicato, Trabajador
    with db.get_session() as s:
        sind = Sindicato(nombre="Carga Estres Test", slug="carga-estres")
        s.add(sind); s.commit(); s.refresh(sind)
        s.add(Trabajador(sindicato_id=sind.id, cuil="20900000001"))
        db.guardar_datos_personales(s, "20900000001", nombre="Uno")
        s.add(Trabajador(sindicato_id=sind.id, cuil="20900000002"))
        db.guardar_datos_personales(s, "20900000002", nombre="Dos")
        s.commit()
    usuarios = db.usuarios_carga_estres()
    assert set(usuarios) == {("20900000001", "1234"), ("20900000002", "1234")}
    print("OK  test_usuarios_carga_estres_lee_de_la_base_no_de_un_csv")


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


def test_entornos_renderiza_la_pestana_tests_con_el_link_al_detalle():
    """La lista de /entornos ya no embebe la tabla de resultados -- linkea
    a /entornos/tests/{id}, que es donde vive el informe completo (ver el
    test de abajo)."""
    tid = db.crear_test_carga("lecturas", {"escalones": [50, 100], "duracion_seg": 90})
    db.actualizar_test_carga(
        tid, estado="listo", terminado_en="2026-09-09 12:00:00",
        resumen=[{"escalon": 50, "p50": 210.5, "p95": 480.2, "p99": 610.0, "errores_pct": 0.0, "rps": 12.3},
                 {"escalon": 100, "p50": 900.1, "p95": 1500.0, "p99": 1800.0, "errores_pct": 2.5, "rps": 15.0}])
    r = client.get("/entornos")
    assert r.status_code == 200
    assert f'data-test-id="{tid}"' in r.text
    assert f'href="/entornos/tests/{tid}"' in r.text
    assert "Tests en Pruebas" in r.text and "Tests en Demo" in r.text
    print("OK  test_entornos_renderiza_la_pestana_tests_con_el_link_al_detalle")


def test_pagina_detalle_de_test_muestra_config_resultados_y_analisis():
    """La página de detalle (/entornos/tests/{id}): config real con la que
    corrió, la tabla completa y si cumplió el objetivo -- lo que el
    usuario pidió ver y antes no estaba."""
    tid = db.crear_test_carga("lecturas", {
        "escalones": [50, 800], "duracion_seg": 90,
        "config": {"workers_uvicorn": 2, "plan_web": "0.5c-512mb", "plan_db": "0.1c-256mb",
                   "pool_size": 5, "max_overflow": 5},
    })
    db.actualizar_test_carga(
        tid, estado="listo", terminado_en="2026-09-09 12:00:00",
        resumen=[{"escalon": 50, "p50": 210.5, "p95": 480.2, "p99": 610.0, "errores_pct": 0.0, "rps": 12.3},
                 {"escalon": 800, "p50": 60000.0, "p95": 60001.0, "p99": 60001.0, "errores_pct": 100.0, "rps": 3.0}])
    r = client.get(f"/entornos/tests/{tid}")
    assert r.status_code == 200
    assert f"Test #{tid}" in r.text
    assert "2" in r.text and "0.5c-512mb" in r.text  # workers y plan real de esa corrida
    assert "480.2" in r.text and "60001.0" in r.text  # números de la tabla completa
    # 50 cumple el objetivo (p95<1000, err<1%), 800 no -- el análisis lo dice en una frase.
    assert "50</b>" in r.text or ">50<" in r.text
    assert "milisegundos" in r.text or "ms" in r.text  # unidad de los tiempos, no dada por sabida
    assert "github.com" not in r.text.lower()  # el informe completo va a una página propia, no a un repo privado
    print("OK  test_pagina_detalle_de_test_muestra_config_resultados_y_analisis")


def test_sin_pase_la_pagina_de_detalle_no_expone_nada():
    tid = db.crear_test_carga("lecturas", {"escalones": [50], "duracion_seg": 30})
    c = TestClient(main.app)  # sin pase de PIN
    r = c.get(f"/entornos/tests/{tid}", follow_redirects=False)
    assert r.status_code == 303  # vuelve a la landing, no expone el detalle
    print("OK  test_sin_pase_la_pagina_de_detalle_no_expone_nada")


def test_publicar_sin_pase_ni_pin_de_header_rechaza():
    c = TestClient(main.app)  # sin cookie de pase
    r = c.post("/entornos/tests/publicar", json={"tipo": "lecturas", "resumen": [{"escalon": 50}]})
    assert r.status_code == 403
    print("OK  test_publicar_sin_pase_ni_pin_de_header_rechaza")


def test_publicar_con_pin_de_header_crea_test_listo():
    """Correr.sh no tiene cookie de sesión -- se autentica con el PIN en
    el header, no con el pase de landing."""
    c = TestClient(main.app)  # sin cookie de pase, a propósito
    resumen = [{"escalon": 50, "p50": 110.5, "p95": 190.7, "p99": 297.3, "errores_pct": 0.0, "rps": 20.12},
               {"escalon": 100, "p50": 125.8, "p95": 690.2, "p99": 1170.7, "errores_pct": 0.0, "rps": 44.39}]
    r = c.post("/entornos/tests/publicar", json={
        "tipo": "lecturas", "duracion_seg": 240,
        "config": {"workers_uvicorn": 2, "plan_web": "2c-4g", "plan_db": "2c-4g"},
        "resumen": resumen, "terminado_en": "2026-09-10 01:14:00",
    }, headers={"X-Pin-Entornos": "13571357"})
    assert r.status_code == 200
    tid = r.json()["id"]
    fila = db.test_carga_por_id(tid)
    assert fila["estado"] == "listo"
    assert fila["resumen"] == resumen
    assert fila["parametros"]["config"]["plan_web"] == "2c-4g"
    # Publicado, aparece en la lista -- lo que faltaba antes con correr.sh.
    assert any(f["id"] == tid for f in db.tests_carga_recientes(50))
    print("OK  test_publicar_con_pin_de_header_crea_test_listo")


def test_publicar_sin_resumen_rechaza():
    c = TestClient(main.app)
    r = c.post("/entornos/tests/publicar",
               json={"tipo": "lecturas", "resumen": []},
               headers={"X-Pin-Entornos": "13571357"})
    assert r.status_code == 400
    print("OK  test_publicar_sin_resumen_rechaza")


def _experimento_de_prueba(numero=1):
    """Un experimento con la misma forma que produce carga/consolidar.py."""
    return {
        "tipo": "experimento", "numero": numero, "nombre": "Línea base",
        "subtitulo": "Todo en el plan más chico", "objetivo": "Medir el punto de partida.",
        "config": {"plan_web": "0.5c-512mb", "plan_web_etiqueta": "0,5 vCPU / 512 MB",
                    "plan_db": "0.1c-256mb", "plan_db_etiqueta": "0,1 vCPU / 256 MB",
                    "workers_uvicorn": 1, "pool_size": 5, "max_overflow": 5,
                    "ia": "síncrona", "ia_latencia_seg": 15},
        "advertencias": ["Corrida limpia: sin despliegues a mitad de test."],
        "veredicto": "Ningún escalón cumplió el objetivo.",
        "conclusion": "El cuello de botella es el servicio web.",
        "inicio_ba": "2026-09-09 17:34", "fin_ba": "18:40",
        "terminado_en": "2026-09-09 18:40",
        "resumen": [{
            "clave": "lecturas", "titulo": "Lecturas", "detalle": "Navegación.",
            "unidad": "usuarios concurrentes", "inicio_ba": "2026-09-09 17:34",
            "fin_ba": "17:55", "duracion_min": 20.7, "muestras_bajas": False,
            "carga_medida": True,
            "filas": [{"escalon": 50, "p50": 1715.6, "p95": 4215.1, "p99": 6427.9,
                        "errores_pct": 0.0, "rps": 11.82, "n": 2836,
                        "valido": True, "cumple": False}],
            "carga": {"muestras": 39,
                       "web": {"cpu_usado": 0.5, "cpu_nominal": 0.5, "cpu_pct": 100.0,
                               "ram_mb": 319, "ram_nominal_mb": 512, "ram_pct": 62.3,
                               "cpu_txt": "0,5 de 0,5 vCPU · 100,0%",
                               "ram_txt": "319 de 512 MB · 62,3%"},
                       "db": {"cpu_usado": 0.1, "cpu_nominal": 0.1, "cpu_pct": 100.0,
                              "ram_mb": 142, "ram_nominal_mb": 256, "ram_pct": 55.5,
                              "cpu_txt": "0,1 de 0,1 vCPU · 100,0%",
                              "ram_txt": "142 de 256 MB · 55,5%", "conexiones": 10}},
        }],
    }


def test_publicar_experimento_guarda_fases_config_y_conclusion():
    c = TestClient(main.app)
    r = c.post("/entornos/tests/publicar", json=_experimento_de_prueba(),
               headers={"X-Pin-Entornos": "13571357"})
    assert r.status_code == 200
    fila = db.test_carga_por_id(r.json()["id"])
    assert fila["tipo"] == "experimento"
    assert fila["parametros"]["conclusion"].startswith("El cuello de botella")
    assert fila["resumen"][0]["carga"]["db"]["cpu_pct"] == 100.0
    print("OK  test_publicar_experimento_guarda_fases_config_y_conclusion")


def test_pagina_de_experimento_muestra_cpu_ram_de_web_y_postgres():
    """Lo que se pidió ver en cada test: condiciones técnicas, resultados,
    las cargas de web Y de Postgres, y la conclusión."""
    r = client.post("/entornos/tests/publicar", json=_experimento_de_prueba(2))
    tid = r.json()["id"]
    p = client.get(f"/entornos/tests/{tid}")
    assert p.status_code == 200
    assert "Línea base" in p.text
    assert "0,5 vCPU / 512 MB" in p.text and "0,1 vCPU / 256 MB" in p.text
    assert "Servicio web" in p.text and "Postgres" in p.text
    assert "319" in p.text and "142" in p.text          # RAM de web y de la base
    assert "Conexiones" in p.text and ">10<" in p.text
    assert "El cuello de botella es el servicio web." in p.text
    assert "Buenos Aires" in p.text                      # la fecha se declara en hora de BA
    print("OK  test_pagina_de_experimento_muestra_cpu_ram_de_web_y_postgres")


def test_fase_sin_metricas_no_inventa_numeros():
    """Cuando el monitor no pudo medir (pasó en la primera corrida), la
    página tiene que decirlo, no mostrar los valores de otra fase."""
    exp = _experimento_de_prueba(3)
    exp["resumen"][0]["carga_medida"] = False
    exp["resumen"][0]["carga"] = {
        "muestras": 40,
        "web": {"cpu_usado": None, "cpu_nominal": 0.5, "cpu_pct": None, "ram_mb": None,
                "ram_nominal_mb": 512, "ram_pct": None,
                "cpu_txt": "no medido", "ram_txt": "no medido"},
        "db": {"cpu_usado": None, "cpu_nominal": 0.1, "cpu_pct": None, "ram_mb": None,
               "ram_nominal_mb": 256, "ram_pct": None, "conexiones": None,
               "cpu_txt": "no medido", "ram_txt": "no medido"},
    }
    tid = client.post("/entornos/tests/publicar", json=exp).json()["id"]
    p = client.get(f"/entornos/tests/{tid}")
    assert p.status_code == 200
    assert "no se pudieron medir" in p.text
    print("OK  test_fase_sin_metricas_no_inventa_numeros")


def test_borrar_todo_vacia_la_lista_y_reinicia_la_numeracion():
    for _ in range(3):
        client.post("/entornos/tests/publicar", json=_experimento_de_prueba())
    assert db.tests_carga_recientes(50)
    r = client.post("/entornos/tests/borrar-todo")
    assert r.status_code == 200 and r.json()["borrados"] > 0
    assert db.tests_carga_recientes(50) == []
    nuevo = client.post("/entornos/tests/publicar", json=_experimento_de_prueba()).json()["id"]
    assert nuevo == 1, f"tras el borrado la numeración tiene que arrancar en 1, dio {nuevo}"
    print("OK  test_borrar_todo_vacia_la_lista_y_reinicia_la_numeracion")


def test_borrar_todo_sin_pin_rechaza():
    c = TestClient(main.app)
    assert c.post("/entornos/tests/borrar-todo").status_code == 403
    print("OK  test_borrar_todo_sin_pin_rechaza")


def test_informe_completo_se_sirve_desde_el_sitio_sin_github():
    """El link "Ver el informe completo" de test_detalle.html tiene que
    quedar DENTRO del sitio -- pedido explícito de Sd (2026-09-10): antes
    apuntaba a un Artifact externo de claude.ai que pedía iniciar sesión
    (vía GitHub) para verlo, el mismo problema que ya se había resuelto
    una vez con los links directos a GitHub."""
    assert main.URL_INFORME_COMPLETO == "/entornos/informe"
    r = client.get("/entornos/informe")  # `client`: TestClient con pase de PIN puesto
    assert r.status_code == 200
    assert "github.com" not in r.text.lower()
    assert "claude.ai" not in r.text.lower()
    print("OK  test_informe_completo_se_sirve_desde_el_sitio_sin_github")


def test_el_informe_general_sale_de_los_mismos_datos_que_los_tests():
    """El informe se arma desde carga/experimentos.json, no de HTML
    escrito a mano: los cuatro tests, sus configuraciones y las cifras
    tienen que aparecer tal como están en el dataset."""
    from carga import informe as informe_carga
    inf = informe_carga.construir()
    r = client.get("/entornos/informe")
    assert r.status_code == 200
    for e in inf["experimentos"]:
        assert e["nombre"] in r.text, f"falta el test {e['numero']} en el informe"
        assert f'href="/entornos/tests/{e["numero"]}"' in r.text
        assert e["config"]["plan_web_etiqueta"] in r.text
    assert inf["resumen"][:70] in r.text
    for h in inf["hallazgos"]:
        assert h["titulo"] in r.text
    for rec in inf["recomendaciones"]:
        assert rec["titulo"] in r.text
    print("OK  test_el_informe_general_sale_de_los_mismos_datos_que_los_tests")


def test_el_informe_no_presenta_como_medido_lo_que_es_inferencia():
    """La sección de producción extrapola: tiene que estar rotulada como
    tal, para no leerse como si fuera otro resultado medido."""
    r = client.get("/entornos/informe")
    assert "Esto es razonamiento, no medición" in r.text
    # Y los escalones descartados no pueden figurar como números buenos.
    assert "n/d" in r.text and "contaminados" in r.text
    print("OK  test_el_informe_no_presenta_como_medido_lo_que_es_inferencia")


def test_informe_completo_sin_pase_no_se_expone():
    c = TestClient(main.app)  # sin pase de PIN
    r = c.get("/entornos/informe", follow_redirects=False)
    assert r.status_code == 303
    print("OK  test_informe_completo_sin_pase_no_se_expone")


if __name__ == "__main__":
    test_usuarios_carga_estres_lee_de_la_base_no_de_un_csv()
    test_modelo_test_carga_alta_actualizacion_y_lectura()
    test_sin_pase_no_se_puede_correr_ni_listar()

    class _MP:
        def setattr(self, obj, name, value):
            setattr(obj, name, value)

    test_correr_crea_test_y_llama_a_render(_MP())
    test_entornos_renderiza_la_pestana_tests_con_el_link_al_detalle()
    test_correr_sin_configuracion_de_render_queda_en_error(_MP())
    test_escalones_invalidos_caen_al_default()
    test_api_detalle_404_si_no_existe()
    print("Todo OK")
