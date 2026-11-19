"""Grilla salarial y convenio en la app del afiliado (PLAN_CONVENIO_ESCALAS.md,
D42 a D48): la pestaña de /app, su acceso en la portada y sus archivos. Pruebas
estáticas sobre las plantillas y los archivos; la API la cubre otro archivo.

Correr con: python -m pytest test_grilla_app_pantalla.py -q
"""
import pathlib
import re

AQUI = pathlib.Path(__file__).parent
TRAB = (AQUI / "templates" / "trabajador.html").read_text(encoding="utf-8")
PORT = (AQUI / "templates" / "portada.html").read_text(encoding="utf-8")
JS = (AQUI / "static" / "grilla_app.js").read_text(encoding="utf-8")
CSS = (AQUI / "static" / "grilla_app.css").read_text(encoding="utf-8")
HOJAS = {m: (AQUI / "static" / "temas" / f"{m}-grilla.css") for m in ("laguna", "noticiero")}


def test_la_pestana_depende_de_la_variable_del_servidor():
    boton = re.search(r'\{% if grilla_convenio_disponible %\}<button class="tab-t" data-tp="grilla".*?</button>\{% endif %\}', TRAB, re.S)
    assert boton, "el botón de la pestaña tiene que estar condicionado a grilla_convenio_disponible"
    assert "Mis Recibos</button>" in TRAB[: boton.start()][-400:], "va después de Mis Recibos"
    i = TRAB.index('id="tp-grilla"')
    assert "{% if grilla_convenio_disponible %}" in TRAB[i - 600: i]


def test_el_panel_lleva_data_mov_vista_y_sus_sub_vistas():
    assert 'class="tpanel" data-mov-vista id="tp-grilla"' in TRAB
    for vista in ("seleccion", "escala", "convenio", "vacio"):
        assert f'id="gr-v-{vista}"' in TRAB
        assert re.search(rf'id="gr-v-{vista}"[^>]*data-mov-vista', TRAB), vista


def test_los_estaticos_van_con_sello():
    for nombre in ("grilla_app.css", "grilla_app.js", "numeros_ar.js"):
        assert re.search(rf"/static/{re.escape(nombre)}\?v=\{{\{{ sello_static\('{re.escape(nombre)}'\) \}}\}}", TRAB), nombre
    assert "temas/' ~ apariencia.tema ~ '-grilla.css" in TRAB
    assert "sello_static('temas/' ~ apariencia.tema ~ '-grilla.css')" in TRAB


def test_existen_las_hojas_de_los_dos_modelos():
    for modelo, ruta in HOJAS.items():
        assert ruta.is_file(), modelo
        txt = ruta.read_text(encoding="utf-8")
        assert f'html[data-tema="{modelo}"]' in txt
        otro = "noticiero" if modelo == "laguna" else "laguna"
        assert f'data-tema="{otro}"' not in txt, "cada hoja habla solo de su modelo"


def test_el_acceso_de_la_portada_lleva_a_la_pestana():
    i = PORT.index('href="/app?tab=grilla"')
    assert "{% if grilla_convenio_disponible %}" in PORT[i - 200: i]
    assert "Grilla salarial y convenio" in PORT[i: i + 500]
    assert 'id="ic-grilla"' in PORT and 'id="ic-grilla"' in TRAB


def test_el_js_no_arma_html_con_datos():
    assert "innerHTML" not in JS and "insertAdjacentHTML" not in JS and "outerHTML" not in JS
    assert "document.write" not in JS
    assert "textContent" in JS


def test_el_js_no_conoce_lo_interno():
    sin_comentarios = re.sub(r"/\*.*?\*/", "", JS, flags=re.S)
    for palabra in ("herramienta", "validaci", "entornos", "sin revisar", "prueba"):
        assert palabra not in sin_comentarios.lower(), palabra
    assert not re.search(r"\bIA\b", JS)
    assert "/api/entornos/" not in JS
    assert "/api/app/grilla" in JS
    for palabra in ("herramienta", "validaci", "entornos", "sin revisar"):
        assert palabra not in TRAB[TRAB.index('id="tp-grilla"'): TRAB.index('id="tp-novedades"')].lower(), palabra


def test_toda_la_lectura_pasa_por_pedirjson():
    assert "pedirJson(" in JS
    assert not re.search(r"\.json\(\)", JS.split("async function pedir")[0])
    # el único fetch es el de respaldo, dentro de pedir()
    assert JS.count("fetch(") == 1


def test_es_una_consulta_no_un_control():
    for rotulo in ("veredicto", "semáforo", "semaforo", "/app?tab=recibo", "Total"):
        assert rotulo.lower() not in JS.lower(), rotulo


def test_el_convenio_baja_en_pdf_y_no_trae_resumenes():
    assert "Descargar el convenio (PDF)" in TRAB
    assert "download" in TRAB[TRAB.index('id="gr-conv-pdf"') - 40: TRAB.index('id="gr-conv-pdf"') + 80]
    for campo in ("resumen", "situaciones", "frecuentes"):
        assert f".{campo}" not in JS and f"\x27{campo}\x27" not in JS, campo


def test_el_movimiento_usa_los_tokens():
    assert "var(--mov-" in CSS and "var(--ease-" in CSS
    assert not re.search(r"transition:[^;]*\d+ms", CSS), "duraciones sueltas: usar los tokens de movimiento.css"
