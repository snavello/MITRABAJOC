"""XSII bloque 5, la pantalla de «vuelta a la Mesa» (estático, sin navegador): hitos propuestos
y archivos de los insumos. Contrato en docs/xsii/API.md, sección «Bloque 5»."""
import re
from pathlib import Path

RAIZ = Path(__file__).parent
PLANTILLA = (RAIZ / "templates" / "xsii.html").read_text(encoding="utf-8")
JS = (RAIZ / "static" / "xsii" / "xsii.js").read_text(encoding="utf-8")
CSS = (RAIZ / "static" / "xsii" / "xsii.css").read_text(encoding="utf-8")


def _entre(a, b):
    return JS[JS.index(a):JS.index(b)]


def _hitos():
    return _entre("Hitos de la Mesa (bloque 5)", "// ------------------------------------------------------------ GUÍA")


def test_cuarta_vista_hitos_con_insignia():
    assert 'data-v="hitos"' in PLANTILLA and 'id="x-bd-hitos"' in PLANTILLA
    assert "const VISTAS = ['guia', 'tablero', 'mapa', 'hitos']" in JS
    assert "S.vista === 'hitos'" in JS and "function vistaHitos(" in JS and "function bandaHitos(" in JS
    assert "bandaHitos()" in JS and "hito de la Mesa para marcar" in _hitos()


def test_rutas_del_contrato():
    b = _hitos()
    assert "pedir('hitos')" in b
    for ruta in ("'hitos/' + x.id + '/marcar'", "'hitos/' + x.id + '/enlace'", "'/enlace/retirar'", "'hitos/sugerencias/aceptar'"):
        assert ruta in b, ruta
    assert "'/archivos'" in b and "'/archivo'" in b and "archivo_id" in b
    assert "'archivo_mesa'" in JS


def test_marcar_pide_segundo_toque_y_no_usa_confirm():
    b = _hitos()
    assert "H.armado !== x.id" in b and "Tocá otra vez" in b and "No marcar" in b
    assert not re.search(r"(?<![A-Za-z.])confirm\(|window\.confirm|alert\(", JS)


def test_el_409_muestra_el_motivo_y_refresca():
    b = _hitos()
    assert "e.status === 409" in b and "refrescarHitos()" in b
    assert "Promise.all([cargarHitos(true), cargar(true)])" in b


def test_textos_del_servidor_como_texto():
    assert "innerHTML" not in JS and "insertAdjacentHTML" not in JS
    b = _hitos()
    assert "x.texto" in b and "a.nombre" in b and "tr.nombre" in b
    assert not re.search(r"https?://", b)


def test_ficha_con_hitos_y_archivos():
    assert "seccionHitos(t)" in JS and "bloqueArchivos(i)" in JS
    assert "t.hitos || []" in JS
    assert "Llegó un archivo en" in JS and "Usar este archivo" in JS
    assert "archivos_nuevos" in JS


def test_asistida_usa_el_archivo_de_la_mesa():
    assert "d.archivo_mesa" in JS and "Usar el archivo de la Mesa (" in JS
    assert "fd.append('archivo_mesa'" in JS and "Subir otro archivo" in JS
    # con la Mesa, el ensayo y la carga mandan el id y NO el archivo
    c = _entre("function formAs(", "function tiempoAs(")
    assert c.index("archivo_mesa") < c.index("fd.append('archivo', base.archivo")
    assert "base.mesa" in c


def test_css_sin_externos_y_con_movil_y_movimiento_reducido():
    for clase in (".banda-h", ".hit-prop", ".hito", ".hch", ".llego", ".arch", ".as-mesa"):
        assert clase in CSS, clase
    assert "@import" not in CSS and "url(http" not in CSS
    assert "prefers-reduced-motion" in CSS
    assert not re.search(r"transition:[^;}]*\b\d+(\.\d+)?m?s\b", CSS[CSS.index("Bloque 5: hitos"):])
