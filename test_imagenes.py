"""Toda imagen que se sube se achica en el servidor (imagenes.py).

Tres capas: el módulo puro, la clasificación fail-closed de TODA ruta que recibe
un UploadFile (una ruta nueva sin clasificar hace fallar el test) y de punta a
punta por HTTP. Las imágenes se generan con Pillow: nada binario versionado.

Correr con: python -m pytest test_imagenes.py -q
"""
import ast
import os
from io import BytesIO
from pathlib import Path

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import pytest
from PIL import Image
from fastapi.testclient import TestClient

import auth
import db
import imagenes
import main

db.crear_tablas()
RAIZ = Path(__file__).parent


def _png(tamano=(2000, 1000), modo="RGBA", color=(200, 30, 30, 0)) -> bytes:
    im = Image.new(modo, tamano, color)
    salida = BytesIO()
    im.save(salida, "PNG")
    return salida.getvalue()


def _abrir(datos: bytes) -> Image.Image:
    im = Image.open(BytesIO(datos))
    im.load()
    return im


# ---------------------------------------------------------------- el módulo

def test_png_con_alfa_sigue_transparente_y_se_achica():
    r = imagenes.achicar(_png(), "logo", "logo.png")
    im = _abrir(r["datos"])
    assert r["mime"] == "image/webp" and im.format == "WEBP"
    assert max(im.size) <= 512 and (r["ancho"], r["alto"]) == im.size
    assert im.mode == "RGBA" and im.getpixel((10, 10))[3] == 0
    assert r["bytes_original"] > 0


def test_jpeg_con_exif_rotado_sale_derecho():
    im = Image.new("RGB", (400, 200), (10, 200, 10))
    exif = Image.Exif()
    exif[0x0112] = 6        # hay que girarla 90 grados
    salida = BytesIO()
    im.save(salida, "JPEG", exif=exif)
    r = imagenes.achicar(salida.getvalue(), "perfil", "f.jpg")
    assert (r["ancho"], r["alto"]) == (200, 400)


def test_gif_animado_sale_fijo():
    cuadros = [Image.new("P", (50, 50), i * 40) for i in range(3)]
    salida = BytesIO()
    cuadros[0].save(salida, "GIF", save_all=True, append_images=cuadros[1:], duration=50, loop=0)
    r = imagenes.achicar(salida.getvalue(), "publicacion", "a.gif")
    im = Image.open(BytesIO(r["datos"]))
    assert r["mime"] == "image/webp" and getattr(im, "n_frames", 1) == 1


def test_no_agranda_una_imagen_chica():
    r = imagenes.achicar(_png((100, 60), "RGB", (1, 2, 3)), "publicacion", "x.png")
    assert (r["ancho"], r["alto"]) == (100, 60)


def test_topes_por_perfil():
    for perfil, lado in (("logo", 512), ("firma", 800), ("perfil", 512),
                         ("publicacion", 1600), ("adjunto", 1600)):
        r = imagenes.achicar(_png((3000, 1500), "RGB", (1, 2, 3)), perfil, "x.png")
        assert max(r["ancho"], r["alto"]) == lado, perfil


def test_rechaza_lo_que_pesa_de_mas_sin_abrirlo():
    with pytest.raises(imagenes.ImagenInvalida) as e:
        imagenes.achicar(b"\0" * (9 * 1024 * 1024), "perfil", "x.png")
    assert "8 MB" in str(e.value) and "9 MB" in str(e.value)


def test_un_txt_con_nombre_de_png_no_es_imagen():
    with pytest.raises(imagenes.ImagenInvalida) as e:
        imagenes.achicar(b"hola, esto no es una imagen", "logo", "x.png")
    assert "no es una imagen" in str(e.value)
    with pytest.raises(imagenes.ImagenInvalida):
        imagenes.achicar(b"", "logo", "x.png")


SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>'


def test_svg_solo_en_logo_y_chico():
    r = imagenes.achicar(SVG, "logo", "l.svg")
    assert r["mime"] == "image/svg+xml" and r["datos"] == SVG
    for perfil in ("firma", "perfil", "publicacion", "adjunto"):
        with pytest.raises(imagenes.ImagenInvalida):
            imagenes.achicar(SVG, perfil, "l.svg")
    grande = SVG.replace(b"</svg>", b"<!--" + b"x" * (201 * 1024) + b"--></svg>")
    with pytest.raises(imagenes.ImagenInvalida) as e:
        imagenes.achicar(grande, "logo", "l.svg")
    assert "200 KB" in str(e.value)
    with pytest.raises(imagenes.ImagenInvalida):
        imagenes.achicar(b"<html><body/></html>", "logo", "l.svg")
    with pytest.raises(imagenes.ImagenInvalida):      # DTD / entidades
        imagenes.achicar(b'<!DOCTYPE svg [<!ENTITY a "b">]><svg/>', "logo", "l.svg")


def test_bomba_de_pixeles_se_rechaza_sin_cargarla():
    liso = Image.new("L", (11000, 11000), 0)
    salida = BytesIO()
    liso.save(salida, "PNG")
    assert len(salida.getvalue()) < imagenes.TOPE_ENTRADA
    with pytest.raises(imagenes.ImagenInvalida) as e:
        imagenes.achicar(salida.getvalue(), "publicacion", "b.png")
    assert "píxeles" in str(e.value)


