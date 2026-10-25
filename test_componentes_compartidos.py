"""Bloque 1 del plan de mejoras de diseño (auditoría del 2026-10-25): las
piezas que comparten todas las pantallas. Cada test nombra el hallazgo que
cierra, para que nadie lo deshaga sin saberlo."""
from pathlib import Path

LOGINS = ["trabajador_login", "empresa_login", "_clave_base", "admin_login", "plataforma_login", "admin_elegir"]


def leer(ruta):
    return Path(ruta).read_text(encoding="utf-8")


def test_inicio_y_salir_van_al_pie_del_riel_del_panel():
    """G4-30: en escritorio la pastilla tapaba la columna de acciones."""
    for modelo in ("laguna", "noticiero"):
        css = leer(f"static/temas/{modelo}-panel.css")
        assert "--flota-quieta: 1" in css and "right: auto" in css
    assert "--flota-quieta" in leer("static/flota.js")


def test_salir_de_la_portada_del_afiliado_va_quieto_en_el_telefono():
    """G2-04: flotaba encima de las novedades."""
    assert ".pt-sesion { position: static;" in leer("templates/portada.html")


def test_las_tablas_del_telefono_avisan_que_siguen():
    """G4-31: el veredicto y las acciones quedaban afuera sin señal."""
    for modelo in ("laguna", "noticiero"):
        assert "G4-31" in leer(f"static/temas/{modelo}-panel.css")


def test_las_explicaciones_tienen_largo_de_linea():
    """G4-34: corrían a 130-170 caracteres por línea."""
    for modelo in ("laguna", "noticiero"):
        assert "max-width: 72ch" in leer(f"static/temas/{modelo}-panel.css")


def test_un_solo_campo_en_laguna():
    """G4-33: rellenos grises sin borde al lado de campos blancos con borde."""
    css = leer("static/temas/laguna-panel.css")
    assert "background-color: var(--lg-claro);\n  color: var(--lg-tinta); font-family: inherit;" not in css


def test_acerca_de_se_lee():
    """G4-38: estaba a 10,5 px y 45% de opacidad."""
    html = leer("templates/admin.html")
    assert "opacity:.45; font-size:10.5px" not in html


def test_el_segundo_nivel_de_pestanas_no_es_una_pastilla():
    """G6-05: Empresas/Notificaciones/Trámites y Ver/Crear eran idénticas."""
    for modelo in ("laguna", "noticiero"):
        assert ".subtabs:has(> .emptram-subtab)" in leer(f"static/temas/{modelo}-panel.css")


def test_los_ingresos_scrollean_y_esconden_la_banda_decorativa():
    """G1-12: overflow:hidden en el body impedía llegar al final del registro.
    G1-16: la banda tipo pasaporte se leía en voz alta. G1-15: 44 px."""
    for nombre in LOGINS:
        html = leer(f"templates/{nombre}.html")
        assert "position:relative; overflow:hidden;" not in html, nombre
        assert '<div class="mrz" aria-hidden="true">' in html, nombre
        if ".tab {" in html:
            assert "min-height:44px" in html, nombre


def test_olvide_mi_clave_en_su_propia_linea():
    """G1-15: iba pegado a una frase de 12 px y se partía en dos renglones."""
    for nombre in ("trabajador_login", "empresa_login"):
        html = leer(f"templates/{nombre}.html")
        assert 'class="olvide"' in html and "#form-registro.activo) .pie" in html


def test_recuperar_muestra_los_pasos_y_la_salida_sin_mail():
    """G1-03 y G1-04."""
    html = leer("templates/recuperar_clave.html")
    assert 'id="pasos"' in html and "clave temporal" in html


def test_el_panel_pide_tu_cuil():
    """G1-06: «CUIT / CUIL» hacía pensar en el CUIT del sindicato."""
    assert "Tu CUIL" in leer("templates/admin_login.html")
