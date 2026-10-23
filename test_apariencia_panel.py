"""La pestaña Apariencia del panel del sindicato (PLAN_TEMAS.md, bloque 3).

Solo el Super Admin elige el modelo por defecto de los afiliados y de los
operadores, la paleta y la foto de portada de cada modelo. Un Admin de
Seccional o un usuario de área reciben 403 aunque armen el POST a mano; un
valor fuera del catálogo o una foto que el sindicato no puede usar no se
guardan (y no se guarda nada a medias). La prueba de lectura de los cuatro
colores es pura y se prueba con los tres gremios de la demo.

Correr con: python -m pytest test_apariencia_panel.py -q
"""
import os

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import auth
import db
import main
import temas
from db import Area, PermisoArea, Seccional, Sindicato, UsuarioSindicato
from modulos import MODULOS
from fastapi.testclient import TestClient
from sqlmodel import Session

db.crear_tablas()

GENERAL, LOCAL, DE_AREA = "20111111112", "20555555556", "27777777772"
UOM = ("#0f2240", "#1a3d6b", "#e8b84b", "#2fa88f")
BANCARIA = ("#132a4a", "#1d4e89", "#e8b84b", "#2f8f83")
GASTRONOMICA = ("#2a0d12", "#7a1f2b", "#3d6b4a", "#c19a3e")

with db.get_session() as s:
    sind = Sindicato(nombre="Apariencia UOM", slug="apariencia-uom", color_base=UOM[0],
                     color_primario=UOM[1], color_acento=UOM[2], color_secundario=UOM[3],
                     modulos_habilitados=list(MODULOS.keys()))
    otro = Sindicato(nombre="Apariencia Otro", slug="apariencia-otro", color_base="#2a0d12")
    s.add(sind); s.add(otro); s.commit(); s.refresh(sind); s.refresh(otro)
    SID, SID_OTRO = sind.id, otro.id
    central = Seccional(sindicato_id=SID, nombre="Sede Central", ve_todas=True)
    ros = Seccional(sindicato_id=SID, nombre="Rosario")
    s.add(central); s.add(ros); s.commit(); s.refresh(central); s.refresh(ros)
    prensa = Area(sindicato_id=SID, seccional_id=central.id, nombre="Prensa")
    s.add(prensa); s.commit(); s.refresh(prensa)
    for seccion in ("noticias", "trabajadores"):
        s.add(PermisoArea(area_id=prensa.id, seccion=seccion))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=GENERAL, cuil=GENERAL, nombre="General",
                           clave_hash=auth.hashear_clave("gen"), es_super_admin=True,
                           seccional_id=central.id))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=LOCAL, cuil=LOCAL, nombre="Local",
                           clave_hash=auth.hashear_clave("loc"), es_admin_seccional=True,
                           seccional_id=ros.id))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=DE_AREA, cuil=DE_AREA, nombre="Prensa",
                           clave_hash=auth.hashear_clave("are"), area_id=prensa.id,
                           seccional_id=central.id))
    s.commit()


def _foto(tema, publicada=True, sindicatos=None):
    fid = db.crear_foto_tema(tema, {"datos": b"RIFF-foto-" + tema.encode(), "mime": "image/webp",
                                    "ancho": 1600, "alto": 1000}, descripcion=f"Foto {tema}")
    campos = {"publicada": publicada}
    if sindicatos is not None:
        campos.update(todos_los_sindicatos=False, sindicatos=sindicatos)
    db.editar_foto_tema(fid, **campos)
    return fid


LAGUNA_1 = _foto("laguna")
LAGUNA_2 = _foto("laguna")
NOTICIERO_1 = _foto("noticiero")
BORRADOR = _foto("laguna", publicada=False)
DE_OTRO = _foto("laguna", sindicatos=[SID_OTRO])


def _cliente(usuario, clave):
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": usuario, "clave": clave}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return c


def _sind():
    with Session(db.engine) as s:
        return s.get(Sindicato, SID)


def _guardar(cliente, **campos):
    datos = {"tema_afiliados": "laguna", "tema_panel": "laguna", "paleta": "colm3na"}
    datos.update(campos)
    return cliente.post("/admin/apariencia", data=datos, follow_redirects=False)


# ---------- El Super Admin guarda ----------

