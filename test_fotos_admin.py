"""Las fotos de portada PROPIAS del sindicato, en /admin -> Apariencia.

Pedido de SDN (2026-11-06): subir la foto de portada desde el admin del
sindicato, sin que plataforma la haya cargado antes. Acá se cuida: que solo el
Super Admin las suba/edite/borre; que cada sindicato vea y toque SOLO las suyas
(un id ajeno o de la biblioteca global es 404); que plataforma no las vea en su
biblioteca ni las toque; que se elijan de portada con el selector de siempre;
que borrar una saque de `fotos_portada`; que un archivo inválido sea 400 con
aviso (nunca 500); y que las reglas de imagen salgan de `fotos_tema`.

Correr con: python -m pytest test_fotos_admin.py -q
"""
import os
from io import BytesIO

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

from PIL import Image
from fastapi.testclient import TestClient
from sqlmodel import Session

import auth
import db
import fotos_tema
import main
from db import Area, PermisoArea, Seccional, Sindicato, UsuarioSindicato
from modulos import MODULOS

db.crear_tablas()

GENERAL, LOCAL, DE_AREA, GENERAL_B = "20111111112", "20555555556", "27777777772", "20333333334"

with db.get_session() as s:
    a = Sindicato(nombre="Fotos Admin A", slug="fotos-admin-a", color_base="#0f2240",
                  modulos_habilitados=list(MODULOS.keys()))
    b = Sindicato(nombre="Fotos Admin B", slug="fotos-admin-b", color_base="#2a0d12",
                  modulos_habilitados=list(MODULOS.keys()))
    s.add(a); s.add(b); s.commit(); s.refresh(a); s.refresh(b)
    SID_A, SID_B = a.id, b.id
    central = Seccional(sindicato_id=SID_A, nombre="Sede Central", ve_todas=True)
    ros = Seccional(sindicato_id=SID_A, nombre="Rosario")
    s.add(central); s.add(ros); s.commit(); s.refresh(central); s.refresh(ros)
    prensa = Area(sindicato_id=SID_A, seccional_id=central.id, nombre="Prensa")
    s.add(prensa); s.commit(); s.refresh(prensa)
    s.add(PermisoArea(area_id=prensa.id, seccion="noticias"))
    s.add(UsuarioSindicato(sindicato_id=SID_A, usuario=GENERAL, cuil=GENERAL, nombre="General A",
                           clave_hash=auth.hashear_clave("gen"), es_super_admin=True,
                           seccional_id=central.id))
    s.add(UsuarioSindicato(sindicato_id=SID_A, usuario=LOCAL, cuil=LOCAL, nombre="Local A",
                           clave_hash=auth.hashear_clave("loc"), es_admin_seccional=True,
                           seccional_id=ros.id))
    s.add(UsuarioSindicato(sindicato_id=SID_A, usuario=DE_AREA, cuil=DE_AREA, nombre="Prensa A",
                           clave_hash=auth.hashear_clave("are"), area_id=prensa.id,
                           seccional_id=central.id))
    centro_b = Seccional(sindicato_id=SID_B, nombre="Sede Central", ve_todas=True)
    s.add(centro_b); s.commit(); s.refresh(centro_b)
    s.add(UsuarioSindicato(sindicato_id=SID_B, usuario=GENERAL_B, cuil=GENERAL_B, nombre="General B",
                           clave_hash=auth.hashear_clave("gen"), es_super_admin=True,
                           seccional_id=centro_b.id))
    s.commit()


def _jpg(color=(120, 80, 40), tamano=(1200, 800)) -> bytes:
    degrade = Image.linear_gradient("L").resize(tamano).convert("RGB")
    im = Image.blend(Image.new("RGB", tamano, color), degrade, 0.3)
    salida = BytesIO()
    im.save(salida, "JPEG", quality=90)
    return salida.getvalue()


def _cliente(usuario, clave):
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": usuario, "clave": clave}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return c


def _plataforma():
    c = TestClient(main.app)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"],
                  auth.crear_sesion("plataforma", id_usuario=1, ident="snavello"))
    return c


def _subir(c, tema="laguna", **extra):
    datos = {"tema": tema, "descripcion": "Asamblea en la planta"}
    datos.update(extra)
    return c.post("/admin/apariencia/fotos", data=datos,
                  files={"archivo": ("planta.jpg", _jpg(), "image/jpeg")})


def _ids(c, tema="laguna"):
    return [f["id"] for f in c.get(f"/admin/apariencia/fotos?tema={tema}").json()["fotos"]]


