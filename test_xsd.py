"""XSD (XSANDERS Design Kit): la copia de la skill en `.claude/skills/xsd/`
es la del commit que dice su `ORIGEN.md`, la ficha de Colm3na
(`xsd/proyectos/mitrabajo/`) apunta a archivos que existen, y las piezas
mecánicas funcionan con una corrida armada a mano, sin navegador ni base.

El kit vive en su propio repositorio (snavello/xsanders-design-kit), con sus
propios tests; los de la corrida falsa se repiten acá porque es esta copia la
que corre en este repositorio.

Correr con: .venv/bin/python -m pytest test_xsd.py -q
"""
import hashlib
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

RAIZ = Path(__file__).resolve().parent
KIT = RAIZ / ".claude" / "skills" / "xsd"
sys.path.insert(0, str(KIT / "herramientas"))
import xsd  # noqa: E402

FICHA_COLM3NA = RAIZ / "xsd" / "proyectos" / "mitrabajo" / "ficha.json"


def test_la_ficha_de_colm3na_apunta_a_archivos_que_existen():
    ficha = json.loads(FICHA_COLM3NA.read_text(encoding="utf-8"))
    for clave in ("pantallas", "contexto"):
        assert (RAIZ / ficha[clave]).exists(), clave
    assert (RAIZ / ficha["referencia"] / "SKILL.md").exists()
    assert "{variante}" in ficha["sesiones"]["comando"] and "{quien}" in ficha["sesiones"]["comando"]
    plantilla = json.loads((KIT / "plantillas" / "ficha.json").read_text(encoding="utf-8"))
    assert set(plantilla) <= set(ficha) | {"base_url"}, "la plantilla tiene claves que Colm3na no usa"


def test_el_inventario_tiene_ids_unicos_y_roles_de_la_ficha():
    ficha = json.loads(FICHA_COLM3NA.read_text(encoding="utf-8"))
    pantallas = json.loads((RAIZ / ficha["pantallas"]).read_text(encoding="utf-8"))
    ids = [p["id"] for p in pantallas]
    assert len(ids) == len(set(ids))
    for p in pantallas:
        assert p["rol"] in ficha["roles"], p["id"]
        assert p["url"].startswith("/"), p["id"]
        assert "-" in p["id"], "el id va después de <variante>-<vista>- en el nombre de la captura"


def test_la_copia_de_la_skill_es_la_del_commit_fijado():
    origen = (KIT / "ORIGEN.md").read_text(encoding="utf-8")
    assert re.search(r"Commit: `[0-9a-f]{40}`", origen)
    fijados = dict(re.findall(r"- `([^`]+)`: `([0-9a-f]{64})`", origen))
    copia = {p.relative_to(KIT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in KIT.rglob("*") if p.is_file() and p.name != "ORIGEN.md" and "__pycache__" not in p.parts}
    assert copia == fijados, "la skill se edita en su repositorio y se vuelve a copiar (ver ORIGEN.md)"
    assert (KIT / "SKILL.md").read_text(encoding="utf-8").startswith("---\nname: xsd\n")


def test_el_informe_no_trae_nada_propio_de_un_proyecto():
    pagina = (KIT / "informe" / "index.html").read_text(encoding="utf-8")
    for palabra in ("Colm3na", "Bancaria", "PRUEBAS", "laguna", "noticiero"):
        assert palabra not in pagina, palabra
    assert pagina.startswith('<meta charset="utf-8">')


# --------------------------------------------------------- una corrida falsa
@pytest.fixture
def corrida(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pantallas.json").write_text(json.dumps([
        {"id": "app-inicio", "app": "App", "nombre": "Inicio", "url": "/", "rol": "ninguno", "temas": True},
        {"id": "app-datos", "app": "App", "nombre": "Datos", "url": "/datos", "rol": "ninguno", "temas": False},
    ]), encoding="utf-8")
    (tmp_path / "contexto.md").write_text("Una app de prueba.", encoding="utf-8")
    ficha = {"proyecto": "prueba", "nombre": "Prueba", "idioma": "castellano", "locale": "es-AR",
             "servidor": {"comando": "x", "puerto": 1}, "sesiones": {"comando": "x {variante} {quien}"},
             "roles": ["ninguno"], "variantes": {"con_variantes": ["claro"], "sin_variantes": "base"},
             "vistas": {"d": {"ancho": 1440, "alto": 900}, "m": {"ancho": 390, "alto": 844, "escala": 2}},
             "pantallas": "pantallas.json", "contexto": "contexto.md", "lecturas": ["REGLAS.md"],
             "referencia": ".claude/skills/impeccable", "trabajo": "trabajo",
             "aviso_capturas": "El distintivo no es diseño."}
    (tmp_path / "ficha.json").write_text(json.dumps(ficha), encoding="utf-8")
    c = tmp_path / "trabajo" / "c1"
    (c / "capturas").mkdir(parents=True)
    for nombre in ("claro-d-app-inicio", "claro-m-app-inicio", "base-d-app-datos"):
        Image.new("RGB", (1440 if "-d-" in nombre else 780, 1200), "white").save(c / "capturas" / f"{nombre}.png")
    (c / "grupos.json").write_text(json.dumps({"G1": {"titulo": "Todo", "pantallas": ["app-inicio", "app-datos"]}}),
                                   encoding="utf-8")
    (c / "hallazgos").mkdir()
    (c / "hallazgos" / "G1.json").write_text(json.dumps({"grupo": "G1", "pantallas": [
        {"id": "app-inicio", "resumen": "r", "nota": 7, "fortalezas": [], "hallazgos": [
            {"id": "G1-01", "titulo": "Baja", "severidad": "baja", "captura": "claro-d-app-inicio.png",
             "zona": {"x": 1, "y": 1, "w": 10, "h": 10}},
            {"id": "G1-02", "titulo": "Alta", "severidad": "alta", "captura": "claro-m-app-inicio.png",
             "zona": {"x": 1, "y": 1, "w": 0, "h": 10}}]},
        {"id": "general", "resumen": "g", "nota": None, "fortalezas": [], "hallazgos": [
            {"id": "G1-03", "titulo": "General", "severidad": "media", "captura": "base-d-app-datos.png"}]}],
        "verificacion": [{"id": "V-01", "resultado": "parcial", "comentario": "a medias"}]}), encoding="utf-8")
    return SimpleNamespace(ficha="ficha.json", corrida="c1", dir=c)


