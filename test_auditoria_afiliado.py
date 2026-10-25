"""La auditoría de diseño de 2026-10 en la app del afiliado (bloque 5a).

Un test por hallazgo que se puede fijar sin mirar la pantalla: lo que la
plantilla arma (clases, textos, orden) y las reglas que cada modelo suma al
final de su hoja, en el bloque «Bloque 5a: afiliado (auditoría 2026-10)».

Correr con: python -m pytest test_auditoria_afiliado.py -q
"""
import os
import re
from pathlib import Path

os.environ.setdefault("PLATAFORMA_PASSWORD", "test-plataforma")

import auth
import db
import main
from db import CuentaTrabajador, Sindicato, Trabajador, TipoTramite, Tramite
from fastapi.testclient import TestClient
from modulos import MODULOS

db.crear_tablas()

MUCHOS = "20456789013"     # afiliado de un sindicato con 8 beneficios
POCOS = "27456789011"      # afiliado de un sindicato con 2 beneficios
TEMAS = Path("static/temas")
PLANTILLA = Path("templates/trabajador.html").read_text(encoding="utf-8")


def _sindicato(s, nombre, slug, beneficios, con_foto):
    sind = Sindicato(nombre=nombre, slug=slug, color_base="#0f2240", color_primario="#1a3d6b",
                     color_acento="#e8b84b", color_secundario="#2fa88f", modulos_habilitados=list(MODULOS))
    s.add(sind); s.commit(); s.refresh(sind)
    for k in range(beneficios):
        s.add(db.Beneficio(sindicato_id=sind.id, rubro=f"Rubro {k}", descripcion=f"Descuento {k}",
                           fecha_desde="2000-01-01", fecha_hasta="2999-12-31", creada=f"2026-01-0{k % 9 + 1} 09:00",
                           **({"imagen_datos": b"fake", "imagen_mime": "image/png"} if con_foto and k == 0 else {})))
    return sind.id


with db.get_session() as s:
    SID = _sindicato(s, "Auditoría Afiliado", "auditoria-afiliado", 8, con_foto=False)
    SID_POCOS = _sindicato(s, "Auditoría Afiliado Pocos", "auditoria-afiliado-pocos", 2, con_foto=True)
    for cuil, sid in ((MUCHOS, SID), (POCOS, SID_POCOS)):
        s.add(CuentaTrabajador(cuil=cuil, nombre="Elsa Río", clave_hash=auth.hashear_clave("x")))
        s.add(Trabajador(sindicato_id=sid, cuil=cuil, registrado=True, activo=True))
    s.add(db.Noticia(sindicato_id=SID, titulo="Sin foto vieja", bajada="Primera", fecha_desde="2000-01-01",
                     fecha_hasta="2999-12-31", creada="2026-01-01 09:00"))
    s.add(db.Noticia(sindicato_id=SID, titulo="Con foto", bajada="Segunda", fecha_desde="2000-01-01",
                     fecha_hasta="2999-12-31", creada="2026-01-02 09:00",
                     imagen1_datos=b"fake", imagen1_mime="image/png"))
    s.add(db.Noticia(sindicato_id=SID, titulo="Sin foto tapa", bajada="Tercera", fecha_desde="2000-01-01",
                     fecha_hasta="2999-12-31", creada="2026-01-03 09:00"))
    # La sigla de "Unión…": el código del tipo lleva la Ó.
    tipo = TipoTramite(sindicato_id=SID, titulo="Reclamo", codigo="UNIÓ-F04", activo=True)
    s.add(tipo); s.commit(); s.refresh(tipo)
    TIPO = tipo.id
    s.commit()


def _cliente(cuil, tema):
    assert db.guardar_tema_persona(cuil, tema, "afiliado")
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident=cuil))
    return c


def _get(cuil, url, tema="laguna"):
    r = _cliente(cuil, tema).get(url)
    assert r.status_code == 200, r.text
    return r.text


def _bloque(hoja):
    texto = (TEMAS / hoja).read_text(encoding="utf-8")
    assert "/* Bloque 5a: afiliado (auditoría 2026-10) */" in texto, f"{hoja}: falta el bloque 5a"
    return texto.split("/* Bloque 5a: afiliado (auditoría 2026-10) */", 1)[1]


# ---------- Portada ----------

def test_g2_01_beneficio_y_novedad_sin_foto():
    html = _get(MUCHOS, "/app/inicio")
    laminas = re.findall(r'<button type="button" class="(car-sl[^"]*)"', html)
    assert laminas and all("sin-foto" in c for c in laminas), laminas
    # las novedades de la lista: sin foto no hay miniatura de relleno
    assert "pt-mini-ico" not in html
    assert re.search(r'class="pt-nov pt-vid sin-foto"', html)
    assert re.search(r'class="pt-nov pt-vid"[^>]*>\s*<span class="pt-mini-marco">', html)
    # con foto, la lámina no se marca
    html = _get(POCOS, "/app/inicio")
    laminas = re.findall(r'<button type="button" class="(car-sl[^"]*)"', html)
    assert laminas.count("car-sl") == 1 and laminas.count("car-sl sin-foto") == 1, laminas
    for hoja in ("laguna-portada.css", "noticiero-portada.css"):
        assert re.search(r"\.car-sl\.sin-foto \{[^}]*height: auto", _bloque(hoja)), hoja
    assert ".pt-nov.sin-foto" in _bloque("noticiero-portada.css")