# ---------- subir, listar y aislamiento ----------

def test_el_super_admin_sube_una_foto_propia_normalizada_en_gris_y_color():
    c = _cliente(GENERAL, "gen")
    r = _subir(c, foco_x="0.3", foco_y="2")
    assert r.status_code == 200, r.text
    fid = r.json()["id"]
    assert (r.json()["ancho"], r.json()["alto"]) == (1200, 800)
    f = db.foto_tema(fid)
    assert f.sindicato_id == SID_A and f.tema == "laguna"
    assert (f.publicada, f.todos_los_sindicatos, f.sindicatos) == (True, False, [SID_A])
    assert (f.foco_x, f.foco_y) == (0.3, 1.0) and f.descripcion == "Asamblea en la planta"
    assert f.datos and f.datos_color and f.datos != f.datos_color      # las dos versiones
    ficha = next(x for x in c.get("/admin/apariencia/fotos?tema=laguna").json()["fotos"] if x["id"] == fid)
    assert ficha["propia"] is True and ficha["color"] is True
    # y se sirve (decorado de la app, como una publicada), también la de color
    assert TestClient(main.app).get(f"/foto-tema/{fid}").status_code == 200
    assert TestClient(main.app).get(f"/foto-tema/{fid}/color").status_code == 200


def test_la_foto_propia_no_aparece_en_otro_sindicato_ni_en_plataforma():
    c = _cliente(GENERAL, "gen")
    fid = _subir(c, tema="noticiero").json()["id"]
    assert fid in _ids(c, "noticiero")
    otro = _cliente(GENERAL_B, "gen")
    assert fid not in _ids(otro, "noticiero")
    assert fid not in [f["id"] for f in _plataforma().get("/plataforma/fotos-tema?tema=noticiero").json()["fotos"]]
    # tampoco la puede usar de portada ni verla en su selector
    assert fid not in {f["id"] for f in db.fotos_disponibles(SID_B, "noticiero")}
    assert not db.elegir_foto_portada(SID_B, "noticiero", fid)
    r = otro.post("/admin/apariencia", data={"tema_afiliados": "laguna", "tema_panel": "laguna",
                                             "paleta": "colm3na", "foto_noticiero": str(fid)},
                  follow_redirects=False)
    assert r.headers["location"] == "/admin?err=aparienciafoto#apariencia"


def test_un_sindicato_no_toca_la_foto_de_otro_ni_la_global_y_plataforma_no_toca_las_propias():
    fid = _subir(_cliente(GENERAL, "gen")).json()["id"]
    otro = _cliente(GENERAL_B, "gen")
    chico = ("x.jpg", _jpg(), "image/jpeg")
    assert otro.post(f"/admin/apariencia/fotos/{fid}", data={"descripcion": "robada"}).status_code == 404
    assert otro.post(f"/admin/apariencia/fotos/{fid}/archivo", files={"archivo": chico}).status_code == 404
    assert otro.post(f"/admin/apariencia/fotos/{fid}/borrar").status_code == 404
    assert db.foto_tema(fid).descripcion == "Asamblea en la planta"
    # una foto de la biblioteca global es de plataforma: el Super Admin tampoco la edita ni borra
    glob = db.crear_foto_tema("laguna", {"datos": b"RIFF-g", "mime": "image/webp", "ancho": 800, "alto": 600})
    propio = _cliente(GENERAL, "gen")
    assert propio.post(f"/admin/apariencia/fotos/{glob}", data={"descripcion": "x"}).status_code == 404
    assert propio.post(f"/admin/apariencia/fotos/{glob}/borrar").status_code == 404
    assert db.foto_tema(glob) is not None
    # y plataforma, por la ruta de su biblioteca, no ve ni toca la propia (404)
    plat = _plataforma()
    assert plat.post(f"/plataforma/fotos-tema/{fid}", data={"descripcion": "x"}).status_code == 404
    assert plat.post(f"/plataforma/fotos-tema/{fid}/borrar").status_code == 404
    assert plat.post(f"/plataforma/fotos-tema/{fid}/archivo", files={"archivo": chico}).status_code == 404
    assert db.foto_tema(fid) is not None


