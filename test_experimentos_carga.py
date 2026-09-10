"""Los 4 experimentos publicados en /entornos#tests-pruebas tienen que
coincidir con los datos crudos de carga/log/, siempre.

Pedido explícito de Sd (2026-09-10) después de encontrar que un informe se
contradecía a sí mismo: "habilitá una revisión meticulosa de cada uno para
no dar información inconsistente que me lleve a tomar decisiones erradas y
ruinosas". carga/verificar.py hace esa auditoría (tiempos contra
resumen.csv, CPU/RAM contra servidor.log, y ninguna cifra en las
conclusiones que no salga de la tabla del propio test); este test la corre
en cada corrida de la suite para que nadie pueda publicar algo que no
cierre con el dato de origen.

Correr con: python test_experimentos_carga.py
"""
import json
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
CARGA = RAIZ / "carga"


def test_la_auditoria_de_consistencia_pasa():
    r = subprocess.run([sys.executable, "verificar.py"], cwd=CARGA,
                        capture_output=True, text=True)
    assert r.returncode == 0, f"carga/verificar.py encontró inconsistencias:\n{r.stdout}\n{r.stderr}"
    assert "Sin inconsistencias" in r.stdout
    print("OK  test_la_auditoria_de_consistencia_pasa")


def test_el_json_consolidado_esta_al_dia_con_los_datos_crudos():
    """Si alguien toca carga/log/ o consolidar.py y se olvida de regenerar,
    el JSON publicado queda viejo -- eso se detecta acá, no en la página."""
    antes = json.loads((CARGA / "experimentos.json").read_text(encoding="utf-8"))
    r = subprocess.run([sys.executable, "-c",
                        "import consolidar, json; print(json.dumps(consolidar.construir(), ensure_ascii=False))"],
                       cwd=CARGA, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == antes, \
        "carga/experimentos.json quedó desactualizado: correr python carga/consolidar.py"
    print("OK  test_el_json_consolidado_esta_al_dia_con_los_datos_crudos")


def test_los_experimentos_estan_numerados_sin_huecos():
    datos = json.loads((CARGA / "experimentos.json").read_text(encoding="utf-8"))
    assert [e["numero"] for e in sorted(datos, key=lambda x: x["numero"])] == list(range(1, len(datos) + 1))
    for e in datos:
        assert e["conclusion"], f"Al experimento {e['numero']} le falta la conclusión."
        assert e["veredicto"], f"Al experimento {e['numero']} le falta el veredicto."
        assert e["config"]["plan_web"] and e["config"]["plan_db"]
        # Cada fase declara la carga de los DOS servicios, aunque sea sin medir.
        for f in e["fases"]:
            assert "web" in f["carga"] and "db" in f["carga"]
    print("OK  test_los_experimentos_estan_numerados_sin_huecos")


def test_las_fechas_estan_en_hora_de_buenos_aires():
    """Las corridas fueron de noche en UTC y de tarde en Buenos Aires: si
    alguna fecha quedara en UTC, se vería un test "de las 22" que en
    realidad fue a las 19."""
    datos = json.loads((CARGA / "experimentos.json").read_text(encoding="utf-8"))
    horas = [int(e["inicio_ba"][11:13]) for e in datos]
    assert all(12 <= h <= 23 for h in horas), f"Horas sospechosas (¿UTC?): {horas}"
    print("OK  test_las_fechas_estan_en_hora_de_buenos_aires")


if __name__ == "__main__":
    test_la_auditoria_de_consistencia_pasa()
    test_el_json_consolidado_esta_al_dia_con_los_datos_crudos()
    test_los_experimentos_estan_numerados_sin_huecos()
    test_las_fechas_estan_en_hora_de_buenos_aires()
    print("Todo OK — los experimentos publicados cierran con los datos crudos.")
