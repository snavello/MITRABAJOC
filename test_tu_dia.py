"""«Tu día» en la portada del afiliado (docs/chat/2026-10-24-pedido-tu-dia.md).

Sin red: los servicios de afuera (MET Norway, BCRA, Georef) se simulan.
Correr con: python -m pytest test_tu_dia.py -q
"""
import json
import os
from datetime import date
from pathlib import Path

os.environ.setdefault("PLATAFORMA_PASSWORD", "test-plataforma")

import pytest
from fastapi.testclient import TestClient

import auth
import db
import fechas
import main
import tu_dia
import tu_dia_fuentes as fuentes
from db import CuentaTrabajador, Seccional, Sindicato, Trabajador, UsuarioSindicato
from modulos import MODULOS

db.crear_tablas()

AFILIADO = "20345678901"
OTRO_AFILIADO = "27345678902"
SUPER = "20111122223"
SUPER_SIN = "20111122231"
HOY = fechas.hoy()

with db.get_session() as s:
    con = Sindicato(nombre="Tu Día Con", slug="tu-dia-con", color_base="#0f2240",
                    modulos_habilitados=list(MODULOS.keys()))
    sin = Sindicato(nombre="Tu Día Sin", slug="tu-dia-sin", color_base="#0f2240",
                    modulos_habilitados=["recibos", "noticias"])
    s.add(con); s.add(sin); s.commit(); s.refresh(con); s.refresh(sin)
    SID, SID_SIN = con.id, sin.id
    sec = Seccional(sindicato_id=SID, nombre="Río Cuarto", latitud=-33.1238, longitud=-64.349)
    s.add(sec); s.commit(); s.refresh(sec)
    s.add(CuentaTrabajador(cuil=AFILIADO, nombre="Jorge Paz", clave_hash=auth.hashear_clave("x"),
                           fecha_nacimiento=f"1980-{HOY.month:02d}-{HOY.day:02d}"))
    s.add(Trabajador(sindicato_id=SID, cuil=AFILIADO, registrado=True, seccional_id=sec.id))
    s.add(CuentaTrabajador(cuil=OTRO_AFILIADO, nombre="Ana Sol", clave_hash=auth.hashear_clave("x")))
    s.add(Trabajador(sindicato_id=SID_SIN, cuil=OTRO_AFILIADO, registrado=True))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=SUPER, cuil=SUPER, nombre="General",
                           clave_hash=auth.hashear_clave("gen"), debe_cambiar_clave=False, es_super_admin=True))
    s.add(UsuarioSindicato(sindicato_id=SID_SIN, usuario=SUPER_SIN, cuil=SUPER_SIN, nombre="General Sin",
                           clave_hash=auth.hashear_clave("gen"), debe_cambiar_clave=False, es_super_admin=True))
    s.commit()


MET = {"properties": {"timeseries": [
    {"time": "2026-10-24T15:00:00Z", "data": {"instant": {"details": {"air_temperature": 14.4, "wind_speed": 3}},
                                              "next_1_hours": {"summary": {"symbol_code": "cloudy"}}}},
    {"time": "2026-10-25T15:00:00Z", "data": {"instant": {"details": {"air_temperature": 16.2}},
                                              "next_6_hours": {"summary": {"symbol_code": "lightrain"}}}},
    {"time": "2026-10-26T15:00:00Z", "data": {"instant": {"details": {"air_temperature": 21.0}},
                                              "next_6_hours": {"summary": {"symbol_code": "clearsky_day"}}}},
]}}
BCRA = {"results": [{"fecha": "2026-10-21", "detalle": [{"codigoMoneda": "USD", "tipoCotizacion": 1526.0}]},
                    {"fecha": "2026-10-22", "detalle": [{"codigoMoneda": "USD", "tipoCotizacion": 1528.0}]},
                    {"fecha": "2026-10-24", "detalle": [{"codigoMoneda": "USD", "tipoCotizacion": 1600.0}]}]}


