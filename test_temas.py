"""Dos modelos de diseño que se cambian a gusto (PLAN_TEMAS.md, bloque 1).

La persona guarda su modelo en la CUENTA; si no eligió, vale el de su
sindicato; si el valor guardado no es uno conocido, el por defecto. La paleta
la decide el sindicato, nunca la persona.

Correr con: python -m pytest test_temas.py -q
"""
import os

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import auth
import db
import main
import temas
from db import CuentaPanel, CuentaTrabajador, Sindicato, Trabajador, UsuarioSindicato
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()

AFILIADO = "20314567898"
OPERADOR = "27389123450"

with db.get_session() as s:
    sind = Sindicato(nombre="Temas UOM", slug="temas-uom", color_base="#0f2240")
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(CuentaTrabajador(cuil=AFILIADO, nombre="Martín Sosa", clave_hash=auth.hashear_clave("x"),
                           provincia="Buenos Aires", localidad="Avellaneda"))
    s.add(Trabajador(sindicato_id=SID, cuil=AFILIADO, registrado=True))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=OPERADOR, nombre="Laura Méndez",
                           clave_hash=auth.hashear_clave("clave-op"), es_super_admin=True))
    s.commit()


def _afiliado():
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident=AFILIADO))
    return c


def _operador():
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": OPERADOR, "clave": "clave-op"}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return c


def test_catalogo_y_resolucion_puros():
    assert temas.TEMA_DEFECTO == "laguna" and set(temas.TEMAS) == {"laguna", "noticiero"}
    assert temas.TEMAS["laguna"]["num"] == 162 and temas.TEMAS["noticiero"]["num"] == 147
    assert temas.resolver_tema("noticiero", "laguna") == "noticiero"      # manda la persona
    assert temas.resolver_tema("", "noticiero") == "noticiero"            # si no eligió, el sindicato
    assert temas.resolver_tema("", None) == "laguna"                      # y si no, el por defecto
    assert temas.resolver_tema("rosa-chicle", "otro") == "laguna"         # basura en la base: el por defecto
    assert temas.resolver_tema(" Noticiero ", None) == "noticiero"
    assert temas.resolver_paleta("sindicato") == "sindicato"
    assert temas.resolver_paleta("arcoiris") == "colm3na"


def test_el_sindicato_nace_en_laguna_con_colores_de_colm3na():
    ap = db.apariencia_de(SID, AFILIADO)
    assert ap == {"tema": "laguna", "paleta": "colm3na", "elegido": "", "defecto": "laguna"}


def test_el_afiliado_guarda_su_modelo_en_la_cuenta():
    c = _afiliado()
    r = c.post("/api/apariencia", data={"tema": "noticiero"})
    assert r.status_code == 200 and r.json() == {"ok": True, "tema": "noticiero"}
    with Session(db.engine) as s:
        assert s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == AFILIADO)).one().tema == "noticiero"
    # se ve en cualquier aparato: un cliente nuevo, misma cuenta
    html = _afiliado().get("/app/inicio").text
    assert 'data-tema="noticiero"' in html and 'data-paleta="colm3na"' in html


def test_un_modelo_que_no_existe_no_se_guarda():
    c = _afiliado()
    assert c.post("/api/apariencia", data={"tema": "rosa-chicle"}).status_code == 400
    with Session(db.engine) as s:
        assert s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == AFILIADO)).one().tema == "noticiero"


def test_vacio_vuelve_al_del_sindicato():
    assert db.set_apariencia_sindicato(SID, tema_afiliados="noticiero", paleta="sindicato")
    c = _afiliado()
    assert c.post("/api/apariencia", data={"tema": ""}).json() == {"ok": True, "tema": ""}
    ap = db.apariencia_de(SID, AFILIADO)
    assert ap["tema"] == "noticiero" and ap["elegido"] == "" and ap["paleta"] == "sindicato"
    assert db.set_apariencia_sindicato(SID, tema_afiliados="laguna", paleta="colm3na")


def test_el_sindicato_no_guarda_valores_fuera_del_catalogo():
    assert not db.set_apariencia_sindicato(SID, tema_panel="rosa-chicle")
    assert not db.set_apariencia_sindicato(SID, paleta="arcoiris")
    with Session(db.engine) as s:
        sind = s.get(Sindicato, SID)
        assert (sind.tema_panel, sind.paleta_tema) == ("laguna", "colm3na")


def test_sin_sesion_no_se_guarda_nada():
    assert TestClient(main.app).post("/api/apariencia", data={"tema": "noticiero"}).status_code == 403
    assert TestClient(main.app).post("/admin/apariencia/mia", data={"tema": "noticiero"}).status_code == 403


def test_el_operador_elige_el_suyo_y_es_aparte_del_afiliado():
    c = _operador()
    r = c.post("/admin/apariencia/mia", data={"tema": "noticiero"})
    assert r.status_code == 200 and r.json()["tema"] == "noticiero"
    with Session(db.engine) as s:
        assert s.exec(select(CuentaPanel).where(CuentaPanel.cuil == OPERADOR)).one().tema == "noticiero"
    assert 'data-tema="noticiero"' in c.get("/admin/inicio").text
    assert 'data-tema="noticiero"' in c.get("/admin").text
    # la elección del panel no toca la del afiliado ni el default del sindicato
    assert db.apariencia_de(SID, AFILIADO)["tema"] == "laguna"
    assert c.post("/admin/apariencia/mia", data={"tema": "rosa-chicle"}).status_code == 400