def test_svg_con_script_o_manejadores_se_rechaza():
    for malo in (b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
                 b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
                 b'<svg xmlns="http://www.w3.org/2000/svg"><a href="javascript:alert(1)"/></svg>'):
        with pytest.raises(imagenes.ImagenInvalida):
            imagenes.achicar(malo, "logo", "l.svg")


# ------------------------------------------------- las puertas, fail-closed

# Rutas con UploadFile que NO son imágenes de la app: documentos que lee la IA,
# contratos, convenios, herramientas internas, recursos y la biblioteca de
# fotos de los modelos (que ya tiene su propio tratamiento: fotos_tema).
EXCEPCIONES = {
    "api_leer": "recibo para la IA",
    "api_aportes": "comprobante de ARCA para la IA",
    "aprender": "aprendizaje: documentos para la IA",
    "api_bancaria_leer": "recibo para la calculadora (IA)",
    "api_laboratorio_correr": "laboratorio de modelos (IA)",
    "api_laboratorio_correr_en_vivo": "laboratorio de modelos (IA)",
}
EXCEPCIONES.update({
    "plataforma_probar_modelos": "banco de pruebas de modelos de IA",
    "admin_lista_cargar": "CSV de listas del sindicato",
    "subir_documento_convenio": "PDF del convenio (RAG)",
    "plataforma_fotos_tema_subir": "biblioteca de fotos de portada: fotos_tema",
    "plataforma_fotos_tema_reemplazar": "biblioteca de fotos de portada: fotos_tema",
    "recursos_subir": "Recursos de /entornos",
})


def _rutas_con_upload():
    arbol = ast.parse((RAIZ / "main.py").read_text(encoding="utf-8"))
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                   and d.func.attr in ("post", "put", "patch") for d in nodo.decorator_list):
            continue
        if "UploadFile" in ast.unparse(nodo.args):
            yield nodo


def _llamados(nodo) -> set:
    return {n.func.id for n in ast.walk(nodo)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}


# Los lectores de bytes que a su vez llaman a `imagenes` (directo o por
# _achicar_o_error), en main.py.
LECTORES = {"_leer_logo", "_leer_adjunto_notificacion", "_leer_archivo_tramite",
            "_adjunto_achicado", "_achicar_o_error"}


def _funciones_que_achican() -> set:
    arbol = ast.parse((RAIZ / "main.py").read_text(encoding="utf-8"))
    achican = set(LECTORES)
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            usa = any(isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                      and n.value.id == "imagenes" and n.attr == "achicar" for n in ast.walk(nodo))
            if usa:
                achican.add(nodo.name)
    return achican


def test_toda_ruta_con_upload_esta_clasificada():
    achican = _funciones_que_achican()
    sin_clasificar = []
    for nodo in _rutas_con_upload():
        if nodo.name in EXCEPCIONES:
            continue
        if _llamados(nodo) & achican:
            continue
        sin_clasificar.append(nodo.name)
    assert not sin_clasificar, (
        "Rutas que reciben un archivo y no pasan por imagenes.achicar ni están en "
        f"la lista de excepciones de este test: {sin_clasificar}. Si es una imagen "
        "de la app, achicala con imagenes.achicar; si es un documento, sumala a EXCEPCIONES.")


def test_los_campos_archivo_de_tramites_tambien_achican():
    """Los campos tipo archivo de los formularios se leen de `request.form()`
    (sin UploadFile en la firma): toda función que mira ARCHIVO_MIMES_TRAMITE
    para armar una respuesta tiene que achicar las imágenes."""
    achican = _funciones_que_achican()
    arbol = ast.parse((RAIZ / "main.py").read_text(encoding="utf-8"))
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if nodo.name in ("_leer_archivo_tramite", "_adjunto_achicado"):
            continue
        if "ARCHIVO_MIMES_TRAMITE" in ast.unparse(nodo):
            assert _llamados(nodo) & achican, nodo.name


def test_las_puertas_de_imagen_llaman_al_modulo():
    """Las puertas conocidas siguen pasando por el módulo (no solo por nombre)."""
    achican = _funciones_que_achican()
    esperadas = {"abm_noticia", "abm_beneficio", "api_subir_foto_perfil",
                 "api_subir_foto_perfil_empresa", "plataforma_marca",
                 "plataforma_alta_sindicato"}
    arbol = ast.parse((RAIZ / "main.py").read_text(encoding="utf-8"))
    por_nombre = {n.name: n for n in ast.walk(arbol)
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for nombre in esperadas:
        assert nombre in por_nombre, nombre
        assert _llamados(por_nombre[nombre]) & achican, nombre
    # Y los lectores de adjuntos achican de verdad.
    for lector in ("_leer_adjunto_notificacion", "_leer_archivo_tramite"):
        assert "_adjunto_achicado" in _llamados(por_nombre[lector]), lector
    assert "_achicar_o_error" in _llamados(por_nombre["_adjunto_achicado"])
    assert "_achicar_o_error" in _llamados(por_nombre["_leer_logo"])


# ------------------------------------------------------- de punta a punta

def _plataforma():
    c = TestClient(main.app)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"],
                  auth.crear_sesion("plataforma", id_usuario=1, ident="snavello"))
    return c