def test_el_super_admin_guarda_modelos_paleta_y_fotos():
    r = _guardar(_cliente(GENERAL, "gen"), tema_afiliados="noticiero", tema_panel="laguna",
                 paleta="sindicato", foto_laguna=str(LAGUNA_1), foto_noticiero=str(NOTICIERO_1))
    assert r.status_code == 303 and r.headers["location"] == "/admin?ok=apariencia#apariencia"
    s = _sind()
    assert (s.tema_afiliados, s.tema_panel, s.paleta_tema) == ("noticiero", "laguna", "sindicato")
    assert db.foto_portada_de(SID, "laguna")["id"] == LAGUNA_1
    assert db.foto_portada_de(SID, "noticiero")["id"] == NOTICIERO_1
    # El afiliado sin elección propia ve el del sindicato.
    assert db.apariencia_de(SID, rol="afiliado")["tema"] == "noticiero"


def test_automatica_saca_la_eleccion_y_vuelve_a_la_mas_nueva():
    c = _cliente(GENERAL, "gen")
    _guardar(c, foto_laguna=str(LAGUNA_1))
    r = _guardar(c, foto_laguna="auto")
    assert r.headers["location"].endswith("ok=apariencia#apariencia")
    assert "laguna" not in (_sind().fotos_portada or {})
    assert db.foto_portada_de(SID, "laguna")["id"] == max(LAGUNA_1, LAGUNA_2)


def test_sin_el_campo_de_foto_no_se_toca_la_elegida():
    """Si no hay fotos para un modelo, la pantalla no manda el grupo: eso no
    puede borrar una elección hecha antes."""
    c = _cliente(GENERAL, "gen")
    _guardar(c, foto_laguna=str(LAGUNA_1))
    _guardar(c)
    assert (_sind().fotos_portada or {}).get("laguna") == LAGUNA_1


# ---------- Lo que no se guarda ----------

def test_valores_fuera_de_catalogo_no_se_guardan_ni_a_medias():
    c = _cliente(GENERAL, "gen")
    _guardar(c, tema_afiliados="laguna", tema_panel="laguna", paleta="colm3na")
    antes = _sind()
    for malo in ({"tema_afiliados": "rosa-chicle"}, {"tema_panel": ""},
                 {"paleta": "arcoiris"}, {"tema_afiliados": "noticiero", "paleta": "x"}):
        r = _guardar(c, **malo)
        assert r.headers["location"] == "/admin?err=apariencia#apariencia", malo
    despues = _sind()
    assert (despues.tema_afiliados, despues.tema_panel, despues.paleta_tema) == \
        (antes.tema_afiliados, antes.tema_panel, antes.paleta_tema)


def test_una_foto_no_disponible_no_se_elige():
    c = _cliente(GENERAL, "gen")
    _guardar(c, foto_laguna=str(LAGUNA_2))
    for foto in (str(BORRADOR), str(DE_OTRO), str(NOTICIERO_1), "999999", "abc", "-1"):
        # Con un cambio de modelo en el mismo POST: tampoco se guarda.
        r = _guardar(c, tema_afiliados="noticiero", foto_laguna=foto)
        assert r.headers["location"] == "/admin?err=aparienciafoto#apariencia", foto
    assert (_sind().fotos_portada or {}).get("laguna") == LAGUNA_2
    assert _sind().tema_afiliados == "laguna"


# ---------- Quién puede ----------

def test_el_admin_de_seccional_y_el_usuario_de_area_reciben_403():
    for usuario, clave in ((LOCAL, "loc"), (DE_AREA, "are")):
        antes = _sind().paleta_tema
        r = _guardar(_cliente(usuario, clave), paleta="sindicato" if antes != "sindicato" else "colm3na")
        assert r.status_code == 403, (usuario, r.status_code)
        assert _sind().paleta_tema == antes


def test_sin_sesion_no_entra():
    r = TestClient(main.app).post("/admin/apariencia", data={"tema_afiliados": "laguna",
                                                             "tema_panel": "laguna",
                                                             "paleta": "colm3na"},
                                  follow_redirects=False)
    assert r.status_code == 403


def test_la_ruta_esta_clasificada_para_los_administradores():
    from permisos import SECCION_SUPER_ADMIN
    assert main.PERMISOS_RUTAS["/admin/apariencia"] == SECCION_SUPER_ADMIN


def test_la_pestana_aparece_solo_al_super_admin():
    html = _cliente(GENERAL, "gen").get("/admin").text
    assert 'data-panel="apariencia"' in html and 'id="panel-apariencia"' in html
    assert 'action="/admin/apariencia"' in html
    assert f"/foto-tema/{LAGUNA_1}" in html and f"/foto-tema/{BORRADOR}" not in html
    assert f"/foto-tema/{DE_OTRO}" not in html
    for usuario, clave in ((LOCAL, "loc"), (DE_AREA, "are")):
        otro = _cliente(usuario, clave).get("/admin").text
        assert 'data-panel="apariencia"' not in otro and 'id="panel-apariencia"' not in otro, usuario
        assert 'action="/admin/apariencia"' not in otro