def test_las_globales_publicadas_siguen_disponibles_despues_de_las_propias():
    glob = db.crear_foto_tema("laguna", {"datos": b"RIFF-g2", "mime": "image/webp", "ancho": 800, "alto": 600})
    db.editar_foto_tema(glob, publicada=True)
    propia = _subir(_cliente(GENERAL, "gen")).json()["id"]
    ids = [f["id"] for f in db.fotos_disponibles(SID_A, "laguna")]
    assert glob in ids and propia in ids and ids.index(propia) < ids.index(glob)
    # el listado de plataforma sigue siendo solo el global
    assert propia not in [f["id"] for f in _plataforma().get("/plataforma/fotos-tema?tema=laguna").json()["fotos"]]


# ---------- editar, reponer, elegir y borrar ----------

def test_editar_foco_y_descripcion_y_volver_a_subir_el_archivo():
    c = _cliente(GENERAL, "gen")
    fid = _subir(c).json()["id"]
    assert c.post(f"/admin/apariencia/fotos/{fid}",
                  data={"descripcion": "  Nueva  ", "foco_x": "0.25", "foco_y": "0.75"}).json() == {"ok": True}
    f = db.foto_tema(fid)
    assert (f.descripcion, f.foco_x, f.foco_y) == ("Nueva", 0.25, 0.75)
    # una foto propia no tiene borrador ni alcance: nada de eso se puede cambiar
    c.post(f"/admin/apariencia/fotos/{fid}", data={"publicada": "0", "todos_los_sindicatos": "1",
                                                   "sindicatos": [str(SID_B)]})
    f = db.foto_tema(fid)
    assert (f.publicada, f.todos_los_sindicatos, f.sindicatos) == (True, False, [SID_A])
    r = c.post(f"/admin/apariencia/fotos/{fid}/archivo",
               files={"archivo": ("otra.jpg", _jpg((10, 90, 200), (1000, 700)), "image/jpeg")})
    assert r.status_code == 200 and (r.json()["ancho"], r.json()["alto"]) == (1000, 700)
    f = db.foto_tema(fid)
    assert (f.ancho, f.foco_x, f.descripcion) == (1000, 0.25, "Nueva") and f.datos_color


def test_se_elige_de_portada_con_el_selector_de_siempre_y_borrar_la_saca():
    c = _cliente(GENERAL, "gen")
    fid = _subir(c).json()["id"]
    r = c.post("/admin/apariencia", data={"tema_afiliados": "laguna", "tema_panel": "laguna",
                                          "paleta": "colm3na", "foto_laguna": str(fid)},
               follow_redirects=False)
    assert r.headers["location"] == "/admin?ok=apariencia#apariencia"
    with Session(db.engine) as s:
        assert s.get(Sindicato, SID_A).fotos_portada.get("laguna") == fid
    assert db.foto_portada_de(SID_A, "laguna")["id"] == fid
    # el selector la muestra, marcada como tuya
    html = c.get("/admin").text
    assert f'name="foto_laguna" value="{fid}"' in html and "Tuya" in html
    assert c.post(f"/admin/apariencia/fotos/{fid}/borrar").json() == {"ok": True}
    with Session(db.engine) as s:
        assert "laguna" not in (s.get(Sindicato, SID_A).fotos_portada or {})
    assert db.foto_tema(fid) is None
    assert c.post(f"/admin/apariencia/fotos/{fid}/borrar").status_code == 404


# ---------- permisos ----------

def test_admin_de_seccional_y_usuario_de_area_son_rechazados_en_todas_las_rutas():
    fid = _subir(_cliente(GENERAL, "gen")).json()["id"]
    antes = db.foto_tema(fid).descripcion
    for usuario, clave in ((LOCAL, "loc"), (DE_AREA, "are")):
        c = _cliente(usuario, clave)
        archivo = {"archivo": ("x.jpg", _jpg(), "image/jpeg")}
        respuestas = [
            c.get("/admin/apariencia/fotos?tema=laguna"),
            c.post("/admin/apariencia/fotos", data={"tema": "laguna"}, files=archivo),
            c.post(f"/admin/apariencia/fotos/{fid}", data={"descripcion": "hack"}),
            c.post(f"/admin/apariencia/fotos/{fid}/archivo", files=archivo),
            c.post(f"/admin/apariencia/fotos/{fid}/borrar"),
        ]
        assert [r.status_code for r in respuestas] == [403] * 5, usuario
    assert db.foto_tema(fid).descripcion == antes


