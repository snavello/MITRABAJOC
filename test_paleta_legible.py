"""La paleta del sindicato corregida para que se lea (PLAN_TEMAS.md, bloque 7).

`temas.paleta_legible` calcula, una sola vez y en el servidor, los colores con
los que los modelos escriben sobre (o con) la marca del gremio; las cuatro
plantillas los vuelcan como variables y las hojas los usan en vez de inventar
su propia corrección. La prueba de lectura muestra el original y el corregido.

Correr con: python -m pytest test_paleta_legible.py -q
"""
import random
import re
from pathlib import Path

import temas

DEMO = {
    "UOM": ("#0f2240", "#1a3d6b", "#e8b84b", "#2fa88f"),
    "Gastronómica": ("#2a0d12", "#7a1f2b", "#3d6b4a", "#c19a3e"),
    "La Bancaria": ("#132a4a", "#1d4e89", "#e8b84b", "#2f8f83"),
}


def _base_oscura(rnd):
    """Una base que pasaría el alta del sindicato (main._es_oscuro)."""
    while True:
        r, g, b = (rnd.randrange(256) for _ in range(3))
        if (r * 299 + g * 587 + b * 114) / 1000 < 140:
            return f"#{r:02x}{g:02x}{b:02x}"


def _cualquiera(rnd):
    return "#" + "".join(f"{rnd.randrange(256):02x}" for _ in range(3))


def _cumple(base, primario, acento, apoyo):
    L = temas.paleta_legible(base, primario, acento, apoyo)
    c = temas.contraste
    assert c(L["tinta_acento"], acento) >= 4.5, (base, acento, L)
    assert c(L["acento_oscuro"], "#ffffff") >= 4.5, (acento, L)
    assert c(L["primario_relleno"], temas._PAPEL) >= 4.5, (primario, L)
    assert c(L["base_relleno"], "#ffffff") >= 4.5, (base, L)
    assert c(L["base_tinta"], temas._PAPEL) >= temas.CONTRASTE_TINTA, (base, L)
    # Aclarar el acento sobre la base llega hasta el blanco; con una base
    # apenas oscura, el blanco es lo mejor que se puede.
    assert c(L["acento_txt"], base) >= min(4.5, c("#ffffff", base)) - 0.01, (base, acento, L)
    return L


def test_cualquier_paleta_valida_queda_legible():
    rnd = random.Random(147162)
    for _ in range(3000):
        _cumple(_base_oscura(rnd), _cualquiera(rnd), _cualquiera(rnd), _cualquiera(rnd))


def test_los_gremios_de_la_demo():
    for colores in DEMO.values():
        _cumple(*colores)


def test_lo_que_ya_se_lee_no_se_toca():
    L = temas.paleta_legible(*DEMO["UOM"])
    assert L["tinta_acento"] == "#0f2240"          # la base sobre el ámbar se lee
    assert L["acento_txt"] == "#e8b84b"            # el ámbar sobre la base, también
    assert L["primario_relleno"] == "#1a3d6b" and L["base_relleno"] == "#0f2240"
    L = temas.paleta_legible(*DEMO["Gastronómica"])
    assert L["tinta_acento"] == "#ffffff"          # verde oscuro: texto blanco
    assert L["acento_txt"] != "#3d6b4a"            # y aclarado como texto sobre la base


def test_conserva_el_tono():
    """Corregir es correr hacia el blanco o el negro, no cambiar de color."""
    import colorsys
    def tono(h):
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
        return colorsys.rgb_to_hsv(r, g, b)[0]
    L = temas.paleta_legible("#3b3b48", "#7fc8f8", "#ffd400", "#ffb3c7")
    assert abs(tono(L["primario_relleno"]) - tono("#7fc8f8")) < 0.02
    assert abs(tono(L["acento_oscuro"]) - tono("#ffd400")) < 0.02


def test_colores_ilegibles_no_rompen():
    L = temas.paleta_legible("verde", "", None, "#zzz")
    assert all(re.fullmatch(r"#[0-9a-f]{6}", v) for v in L.values())


