"""XSII, bloque 1: la pantalla (estática, sin navegador). Plantilla, CSS y JS
cumplen las reglas del proyecto: estáticos con sello, nada externo, nada de
HTML armado con datos del servidor, rutas del contrato y «Preguntame»
prendido (bloque 2)."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).parent
PLANTILLA = (RAIZ / "templates" / "xsii.html").read_text(encoding="utf-8")
JS = (RAIZ / "static" / "xsii" / "xsii.js").read_text(encoding="utf-8")
CSS = (RAIZ / "static" / "xsii" / "xsii.css").read_text(encoding="utf-8")


def test_plantilla_carga_css_y_js_con_sello():
    assert "{{ sello_static('xsii/xsii.css') }}" in PLANTILLA
    assert "{{ sello_static('xsii/xsii.js') }}" in PLANTILLA
    assert "{{ sello_static('movimiento.css') }}" in PLANTILLA
    for m in re.findall(r'(?:src|href)="(/static/[^"]+)"', PLANTILLA):
        assert "?v=" in m, m


def test_sin_cdn_ni_fuentes_externas():
    for texto in (PLANTILLA, JS, CSS):
        externas = [u for u in re.findall(r"https?://[^\s'\"]+", texto) if u != "http://www.w3.org/2000/svg"]
        assert not externas, externas
        assert "googleapis" not in texto and "gstatic" not in texto


def test_js_no_arma_html_con_datos_ni_usa_prompt():
    assert "innerHTML" not in JS
    assert "insertAdjacentHTML" not in JS
    assert "outerHTML" not in JS
    assert "document.write" not in JS
    assert "prompt(" not in JS.replace("preguntame", "")
    assert not re.search(r"\beval\(|new Function", JS)


def test_js_usa_las_rutas_del_contrato():
    assert "/api/entornos/xsii/p/" in JS
    for ruta in ("'tablero'", "'tarea/'", "/decision'", "/decision/deshacer'", "'insumo/'", "/retirar'"):
        assert ruta in JS, ruta
    for clave in ("completada_a_mano", "no_aplica", "pospuesta", "confirmada"):
        assert clave in JS


def test_preguntame_prendido_y_maneja_disponible_false():
    assert "Preguntame" in JS
    assert "P.disponible" in JS and "P.motivo" in JS
    assert "S.D.preguntame" in JS
    # solo queda el texto viejo para un servidor que no trae `preguntame`
    assert JS.count("Llega en el próximo bloque") == 1
    assert "if (!P) {" in JS
    for ruta in ("'preguntar'", "'insumo/' + encodeURIComponent(clave) + '/reclamo'", "/reclamo'"):
        assert ruta in JS, ruta
    for pieza in ("aria-expanded", "aria-live", "Escape", "Crear en la Mesa", "Descartar",
                  "Respuesta simulada: en este entorno no se llama a la IA.",
                  "Va como respuesta en la tarjeta", "resultado"):
        assert pieza in JS, pieza
    assert "if (st.cargando) return;" in JS
    for punto in ("'recomendada'", "'tarea'", "'mapa'"):
        assert f"pm({punto}" in JS, punto
    assert "Reclamar en la Mesa" in JS and "abrirReclamo(" in JS


def test_el_servidor_no_decide_en_la_pantalla_el_texto_va_como_nodo():
    # los codigos de la respuesta son botones con nodos de texto
    assert "createTextNode(texto.slice" in JS
    assert "white-space:pre-line" in CSS


def test_el_js_compila_con_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("no hay node en este entorno")
    r = subprocess.run([node, "--check", str(RAIZ / "static" / "xsii" / "xsii.js")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def _funciones(texto):
    """(inicio, fin) de cada `function nombre(...) {` por conteo de llaves (ignora cadenas y comentarios de linea)."""
    limpio = re.sub(r"//[^\n]*", "", texto)
    limpio = re.sub(r"'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\"", "''", limpio)
    out = []
    for m in re.finditer(r"function\s*\w*\s*\([^)]*\)\s*\{", limpio):
        i, prof = m.end(), 1
        while i < len(limpio) and prof:
            prof += {"{": 1, "}": -1}.get(limpio[i], 0)
            i += 1
        out.append((m.start(), limpio[m.end():i - 1]))
    return out


def test_sin_const_o_let_repetidos_en_el_mismo_nivel_de_una_funcion():
    """Una variable repetida dejo el Mapa en blanco en el bloque 1: `const x` dos veces al
    mismo nivel de llaves de una misma funcion es un SyntaxError que solo se ve al correr."""
    problemas = []
    for _, cuerpo in _funciones(JS):
        nivel, vistos = 0, {}
        pila = [set()]
        for tok in re.finditer(r"\{|\}|(?<!\()\b(?:const|let)\s+(\w+)", cuerpo):
            t = tok.group(0)
            if t == "{":
                pila.append(set())
            elif t == "}":
                if len(pila) > 1:
                    pila.pop()
            else:
                nombre = tok.group(1)
                if nombre in pila[-1]:
                    problemas.append(nombre)
                pila[-1].add(nombre)
    assert not problemas, problemas


def test_las_tres_vistas_y_la_url():
    for v in ("guia", "tablero", "mapa"):
        assert f'data-v="{v}"' in PLANTILLA
    assert "history.replaceState" in JS
    assert "'vista'" in JS and "'tarea'" in JS


def test_pantalla_para_quien_no_es_equipo():
    assert "{% if es_equipo %}" in PLANTILLA and "/entornos" in PLANTILLA
    # el script solo se carga si es del equipo
    assert PLANTILLA.rindex("xsii.js") > PLANTILLA.rindex("{% if es_equipo %}")


def test_accesibilidad_y_movimiento():
    assert "aria-pressed" in JS and "aria-pressed" in PLANTILLA
    assert ":focus-visible" in CSS
    assert "prefers-reduced-motion" in CSS
    assert "(hover:hover)" in CSS
    assert "var(--mov-" in CSS and "var(--ease-" in CSS
    assert "@media (max-width:600px)" in CSS


def test_boton_abrir_xsii_en_la_pestana_implementacion():
    equipo = (RAIZ / "static" / "implementacion" / "equipo.js").read_text(encoding="utf-8")
    assert "/entornos/xsii/" in equipo and "Abrir XSII" in equipo


def test_no_hay_guiones_largos_en_los_textos():
    for texto in (PLANTILLA, JS):
        assert "—" not in texto


def test_mapa_rutea_por_pasillos_y_tablero_en_tarjetas():
    assert "redondeada(" in JS and "yPasillo" in JS and "usoGap" in JS
    assert "@media (max-width:700px)" in CSS and "tr.fila" in CSS


def test_textos_del_pedido_deshacer_y_ficha_resuelta():
    assert "Pedido hoy" in JS and "Pedido ayer" in JS
    assert "d.dias >= 2" in JS
    for t in ("Retomar", "Deshacer la confirmación", "Deshacer: completada a mano", "Volver a aplicar"):
        assert t in JS, t
    assert "frenos.length && !resuelta(t)" in JS
    assert "Lo que diría el control (no cuenta: la tarea no aplica)" in JS
    assert "Lo que calcula el control" in JS
    assert "Primero registrá que llegó el insumo." in JS
    assert "no aplican)" in JS
