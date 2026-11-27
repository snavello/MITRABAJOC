"""XSII, bloque 4: mapeo de columnas, opciones con valor, resultados grandes, comparación y espera
(estático, sin navegador). Todo genérico: ningún texto de una tarea puntual en el JS de la asistida."""
import re
from pathlib import Path

RAIZ = Path(__file__).parent
JS = (RAIZ / "static" / "xsii" / "xsii.js").read_text(encoding="utf-8")
CSS = (RAIZ / "static" / "xsii" / "xsii.css").read_text(encoding="utf-8")


def _bloque():
    return JS[JS.index("Carga asistida (bloque 3)"):JS.index("// ------------------------------------------------------------ FICHA")]


def test_nada_de_una_tarea_puntual_en_el_bloque():
    b = _bloque().lower()
    for palabra in ("seccional", "sede central", "est-01", "est-02", "pad-0", "padrón", "padron", "afiliado", "cuil", "legajo"):
        assert palabra not in b, palabra


def test_mapeo_de_columnas():
    b = _bloque()
    for pieza in ("Columnas de la planilla", "Volver a ensayar con estas columnas", "No usar", "(obligatorio)",
                  "mapeo.faltan", "e.mapeo", "d.campos", "o.mapeo", "'data-i'"):
        assert pieza in b or pieza.replace("mapeo.faltan", "m.faltan") in b, pieza
    assert "function bloqueMapa(" in b and "function refrescarMapa(" in b and "function diffsMapa(" in b
    assert "o.disabled" in b  # un campo ya elegido en otra columna se deshabilita en las demás
    assert "Falta una columna para" in b


def test_solo_viaja_lo_que_la_persona_cambio():
    b = _bloque()
    assert "mapaBase" in b and "diffsMapa(A)" in b and "opciones.mapeo" not in b
    assert "o.mapeo = m" in b


def test_opciones_con_valor_numerico():
    b = _bloque()
    assert "o.tipo === 'numero'" in b and "type: 'number'" in b
    assert "o.minimo" in b and "o.maximo" in b
    assert "v === null" in b  # vacío = no se manda


def test_resultados_grandes():
    b = _bloque()
    for pieza in ("e.motivos", "m.cantidad", "filas_truncadas", "los totales de arriba cuentan todas", "A.motivo", "toLocaleString"):
        assert pieza in b + JS, pieza
    assert "max-height" in CSS and "position:sticky" in CSS.replace(" ", "")


def test_comparacion_en_el_momento_4():
    b = _bloque()
    assert "k.comparacion" in b and "Declarado" in b and "En el sistema" in b and "Diferencia" in b
    assert ".as-comp.cero" in CSS and ".as-comp.dif" in CSS and "var(--ok)" in CSS and "var(--miel)" in CSS


def test_espera_con_tiempo_y_reintento():
    b = _bloque()
    for pieza in ("function esperaAs(", "x-as-reloj", "setInterval", "AbortController", "Reintentar", "if (!A || A.trabajando) return;"):
        assert pieza in b, pieza
    assert "AbortError" in JS


def test_textos_del_servidor_como_texto_y_estilos_seguros():
    assert "innerHTML" not in JS
    assert not re.search(r"transition:[^;}]*\b(height|max-height)\b", CSS)
    reducido = CSS[CSS.index("@media (prefers-reduced-motion:reduce)"):]
    assert ".as-mo" in reducido
    assert ".as-mc.cabe{display:none}" in CSS  # móvil: la tabla de columnas pasa a tarjetas


def test_texto_pegado_viaja_como_archivo():
    # Starlette limita a 1 MB un campo de texto de un multipart: lo pegado va como Blob.
    assert "new Blob([base.texto]" in JS
    assert "fd.append('texto'" not in JS


def test_avisa_en_el_paso_1_si_la_carga_esta_frenada():
    assert "x-as-previas" in JS
    assert "la carga todavía no se puede" in JS


def test_dejar_afuera_todas_no_miente_con_el_listado_recortado():
    assert "dudosasSinListar" in JS
    assert "x-as-sinlistar" in JS


def test_la_diferencia_con_lo_declarado_se_dice_en_que_sigue():
    assert "no coincide con el total declarado" in JS