def test_la_prueba_de_lectura_muestra_el_corregido():
    avisos = temas.prueba_de_lectura("#3b3b48", "#7fc8f8", "#ffd400", "#ffb3c7")
    por_clave = {a["clave"]: a for a in avisos}
    a = por_clave["blanco_sobre_primario"]
    assert a["original"] == "#7fc8f8" and temas.contraste(a["corregido"], temas._PAPEL) >= 4.5
    a = por_clave["acento_sobre_claro"]
    assert a["original"] == "#ffd400" and temas.contraste(a["corregido"], "#ffffff") >= 4.5
    for a in avisos:
        assert set(a) >= {"original", "corregido"}


def test_una_sola_implementacion():
    """Las plantillas vuelcan paleta_legible; nadie calcula luminancias en
    Jinja ni corrige con oklch(from ...) en las hojas."""
    for nombre in ("portada", "trabajador", "admin_portada", "admin"):
        html = Path(f"templates/{nombre}.html").read_text(encoding="utf-8")
        assert 'import variables_legibles' in html and "variables_legibles(" in html, nombre
        assert "_ac_lum" not in html and "set _lum" not in html, nombre
    for hoja in Path("static/temas").glob("*.css"):
        assert "oklch(from" not in hoja.read_text(encoding="utf-8"), hoja.name


def test_el_parcial_vuelca_las_variables():
    import main
    t = main.templates.env.from_string(
        '{% from "_paleta_legible.html" import variables_legibles %}'
        '{{ variables_legibles("marca", "#3b3b48", "#7fc8f8", "#ffd400", "#ffb3c7") }}')
    css = t.render()
    L = temas.paleta_legible("#3b3b48", "#7fc8f8", "#ffd400", "#ffb3c7")
    for clave, var in (("tinta_acento", "tinta-acento"), ("acento_txt", "acento-txt"),
                       ("acento_oscuro", "acento-oscuro"), ("primario_relleno", "primario-relleno"),
                       ("base_relleno", "base-relleno"), ("base_tinta", "base-tinta")):
        assert f"--marca-{var}: {L[clave]};" in css


def test_las_hojas_usan_los_corregidos_con_la_paleta_del_sindicato():
    """Con la paleta del sindicato, el primario (Laguna: botones con texto
    blanco) y la base (Noticiero: la tinta y sus mezclas) salen corregidos."""
    for hoja in Path("static/temas").glob("*.css"):
        if "-plataforma" in hoja.name:
            # Plataforma no tiene sindicato: va siempre con la paleta de Colm3na
            # (db.apariencia_plataforma), así que sus hojas no traen ese bloque.
            continue
        css = hoja.read_text(encoding="utf-8")
        bloques = re.findall(r'\[data-paleta="sindicato"\] \{(.*?)\n\}', css, re.S)
        assert bloques, hoja.name
        cuerpo = "".join(bloques)
        assert re.search(r"var\(--(marca|gremio)-primario\)(?!\))", cuerpo.replace(
            "-primario-relleno, var(--marca-primario))", "").replace(
            "-primario-relleno, var(--gremio-primario))", "")) is None, hoja.name
        if hoja.name.startswith("noticiero"):
            assert "-base-tinta" in cuerpo, hoja.name


def test_con_la_paleta_del_sindicato_la_marca_manda_en_encabezado_y_riel():
    """SDN, 2026-10-23: con «Colores del sindicato» el encabezado y el riel
    del panel van en el color base del gremio y la sección activa en su
    acento; en la app del afiliado, el encabezado."""
    for modelo in ("laguna", "noticiero"):
        panel = Path(f"static/temas/{modelo}-panel.css").read_text(encoding="utf-8")
        pre = f'html[data-tema="{modelo}"][data-paleta="sindicato"]'
        assert f"{pre} .marca-barra" in panel and f"{pre} .nav-strip" in panel and f"{pre} .tab-btn.activa" in panel
        assert "var(--marca-base-relleno" in panel and "var(--marca-tinta-acento" in panel
        app = Path(f"static/temas/{modelo}-app.css").read_text(encoding="utf-8")
        assert f"{pre} .marca-barra" in app and "var(--gremio-base-relleno" in app