@pytest.fixture(autouse=True)
def _sin_red(monkeypatch):
    """Ningún test sale a la red; la caché arranca vacía."""
    def falso(url):
        if "met.no" in url:
            return MET
        if "bcra" in url:
            return {"results": [{"fecha": (HOY.replace(day=1)).isoformat(),
                                 "detalle": [{"codigoMoneda": "USD", "tipoCotizacion": 1500.0}]}]}
        raise AssertionError("pedido inesperado: " + url)
    monkeypatch.setattr(fuentes, "_pedir_json", falso)
    with db.get_session() as s:
        for f in s.exec(db.select(db.CacheExterna)).all():
            s.delete(f)
        s.commit()
    yield


def _afiliado(cuil=AFILIADO):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident=cuil))
    return c


# ------------------------------------------------------------ lo puro ----

def test_la_configuracion_descarta_lo_que_no_esta_en_el_catalogo():
    c = tu_dia.normalizar_config({"rubros": ["salud", "inventado", "salud", "mercados"],
                                  "intervalo": 7, "politicas": "si"})
    assert c == {"rubros": ["salud", "mercados"], "politicas": True, "intervalo": 6}
    assert tu_dia.config_efectiva(None) == tu_dia.POR_DEFECTO
    assert "saludo" not in tu_dia.RUBROS and "feriados" not in tu_dia.RUBROS   # decisiones de SDN


def test_rubro_apagado_no_viene_y_politicas_solo_si_se_prenden():
    efem = [{"id": "a", "mmdd": "10-17", "politica": True, "linea": "Política", "fuente": "x"},
            {"id": "b", "mmdd": "10-17", "politica": False, "linea": "Neutra", "fuente": "x"},
            {"id": "c", "mmdd": "10-17", "dudosa": True, "linea": "Dudosa", "fuente": "x"}]
    dia = date(2026, 10, 17)
    def carga(rubro):
        return efem if rubro == "efemerides" else [{"id": "s", "linea": "Salud", "fuente": "y"}]
    items = tu_dia.armar_items({"rubros": ["efemerides"], "politicas": False}, dia, cargador=carga)
    assert [i["linea"] for i in items] == ["Neutra"]
    lineas = {tu_dia.armar_items({"rubros": ["efemerides"], "politicas": True}, dia, cargador=carga)[0]["linea"]
              for _ in range(3)}
    assert lineas <= {"Política", "Neutra"}
    assert "Dudosa" not in [c["linea"] for c in tu_dia.candidatos("efemerides", efem, dia, True)]
    assert all(i["rubro"] != "salud" for i in items)


def test_el_item_del_dia_es_el_mismo_para_todos_ese_dia():
    lista = [{"id": str(n), "linea": f"Item {n}", "fuente": "x"} for n in range(30)]
    d = date(2026, 5, 29)
    assert {tu_dia.item_del_dia("curiosos", lista, d)["linea"] for _ in range(5)} == \
           {tu_dia.item_del_dia("curiosos", lista, d)["linea"]}
    otros = {tu_dia.item_del_dia("curiosos", lista, date(2026, 5, n))["linea"] for n in range(1, 29)}
    assert len(otros) > 5


def test_cada_item_es_un_articulo_con_parrafos_y_enlace():
    """Pedido de SDN (2026-11-10): la hoja de detalle trae título, 3 o 4
    párrafos y el enlace a la fuente; un ítem viejo con solo `texto` sigue
    saliendo con ese texto como único párrafo, y una url que no es https no
    viaja como enlace."""
    nuevo = [{"id": "a", "linea": "L", "titulo": "T", "texto": "Resumen", "fuente": "F",
              "parrafos": ["Uno", " Dos ", "", "Tres"], "url": "https://www.argentina.gob.ar/salud"}]
    it = tu_dia.item_del_dia("salud", nuevo, date(2026, 11, 10))
    assert it["parrafos"] == ["Uno", "Dos", "Tres"] and it["url"] == "https://www.argentina.gob.ar/salud"
    viejo = [{"id": "b", "linea": "L", "texto": "Solo texto", "fuente": "F", "url": "javascript:alert(1)"}]
    it = tu_dia.item_del_dia("curiosos", viejo, date(2026, 11, 10))
    assert it["parrafos"] == ["Solo texto"] and it["url"] == ""
    d = tu_dia.item_dolar({"fecha": "2026-11-09", "valor": 1500.0, "anterior": None})
    assert len(d["parrafos"]) >= 3 and d["url"].startswith("https://www.bcra.gob.ar")


