"""XSII bloque 4b, pantalla de «Conceptos desde los recibos de muestra» (estático, sin navegador).
La entrada «recibos» comparte la ficha con las asistidas de planilla; lo que cambia es el flujo."""
import re
from pathlib import Path

RAIZ = Path(__file__).parent
JS = (RAIZ / "static" / "xsii" / "xsii.js").read_text(encoding="utf-8")
CSS = (RAIZ / "static" / "xsii" / "xsii.css").read_text(encoding="utf-8")


def _bloque():
    return JS[JS.index("Lectura de recibos de muestra (bloque 4b)"):JS.index("// ------------------------------------------------------------ FICHA")]


def test_el_bloque_existe_y_va_por_la_entrada_recibos():
    b = _bloque()
    assert "d.entrada === 'recibos'" in JS and "esRb(A)" in JS
    for f in ("function paso1Rb(", "function paso2Rb(", "function paso3Rb(", "function cuerpoRb(", "function cargarRb(", "function leerRb("):
        assert f in b or f.replace("function ", "async function ") in b, f
    # la planilla sigue como estaba: sin entrada se usan los pasos de siempre
    assert "paso1As(t, A, d)" in JS and "paso2As(t, A)" in JS and "paso3As(t, A)" in JS
    assert "d.entrada === 'recibos' ? 'Leer los recibos' : 'Cargar desde la planilla'" in JS


def test_nada_de_innerhtml_ni_cdn():
    assert "innerHTML" not in JS and "insertAdjacentHTML" not in JS and "outerHTML" not in JS
    assert "document.write" not in JS
    assert not re.search(r"https?://", _bloque())
    assert "@import" not in CSS and "url(http" not in CSS


def test_de_a_un_archivo_por_pedido_y_dos_en_paralelo():
    b = _bloque()
    assert "PARALELO_RB = 2" in b
    assert "fd.append('archivo', it.archivo, it.archivo.name)" in b and b.count("fd.append('archivo'") == 1
    assert "'/ensayo'" in b and "'/carga'" in b
    assert "multiple: true" in b and "'drop'" in b and "'dragover'" in b


def test_cola_detener_y_sumar_mas():
    b = _bloque()
    for pieza in ("Detener", "Seguir leyendo", "Sumar más recibos", "A.detenido", "A.pausa", "Probar de nuevo", "progressbar", "aria-valuenow",
                  "status === 429", "x-rb-prog"):
        assert pieza in b, pieza
    assert "' de ' + num(tot)" in b  # «12 de 37»


def test_estado_de_la_ia_en_el_momento_1():
    b = _bloque()
    assert "ia.disponible === false" in b and "ia.simulada" in b and "d.ia" in b


def test_propuestas_juntadas_por_clave_y_editables():
    b = _bloque()
    for pieza in ("A.props[p.clave]", "q.veces +=", "Los recibos no coinciden en el rubro", "d.rubros", "d.categorias_sindicales", "d.genericos",
                  "Descartar", "Volver a incluir", "Corresponde a", "Categoría sindical", "p.rubro === 'descuento'", "p.cuit && gens.length",
                  "'rechazada'", "maxlength: '120'", "Dudosas", "Rechazadas", "Descartadas"):
        assert pieza in b, pieza
    # una rechazada no se puede incluir
    assert "p.estado !== 'rechazada'" in b and "rech ? null : h('button'" in b


def test_agrupadas_por_empleador_con_las_dudosas_arriba():
    b = _bloque()
    assert "function gruposRb(" in b and "p.cuit" in b and "dudosas" in b and "(b.dudosas - a.dudosas)" in b


def test_la_carga_es_json_con_los_campos_del_contrato():
    b = _bloque()
    for pieza in ("enviar(rutaAs(A.codigo) + '/carga', cuerpo)", "codigo_generico", "categoria_sindical", "cuit_empleador", "recibos_leidos", "descripcion: p.desc.trim()"):
        assert pieza in b, pieza
    assert "categoria_sindical: p.rubro === 'descuento' ? p.cat : ''" in b
    assert "A.confirmando" in b  # dos toques, como las otras
    assert "Confirmar la carga" in b and "Voy a cargar " in b


def test_el_resultado_reusa_control_y_destrabo():
    assert "paso4As(t, A)" in _bloque()
    assert "['cargados', 'Cargados']" in JS and "['recibos_leidos', 'Recibos leídos']" in JS


def test_errores_429_400_red_y_no_json():
    b = _bloque()
    assert "e.status === 429" in b and "e.status === 401" in b
    assert "detalleErrorRb" in b and "c.detalle" in b and "e.cuerpo" in b
    assert "this.cuerpo" in JS  # pedirJson conserva el cuerpo del 400
    assert "El servidor no respondió como se esperaba" in JS  # respuesta que no es JSON
    assert "ESPERA_RB_MS" in b and "AbortController" in b


def test_aviso_si_hay_propuestas_sin_cargar():
    assert "beforeunload" in JS and "sinCargarRb()" in JS
    assert "function volverGuia() { if (!puedeSalirRb(volverGuia)) return;" in JS
    assert "puedeSalirRb(function () { cerrarAsistida(null); })" in JS
    assert "AVISO_SALIR_RB" in JS and "Salir igual" in JS and "Quedarme" in JS
    assert not re.search(r"\bconfirm\(", JS)  # el aviso va en la pantalla, no en un diálogo del navegador


def test_un_cambio_de_texto_no_redibuja():
    b = _bloque()
    assert "function vivoRb(" in b and "oninput: function (e) { p.desc = e.target.value" in b


def test_nada_del_servidor_va_como_html():
    b = _bloque()
    # nombres de archivo, descripciones, avisos y errores entran por h(): nodos de texto
    assert "it.nombre" in b and "p.avisos" in b
    assert "createTextNode" in JS


def test_estilos_responsive_y_movimiento_con_tokens():
    for clase in (".rb-prog", ".rb-riel", ".rb-f", ".rb-ed", ".rb-fil", ".rb-gr", ".rb-zona", ".rb-g-t", ".rb-it"):
        assert clase in CSS, clase
    rb = CSS[CSS.index("Lectura de recibos de muestra (bloque 4b)"):]
    assert "@media (max-width:600px)" in rb and "@media (prefers-reduced-motion:reduce)" in rb
    for t in re.findall(r"transition:([^;}]*)", rb):
        assert t.strip() == "none" or ("var(--mov-" in t and "var(--ease-" in t), t
    assert not re.search(r"\b\d+ms\b", rb) and "cubic-bezier" not in rb
    assert "min-height:48px" in rb  # el botón principal grande para el dedo


def test_la_planilla_no_se_toco():
    # los textos de siempre siguen en su lugar
    for pieza in ("Ensayar (no guarda nada)", "Descargar el modelo", "Columnas de la planilla", "function ensayarAs(", "function cargarAs("):
        assert pieza in JS, pieza