def test_la_pestana_va_despues_de_areas_y_usuarios():
    html = _cliente(GENERAL, "gen").get("/admin").text
    tira = html[html.index('<nav class="nav-strip">'):html.index("</nav>")]
    assert tira.index('data-panel="administradores"') < tira.index('data-panel="apariencia"')
    assert tira.rindex("data-panel=") == tira.index('data-panel="apariencia"'), "va al final"


def test_sin_fotos_lo_dice():
    with db.get_session() as s:
        sin = Sindicato(nombre="Apariencia Sin Fotos", slug="apariencia-sin", color_base="#0f2240")
        s.add(sin); s.commit(); s.refresh(sin)
        s.add(UsuarioSindicato(sindicato_id=sin.id, usuario="20900000015", cuil="20900000015",
                               nombre="Solo", clave_hash=auth.hashear_clave("solo"),
                               es_super_admin=True))
        s.commit()
        sid_sin = sin.id
    # Las fotos "para todos" también le llegan: se las restringe al resto.
    for fid in (LAGUNA_1, LAGUNA_2, NOTICIERO_1):
        db.editar_foto_tema(fid, todos_los_sindicatos=False, sindicatos=[SID])
    try:
        html = _cliente("20900000015", "solo").get("/admin").text
        assert html.count("Todavía no hay fotos para este modelo. Las carga Colm3na.") == 2
        assert db.fotos_disponibles(sid_sin, "laguna") == []
    finally:
        for fid in (LAGUNA_1, LAGUNA_2, NOTICIERO_1):
            db.editar_foto_tema(fid, todos_los_sindicatos=True)


# ---------- Tu modelo (cualquier operador) ----------

def test_tu_modelo_esta_en_la_portada_de_cualquier_operador():
    for usuario, clave in ((GENERAL, "gen"), (LOCAL, "loc"), (DE_AREA, "are")):
        c = _cliente(usuario, clave)
        assert "Tu modelo" in c.get("/admin/inicio").text, usuario
        r = c.post("/admin/apariencia/mia", data={"tema": "noticiero"})
        assert r.status_code == 200 and r.json()["tema"] == "noticiero", usuario
        c.post("/admin/apariencia/mia", data={"tema": ""})


# ---------- Prueba de lectura (pura) ----------

def test_prueba_de_lectura_con_los_tres_gremios():
    uom = temas.prueba_de_lectura(*UOM)
    bancaria = temas.prueba_de_lectura(*BANCARIA)
    gastro = temas.prueba_de_lectura(*GASTRONOMICA)
    # El dorado de UOM y La Bancaria no sirve como texto sobre blanco.
    assert [a["clave"] for a in uom] == ["acento_sobre_claro"]
    assert [a["clave"] for a in bancaria] == ["acento_sobre_claro"]
    assert "muy claro" in uom[0]["aviso"] and uom[0]["contraste"] < 4.5
    # El verde oscuro de la Gastronómica no se lee como texto sobre su base.
    assert [a["clave"] for a in gastro] == ["acento_sobre_base"]
    assert "muy oscuro" in gastro[0]["aviso"] and gastro[0]["contraste"] < gastro[0]["minimo"]
    for a in uom + bancaria + gastro:
        assert set(a) == {"clave", "combinacion", "contraste", "minimo", "aviso"}


def test_prueba_de_lectura_que_pasa_y_casos_borde():
    assert temas.prueba_de_lectura("#0b1020", "#1d4e89", "#1f7a8c", "#2fa88f") == []
    assert temas.contraste("#ffffff", "#000000") == 21.0
    assert temas.contraste("#fff", "#ffffff") == 1.0
    claro = temas.prueba_de_lectura("#f0f0f0", "#eeeeee", "#1f7a8c", "#2fa88f")
    assert {"blanco_sobre_base", "blanco_sobre_primario"} <= {a["clave"] for a in claro}
    malo = temas.prueba_de_lectura("#0b1020", "azul", "#1f7a8c", "")
    assert {a["clave"] for a in malo} == {"color_primario", "color_apoyo"}


def test_la_pantalla_muestra_el_resultado_de_la_prueba():
    html = _cliente(GENERAL, "gen").get("/admin").text
    assert "El acento es muy claro para usarlo como texto sobre fondo claro" in html
    for c in UOM:
        assert c in html
