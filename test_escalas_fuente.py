"""La fuente de las grillas (escalas_fuente.py): el parseo de las notas reales de
labancaria.org y la red simulada. Las respuestas de `fixtures/escalas/` son las
reales del 2026-11-16 (búsquedas «grillas» y «actualización salarial» de la
interfaz de WordPress del sitio).

Correr con: python -m pytest test_escalas_fuente.py -q
"""
import json
from pathlib import Path

import pytest

import escalas_fuente as f

FIX = Path(__file__).parent / "fixtures" / "escalas"


def _posts():
    return (json.loads((FIX / "busqueda_grillas.json").read_text(encoding="utf-8"))
            + json.loads((FIX / "busqueda_actualizacion.json").read_text(encoding="utf-8")))


# ---------------------------------------------------------------- títulos
def test_titulo_de_grillas():
    assert f.parsear_titulo_grillas("GRILLAS ACTUALIZACIÓN SALARIAL 20-10-26") == {"fecha": "2026-10-20"}
    assert f.parsear_titulo_grillas("GRILLAS ACTUALIZACION SALARIAL 11-09-2026") == {"fecha": "2026-09-11"}
    assert f.parsear_titulo_grillas("GRILLAS ACTUALIZACIÓN SALARIAL 31-02-26") is None      # fecha imposible
    assert f.parsear_titulo_grillas("ACTUALIZACIÓN SALARIAL  OCTUBRE 2026: 2,2%") is None
    assert f.parsear_titulo_grillas("Intereses Colectivos. Programa N° 219") is None


def test_titulo_de_comunicado():
    assert f.parsear_titulo_comunicado("ACTUALIZACIÓN SALARIAL  OCTUBRE 2026: 2,2%") == {"periodo": "2026-10", "porcentaje": 2.2}
    assert f.parsear_titulo_comunicado("ACTUALIZACIÓN SALARIAL JULIO 2026: 2,1%") == {"periodo": "2026-07", "porcentaje": 2.1}
    assert f.parsear_titulo_comunicado("ACTUALIZACIÓN SALARIAL  SETIEMBRE 2026: 1,9%")["periodo"] == "2026-09"
    assert f.parsear_titulo_comunicado("GRILLAS ACTUALIZACIÓN SALARIAL 20-10-26") is None
    assert f.parsear_titulo_comunicado("ACTUALIZACIÓN SALARIAL  OCTUBRE 2026") is None       # sin porcentaje: no se adivina
    assert f.parsear_titulo_comunicado("ACTUALIZACIÓN SALARIAL  FRUTILLA 2026: 2,2%") is None


# ---------------------------------------------------------------- PDF de una nota
def test_el_pdf_sale_del_visor_embebido_de_la_nota_real():
    por_id = {p["id"]: p for p in _posts()}
    sep = f.pdfs_de_contenido(por_id[43495]["content"]["rendered"])
    assert sep == ["https://labancaria.org/wp-content/uploads/2026/10/acuerdo-salarial.pdf",
                   "https://labancaria.org/wp-content/uploads/2026/10/grillas-del-acuerdo.pdf"]
    # Dos PDF: elige el que dice «grilla».
    assert f.elegir_pdf_grillas(sep) == ("https://labancaria.org/wp-content/uploads/2026/10/grillas-del-acuerdo.pdf", "")
    ago = f.pdfs_de_contenido(por_id[43102]["content"]["rendered"])
    assert f.elegir_pdf_grillas(ago) == ("https://labancaria.org/wp-content/uploads/2026/09/GRILLAS-AGOSTO-2026.pdf", "")


def test_elegir_pdf_no_adivina():
    assert f.elegir_pdf_grillas([])[0] is None
    assert f.elegir_pdf_grillas(["https://labancaria.org/a.pdf", "https://labancaria.org/b.pdf"])[0] is None
    assert f.elegir_pdf_grillas(["https://labancaria.org/grillas-1.pdf", "https://labancaria.org/grillas-2.pdf"])[0] is None
    assert f.elegir_pdf_grillas(["https://labancaria.org/solo.pdf"]) == ("https://labancaria.org/solo.pdf", "")


def test_un_enlace_directo_al_pdf_tambien_se_encuentra():
    assert f.pdfs_de_contenido('<p><a href="https://labancaria.org/wp-content/uploads/x/GRILLAS.pdf">bajar</a></p>') == \
        ["https://labancaria.org/wp-content/uploads/x/GRILLAS.pdf"]


# ---------------------------------------------------------------- comunicados reales
@pytest.mark.parametrize("post_id, inicial, roe, minimo", [
    (43098, 2505061.24, 72413.50, 2233175.44),        # agosto
    (43475, 2552560.34, 73786.55, 2275519.25),        # septiembre: HTML partido en un <span> por dígito
    (43798, 2608320.16, 75398.39, None),              # octubre: el mínimo del Día del Bancario viene con otras palabras
    (42849, 2463757.68, 71219.54, 2196354.74),        # julio
])
def test_el_comunicado_real_da_el_inicial_y_el_roe_al_centavo(post_id, inicial, roe, minimo):
    p = next(p for p in _posts() if p["id"] == post_id)
    datos, motivo = f.parsear_comunicado(p["content"]["rendered"])
    assert motivo == "" and datos is not None
    assert datos["inicial"] == inicial and datos["roe"] == roe
    assert datos["dia_bancario_minimo"] == minimo
    assert round(datos["inicial"] + datos["roe"], 2) == datos["total"]


