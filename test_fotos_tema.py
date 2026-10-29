"""Biblioteca de fotos por modelo de diseño (PLAN_TEMAS.md, bloque 2).

Toda foto entra normalizada (gris, niveles y brillo parejos): así una foto
oscura y una sobreexpuesta quedan parejas y el color lo pone el modelo. Las
carga plataforma; un borrador no lo ve nadie más; publicada, la usan todos
los sindicatos o los elegidos; cada sindicato elige su portada.

Correr con: python -m pytest test_fotos_tema.py -q
"""
import os
from io import BytesIO

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

from PIL import Image, ImageChops
from fastapi.testclient import TestClient

import auth
import db
import fotos_tema
import main

db.crear_tablas()

with db.get_session() as s:
    a = db.Sindicato(nombre="Fotos A", slug="fotos-a", color_base="#0f2240")
    b = db.Sindicato(nombre="Fotos B", slug="fotos-b", color_base="#2a0d12")
    s.add(a); s.add(b); s.commit(); s.refresh(a); s.refresh(b)
    SID_A, SID_B = a.id, b.id


def _jpg(color, tamano=(1200, 800)) -> bytes:
    """Una foto de prueba con tonos continuos (degradé + ruido) teñida de
    `color`: con un color oscuro sale subexpuesta, con uno claro sobreexpuesta."""
    degrade = Image.linear_gradient("L").resize(tamano).convert("RGB")
    ruido = Image.effect_noise(tamano, 40).convert("RGB")
    base = Image.new("RGB", tamano, color)
    im = Image.blend(Image.blend(base, degrade, 0.25), ruido, 0.2)
    salida = BytesIO()
    im.save(salida, "JPEG", quality=90)
    return salida.getvalue()


def _plataforma():
    c = TestClient(main.app)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"],
                  auth.crear_sesion("plataforma", id_usuario=1, ident="snavello"))
    return c


def test_normaliza_a_gris_con_brillo_parejo_y_tamano_acotado():
    oscura = fotos_tema.normalizar(_jpg((20, 30, 60), (3000, 2000)))
    clara = fotos_tema.normalizar(_jpg((200, 190, 120)))
    for f in (oscura, clara):
        im = Image.open(BytesIO(f["datos"]))
        assert f["mime"] == "image/webp" and im.format == "WEBP"
        # gris (webp no tiene modo gris: se guarda RGB con los tres canales
        # iguales); el color lo pone el modelo al mostrarla
        # (la compresión con pérdida deja diferencias de un par de niveles)
        r, g, b = im.convert("RGB").split()
        assert ImageChops.difference(r, g).getextrema()[1] <= 6
        assert ImageChops.difference(g, b).getextrema()[1] <= 6
        assert max(im.size) <= fotos_tema.LADO_MAXIMO
        assert abs(fotos_tema.brillo_medio(im) - fotos_tema.BRILLO_MEDIO) < 0.08
    assert (oscura["ancho"], oscura["alto"]) == (1600, 1067)    # 3000x2000 acotada, misma proporción


def test_guarda_tambien_la_original_en_color_del_mismo_tamano():
    """Pedido de los sindicatos (2026-10-29): la normalizada sigue en gris y
    al lado va la original en color, con la misma medida y orientación."""
    f = fotos_tema.normalizar(_jpg((20, 120, 200), (3000, 2000)))
    color = Image.open(BytesIO(f["datos_color"]))
    assert f["mime_color"] == "image/webp" and color.format == "WEBP"
    assert color.size == (f["ancho"], f["alto"]) == (1600, 1067)
    # de verdad en color: los canales difieren (la foto va teñida de azul)
    r, g, b = color.convert("RGB").split()
    assert ImageChops.difference(r, b).getextrema()[1] > 60
    # y la original no se "normaliza": el brillo queda el de la foto, no el objetivo
    assert abs(fotos_tema.brillo_medio(color) - fotos_tema.brillo_medio(
        Image.open(BytesIO(_jpg((20, 120, 200)))))) < 0.05