def test_g2_02_contador_con_muchos_y_puntos_tactiles_con_pocos():
    html = _get(MUCHOS, "/app/inicio", "noticiero")
    assert 'class="car-pie muchos"' in html
    assert 'class="car-punto' not in html, "con más de seis beneficios no van los puntos"
    assert re.search(r'<span class="car-cont num"[^>]*><b id="car-n">1</b> de 8</span>', html)
    assert "contador.textContent = i + 1" in html
    # las flechas del pie (para el teléfono), con su rótulo
    assert html.count('class="car-pf car-pf-izq"') == 1 and html.count('class="car-pf car-pf-der"') == 1
    html = _get(POCOS, "/app/inicio")
    assert 'class="car-pie"' in html and len(re.findall(r'<button type="button" class="car-punto', html)) == 2
    for hoja in ("laguna-portada.css", "noticiero-portada.css"):
        b = _bloque(hoja)
        assert re.search(r"\.car-punto, html\[data-tema=\"\w+\"\] \.car-punto\.on \{ width: 44px; height: 44px;", b), hoja
        assert re.search(r"@media \(max-width: 760px\) \{[^}]*\.car-marco \.car-flecha \{ display: none; \}", b), hoja
    # en el teléfono: puntos fuera, contador y flechas en el pie, texto en 3 renglones
    m = re.search(r"@media \(max-width: 760px\) \{(.*?)\n  \}", html, re.S)
    assert m and ".car-pf { display: inline-flex; }" in m.group(1) and "-webkit-line-clamp: 3" in m.group(1)


def test_g2_03_el_pronostico_dice_de_que_dia_es():
    js = Path("static/tu_dia.js").read_text(encoding="utf-8")
    assert "x.title = p.dia" not in js, "el día no puede vivir solo en un title"
    assert "el('span', 'pt-dia-pron-d', diaCorto(p.dia))" in js
    assert "function diaCorto(dia)" in js and "if (dia === 'mañana')" in js
    for hoja in ("laguna-portada.css", "noticiero-portada.css"):
        assert ".pt-dia-esc .pt-dia-pron-d" in _bloque(hoja), hoja


def test_g2_05_mis_recibos_boton_abajo_en_todos_los_anchos():
    b = _bloque("laguna-portada.css")
    linea = 'html[data-tema="laguna"] .pt-sec-tus .pt-rec-cta { grid-column: 1 / -1; grid-row: auto; justify-self: start; margin-top: 8px; }'
    assert "\n" + linea in b, "la regla va sin media query (sin sangría)"


# ---------- App: Tu Recibo, Novedades, Mis aportes ----------

def test_g2_08_pasos_solo_el_verbo_en_telefono_angosto():
    b = _bloque("laguna-app.css")
    m = re.search(r"@media \(max-width: 420px\) \{(.*?)\n\}", b, re.S)
    assert m and '.rc-paso small { display: none; }' in m.group(1)


def test_g2_11_y_g2_12_novedades_un_nodo_y_leer():
    html = _get(MUCHOS, "/app")
    botones = re.findall(r'<button type="button" class="(nv-m[^"]*)"[^>]*>(.*?)</button>', html, re.S)
    assert len(botones) == 3, botones
    for clase, cuerpo in botones:
        tiene_av = 'class="nv-av"' in cuerpo
        assert ("sin-foto" in clase) != tiene_av, (clase, cuerpo)
        if tiene_av:
            assert "<img" in cuerpo
        assert "#ic-nov" not in cuerpo, "el megáfono repetía en cada noticia que es una noticia"
        assert '<span class="nv-leer">Leer' in cuerpo
    assert ".nv-m.sin-foto { padding-left:26px; }" in PLANTILLA


def test_g2_13_mis_aportes_un_solo_titulo():
    html = _get(MUCHOS, "/app")
    assert "Estado de tus aportes" not in html
    tarjeta = re.search(r'<div class="sem-card">(.*?)<div id="sem-cuerpo">', html, re.S).group(1)
    assert "Semáforo" in tarjeta and "Jubilación y obra social · últimos 12 meses" in tarjeta
    assert "<h2" not in tarjeta


def test_g2_14_arca_sin_flecha_de_caracter():
    assert "↗" not in PLANTILLA
    assert '<b>1 · Consultar en ARCA<span class="solo-lector"> (se abre en otra pestaña)</span></b>' in PLANTILLA
    assert '.solo-lector {' in PLANTILLA
    assert 'a.th-tile.externo::after { display: none; }' in _bloque("noticiero-app.css")