def test_un_comunicado_que_no_cierra_no_devuelve_nada():
    """Si un dígito se perdió al partir el HTML, la cuenta no cierra: no se
    devuelve un dato a medias."""
    malo = "<p>Salario Inicial + Participación Ganancias (ROE): $ 2.552.560,34 + $ 73.786,55 = $ 2.626.346,98</p>"
    datos, motivo = f.parsear_comunicado(malo)
    assert datos is None and "no cierra" in motivo


@pytest.mark.parametrize("html", ["", "<p>Nada de números</p>", "<p>Salario Inicial + ROE: dos mil</p>",
                                  "<p>ROE: $ 2.552.560,34 + $ 73.786,55</p>"])
def test_un_formato_que_cambio_es_no_encontrado_con_motivo(html):
    datos, motivo = f.parsear_comunicado(html)
    assert datos is None and motivo


# ---------------------------------------------------------------- clasificar y aparear
def test_clasifica_las_notas_reales_y_ignora_el_resto():
    c = f.clasificar_posts(_posts())
    assert [g["fecha"] for g in c["grillas"]] == ["2026-06-16", "2026-07-16", "2026-08-18", "2026-09-11", "2026-10-20"]
    assert [x["periodo"] for x in c["comunicados"]] == ["2026-07", "2026-08", "2026-09", "2026-10"]
    assert all(g["pdf_url"].startswith("https://labancaria.org/wp-content/uploads/") for g in c["grillas"])
    # «Intereses Colectivos» no es ni una cosa ni la otra.
    assert not any("Intereses" in x["titulo"] for x in c["grillas"] + c["comunicados"])


def test_el_periodo_es_el_mes_del_comunicado_no_el_de_la_fecha_de_la_nota():
    c = f.clasificar_posts(_posts())
    pares = {p["grilla"]["fecha"]: p for p in f.aparear(c["grillas"], c["comunicados"])}
    assert pares["2026-09-11"]["periodo"] == "2026-08"       # la nota del 11-09-26 es agosto
    assert pares["2026-10-20"]["periodo"] == "2026-09"       # la del 20-10-26 es septiembre
    assert pares["2026-08-18"]["periodo"] == "2026-07"
    assert pares["2026-10-20"]["comunicado"]["inicial"] == 2552560.34


def test_sin_comunicado_publicado_antes_no_hay_par():
    c = f.clasificar_posts(_posts())
    pares = {p["grilla"]["fecha"]: p for p in f.aparear(c["grillas"], c["comunicados"])}
    # El de junio no está entre los resultados de la búsqueda: no se adivina.
    assert pares["2026-06-16"]["periodo"] is None and pares["2026-06-16"]["motivo"]


def test_dos_notas_de_grillas_para_el_mismo_comunicado_no_se_adivinan():
    c = f.clasificar_posts(_posts())
    g = next(g for g in c["grillas"] if g["fecha"] == "2026-10-20")
    otra = {**g, "post_id": 999, "publicada": "2026-10-21"}
    pares = f.aparear([g, otra], c["comunicados"])
    assert all(p["periodo"] is None for p in pares)


def test_mes_siguiente_y_nombre():
    assert f.mes_siguiente("2026-08") == "2026-09" and f.mes_siguiente("2026-12") == "2027-01"
    assert f.nombre_del_periodo("2026-09") == "Septiembre 2026"


# ---------------------------------------------------------------- red simulada
def test_la_red_nunca_levanta_hacia_el_hilo():
    def cae(url):
        raise f.ErrorFuente("TimeoutError: sin respuesta")
    r = f.listar_novedades(get_json=cae)
    assert r["ok"] is False and "labancaria.org" in r["motivo"]


def test_respuesta_vacia_o_formato_cambiado_no_es_sin_novedades():
    assert f.listar_novedades(get_json=lambda u: [])["ok"] is False
    assert f.listar_novedades(get_json=lambda u: {"code": "rest_no_route"})["ok"] is False
    # Notas que existen pero ninguna con el título esperado: el sitio cambió.
    raro = [{"id": 1, "date": "2026-11-01T10:00:00", "link": "x", "title": {"rendered": "Otra cosa"}, "content": {"rendered": ""}}]
    r = f.listar_novedades(get_json=lambda u: raro)
    assert r["ok"] is False and "cambió" in r["motivo"]


def test_listar_novedades_con_las_respuestas_reales():
    def get(url):
        return json.loads((FIX / ("busqueda_grillas.json" if "search=grillas" in url else "busqueda_actualizacion.json")).read_text(encoding="utf-8"))
    r = f.listar_novedades(get_json=get)
    assert r["ok"] is True and len(r["pares"]) == 5
    nuevo = [p for p in r["pares"] if p["periodo"] == "2026-09"]
    assert len(nuevo) == 1 and nuevo[0]["grilla"]["pdf_url"].endswith("grillas-del-acuerdo.pdf")


def test_el_pdf_solo_se_baja_del_sitio_del_sindicato():
    for url in ("http://labancaria.org/x.pdf", "https://otro.org/x.pdf", "https://labancaria.org/x.html",
                "https://labancaria.org.evil.com/x.pdf", "file:///etc/passwd", ""):
        with pytest.raises(f.ErrorFuente):
            f.descargar_pdf(url)


def test_un_archivo_que_no_es_pdf_se_rechaza(monkeypatch):
    monkeypatch.setattr(f, "_pedir", lambda url, tope, timeout=0: b"<html>no soy un pdf</html>")
    with pytest.raises(f.ErrorFuente):
        f.descargar_pdf("https://labancaria.org/wp-content/uploads/x/grillas.pdf")
    monkeypatch.setattr(f, "_pedir", lambda url, tope, timeout=0: b"%PDF-1.7 ...")
    assert f.descargar_pdf("https://labancaria.org/wp-content/uploads/x/grillas.pdf").startswith(b"%PDF")
