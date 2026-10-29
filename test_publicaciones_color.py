"""Las fotos de Noticias y Beneficios en la portada, en gris o en color
(2026-10-29, el mismo esquema que la foto de portada de los modelos).

De cada imagen se guarda además la versión normalizada (gris, niveles y
brillo parejos): al subirla y, en las de antes, la primera vez que se pide.
El Super Admin elige en Apariencia, por modelo, cuánto color muestran la
nota de tapa y el carrusel; la portada funde la de color encima de la
normalizada con esa opacidad.

Correr con: python -m pytest test_publicaciones_color.py -q
"""
import os
from io import BytesIO

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

from PIL import Image, ImageChops
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import auth
import db
import fotos_tema
import main
from db import Beneficio, Noticia, Sindicato, Trabajador, UsuarioSindicato
from modulos import MODULOS_INICIALES

db.crear_tablas()

ADMIN, CUIL = "20111111120", "20111111112"
with db.get_session() as s:
    sind = Sindicato(nombre="Pub Color", slug="pub-color", color_base="#0f2240",
                     modulos_habilitados=list(MODULOS_INICIALES))
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=ADMIN, cuil=ADMIN, nombre="Admin",
                           clave_hash=auth.hashear_clave("clave"), debe_cambiar_clave=False, es_super_admin=True))
    s.add(Trabajador(sindicato_id=SID, cuil=CUIL, activo=True, registrado=True))
    db.guardar_datos_personales(s, CUIL, nombre="Ana")
    s.commit()

admin = TestClient(main.app)
admin.post("/admin/login", data={"usuario": ADMIN, "clave": "clave"})
trab = TestClient(main.app)
trab.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident=CUIL))


def _png(color=(30, 120, 220), tamano=(400, 260)) -> bytes:
    degrade = Image.linear_gradient("L").resize(tamano).convert("RGB")
    im = Image.blend(Image.new("RGB", tamano, color), degrade, 0.3)
    salida = BytesIO()
    im.save(salida, "PNG")
    return salida.getvalue()


def _es_gris(datos: bytes) -> bool:
    r, g, b = Image.open(BytesIO(datos)).convert("RGB").split()
    return ImageChops.difference(r, b).getextrema()[1] <= 6


def _apariencia(**campos):
    datos = {"tema_afiliados": "laguna", "tema_panel": "laguna", "paleta": "colm3na"}
    datos.update(campos)
    return admin.post("/admin/apariencia", data=datos, follow_redirects=False)


def test_normalizar_imagen_no_exige_tamano_minimo_y_sale_gris():
    f = fotos_tema.normalizar_imagen(_png(tamano=(300, 200)))
    assert f["mime"] == "image/webp" and (f["ancho"], f["alto"]) == (300, 200)
    assert _es_gris(f["datos"])
    try:
        fotos_tema.normalizar_imagen(b"no soy una imagen")
        assert False, "tenía que fallar"
    except fotos_tema.FotoInvalida:
        pass
    assert db.normalizada_o_none(b"no soy una imagen") is None and db.normalizada_o_none(None) is None


