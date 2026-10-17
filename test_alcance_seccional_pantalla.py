"""La pantalla no ofrece lo que el servidor va a descartar
(PLAN_ALCANCE_SECCIONAL.md, sección 5, Bloque 7b, frentes G2 a G5).

Se pide `GET /admin` con un Admin de Seccional (LOCAL, alcance = Rosario) y
con el administrador general, y se lee el HTML servido: Ver código fuente
muestra todo lo que viaja, así que acá se mira lo que VIAJA, no lo que se ve.

Es fail-closed: se recorren TODOS los `<input name="destino_seccionales">` y
TODOS los bloques `.check-seccionales` de la página, no solo los que existían
cuando se escribió el test. Un selector nuevo de seccional que ofrezca las
ajenas hace fallar el archivo.

Correr con: python -m pytest test_alcance_seccional_pantalla.py -q
"""
import os

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import re
from html.parser import HTMLParser

import db
import auth
import main
from db import Sindicato, UsuarioSindicato, Seccional
from modulos import MODULOS
from fastapi.testclient import TestClient

db.crear_tablas()

# CUIL con módulo 11 (`cuit.corregir`), distintos de los de otros tests.
GENERAL, LOCAL = "20314159269", "20314159277"

with db.get_session() as s:
    sind = Sindicato(nombre="Sindicato Alcance Pantalla", slug="alcance-pantalla",
                     color_base="#0f1b2d", modulos_habilitados=list(MODULOS.keys()))
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    # Rosario está ubicada en el mapa y Córdoba no: el aviso "sin ubicación"
    # (G5) solo habla de Córdoba.
    ros = Seccional(sindicato_id=SID, nombre="Rosario", latitud=-32.95, longitud=-60.65)
    cba = Seccional(sindicato_id=SID, nombre="Córdoba")
    s.add(ros); s.add(cba); s.commit(); s.refresh(ros); s.refresh(cba)
    SEC_ROS, SEC_CBA = ros.id, cba.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=GENERAL, cuil=GENERAL, nombre="General",
                           clave_hash=auth.hashear_clave("gen"), es_super_admin=True))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=LOCAL, cuil=LOCAL, nombre="Local Rosario",
                           clave_hash=auth.hashear_clave("loc"), es_admin_seccional=True,
                           seccional_id=SEC_ROS))
    s.commit()

OTRA = "Córdoba"
# Bloques `.check-seccionales` que NO son de seccionales (otro vocabulario).
NO_SECCIONALES = {"areas_pase", "cortes", "secciones"}


class _Pagina(HTMLParser):
    """Junta, de una sola pasada, lo que hace falta para mirar los selectores.

    - `inputs_destino`: value de cada `<input name="destino_seccionales">`.
    - `bloques`: cada `.check-seccionales` con su id, sus inputs (name, value)
      y su texto.
    - `capturas`: texto de ciertos elementos por id.
    - `opciones`: los `value` de las `<option>` de cada `<select>` con id.
    """
    ID_CAPTURADOS = ("form-noticia", "form-beneficio", "notif-valores-seccional",
                     "notif-alcance-aviso", "pub-seccionales", "notif-criterio",
                     "pub-criterio", "not-destino-fijo", "ben-destino-fijo")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.inputs_destino = []
        self.bloques = []
        self.capturas = {}
        self.opciones = {}
        self._bloque = None      # [profundidad, dict]
        self._abiertas = []      # [id, tag, profundidad]
        self._select = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "input" and a.get("name") == "destino_seccionales":
            self.inputs_destino.append(a.get("value"))
        if tag == "input" and self._bloque is not None:
            self._bloque[1]["inputs"].append((a.get("name"), a.get("value")))
        for c in self._abiertas:
            if c[1] == tag:
                c[2] += 1
        if a.get("id") in self.ID_CAPTURADOS:
            self.capturas[a["id"]] = {"texto": ""}
            self._abiertas.append([a["id"], tag, 1])
        if tag == "select" and a.get("id"):
            self._select = a["id"]
            self.opciones[self._select] = []
        if tag == "option" and self._select:
            self.opciones[self._select].append(a.get("value"))
        if tag == "div":
            if self._bloque is not None:
                self._bloque[0] += 1
            elif "check-seccionales" in (a.get("class") or "").split():
                self._bloque = [1, {"id": a.get("id"), "inputs": [], "texto": ""}]

    def handle_endtag(self, tag):
        if tag == "select":
            self._select = None
        for c in list(self._abiertas):
            if c[1] == tag:
                c[2] -= 1
                if c[2] == 0:
                    self._abiertas.remove(c)
        if tag == "div" and self._bloque is not None:
            self._bloque[0] -= 1
            if self._bloque[0] == 0:
                self.bloques.append(self._bloque[1])
                self._bloque = None

    def handle_data(self, data):
        for c in self._abiertas:
            self.capturas[c[0]]["texto"] += data
        if self._bloque is not None:
            self._bloque[1]["texto"] += data


def _pagina(usuario, clave):
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": usuario, "clave": clave})
    assert r.status_code in (200, 302, 303), r.status_code
    r = c.get("/admin")
    assert r.status_code == 200, r.status_code
    p = _Pagina()
    p.feed(r.text)
    p.html = r.text
    return p