def _admin(modulos):
    with db.get_session() as s:
        sind = db.Sindicato(nombre="Imag " + "-".join(modulos), slug="imag-" + "-".join(modulos),
                            modulos_habilitados=modulos)
        s.add(sind); s.commit(); s.refresh(sind)
        u = db.UsuarioSindicato(sindicato_id=sind.id, usuario=f"20{sind.id:09d}", nombre="Admin",
                                clave_hash=auth.hashear_clave("x"), debe_cambiar_clave=False,
                                es_super_admin=True)
        s.add(u); s.commit(); s.refresh(u)
        sid, uid = sind.id, u.id
    c = TestClient(main.app)
    c.cookies.set("sesion_sindicato", auth.crear_sesion("sindicato", uid, sid))
    return c, sid


def test_logo_de_sindicato_sale_achicado_en_webp():
    c = _plataforma()
    r = c.post("/plataforma/sindicato", data={"nombre": "Gremio Logo", "color_base": "#0f2240"},
               files={"logo": ("logo.png", _png((2000, 900)), "image/png")}, follow_redirects=False)
    assert r.status_code == 303, r.text
    with db.get_session() as s:
        sind = s.exec(db.select(db.Sindicato).where(db.Sindicato.nombre == "Gremio Logo")).first()
        sid = sind.id
    r = TestClient(main.app).get(f"/logo/{sid}")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    im = _abrir(r.content)
    assert max(im.size) <= 512 and im.mode == "RGBA"


def test_logo_que_no_es_imagen_vuelve_con_aviso_y_no_es_500():
    c = _plataforma()
    r = c.post("/plataforma/sindicato", data={"nombre": "Gremio Roto", "color_base": "#0f2240"},
               files={"logo": ("logo.png", b"no soy una imagen", "image/png")},
               headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and "error=imagen" in r.headers["location"]
    with db.get_session() as s:
        assert s.exec(db.select(db.Sindicato).where(db.Sindicato.nombre == "Gremio Roto")).first() is None


def test_noticia_con_imagen_grande_se_guarda_chica():
    c, sid = _admin(["noticias"])
    r = c.post("/admin/noticia", data={"titulo": "Con foto", "fecha_desde": "2020-01-01",
                                       "fecha_hasta": "2099-12-31"},
               files={"imagen1": ("f.png", _png((3200, 2400), "RGB", (20, 90, 160)), "image/png")},
               follow_redirects=False)
    assert r.status_code == 303 and "error" not in r.headers["location"], r.text
    with db.get_session() as s:
        n = s.exec(db.select(db.Noticia).where(db.Noticia.sindicato_id == sid)).first()
        nid = n.id
    r = c.get(f"/noticia-imagen/{nid}/1")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    assert max(_abrir(r.content).size) <= 1600
    assert c.get(f"/noticia-imagen/{nid}/1/normalizada").status_code == 200


def test_noticia_con_svg_se_rechaza():
    c, sid = _admin(["noticias", "beneficios"])
    r = c.post("/admin/beneficio", data={"rubro": "X", "fecha_desde": "2020-01-01",
                                         "fecha_hasta": "2099-12-31"},
               files={"imagen": ("f.svg", SVG, "image/svg+xml")},
               headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and "error=imagen" in r.headers["location"]


def test_foto_de_perfil_grande_entra_y_sale_achicada():
    cuil = "20111111112"
    with db.get_session() as s:
        s.add(db.CuentaTrabajador(cuil=cuil, clave_hash=auth.hashear_clave("x")))
        s.commit()
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident=cuil))
    r = c.post("/api/perfil/foto", files={"foto": ("f.jpg", _png((3000, 3000), "RGB", (9, 9, 9)), "image/png")})
    assert r.status_code == 200, r.text
    r = c.get(f"/perfil-foto/{cuil}")
    assert r.headers["content-type"] == "image/webp" and max(_abrir(r.content).size) <= 512
    r = c.post("/api/perfil/foto", files={"foto": ("f.png", b"nada", "image/png")})
    assert r.status_code == 400 and "imagen" in r.json()["detail"]


def test_un_png_con_un_svg_en_los_metadatos_no_es_un_svg():
    """El logo de La Bancaria es un PNG con metadatos C2PA que citan
    `<svg ...>`: se achica como PNG, no se rechaza como SVG gigante."""
    import struct
    import zlib
    base = _png((600, 600))
    meta = b"image/svg+xml\x00<svg width=\"716\" height=\"716\" xmlns=\"x\">"
    chunk = struct.pack(">I", len(meta)) + b"caBX" + meta + struct.pack(">I", zlib.crc32(b"caBX" + meta))
    fin = base.rfind(b"\x00\x00\x00\x00IEND")
    con_meta = base[:fin] + chunk + base[fin:]
    r = imagenes.achicar(con_meta, "logo")
    assert r["mime"] == "image/webp"