def test_sin_sesion_no_se_toca_nada():
    anon = TestClient(main.app)
    archivo = {"archivo": ("x.jpg", _jpg(), "image/jpeg")}
    for r in (anon.get("/admin/apariencia/fotos?tema=laguna"),
              anon.post("/admin/apariencia/fotos", data={"tema": "laguna"}, files=archivo),
              anon.post("/admin/apariencia/fotos/1", data={"descripcion": "x"}),
              anon.post("/admin/apariencia/fotos/1/archivo", files=archivo),
              anon.post("/admin/apariencia/fotos/1/borrar")):
        assert r.status_code in (401, 403), r.status_code


# ---------- archivos inválidos: 400 con aviso, nunca 500 ----------

def test_un_archivo_invalido_es_400_con_el_motivo():
    c = _cliente(GENERAL, "gen")
    cuenta = len(_ids(c))
    casos = (
        (b"no soy una imagen", "No se pudo leer"),
        (b"", "ninguna"),
        (_jpg(tamano=(300, 200)), "muy chica"),
        (b"\0" * (fotos_tema.MAX_BYTES + 1), f"{fotos_tema.MAX_MB} MB"),
    )
    for datos, frase in casos:
        r = c.post("/admin/apariencia/fotos", data={"tema": "laguna"}, files={"archivo": ("x.jpg", datos, "image/jpeg")})
        assert r.status_code == 400 and frase in r.json()["detail"], (frase, r.status_code, r.text)
    r = c.post("/admin/apariencia/fotos", data={"tema": "rosa"}, files={"archivo": ("x.jpg", _jpg(), "image/jpeg")})
    assert r.status_code == 400 and "modelo" in r.json()["detail"]
    fid = _subir(c).json()["id"]
    r = c.post(f"/admin/apariencia/fotos/{fid}/archivo", files={"archivo": ("x.txt", b"hola", "text/plain")})
    assert r.status_code == 400 and "No se pudo leer" in r.json()["detail"]
    assert len(_ids(c)) == cuenta + 1                                  # solo la buena


def test_una_bomba_de_pixeles_se_rechaza_sin_decodificarla():
    liso = Image.new("L", (11000, 11000), 0)
    salida = BytesIO()
    liso.save(salida, "PNG")
    assert len(salida.getvalue()) < fotos_tema.MAX_BYTES
    r = _cliente(GENERAL, "gen").post("/admin/apariencia/fotos", data={"tema": "laguna"},
                                      files={"archivo": ("b.png", salida.getvalue(), "image/png")})
    assert r.status_code == 400 and "píxeles" in r.json()["detail"]


def test_una_foto_inexistente_es_404():
    c = _cliente(GENERAL, "gen")
    assert c.post("/admin/apariencia/fotos/99999999", data={"descripcion": "x"}).status_code == 404
    assert c.post("/admin/apariencia/fotos/99999999/borrar").status_code == 404


# ---------- las reglas de imagen salen de un solo lugar ----------

def test_los_textos_de_ayuda_de_las_dos_pantallas_leen_las_reglas_de_fotos_tema():
    r = fotos_tema.reglas()
    assert (r["max_mb"], r["lado_minimo"], r["lado_maximo"]) == (8, 600, 1600)
    frase = f"{r['formatos']}, hasta {r['max_mb']} MB, de al menos {r['lado_minimo']} px de lado."
    admin = _cliente(GENERAL, "gen").get("/admin").text
    plat = _plataforma().get("/plataforma").text
    for html in (admin, plat):
        assert frase in html
        assert f'accept="{r["accept"]}"' in html
        assert f'data-max-bytes="{r["max_bytes"]}"' in html and f'data-lado-minimo="{r["lado_minimo"]}"' in html
    for _, etiqueta in r["saturaciones"]:
        assert etiqueta in admin
    assert str(r["lado_maximo"]) in admin
    # la pantalla trae la tarjeta y su script; nada de los topes escritos en el JS
    assert 'id="ap-fotos-propias"' in admin and "/static/fotos_propias.js?v=" in admin
    js = open("static/fotos_propias.js", encoding="utf-8").read()
    plantilla_plat = open("templates/plataforma.html", encoding="utf-8").read()
    for fuente in (js, plantilla_plat[plantilla_plat.index("Biblioteca de fotos de los modelos (PLAN_TEMAS.md, D5) ----------\n"):]):
        assert "8 * 1024" not in fuente and "600;" not in fuente and "'8 MB'" not in fuente
    for prohibido in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert prohibido not in js, prohibido
    assert "textContent" in js


def test_la_pestana_de_plataforma_dice_que_cada_sindicato_sube_las_suyas():
    html = _plataforma().get("/plataforma").text
    assert "Cada sindicato sube sus propias fotos desde su Apariencia" in html
