"""XSII, bloque 3: la carga asistida en la ficha (estatico, sin navegador).
Genérica: ningun texto de una tarea puntual (seccionales) vive en el JS."""
import re
from pathlib import Path

RAIZ = Path(__file__).parent
JS = (RAIZ / "static" / "xsii" / "xsii.js").read_text(encoding="utf-8")
CSS = (RAIZ / "static" / "xsii" / "xsii.css").read_text(encoding="utf-8")


def test_boton_principal_y_ruta_de_la_asistida():
    assert "Cargar desde la planilla" in JS
    assert "t.asistida" in JS
    assert "'/asistida'" in JS or "/asistida'" in JS
    for ruta in ("/ensayo'", "/carga'", "/modelo.csv'"):
        assert ruta in JS, ruta
    assert "Ir a la pantalla" in JS
    assert "Se carga desde una planilla, con ensayo previo." in JS


def test_los_cuatro_momentos_y_sus_piezas():
    for pieza in ("'Qué voy a hacer'", "'Ensayo'", "'Carga'", "'Control'", "Nada se guardó todavía",
                  "Ensayar (no guarda nada)", "Descargar el modelo", "Dejar afuera", "Confirmar la carga",
                  "Esto destrabó", "Qué sigue", "Volver a ensayar", "'Listo'", "Seguir", "Volver"):
        assert pieza in JS, pieza
    for fn in ("paso1As", "paso2As", "paso3As", "paso4As", "ensayarAs", "cargarAs"):
        assert f"function {fn}(" in JS, fn
    for v in ("validas", "dudosas", "rechazadas", "ya_existen"):
        assert v in JS, v
    for v in ("huella", "dejar_afuera", "'archivo'", "'opciones'", "FormData"):
        assert v in JS, v


def test_confirmacion_propia_sin_confirm_ni_doble_envio():
    assert not re.search(r"\bconfirm\(", JS)
    assert "if (!A || A.trabajando) return;" in JS
    assert "A.confirmando" in JS


def test_nada_de_una_tarea_puntual_en_el_js_de_la_asistida():
    inicio = JS.index("Carga asistida (bloque 3)")
    fin = JS.index("// ------------------------------------------------------------ FICHA")
    bloque = JS[inicio:fin].lower()
    for palabra in ("seccional", "sede central", "est-01", "est-02", "padrón", "padron"):
        assert palabra not in bloque, palabra
    assert "info.titulo" not in bloque and "d.titulo" in bloque
    assert "d.que_voy_a_hacer" in bloque and "d.columnas" in bloque and "d.opciones" in bloque


def test_errores_del_servidor_como_texto_y_sin_html():
    assert "innerHTML" not in JS
    assert "A.error = e.message" in JS
    assert "e.status" in JS


def test_estilos_y_movimiento_de_la_asistida():
    for clase in (".as{", ".as-pasos", ".as-nada", ".as-kpis", ".as-k", ".as-f", ".as-arch", ".as-resto"):
        assert clase in CSS, clase
    assert "pil.dudosa" in CSS and "pil.rechazada" in CSS
    assert "var(--miel)" in CSS
    reducido = CSS[CSS.index("@media (prefers-reduced-motion:reduce)"):]
    assert ".as-paso.entra" in reducido
    assert not re.search(r"transition:[^;}]*\b(height|max-height)\b", CSS)


# --- QA de pantalla del bloque 3 (2026-11-27) ---

def test_la_fila_muestra_nombre_direccion_y_ubicacion_sin_claves_crudas():
    assert "function detalleFila(" in JS
    for clave in ("r.direccion", "r.sede_central", "r.ubicacion", "ACCION_AS"):
        assert clave in JS, clave
    assert "Se crea" in JS and "No se toca" in JS
    assert ".as-d{" in CSS
    # nunca se vuelcan todas las claves del resumen (salia «false» o «y, x» como si fuera el nombre)
    assert "Object.keys(r)" not in JS


def test_lo_que_se_escribe_sale_de_la_accion_de_cada_fila():
    assert "c.cambian" in JS and "c.sinCambio" in JS
    assert "resumen.accion !== 'sin_tocar'" in JS


def test_con_el_panel_abierto_las_flechas_no_cambian_de_ficha():
    assert "if (S.abierta && asDe(S.abierta)) return;" in JS


def test_se_puede_salir_desde_el_ensayo_y_desde_la_carga():
    assert JS.count("id: 'x-as-cerrar'") >= 3


def test_el_cierre_avisa_de_las_que_quedaron_sin_ubicar():
    assert "sin ubicar" in JS and "k.detalle" in JS and "'Sin ubicar'" in JS


def test_planilla_sin_filas_y_actualizar_existentes_se_explican():
    assert "La planilla no trae filas." in JS
    assert "Actualizar las que ya existen" in JS