def test_el_catalogo_de_saturaciones():
    assert [n for n, _ in fotos_tema.SATURACIONES] == [0, 25, 50, 75, 100]
    assert fotos_tema.saturacion_valida("50") == 50 and fotos_tema.saturacion_valida(100) == 100
    assert fotos_tema.saturacion_valida("75 %") == 75
    for malo in ("30", "", None, "cien", -25, "0.5"):
        assert fotos_tema.saturacion_valida(malo) is None, malo


def test_rechaza_lo_que_no_sirve():
    for datos, frase in ((b"", "ninguna"), (b"no soy una imagen", "No se pudo leer"),
                         (_jpg((90, 90, 90), (300, 200)), "muy chica")):
        try:
            fotos_tema.normalizar(datos)
            assert False, "tenía que fallar"
        except fotos_tema.FotoInvalida as e:
            assert frase in str(e)


def test_plataforma_sube_publica_y_el_borrador_no_se_ve():
    c = _plataforma()
    r = c.post("/plataforma/fotos-tema", data={"tema": "laguna", "descripcion": "Asamblea en la planta",
                                               "foco_x": "0.3", "foco_y": "2"},
               files={"archivo": ("planta.jpg", _jpg((120, 80, 40)), "image/jpeg")})
    assert r.status_code == 200, r.text
    fid = r.json()["id"]
    f = db.foto_tema(fid)
    assert (f.publicada, f.foco_x, f.foco_y) == (False, 0.3, 1.0)    # el foco se acota a 0..1
    assert TestClient(main.app).get(f"/foto-tema/{fid}").status_code == 404   # borrador: nadie más
    assert c.get(f"/foto-tema/{fid}").status_code == 200
    assert c.post(f"/plataforma/fotos-tema/{fid}", data={"publicada": "1"}).json() == {"ok": True}
    r = TestClient(main.app).get(f"/foto-tema/{fid}")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    assert [x["id"] for x in c.get("/plataforma/fotos-tema?tema=laguna").json()["fotos"]] == [fid]


def test_la_version_en_color_se_sirve_aparte_y_la_foto_vieja_se_repone():
    c = _plataforma()
    r = c.post("/plataforma/fotos-tema", data={"tema": "laguna"},
               files={"archivo": ("x.jpg", _jpg((30, 90, 160)), "image/jpeg")})
    fid = r.json()["id"]
    # borrador: la de color tampoco la ve nadie más
    assert TestClient(main.app).get(f"/foto-tema/{fid}/color").status_code == 404
    assert c.get(f"/foto-tema/{fid}/color").status_code == 200
    c.post(f"/plataforma/fotos-tema/{fid}", data={"publicada": "1"})
    r = TestClient(main.app).get(f"/foto-tema/{fid}/color")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    im = Image.open(BytesIO(r.content)).convert("RGB")
    assert ImageChops.difference(*im.split()[::2]).getextrema()[1] > 60     # en color
    ficha = next(x for x in c.get("/plataforma/fotos-tema?tema=laguna").json()["fotos"] if x["id"] == fid)
    assert ficha["color"] is True and ficha["v_color"] > 0
    # Una foto de antes (sin versión en color): 404 en /color y lo dice la ficha.
    vieja = db.crear_foto_tema("laguna", {"datos": b"RIFF-gris", "mime": "image/webp", "ancho": 1600, "alto": 900},
                               descripcion="de antes", foco_x=0.2, foco_y=0.8)
    db.editar_foto_tema(vieja, publicada=True)
    assert TestClient(main.app).get(f"/foto-tema/{vieja}/color").status_code == 404
    assert next(x for x in c.get("/plataforma/fotos-tema?tema=laguna").json()["fotos"]
                if x["id"] == vieja)["color"] is False
    # Volver a subir el archivo: las dos versiones nuevas, lo demás igual.
    r = c.post(f"/plataforma/fotos-tema/{vieja}/archivo",
               files={"archivo": ("x.jpg", _jpg((200, 40, 40)), "image/jpeg")})
    assert r.status_code == 200 and r.json()["id"] == vieja
    f = db.foto_tema(vieja)
    assert f.datos_color and f.datos != b"RIFF-gris" and (f.ancho, f.alto) == (1200, 800)
    assert (f.publicada, f.descripcion, f.foco_x, f.foco_y) == (True, "de antes", 0.2, 0.8)
    assert c.post("/plataforma/fotos-tema/999999/archivo",
                  files={"archivo": ("x.jpg", _jpg((1, 2, 3)), "image/jpeg")}).status_code == 404
    assert c.post(f"/plataforma/fotos-tema/{vieja}/archivo",
                  files={"archivo": ("x.txt", b"hola", "text/plain")}).status_code == 400


