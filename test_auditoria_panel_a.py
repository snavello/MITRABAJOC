"""Auditoría de diseño 2026-10, bloque 5b (panel A): la portada del panel,
Reportes, Reglas, Conceptos, Trabajadores y Aprendizaje.

Lo que se verifica:
- formato_ar.py (números en formato argentino, G4-35) y su espejo en el
  navegador, static/numeros_ar.js, dan lo mismo.
- La portada muestra una línea de estado contada en el servidor (G4-01),
  con el recorte de seccional de quien mira.
- El padrón se pagina en el servidor (G4-19): /admin trae 50 filas, la ruta
  /admin/trabajadores/lista busca por CUIL y por nombre (sin tildes),
  pagina, recorta por seccional y está clasificada en PERMISOS_RUTAS.
- Cada fila del padrón tiene una sola acción a la vista y el resto en el
  menú «Más», con «Dar de baja» al final (G4-15), «Confirmar identidad»
  (G4-20) y la marca del mapa solo si la persona está ubicada (G4-17).
- La carga masiva tiene ensayo (G4-26): con `ensayo=1` no escribe nada y
  dice qué entra y qué queda afuera, con su línea y su motivo; sin ensayo
  carga lo mismo.
- Reglas y Conceptos: títulos del alta, rótulos a la vista, vigencia en
  castellano, tolerancia en pesos, sin rojo/verde para remunerativo.
- Aprendizaje: título corto, zona para subir con ícono y la razón del botón
  apagado.

Correr con: python -m pytest test_auditoria_panel_a.py -q
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import auth
import db
import formato_ar
import main
from db import Concepto, Formula, Seccional, Sindicato, Trabajador, UsuarioSindicato
from fastapi.testclient import TestClient
from modulos import MODULOS
from sqlmodel import select

db.crear_tablas()

GENERAL, LOCAL = "20412233442", "20555555556"

with db.get_session() as s:
    sind = Sindicato(nombre="Panel A Auditoría", slug="panel-a-auditoria", color_base="#0f2240",
                     color_primario="#1a3d6b", color_acento="#e8b84b", color_secundario="#2fa88f",
                     modulos_habilitados=list(MODULOS.keys()))
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    ros = Seccional(sindicato_id=SID, nombre="Rosario")
    cba = Seccional(sindicato_id=SID, nombre="Córdoba")
    s.add(ros); s.add(cba); s.commit(); s.refresh(ros); s.refresh(cba)
    SEC_ROS, SEC_CBA = ros.id, cba.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=GENERAL, cuil=GENERAL, nombre="Laura Méndez",
                           clave_hash=auth.hashear_clave("gen"), es_super_admin=True))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=LOCAL, cuil=LOCAL, nombre="Local Rosario",
                           clave_hash=auth.hashear_clave("loc"), es_admin_seccional=True,
                           seccional_id=SEC_ROS))
    # 60 afiliados: 40 en Rosario y 20 en Córdoba. Uno con tilde para buscar.
    CUILES = []
    for i in range(60):
        cuil = formato_ar.cuit.siguiente_libre("2070000%04d" % i, CUILES)
        CUILES.append(cuil)
        sec = SEC_ROS if i < 40 else SEC_CBA
        s.add(Trabajador(sindicato_id=SID, cuil=cuil, seccional_id=sec, activo=True,
                         registrado=(i % 3 == 0)))
        cta = db.asegurar_cuenta(s, cuil)
        cta.nombre = "José Pérez" if i == 5 else "Afiliado %02d" % i
        cta.localidad, cta.provincia = "Rosario", "Santa Fe"
        if i == 7:
            cta.latitud, cta.longitud, cta.precision_geo = -32.9, -60.6, "exacta"
    s.add(Concepto(sindicato_id=SID, codigo="VIAT", nombre="Viáticos", tipo="ingreso", remunerativo=False))
    s.add(Concepto(sindicato_id=SID, codigo="NUEVO1", nombre="Algo nuevo", tipo="ingreso",
                   remunerativo=True, pendiente_revision=True))
    s.add(Formula(sindicato_id=SID, target="VIAT", descripcion="Prueba", expr="0.01 * base_remunerativa",
                  tolerancia=1.0, fecha_desde="2026-03-01", fecha_hasta="2026-12-31"))
    s.add(Formula(sindicato_id=SID, target="VIAT", descripcion="Vieja", expr="0.01 * base_remunerativa",
                  tolerancia=2.5, fecha_desde="2020-01-01", fecha_hasta="2020-12-31"))
    s.commit()

PERSONA_TILDE = CUILES[5]
UBICADA = CUILES[7]


def _cliente(usuario, clave):
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": usuario, "clave": clave}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return c


GEN = _cliente(GENERAL, "gen")


# ---------------------------------------------------------------- formato_ar

def test_formato_argentino():
    assert formato_ar.miles(1583) == "1.583"
    assert formato_ar.miles(1234567.5, 2) == "1.234.567,50"
    assert formato_ar.pesos(1.0) == "$ 1,00"
    assert formato_ar.pesos(-1200) == "-$ 1.200,00"
    assert formato_ar.pesos(None) == "—" and formato_ar.pesos("x") == "—"
    assert formato_ar.porcentaje(2.5) == "2,5%"
    assert formato_ar.porcentaje(21) == "21%"
    assert formato_ar.periodo_corto("2026-09") == "sep. 2026"
    assert formato_ar.periodo_corto("cualquiera") == "cualquiera"
    assert formato_ar.cuil("20480000917") == "20-48000091-7"
    assert formato_ar.contar(1, "recibo", "recibos") == "1 recibo"
    assert formato_ar.contar(1583, "recibo", "recibos") == "1.583 recibos"


def test_vigencia_en_castellano():
    assert formato_ar.vigencia("", "") == "Siempre"
    assert formato_ar.vigencia("2026-03-01", None) == "Desde el 01/03/2026"
    assert formato_ar.vigencia("", "2026-12-31") == "Hasta el 31/12/2026"
    assert formato_ar.vigencia("2026-03-01", "2026-12-31") == "Del 01/03 al 31/12/2026"
    assert formato_ar.vigencia("2025-03-01", "2026-12-31") == "Del 01/03/2025 al 31/12/2026"


@pytest.mark.skipif(not shutil.which("node"), reason="sin Node no se puede correr el espejo JS")
def test_el_espejo_js_dice_lo_mismo():
    js = Path("static/numeros_ar.js").read_text(encoding="utf-8")
    prueba = js.replace("window.NumAR", "globalThis.NumAR") + """
    console.log(JSON.stringify([NumAR.miles(1583), NumAR.pesos(1), NumAR.pesos(-1200), NumAR.pesos(null),
      NumAR.porcentaje(2.5), NumAR.porcentaje(21), NumAR.periodo('2026-09'), NumAR.cuil('20480000917'),
      NumAR.contar(1583, 'recibo', 'recibos')]));
    """
    salida = subprocess.run(["node", "-e", prueba.replace("window", "globalThis")],
                            capture_output=True, text=True, timeout=20)
    assert salida.returncode == 0, salida.stderr
    assert json.loads(salida.stdout) == [
        formato_ar.miles(1583), formato_ar.pesos(1), formato_ar.pesos(-1200), formato_ar.pesos(None),
        formato_ar.porcentaje(2.5), formato_ar.porcentaje(21), formato_ar.periodo_corto("2026-09"),
        formato_ar.cuil("20480000917"), formato_ar.contar(1583, "recibo", "recibos")]


# ---------------------------------------------------------------- portada

def test_la_portada_dice_el_estado_real_de_cada_acceso():
    html = GEN.get("/admin/inicio").text
    assert "60 activos" in html and "40 sin registrar" in html
    assert "1 por revisar" in html          # el concepto pendiente
    assert "pt-fila-dato" in html
    # Reglas no tiene dato: deja su descripción.
    assert "Cálculo de cada aporte" in html


def test_la_portada_del_admin_de_seccional_cuenta_solo_su_seccional():
    local = _cliente(LOCAL, "loc")
    html = local.get("/admin/inicio").text
    assert "40 activos" in html and "60 activos" not in html


def test_estado_portada_es_puro_sql_y_respeta_permisos():
    with db.get_session() as s:
        uid = s.exec(select(UsuarioSindicato).where(UsuarioSindicato.cuil == GENERAL)).first().id
    est = db.estado_portada_panel(SID, uid, ["recibos"], {"trabajadores"})
    assert "trabajadores" in est and "reportes" not in est and "noticias" not in est


# ---------------------------------------------------------------- padrón paginado

def test_la_ruta_del_padron_esta_clasificada():
    assert main.PERMISOS_RUTAS["/admin/trabajadores/lista"] == "trabajadores"


def test_admin_trae_solo_la_primera_pagina():
    html = GEN.get("/admin").text
    filas = re.findall(r'<tr class="fila-trabajador" data-cuil="(\d+)"', html)
    assert len(filas) == 50
    assert "Trabajadores (60 activos)" in html
    assert 'data-paginas="2"' in html


def test_la_lista_pagina_y_busca_en_el_servidor():
    d = GEN.get("/admin/trabajadores/lista", params={"pagina": 2}).json()
    assert d["total"] == 60 and d["paginas"] == 2 and d["pagina"] == 2
    assert d["html"].count('class="fila-trabajador"') == 10
    # Por nombre, sin tildes ni mayúsculas.
    d = GEN.get("/admin/trabajadores/lista", params={"nombre": "jose perez"}).json()
    assert d["total"] == 1 and PERSONA_TILDE in d["html"]
    # Por CUIL, con o sin guiones.
    d = GEN.get("/admin/trabajadores/lista", params={"cuil": formato_ar.cuil(PERSONA_TILDE)}).json()
    assert d["total"] == 1
    d = GEN.get("/admin/trabajadores/lista", params={"nombre": "nadie así"}).json()
    assert d["total"] == 0 and "Nadie del padrón coincide" in d["html"]


def test_la_lista_recorta_por_seccional():
    local = _cliente(LOCAL, "loc")
    d = local.get("/admin/trabajadores/lista").json()
    assert d["total"] == 40 and d["activos"] == 40
    d = local.get("/admin/trabajadores/lista", params={"cuil": CUILES[50]}).json()
    assert d["total"] == 0, "un afiliado de Córdoba no aparece para el admin de Rosario"


def test_la_pagina_del_padron_coincide_con_el_padron_entero():
    with db.get_session() as s:
        todos = [f["cuil"] for f in db.padron_del_sindicato(s, SID)]
        pag = db.pagina_del_padron(s, SID, None, por_pagina=60)
    assert sorted(todos) == sorted(f["cuil"] for f in pag["filas"])
    with db.get_session() as s:
        assert db.pagina_del_padron(s, SID, set())["total"] == 0


def test_cada_fila_tiene_editar_y_el_menu_mas():
    html = GEN.get("/admin").text
    fila = re.search(r'<tr class="fila-trabajador" data-cuil="%s".*?</tr>' % CUILES[0], html, re.S).group(0)
    assert fila.count(">Editar</button>") == 1
    assert '<details class="menu-mas">' in fila
    lista = fila.split('class="menu-mas-lista"')[1]
    assert lista.index("Generar credencial") < lista.index("menu-mas-sep") < lista.index("Dar de baja")
    assert "Confirmé su identidad" not in html
    assert formato_ar.cuil(CUILES[0]) in fila


def test_la_marca_del_mapa_solo_si_esta_ubicada():
    html = GEN.get("/admin/trabajadores/lista", params={"pagina": 1}).json()["html"]
    assert "Sin ubicar" not in html
    ubicada = re.search(r'<tr class="fila-trabajador" data-cuil="%s".*?</tr>' % UBICADA, html, re.S).group(0)
    assert "En el mapa" in ubicada
    otra = re.search(r'<tr class="fila-trabajador" data-cuil="%s".*?</tr>' % CUILES[8], html, re.S).group(0)
    assert "En el mapa" not in otra


# ---------------------------------------------------------------- carga masiva con ensayo

def _hay(cuil):
    with db.get_session() as s:
        return s.exec(select(Trabajador).where(Trabajador.sindicato_id == SID,
                                               Trabajador.cuil == cuil)).first() is not None


def test_el_ensayo_no_escribe_y_dice_por_que_queda_afuera():
    nuevo = formato_ar.cuit.siguiente_libre("20800000010", CUILES)
    sin_localidad = formato_ar.cuit.siguiente_libre("27800000010", CUILES)
    lista = "\n".join([
        f"{nuevo}, Nueva Persona, , , , Rosario, Santa Fe",
        f"{sin_localidad}, Sin Localidad",
        f"{CUILES[0]}, Repetido, , , , Rosario, Santa Fe",
        "20000000000, Mal CUIL, , , , Rosario, Santa Fe",
    ])
    r = GEN.post("/admin/trabajador/masivo", data={"lista": lista, "ensayo": "1"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["lineas"] == 4 and d["altas"] == 1 and d["afuera_total"] == 3
    motivos = {a["linea"]: a["motivo"] for a in d["afuera"]}
    assert "localidad" in motivos[2]
    assert "ya está en el padrón" in motivos[3]
    assert "no es válido" in motivos[4]
    assert not _hay(nuevo), "el ensayo no escribe"
    # Sin ensayo, carga lo mismo que dijo el ensayo.
    r = GEN.post("/admin/trabajador/masivo", data={"lista": lista}, follow_redirects=False)
    assert r.status_code == 303 and "altas=1" in r.headers["location"]
    assert _hay(nuevo)


def test_la_pantalla_ofrece_revisar_antes_de_cargar():
    html = GEN.get("/admin").text
    assert "Revisar antes de cargar" in html
    # El ejemplo ya no está adentro del cuadro de texto.
    area = re.search(r'<textarea name="lista"[^>]*>', html).group(0)
    assert "placeholder" not in area
    assert 'class="masivo-ejemplo"' in html


# ---------------------------------------------------------------- Reglas, Conceptos, Aprendizaje

def test_reglas_con_titulo_rotulos_y_vigencia_legible():
    html = GEN.get("/admin").text
    assert '<h3 class="alta-titulo" id="f-titulo">Agregar una regla</h3>' in html
    assert "Tolerancia ($)" in html
    assert "(sin inicio)" not in html and "→ vigente" not in html
    assert "Del 01/03 al 31/12/2026" in html
    assert "$ 1,00" in html and "$ 2,50" in html
    assert "Vencida" in html


def test_conceptos_sin_rojo_ni_verde_para_remunerativo():
    html = GEN.get("/admin").text
    panel = html.split('id="panel-conceptos"')[1].split('id="panel-trabajadores"')[0]
    viat = re.search(r'<tr class="fila-concepto[^"]*"\s+data-cuil="" data-nombre="Viáticos">.*?</tr>', panel, re.S).group(0)
    assert "tag-no" not in viat and "tag-neutro" in viat
    assert "ref-cuadro" not in panel, "sin la leyenda de colores"
    assert "es-ingreso" not in panel and "es-descuento" not in panel
    assert "por revisar" in panel
    assert '<h3 class="alta-titulo" id="c-titulo">Agregar un concepto</h3>' in panel
    assert "CUIT del empleador <span class=\"opc\">(vacío = vale para todos)</span>" in panel


def test_aprendizaje_titulo_corto_y_zona_para_subir():
    html = GEN.get("/admin").text
    assert '<h2 class="titulo-pagina" id="aprendizaje">Aprendizaje</h2>' in html
    assert "drop-recibos" in html and "Arrastrá los recibos acá" in html
    assert 'id="ap-falta">Elegí al menos un recibo.' in html


def test_reportes_rotulos_y_paginado_arriba():
    html = GEN.get("/admin").text
    assert "<span>Verificado desde</span>" in html and "<span>hasta</span>" in html
    assert 'id="rep-paginas-arriba"' in html
    assert 'class="col-enviado"' in html


# ---------------------------------------------------------------- reglas de la casa

def test_lo_nuevo_de_static_va_con_sello():
    html = GEN.get("/admin").text
    for nombre in ("panel_formularios.css", "numeros_ar.js", "panel_padron.js"):
        assert f"/static/{nombre}?v={main._sello_static(nombre)}" in html


def _partes(selector):
    """Las partes de un selector separadas por comas, sin cortar adentro de :is()."""
    partes, nivel, actual = [], 0, ""
    for ch in selector:
        nivel += (ch == "(") - (ch == ")")
        if ch == "," and nivel == 0:
            partes.append(actual); actual = ""
        else:
            actual += ch
    return partes + [actual]


def test_los_bloques_5b_de_las_hojas_de_los_modelos():
    for hoja in ("laguna-panel", "noticiero-panel", "laguna-panel-portada", "noticiero-panel-portada"):
        css = Path(f"static/temas/{hoja}.css").read_text(encoding="utf-8")
        assert "/* Bloque 5b: panel A (auditoría 2026-10) */" in css, hoja
        modelo = hoja.split("-")[0]
        bloque = css.split("/* Bloque 5b: panel A (auditoría 2026-10) */")[1]
        bloque = re.sub(r"/\*.*?\*/", "", bloque, flags=re.S)
        for sel in re.findall(r"(?:^|})\s*([^{}@]+?)\s*{", bloque):
            for parte in _partes(sel):
                parte = parte.strip()
                if parte and not parte.startswith(("from", "to", "@")):
                    assert parte.startswith(f'html[data-tema="{modelo}"]'), (hoja, parte)