def _banco(n):
    return [{"id": f"q{k}", "titulo": f"¿P{k}?", "opciones": ["a", "b", "c"], "correcta": k % 3,
             "explicacion": "x", "fuente": "f", "url": "https://x.y", "nivel": tu_dia.NIVELES[k % 3]}
            for k in range(n)]


def test_la_trivia_da_diez_por_dia_sin_repetir_en_la_tanda():
    banco = _banco(47)                                   # 4 tandas de 10 días, 7 sobran por tanda
    dias = [date(2026, 11, 1) + __import__("datetime").timedelta(days=k) for k in range(60)]
    kits = [tu_dia.trivia_del_dia(banco, d) for d in dias]
    assert all(len(k) == 10 for k in kits)
    # Determinista: todos ven lo mismo el mismo día.
    assert [q["id"] for q in tu_dia.trivia_del_dia(banco, dias[3])] == [q["id"] for q in kits[3]]
    # Dentro de una tanda (47 // 10 = 4 días) ninguna pregunta se repite.
    por_tanda = len(banco) // 10
    for d, k in zip(dias, kits):
        tanda = d.toordinal() // por_tanda
        vecinos = [kk for dd, kk in zip(dias, kits) if dd.toordinal() // por_tanda == tanda]
        ids = [q["id"] for kk in vecinos for q in kk]
        assert len(ids) == len(set(ids)), d
    # Dos días seguidos no son el mismo kit, y el kit va de fácil a difícil.
    assert [q["id"] for q in kits[0]] != [q["id"] for q in kits[1]]
    for k in kits:
        niveles = [tu_dia.NIVELES.index(q["nivel"]) for q in k]
        assert niveles == sorted(niveles)
    # Lo dudoso y lo que no tiene tres opciones no entra; con poco banco salen las que hay.
    chico = _banco(4) + [{"id": "mal", "opciones": ["a"], "correcta": 0}, dict(_banco(1)[0], id="dud", dudosa=True)]
    assert sorted(q["id"] for q in tu_dia.trivia_del_dia(chico, dias[0])) == ["q0", "q1", "q2", "q3"]
    assert tu_dia.trivia_del_dia([], dias[0]) == []


def test_el_comentario_alienta_hasta_cuatro_y_elogia_desde_cinco():
    textos = [tu_dia.comentario_puntaje(n) for n in range(11)]
    assert len(tu_dia.COMENTARIOS_PUNTAJE) == 11 and len({t["titulo"] for t in textos}) == 11
    for n in range(5):
        assert "mañana" in textos[n]["texto"].lower(), n          # ánimo para la próxima
        assert "!" not in textos[n]["titulo"] or n == 1
    assert textos[5]["titulo"].startswith("¡Aprobado")
    for n in range(5, 11):
        assert textos[n]["titulo"].startswith("¡"), n            # elogio creciente
    assert "Diez de diez" in textos[10]["titulo"]
    assert tu_dia.comentario_puntaje(3, 5) == tu_dia.comentario_puntaje(6)   # se escala
    assert tu_dia.comentario_puntaje(99) == textos[10] and tu_dia.comentario_puntaje(-1) == textos[0]
    it = tu_dia.item_trivia(_banco(30), date(2026, 11, 10))
    assert it["rubro"] == "juego" and it["chip"] == "Trivia" and len(it["preguntas"]) == 10
    assert len(it["comentarios"]) == 11 and it["comentarios"][7]["titulo"] == textos[7]["titulo"]
    assert "10 preguntas" in it["linea"]


def test_salud_solo_en_sus_meses():
    lista = [{"id": "a", "linea": "Antigripal", "meses": [3, 4, 5, 6], "fuente": "x"},
             {"id": "b", "linea": "Lavado de manos", "meses": [], "fuente": "x"}]
    assert [i["linea"] for i in tu_dia.candidatos("salud", lista, date(2026, 10, 1))] == ["Lavado de manos"]
    assert len(tu_dia.candidatos("salud", lista, date(2026, 4, 1))) == 2


def test_cumple_y_el_29_de_febrero():
    assert tu_dia.es_cumple("1980-05-29", date(2026, 5, 29))
    assert not tu_dia.es_cumple("1980-05-29", date(2026, 5, 30))
    assert tu_dia.es_cumple("1984-02-29", date(2026, 2, 28))
    assert not tu_dia.es_cumple("1984-02-29", date(2028, 2, 28))
    assert not tu_dia.es_cumple(None, date(2026, 5, 29)) and not tu_dia.es_cumple("basura", date(2026, 5, 29))


def test_met_norway_y_bcra_se_resumen_bien():
    c = fuentes.resumir_met(MET, date(2026, 10, 24))
    assert c["temp"] == 14 and c["icono"] == "nublado" and c["texto"] == "Nublado"
    assert c["pronostico"] == [{"dia": "mañana", "icono": "lluvia", "max": 16},
                               {"dia": "lun", "icono": "sol", "max": 21}]
    assert fuentes._icono_met("heavyrainandthunder") == "tormenta"
    assert fuentes._icono_met("partlycloudy_night") == "parcial"
    assert fuentes._icono_met("cloudy", viento=12) == "viento"
    b = fuentes.resumir_bcra(BCRA, date(2026, 10, 24))
    assert b == {"fecha": "2026-10-22", "valor": 1528.0, "anterior": 1526.0}     # el de hoy no cerró
    it = tu_dia.item_dolar(b)
    assert it["chip"] == "Dólar" and "$ 1.528,00" in it["linea"] and "▲ 0,1%" in it["linea"]
    assert it["fuente"].startswith("Banco Central")


# --------------------------------------------------------------- rutas ----

def test_sin_el_modulo_no_hay_franja_ni_datos():
    c = _afiliado(OTRO_AFILIADO)
    assert c.get("/api/tu-dia").status_code == 403
    html = c.get("/app/inicio").text
    assert 'class="pt-dia pt-dia-' not in html and "tu_dia.js" not in html
    assert 'id="overlay-tudia"' not in html and 'id="pt-cumple"' not in html


def test_con_el_modulo_la_portada_trae_las_dos_franjas_y_el_script():
    html = _afiliado().get("/app/inicio").text
    assert 'class="pt-dia pt-dia-esc cargando"' in html and 'class="pt-dia pt-dia-tel cargando"' in html
    assert "/static/tu_dia.js?v=" in html and 'id="overlay-tudia"' in html and 'id="pt-cumple"' in html
    assert "pt-hola-k" not in html


def test_la_respuesta_trae_clima_items_y_nunca_coordenadas():
    db.set_tu_dia(SID, {"rubros": ["mercados", "curiosos"], "intervalo": 10})
    r = _afiliado().get("/api/tu-dia")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["intervalo"] == 10 and d["alerta"] is None
    assert d["clima"]["localidad"] == "Río Cuarto" and "MET Norway" in d["clima"]["fuente"]
    assert [i["rubro"] for i in d["items"]][:1] == ["mercados"]
    assert d["clima"]["url"].startswith("https://")
    for i in d["items"]:
        assert i["parrafos"] and all(i["parrafos"]), i["rubro"]
    texto = json.dumps(d)
    assert "-33.1" not in texto and "-64.3" not in texto and "latitud" not in texto
    assert d["hora_ba"].startswith(HOY.isoformat())


def test_un_tercero_que_falla_no_rompe(monkeypatch):
    def cae(url):
        raise OSError("sin red")
    monkeypatch.setattr(fuentes, "_pedir_json", cae)
    db.set_tu_dia(SID, {"rubros": ["mercados", "consumidor"]})
    r = _afiliado().get("/api/tu-dia")
    assert r.status_code == 200
    d = r.json()
    assert d["clima"] is None and all(i["rubro"] != "mercados" for i in d["items"])


def test_el_cumple_se_saluda_una_sola_vez():
    with db.get_session() as s:
        cta = s.exec(db.select(CuentaTrabajador).where(CuentaTrabajador.cuil == AFILIADO)).first()
        cta.cumple_visto = ""; s.add(cta); s.commit()
    c = _afiliado()
    assert c.get("/api/tu-dia").json()["cumple"] == {"nombre": "Jorge"}
    assert c.post("/api/tu-dia/cumple-visto").json() == {"ok": True}
    assert c.get("/api/tu-dia").json()["cumple"] is None
    assert TestClient(main.app).post("/api/tu-dia/cumple-visto").status_code == 401


def test_la_ruta_trae_el_kit_de_la_trivia_entero():
    db.set_tu_dia(SID, {"rubros": ["juego"]})
    d = _afiliado().get("/api/tu-dia").json()
    (it,) = d["items"]
    assert it["rubro"] == "juego" and len(it["preguntas"]) == tu_dia.TRIVIA_PREGUNTAS
    assert all(len(q["opciones"]) == 3 and q["explicacion"] and q["url"].startswith("https://") for q in it["preguntas"])
    assert len(it["comentarios"]) == 11
    assert len({q["id"] for q in it["preguntas"]}) == 10


def test_la_configuracion_es_de_cada_sindicato():
    db.set_tu_dia(SID, {"rubros": ["juego"]})
    assert tu_dia.config_efectiva(db.tu_dia_de(SID_SIN)) == tu_dia.POR_DEFECTO
    assert db.tu_dia_de(SID)["rubros"] == ["juego"]


def test_el_super_admin_guarda_los_rubros_desde_apariencia():
    c = TestClient(main.app)
    assert c.post("/admin/login", data={"usuario": SUPER, "clave": "gen"}, follow_redirects=False).status_code == 303
    html = c.get("/admin").text
    assert 'action="/admin/apariencia/tu-dia"' in html
    r = c.post("/admin/apariencia/tu-dia", data={"rubros": ["salud", "inventado", "efemerides"],
                                                 "politicas": "1", "intervalo": "15"}, follow_redirects=False)
    assert r.status_code == 303
    assert db.tu_dia_de(SID) == {"rubros": ["salud", "efemerides"], "politicas": True, "intervalo": 15}
    assert main.PERMISOS_RUTAS["/admin/apariencia/tu-dia"] == main.SECCION_SUPER_ADMIN


def test_apagado_se_ve_en_apariencia_y_dice_quien_lo_prende():
    """Un módulo apagado que no aparece no se puede adivinar (SDN): el bloque
    va siempre, marcado Apagado, con los controles quietos."""
    c = TestClient(main.app)
    assert c.post("/admin/login", data={"usuario": SUPER_SIN, "clave": "gen"}, follow_redirects=False).status_code == 303
    html = c.get("/admin").text
    assert 'id="td-config"' in html and 'td-estado off' in html and ">Apagado<" in html
    assert "lo prende Colm3na" in html
    assert '<fieldset class="td-campos" disabled>' in html
    c2 = TestClient(main.app)
    c2.post("/admin/login", data={"usuario": SUPER, "clave": "gen"})
    html2 = c2.get("/admin").text
    assert 'td-estado on' in html2 and '<fieldset class="td-campos" >' in html2


def test_tu_dia_viene_prendido_por_defecto():
    from modulos import MODULOS_INICIALES
    assert "tu_dia" in MODULOS_INICIALES


def test_la_ficha_de_plataforma_no_apaga_un_modulo_que_no_mostro():
    """Así se perdió «Tu día» en La Bancaria: una pantalla abierta antes del
    despliegue no tenía la casilla y guardarla reemplazaba la lista entera."""
    f = main._modulos_tras_editar
    actuales = ["recibos", "noticias", "tu_dia"]
    # El formulario mostró recibos y noticias (no tu_dia) y destildó noticias.
    assert f(actuales, ["recibos"], ["recibos", "noticias"]) == ["recibos", "tu_dia"]
    # Mostró todo y destildó tu_dia: ahí sí se apaga.
    assert f(actuales, ["recibos", "noticias"], list(MODULOS)) == ["recibos", "noticias"]
    # Un formulario de antes, sin la lista de ofrecidos, no apaga nada.
    assert sorted(f(actuales, ["recibos"], [])) == ["noticias", "recibos", "tu_dia"]
    # Prender uno nuevo.
    assert f(["recibos"], ["recibos", "encuestas"], list(MODULOS)) == ["recibos", "encuestas"]


def test_la_ficha_de_plataforma_declara_cada_modulo_que_muestra():
    html = Path("templates/plataforma.html").read_text(encoding="utf-8")
    assert 'name="modulos_ofrecidos" value="{{ clave }}"' in html


# --------------------------------------------------------- el contenido ----

@pytest.mark.parametrize("rubro", [r for r in tu_dia.RUBROS if r != "mercados"])
def test_el_contenido_curado_cumple_las_reglas(rubro):
    ruta = Path("data/tu_dia") / f"{rubro}.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert datos.get("revisado") is False or datos.get("revisado") is True
    items = datos["items"]
    assert items and len({i["id"] for i in items}) == len(items)
    for i in items:
        assert i.get("fuente", "").strip(), i["id"]
        assert i.get("url", "").startswith("https://"), i["id"]       # el enlace al origen (2026-11-10)
        assert len(i.get("chip", "")) <= 14, i["id"]
        if rubro == "juego":
            # El banco de la trivia: pregunta, tres opciones, explicación con su fuente.
            assert 0 < len(i["titulo"]) <= 120 and i["titulo"].endswith("?"), i["id"]
            assert len(i["opciones"]) == 3 and i["correcta"] in (0, 1, 2), i["id"]
            assert len(i.get("explicacion", "")) >= 30 and i.get("nivel") in tu_dia.NIVELES, i["id"]
            continue
        assert 0 < len(i.get("linea", "")) <= 80, i["id"]
        # El artículo de la hoja: 3 o 4 párrafos de verdad.
        assert 3 <= len(i.get("parrafos") or []) <= 4, i["id"]
        assert all(len(p.split()) >= 20 and "\n" not in p for p in i["parrafos"]), i["id"]
        if rubro == "consumidor":
            assert i.get("norma"), i["id"]
        if rubro == "efemerides":
            mes, dia = (int(x) for x in i["mmdd"].split("-"))
            date(2024, mes, dia)
            assert i["tipo"] in ("nacional", "obrera") and isinstance(i.get("politica"), bool), i["id"]


def test_el_banco_de_la_trivia_alcanza_para_semanas_sin_repetir():
    """Con diez por día, el banco tiene que dar varias semanas de kits sin
    repetir una pregunta (una tanda = len // 10 días)."""
    datos = json.loads(Path("data/tu_dia/juego.json").read_text(encoding="utf-8"))["items"]
    vivas = [i for i in datos if not i.get("dudosa")]
    assert len(vivas) // tu_dia.TRIVIA_PREGUNTAS >= 20
    assert len({i["titulo"].strip().lower() for i in vivas}) == len(vivas)      # sin preguntas repetidas


def test_las_efemerides_cubren_el_anio():
    datos = json.loads(Path("data/tu_dia/efemerides.json").read_text(encoding="utf-8"))["items"]
    dias = {i["mmdd"] for i in datos}
    assert len(dias) == 366
