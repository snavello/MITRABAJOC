"""Escenario "filtro frenético" del harness de carga (C7 del cuelgue de Pruebas
del 2026-09-18, docs/chat/2026-09-19-cuelgue-dashboard-conexiones.md).

El escenario en sí se corre a mano contra Pruebas con k6 (gasta la base de
Pruebas y necesita la clave de un admin), así que esto solo cuida que el script
exista, sea sintácticamente válido, respete las reglas del harness y esté
enganchado en `carga/correr.sh`.

Correr con: .venv/Scripts/python.exe -m pytest test_carga_panel.py -q
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).parent
SCRIPT = RAIZ / "carga" / "k6" / "test3_panel.js"
CORRER = RAIZ / "carga" / "correr.sh"
JS = SCRIPT.read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node no está instalado")
def test_el_script_de_k6_es_javascript_valido():
    with tempfile.TemporaryDirectory() as d:
        copia = Path(d) / "test3_panel.mjs"          # k6 usa módulos ES
        copia.write_text(JS, encoding="utf-8")
        r = subprocess.run([shutil.which("node"), "--check", str(copia)],
                           capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr


def test_reproduce_el_escenario_pedido():
    assert "vus: LECTORES" in JS and "const LECTORES = 20;" in JS          # 20 lectores
    assert "const CAMBIOS_DE_FILTRO = 30;" in JS                            # 30 cambios...
    assert "startTime: '60s'" in JS and "sleep(2)" in JS                    # ...en ~60 s
    assert "empresas=" in JS                                                # con filtro de empresa
    assert "timeout: ABANDONO" in JS and "const ABANDONO = '250ms';" in JS  # abandona los pedidos
    assert "/admin/dashboard/" in JS and "/trabajador/login" in JS


def test_los_criterios_de_aceptacion_estan_en_el_script():
    assert "errores_500: ['rate==0']" in JS                                 # 0 % de 500
    assert "res.status >= 500 && res.status !== 503" in JS                  # un 503 no es error
    assert "razon <= 2" in JS                                               # p95 no se degrada más de 2x
    assert "APROBADO" in JS


def test_pide_la_clave_por_entorno_y_no_la_escribe():
    assert "__ENV.ADMIN_CLAVE" in JS
    assert "Falta ADMIN_CLAVE" in JS
    # la única clave de admin nombrada en el repo es la de la demo documentada
    # en CLAUDE.md; este script no debe traer ninguna
    assert "-demo'" not in JS and '-demo"' not in JS


def test_correr_sh_lo_engancha_solo_con_clave_y_no_rompe_el_bash():
    sh = CORRER.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert "k6/test3_panel.js" in sh
    assert 'if [[ -n "${ADMIN_CLAVE:-}" ]]' in sh
    # sigue apuntando solo a Pruebas
    assert 'BASE_URL" != *"pruebas"*' in sh
    bash = shutil.which("bash")
    if bash:
        r = subprocess.run([bash, "-n"], input=sh, capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