def _args(c, **extra):
    base = {"ficha": c.ficha, "corrida": c.corrida, "vuelta": 1, "titulo": None, "subtitulo": None, "intro": None}
    return SimpleNamespace(**{**base, **extra})


def test_el_encargo_no_deja_marcadores(corrida):
    xsd.brief(_args(corrida))
    texto = (corrida.dir / "brief.md").read_text(encoding="utf-8")
    assert not re.search(r"\{[A-Z_]+\}", texto)
    assert "Una app de prueba." in texto and "REGLAS.md" in texto


def test_el_informe_ordena_por_gravedad_y_limpia_las_zonas(corrida):
    xsd.informe(_args(corrida))
    datos = json.loads((corrida.dir / "informe" / "datos.json").read_text(encoding="utf-8"))
    inicio = next(p for p in datos["pantallas"] if p["id"] == "app-inicio")
    assert [h["id"] for h in inicio["hallazgos"]] == ["G1-02", "G1-01"]
    assert inicio["hallazgos"][0]["zona"] is None            # w = 0 no se dibuja
    assert inicio["hallazgos"][1]["capturaJpg"] == "claro-d-app-inicio.jpg"
    assert {c["modelo"] for c in inicio["capturas"]} == {"claro"}
    datos_p = next(p for p in datos["pantallas"] if p["id"] == "app-datos")
    assert [c["modelo"] for c in datos_p["capturas"]] == ["base"]
    assert any(p["id"] == "general-g1" for p in datos["pantallas"])
    assert datos["aviso_capturas"] == "El distintivo no es diseño."
    assert datos["clave"] == "xsd-prueba-c1"
    archivos = json.loads((corrida.dir / "informe" / "archivos.json").read_text(encoding="utf-8"))
    assert {"path": "datos.json"} in archivos and len(archivos) == 4
    assert (corrida.dir / "informe" / "index.html").exists()


def test_decisiones_previos_y_encargos(corrida, tmp_path):
    desde = tmp_path / "bajadas" / "decisiones"
    desde.mkdir(parents=True)
    (desde / "G1-01.json").write_text(json.dumps({"estado": "aceptar"}), encoding="utf-8")
    (desde / "G1-02.json").write_text(json.dumps({"estado": "cambio", "nota": "otra cosa"}), encoding="utf-8")
    (desde / "G1-03.json").write_text(json.dumps({"estado": "dejar"}), encoding="utf-8")
    xsd.decisiones(_args(corrida, desde=str(tmp_path / "bajadas")))
    cons = json.loads((corrida.dir / "consolidado.json").read_text(encoding="utf-8"))
    assert {h["id"]: h["estado"] for h in cons} == {"G1-01": "aceptar", "G1-02": "cambio", "G1-03": "dejar"}
    assert next(h for h in cons if h["id"] == "G1-02")["nota"] == "otra cosa"

    (corrida.dir / "aplicar.json").write_text(json.dumps({"equipo": {"hallazgos": ["G1-"], "parciales": ["V-01"]}}),
                                              encoding="utf-8")
    xsd.encargos(_args(corrida))
    enc = json.loads((corrida.dir / "encargos" / "equipo.json").read_text(encoding="utf-8"))
    assert [h["id"] for h in enc["hallazgos"]] == ["G1-01", "G1-02"]      # «dejar» no entra
    assert [p["id"] for p in enc["parciales_de_la_vuelta_anterior"]] == ["V-01"]

    xsd.previos(_args(corrida, consolidado=str(corrida.dir / "consolidado.json")))
    prev = json.loads((corrida.dir / "previos" / "G1.json").read_text(encoding="utf-8"))
    assert [p["id"] for p in prev["pantallas"]] == ["app-inicio", "app-datos"]
    # El general entra porque nombra una pantalla del grupo (en su captura), y
    # entra con su «dejar»: así el revisor sabe que no lo tiene que repetir.
    assert {h["id"]: h["estado"] for h in prev["hallazgos_anteriores"]} == {
        "G1-01": "aceptar", "G1-02": "cambio", "G1-03": "dejar"}


def test_el_avance_suma_y_actualiza_bloques(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    xsd.avance(SimpleNamespace(titulo="Plan", nota=None, bloque=["b1=en_curso:Capturas|empezando"]))
    xsd.avance(SimpleNamespace(titulo=None, nota="ok", bloque=["b1=hecho:", "b2=pendiente:Revisores"]))
    d = json.loads((tmp_path / "xsd-trabajo" / "avance.json").read_text(encoding="utf-8"))
    assert d["titulo"] == "Plan" and d["nota"] == "ok"
    assert [(b["id"], b["estado"], b["nombre"]) for b in d["bloques"]] == [("b1", "hecho", "Capturas"),
                                                                           ("b2", "pendiente", "Revisores")]
    assert d["bloques"][0]["detalle"] == "empezando"