def test_sin_sesion_de_plataforma_no_se_toca_nada():
    anon = TestClient(main.app)
    assert anon.get("/plataforma/fotos-tema").status_code == 403
    assert anon.post("/plataforma/fotos-tema", data={"tema": "laguna"},
                     files={"archivo": ("x.jpg", _jpg((1, 2, 3)), "image/jpeg")}).status_code == 403
    assert anon.post("/plataforma/fotos-tema/1/archivo",
                     files={"archivo": ("x.jpg", _jpg((1, 2, 3)), "image/jpeg")}).status_code == 403


def test_un_modelo_que_no_existe_o_una_foto_rota_es_400():
    c = _plataforma()
    r = c.post("/plataforma/fotos-tema", data={"tema": "rosa"},
               files={"archivo": ("x.jpg", _jpg((1, 2, 3)), "image/jpeg")})
    assert r.status_code == 400
    r = c.post("/plataforma/fotos-tema", data={"tema": "noticiero"},
               files={"archivo": ("x.txt", b"hola", "text/plain")})
    assert r.status_code == 400 and "No se pudo leer" in r.json()["detail"]


def test_disponibilidad_por_sindicato_y_portada_elegida():
    c = _plataforma()
    ids = []
    for color in ((50, 60, 70), (160, 150, 140)):
        r = c.post("/plataforma/fotos-tema", data={"tema": "noticiero"},
                   files={"archivo": ("x.jpg", _jpg(color), "image/jpeg")})
        ids.append(r.json()["id"])
    todos, solo_b = ids
    c.post(f"/plataforma/fotos-tema/{todos}", data={"publicada": "1"})
    c.post(f"/plataforma/fotos-tema/{solo_b}", data={"publicada": "1", "todos_los_sindicatos": "0",
                                                     "sindicatos": [str(SID_B), "999999"]})
    assert db.foto_tema(solo_b).sindicatos == [SID_B]                  # el que no existe se descarta
    assert [f["id"] for f in db.fotos_disponibles(SID_A, "noticiero")] == [todos]
    assert {f["id"] for f in db.fotos_disponibles(SID_B, "noticiero")} == {todos, solo_b}
    # A no puede elegir una que no tiene; B sí
    assert not db.elegir_foto_portada(SID_A, "noticiero", solo_b)
    assert db.elegir_foto_portada(SID_B, "noticiero", todos)
    assert db.foto_portada_de(SID_B, "noticiero")["id"] == todos
    # sin elegir, la más nueva disponible; borrar la elegida la saca de la portada
    assert db.foto_portada_de(SID_A, "noticiero")["id"] == todos
    assert c.post(f"/plataforma/fotos-tema/{todos}/borrar").json() == {"ok": True}
    assert db.foto_portada_de(SID_B, "noticiero")["id"] == solo_b
    assert db.foto_portada_de(SID_A, "noticiero") is None
    with db.get_session() as s:
        assert "noticiero" not in (s.get(db.Sindicato, SID_B).fotos_portada or {})