def test_al_subir_se_guarda_la_normalizada_y_se_sirve_aparte():
    r = admin.post("/admin/noticia", data={"titulo": "Con foto", "bajada": "", "texto_completo": "",
                                           "fecha_desde": "2020-01-01", "fecha_hasta": "2030-12-31"},
                   files={"imagen1": ("f.png", _png(), "image/png")}, follow_redirects=False)
    assert r.status_code == 303
    r = admin.post("/admin/beneficio", data={"rubro": "Turismo", "descripcion": "", "link": "",
                                             "fecha_desde": "2020-01-01", "fecha_hasta": "2030-12-31"},
                   files={"imagen": ("b.png", _png((200, 40, 40)), "image/png")}, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        n = s.exec(select(Noticia).where(Noticia.sindicato_id == SID, Noticia.titulo == "Con foto")).first()
        b = s.exec(select(Beneficio).where(Beneficio.sindicato_id == SID, Beneficio.rubro == "Turismo")).first()
        assert n.imagen1_norm and _es_gris(n.imagen1_norm) and n.imagen2_norm is None
        assert b.imagen_norm and _es_gris(b.imagen_norm)
        nid, bid = n.id, b.id
    anon = TestClient(main.app)
    r = anon.get(f"/noticia-imagen/{nid}/1/normalizada")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp" and _es_gris(r.content)
    assert not _es_gris(anon.get(f"/noticia-imagen/{nid}/1").content)     # la original sigue en color
    r = anon.get(f"/beneficio-imagen/{bid}/normalizada")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp" and _es_gris(r.content)
    assert anon.get(f"/noticia-imagen/{nid}/2/normalizada").status_code == 404
    assert anon.get(f"/noticia-imagen/{nid}/3/normalizada").status_code == 404
    assert anon.get("/beneficio-imagen/999999/normalizada").status_code == 404


def test_una_imagen_de_antes_se_normaliza_la_primera_vez_que_se_pide():
    with Session(db.engine) as s:
        n = Noticia(sindicato_id=SID, titulo="De antes", bajada="", texto_completo="",
                    fecha_desde="2020-01-01", fecha_hasta="2030-12-31", creada="2026-01-01 10:00",
                    imagen1_datos=_png((20, 160, 60)), imagen1_mime="image/png")
        rota = Beneficio(sindicato_id=SID, rubro="Rota", descripcion="", link="",
                         fecha_desde="2020-01-01", fecha_hasta="2030-12-31", creada="2026-01-01 10:00",
                         imagen_datos=b"GIF89a-no-es-imagen", imagen_mime="image/gif")
        s.add(n); s.add(rota); s.commit(); s.refresh(n); s.refresh(rota)
        nid, rid = n.id, rota.id
    r = TestClient(main.app).get(f"/noticia-imagen/{nid}/1/normalizada")
    assert r.status_code == 200 and _es_gris(r.content)
    with Session(db.engine) as s:
        assert s.get(Noticia, nid).imagen1_norm == r.content      # quedó guardada
    # Una imagen que no se puede leer: sale la de color tal cual, sin 500.
    r = TestClient(main.app).get(f"/beneficio-imagen/{rid}/normalizada")
    assert r.status_code == 200 and r.content == b"GIF89a-no-es-imagen" and r.headers["content-type"] == "image/gif"


def test_el_super_admin_elige_el_nivel_y_la_portada_funde_las_capas():
    with Session(db.engine) as s:
        nid = s.exec(select(Noticia.id).where(Noticia.sindicato_id == SID, Noticia.titulo == "Con foto")).first()
        bid = s.exec(select(Beneficio.id).where(Beneficio.sindicato_id == SID, Beneficio.rubro == "Turismo")).first()
    # Por defecto, normalizada: solo la capa en gris.
    html = trab.get("/app/inicio").text
    assert f'src="/noticia-imagen/{nid}/1/normalizada"' in html and f'src="/beneficio-imagen/{bid}/normalizada"' in html
    assert "foto-color" not in html
    r = _apariencia(publicaciones_laguna="50", publicaciones_noticiero="25")
    assert r.headers["location"].endswith("ok=apariencia#apariencia")
    with Session(db.engine) as s:
        assert s.get(Sindicato, SID).saturacion_publicaciones == {"laguna": 50, "noticiero": 25}
    html = trab.get("/app/inicio").text
    assert f'src="/noticia-imagen/{nid}/1/normalizada"' in html
    assert f'class="pt-mini foto-color" src="/noticia-imagen/{nid}/1"' in html and "--foto-sat: 0.5" in html
    assert f'class="foto-color" src="/beneficio-imagen/{bid}"' in html
    # Full color: la normalizada no se pide.
    _apariencia(publicaciones_laguna="100")
    html = trab.get("/app/inicio").text
    assert "/normalizada" not in html and f'src="/noticia-imagen/{nid}/1"' in html
    # La pestaña muestra el selector con lo elegido, aparte del de la foto de portada.
    panel = admin.get("/admin").text
    assert 'name="publicaciones_laguna" value="100" checked' in panel
    assert 'name="publicaciones_noticiero" value="25" checked' in panel
    # Y aparece aunque el modelo no tenga fotos de portada (este sindicato no tiene ninguna).
    assert 'name="saturacion_laguna"' not in panel
    assert "Color de las fotos de noticias y beneficios" in panel


def test_un_nivel_fuera_del_catalogo_rechaza_todo_y_sin_el_campo_no_se_toca():
    _apariencia(publicaciones_laguna="75")
    r = _apariencia(tema_afiliados="noticiero", publicaciones_laguna="60")
    assert r.headers["location"] == "/admin?err=apariencia#apariencia"
    with Session(db.engine) as s:
        sind = s.get(Sindicato, SID)
        assert sind.saturacion_publicaciones["laguna"] == 75 and sind.tema_afiliados == "laguna"
    _apariencia()
    assert db.saturacion_publicaciones_de(SID, "laguna") == 75
    assert not db.elegir_saturacion_publicaciones(SID, "rosa", 50)