def _bloques_de_seccionales(p):
    """Todo `.check-seccionales` que no sea de otro vocabulario (provincias,
    áreas de pase, cortes, secciones): ante la duda se lo trata como de
    seccionales, que es el lado seguro."""
    return [b for b in p.bloques
            if "provincias" not in (b["id"] or "")
            and not any(n in NO_SECCIONALES for n, _ in b["inputs"])]


# ---------------------------------------------------------------- el local

def test_local_destino_de_noticias_y_beneficios_no_ofrece_otras_seccionales():
    p = _pagina(LOCAL, "loc")
    ajenos = [v for v in p.inputs_destino if v != str(SEC_ROS)]
    assert ajenos == [], f"el local ve destinos fuera de su alcance: {ajenos}"
    # Con una sola seccional en el alcance no hay nada que elegir: una línea
    # fija y ningún input.
    assert p.inputs_destino == []
    for fijo in ("not-destino-fijo", "ben-destino-fijo"):
        assert fijo in p.capturas, fijo
        assert "Va a tu seccional" in p.capturas[fijo]["texto"]
        assert "Rosario" in p.capturas[fijo]["texto"]
        assert OTRA not in p.capturas[fijo]["texto"]
    for form in ("form-noticia", "form-beneficio"):
        assert form in p.capturas, form
        assert OTRA not in p.capturas[form]["texto"], form
        assert "todas las seccionales" not in p.capturas[form]["texto"], form


def test_local_ningun_bloque_de_seccionales_tiene_un_id_ajeno():
    p = _pagina(LOCAL, "loc")
    for b in _bloques_de_seccionales(p):
        for nombre, valor in b["inputs"]:
            assert valor != str(SEC_CBA), (b["id"], nombre, valor)
        assert OTRA not in b["texto"], (b["id"], b["texto"])


def test_local_notificaciones_no_ofrece_por_seccional_y_dice_el_alcance():
    p = _pagina(LOCAL, "loc")
    assert "seccional" not in p.opciones["notif-criterio"]
    # Los demás criterios siguen: se aplican dentro de su seccional.
    for criterio in ("cuil", "cuit_empleador", "provincia"):
        assert criterio in p.opciones["notif-criterio"]
    assert "notif-valores-seccional" not in p.capturas
    assert "notif-check-seccionales" not in [b["id"] for b in p.bloques]
    aviso = p.capturas["notif-alcance-aviso"]["texto"]
    assert "llegan solo a afiliados de tu seccional" in aviso
    assert "Rosario" in aviso and OTRA not in aviso


def test_local_encuesta_publicar_no_ofrece_por_seccional():
    p = _pagina(LOCAL, "loc")
    assert "pub-criterio" in p.opciones, "el modal de publicar no se dibujó"
    assert "seccional" not in p.opciones["pub-criterio"]
    for criterio in ("todos", "provincia", "cuit_empleador", "cuil"):
        assert criterio in p.opciones["pub-criterio"]
    assert "pub-seccionales" not in p.capturas
    assert "A todo el padrón de tu seccional" in p.capturas["pub-criterio"]["texto"]
    assert OTRA not in p.capturas["pub-criterio"]["texto"]


def test_local_la_otra_seccional_no_aparece_en_ningun_selector_de_seccional():
    p = _pagina(LOCAL, "loc")
    for ident in ("notif-criterio", "pub-criterio", "form-noticia", "form-beneficio"):
        assert OTRA not in p.capturas[ident]["texto"], ident


def test_local_aviso_de_seccionales_sin_ubicacion_no_cuenta_las_ajenas():
    p = _pagina(LOCAL, "loc")
    assert not re.search(r"seccionales? sin ubicación", p.html)


# --------------------------------------------------------------- el general

def test_general_sigue_viendo_las_dos_seccionales_en_los_cuatro_bloques():
    p = _pagina(GENERAL, "gen")
    # Noticias y Beneficios: dos casillas cada uno, de las dos seccionales.
    assert sorted(p.inputs_destino) == sorted([str(SEC_ROS), str(SEC_CBA)] * 2)
    por_id = {b["id"]: b for b in p.bloques}
    for ident in ("not-destino", "ben-destino", "notif-check-seccionales"):
        assert ident in por_id, ident
        assert sorted(v for _, v in por_id[ident]["inputs"]) == sorted([str(SEC_ROS), str(SEC_CBA)]), ident
        assert "Rosario" in por_id[ident]["texto"] and OTRA in por_id[ident]["texto"], ident
    # Encuestas -> Publicar: el bloque no tiene id, se lo reconoce por su name.
    publicar = [b for b in p.bloques if any(n == "valores" for n, _ in b["inputs"])]
    assert len(publicar) == 1
    assert sorted(v for _, v in publicar[0]["inputs"]) == sorted([str(SEC_ROS), str(SEC_CBA)])
    # Las opciones "Por seccional" siguen.
    assert "seccional" in p.opciones["notif-criterio"]
    assert "seccional" in p.opciones["pub-criterio"]
    # Y sus textos de siempre, sin el aviso del acotado.
    assert "notif-alcance-aviso" not in p.capturas
    assert "not-destino-fijo" not in p.capturas
    assert "Sin marcar ninguna = todas las seccionales" in p.capturas["form-noticia"]["texto"]
    assert "Sin marcar ninguna = todas las seccionales" in p.capturas["form-beneficio"]["texto"]
    assert "A todo el padrón de tu seccional" not in p.html


def test_general_ve_el_aviso_de_seccionales_sin_ubicacion():
    p = _pagina(GENERAL, "gen")
    assert "1 seccional sin ubicación" in p.html