# ---------- Trámites ----------

def test_g3_04_lista_por_ultimo_movimiento():
    filas = []
    with db.get_session() as s:
        for k, (creado, actualizado) in enumerate((("2026-01-01 10:00", "2026-03-01 10:00"),
                                                   ("2026-02-01 10:00", "2026-02-02 10:00"),
                                                   ("2026-03-01 10:00", "2026-03-05 10:00"))):
            tr = Tramite(sindicato_id=SID_POCOS, tipo_tramite_id=TIPO, cuil=POCOS,
                         numero_expediente=f"ORDEN-2026-00000{k}", estado="terminado",
                         creado=creado, actualizado=actualizado)
            s.add(tr); s.commit(); s.refresh(tr)
            filas.append(tr.numero_expediente)
    orden = [t["numero_expediente"] for t in db.tramites_de_trabajador(POCOS, SID_POCOS)]
    assert orden == [filas[2], filas[0], filas[1]], orden
    # y del lado del cliente: primero lo que te toca mirar, después por fecha
    assert "tramitesCache = ordenarTramites(data.tramites || []);" in PLANTILLA
    assert "t.novedad || t.estado === 'respondido' || t.estado === 'espera_info'" in PLANTILLA


def test_g3_05_estados_con_su_color_y_sin_estilos_en_linea():
    assert "ESTADO_TAG_COLOR" not in PLANTILLA
    tramites = PLANTILLA.split("// ==================== Trámites ====================", 1)[1]
    assert not re.search(r'class="(th-)?tag" style="background', tramites)
    for estado in ("iniciado", "en_tratamiento", "respondido", "espera_info", "terminado"):
        assert f".est-{estado} {{" in PLANTILLA, estado
    for hoja in ("laguna-app.css", "noticiero-app.css"):
        b = _bloque(hoja)
        res = re.search(r"--est-res-f: ([^;]+);", b).group(1)
        ter = re.search(r"--est-ter-f: ([^;]+);", b).group(1)
        tra = re.search(r"--est-tra-f: ([^;]+);", b).group(1)
        assert len({res, ter, tra}) == 3, (hoja, res, ter, tra)
        assert "amb" in tra and "ok" in res, hoja


def test_g3_06_mensaje_en_dos_renglones_y_fecha_arriba():
    assert '<div class="der">${tagEstadoTh(t.estado, t.estado_label)}<span class="cuando">' in PLANTILLA
    assert '<div class="pie msg"><span>${pie}</span></div>' in PLANTILLA
    assert re.search(r"\.th-r \.pie\.msg > span:first-child \{ display:-webkit-box; -webkit-line-clamp:2;", PLANTILLA)
    assert ".cont:has(#tp-tramites.activo) { max-width:720px; }" in PLANTILLA


def test_g3_07_la_barra_solo_con_sus_nombres():
    lista = PLANTILLA.split("function renderLista()", 1)[1].split("function renderTramites()", 1)[0]
    assert "th-prog" not in lista and "PROGRESO_TRAM" not in lista
    assert "const TRAMOS = ['Iniciado', 'En tratamiento', 'Respondido', 'Terminado'];" in PLANTILLA
    assert PLANTILLA.count("${progresoTram(t.estado)}") == 1      # Necesita tu atención
    assert "${progresoTram(d.estado)}" in PLANTILLA              # el detalle


def test_g3_08_expediente_sin_tildes_y_buscador_con_las_dos_formas():
    assert db.prefijo_expediente("UNIÓ-F04") == "UNIOF04"
    assert db.prefijo_expediente("ñandú") == "NANDU"
    nuevo = db.crear_tramite(SID, TIPO, MUCHOS, [])
    assert nuevo and re.fullmatch(r"UNIOF04-\d{4}-\d{6}", nuevo["numero_expediente"]), nuevo
    # un número viejo, emitido con la Ó, se encuentra tipeándolo sin tilde
    with db.get_session() as s:
        s.add(Tramite(sindicato_id=SID, tipo_tramite_id=TIPO, cuil=MUCHOS, numero_expediente="UNIÓF04-2025-000777",
                      estado="iniciado", creado="2025-01-01 10:00", actualizado="2025-01-01 10:00"))
        s.commit()
    assert db.tramite_por_numero_expediente("UNIOF04-2025-000777")["numero_expediente"] == "UNIÓF04-2025-000777"
    assert db.tramite_por_numero_expediente(nuevo["numero_expediente"].replace("UNIO", "UNIÓ"))["id"] == nuevo["id"]
    assert db.tramite_por_numero_expediente("UNIOF04-2025-000778") is None
    # y la ruta del afiliado, con lo que tipea la persona
    c = _cliente(MUCHOS, "laguna")
    assert c.get("/api/tramite/uniof04-2025-000777").status_code == 200
    # la sigla del lote sintético tampoco lleva tildes
    lote = Path("cargar_lote_sindicato.py").read_text(encoding="utf-8")
    assert "db.sin_tildes(nombre).upper()" in lote
