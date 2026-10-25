"""Auditoría de diseño 2026-10, bloque 5c: el panel del sindicato de
Noticias a Apariencia (las pestañas que no son la portada, Reportes, Reglas,
Conceptos, Trabajadores ni Aprendizaje).

Lo que se verifica, hallazgo por hallazgo (el id de la auditoría al lado):
- Noticias y Beneficios: fechas cortas que no se parten, sin la hora en la
  lista (G5-09); el beneficio dice su descripción y lleva miniatura (G5-10).
- Notificaciones: el destino dicho como a quién le llegó y los leídos con
  su porcentaje (G5-12).
- Trámites: la bandeja abre en lo que falta terminar, con pastillas por de
  quién es el próximo paso (G5-13); cada estado con su forma (G5-14); el
  nombre de la persona y un buscador que entra (G5-15); el CUIL de prueba
  con rótulo (G5-16); el expediente de la carátula legible (G5-17); el
  rótulo corto del área (G5-18).
- Encuestas: una acción principal por fila y Cerrar aparte (G5-20); la
  cerrada en gris (G5-21); la toma por su número (G5-22); el porcentaje
  (G5-23); el constructor como hoja de trabajo (G5-24, G5-25, G5-27); el
  modo sin valor por defecto, y el servidor no lo inventa (G5-26).
- Empleadores (G6-01 a G6-07), Seccionales (G6-09, G6-10), Listas (G6-11 a
  G6-13), Áreas y Usuarios (G6-14 a G6-17) y Apariencia (G6-18 a G6-21).
- Las dos hojas de los modelos suman su bloque al final, con el comentario
  del bloque, y todo selector empieza con su html[data-tema].

Correr con: python -m pytest test_auditoria_panel_b.py -q
"""
import json
import os
import re
import uuid
from pathlib import Path

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import auth
import db
import main
from db import (Beneficio, CuentaTrabajador, Empleador, Noticia, Notificacion, Sindicato,
                TipoTramite, Tramite, UsuarioSindicato)
from fastapi.testclient import TestClient

db.crear_tablas()

OPERADOR = "20412233450"
SUFIJO = uuid.uuid4().hex[:6].upper()
PREGUNTAS = [{"etiqueta": "¿Conforme con la obra social?", "tipo_dato": "escala",
              "escala_min": 1, "escala_max": 5, "etiqueta_min": "Nada", "etiqueta_max": "Mucho",
              "ancho": "completo", "obligatorio": True}]

with db.get_session() as s:
    sind = Sindicato(nombre="Panel B Bancaria", slug=f"panel-b-{SUFIJO.lower()}", color_base="#0f2240",
                     color_primario="#1a3d6b", color_acento="#e8b84b", color_secundario="#2fa88f",
                     modulos_habilitados=["recibos", "noticias", "beneficios", "notificaciones",
                                          "tramites", "encuestas", "empleadores"])
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    op = UsuarioSindicato(sindicato_id=SID, usuario=OPERADOR, nombre="Laura Méndez",
                          clave_hash=auth.hashear_clave("clave-op"), es_super_admin=True)
    s.add(op); s.commit(); s.refresh(op)
    UID = op.id
    s.add(Noticia(sindicato_id=SID, titulo="Asamblea de delegados", bajada="Se votó el plan",
                  fecha_desde="2026-10-01", fecha_hasta="2099-12-31", creada="2026-10-08 20:59"))
    s.add(Beneficio(sindicato_id=SID, rubro="Óptica", descripcion="Anteojos con 30% de descuento\nSegunda línea",
                    fecha_desde="2026-10-01", fecha_hasta="2099-12-31", creada="2026-10-09 10:15",
                    imagen_datos=b"GIF89a", imagen_mime="image/gif"))
    s.add(Beneficio(sindicato_id=SID, rubro="Salud", descripcion="Consultas sin cargo",
                    fecha_desde="2026-10-01", fecha_hasta="2099-12-31", creada="2026-10-09 11:00"))
    s.add(Notificacion(sindicato_id=SID, remitente="Comisión Directiva", texto="Asamblea el viernes",
                       criterio="cuil", criterio_valores=["20111111112", "27222222228"],
                       origen="manual", enviado_en="2026-10-10 09:00", cantidad_destinatarios=2))
    tipo = TipoTramite(sindicato_id=SID, titulo="Reintegro", codigo=f"PB{SUFIJO}")
    s.add(tipo); s.commit(); s.refresh(tipo)
    CUIL_ANA = "27300000015"
    if not s.exec(db.select(CuentaTrabajador).where(CuentaTrabajador.cuil == CUIL_ANA)).first():
        s.add(CuentaTrabajador(cuil=CUIL_ANA, nombre="Ana Paredes"))
    for n, (estado, actualizado) in enumerate([("iniciado", "2026-10-02 10:00"),
                                                ("respondido", "2026-09-01 10:00"),
                                                ("espera_info", "2026-10-05 10:00"),
                                                ("terminado", "2026-10-06 10:00")]):
        s.add(Tramite(sindicato_id=SID, tipo_tramite_id=tipo.id, numero_expediente=f"PB{SUFIJO}-2026-{n:06d}",
                      cuil=CUIL_ANA, estado=estado, creado=actualizado, actualizado=actualizado))
    s.add(Empleador(sindicato_id=SID, cuit="30111222335", razon_social="Constructora Activa SA", activo=True))
    s.add(Empleador(sindicato_id=SID, cuit="30500000003", razon_social="Cerrada SRL", activo=False))
    s.commit()

ENC_RAIZ = db.crear_encuesta(SID, UID, None, {"titulo": "Clima laboral", "descripcion": "", "modo": "anonima",
                                              "cortes": [], "fecha_desde": "", "fecha_hasta": "",
                                              "mostrar_resultados": False}, PREGUNTAS)
ENC_2 = db.duplicar_encuesta(ENC_RAIZ, SID, UID)
ENC_3 = db.duplicar_encuesta(ENC_RAIZ, SID, UID)


def _operador(tema="laguna"):
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": OPERADOR, "clave": "clave-op"}, follow_redirects=False)
    assert r.status_code == 303, r.text
    c.post("/admin/apariencia/mia", data={"tema": tema})
    return c


HTML = _operador().get("/admin").text


def _panel(nombre: str) -> str:
    """El HTML de una pestaña: desde su <div class="panel" ...> hasta la próxima."""
    ini = HTML.index(f'id="panel-{nombre}"')
    fin = HTML.find('<div class="panel" data-mov-vista id="panel-', ini + 10)
    return HTML[ini:fin if fin > 0 else len(HTML)]


# ---------------------------------------------------------------- Noticias y Beneficios

def test_noticias_fecha_corta_sin_hora_y_sin_partirse():
    p = _panel("noticias")
    assert 'title="2026-10-08 20:59">08/10/26</span>' in p     # cargada: sin la hora, con title
    assert "2026-10-08 20:59</td>" not in p
    assert 'class="muted lst-nowrap">' in p and "lst-dest" in p
    assert 'style="background:#eee;color:#5f6676;"' not in p    # la vencida usa .tag-neutra


def test_beneficios_dicen_su_descripcion_y_llevan_miniatura():
    p = _panel("beneficios")
    assert 'class="ben-mini" src="/beneficio-imagen/' in p
    assert 'class="ben-mini vacia"' in p                        # sin imagen: el hueco dibujado
    assert '<span class="lst-baja"' in p and ">Anteojos con 30% de descuento</span>" in p
    assert "Segunda línea</span>" not in p                      # solo la primera línea


# ---------------------------------------------------------------- Notificaciones

def test_notificaciones_destino_y_leidos_en_palabras():
    p = _panel("notificaciones")
    assert "Personas puntuales (2)" in p
    assert re.search(r"0 de 2 <span class=\"lst-pct\">· 0 %</span>", p)
    assert ">CUIL</td>" not in p


# ---------------------------------------------------------------- Trámites

def test_bandeja_abre_en_sin_terminar_y_lo_que_mas_espera_arriba():
    p = _panel("tramites")
    assert re.search(r'id="tr-titulo">3 sin terminar <span class="lst-de">de 4</span>', p)
    for grupo in ("abiertos", "sindicato", "afiliado", "terminados", "todos"):
        assert f'data-grupo="{grupo}"' in p
    assert 'class="sec lst-pastilla activa" data-grupo="abiertos" aria-pressed="true"' in p
    filas = re.findall(r'data-estado="(\w+)" data-actualizado="([^"]+)"', p)
    abiertas = [f for f in filas if f[0] != "terminado"]
    assert [a for _, a in abiertas] == sorted(a for _, a in abiertas)   # el más viejo primero
    assert filas[-1][0] == "terminado"
    assert re.search(r'data-estado="terminado"[^>]*style="display:none"', p)


def test_estado_por_de_quien_es_el_proximo_paso():
    p = _panel("tramites")
    assert '<span class="tag tag-pend">Iniciado</span>' in p
    assert '<span class="tag tag-espera">Respondido</span>' in p
    assert '<span class="tag tag-espera">Espera al afiliado</span>' in p
    assert '<span class="tag tag-si">Terminado</span>' in p
    assert "A la espera de información del afiliado</span>" not in p
    # el label largo sigue siendo el de la app del afiliado: solo el panel lo acorta
    assert db.ESTADOS_TRAMITE_LABEL["espera_info"] == "A la espera de información del afiliado"


def test_bandeja_con_nombre_y_buscador_que_entra():
    p = _panel("tramites")
    assert "<th>Nombre</th>" in p and "<td>Ana Paredes</td>" in p
    assert 'data-persona="Ana Paredes"' in p
    assert 'placeholder="Nombre o CUIL"' in p and 'placeholder="N° de expediente"' in p
    assert "Buscar por N° de expediente" not in HTML
    assert all("nombre" in t for t in db.tramites_del_sindicato(SID))


def test_constructor_cuil_de_prueba_carátula_y_rotulo_corto():
    assert '<label for="tt-cuil-prueba">Probar con el CUIL de</label>' in HTML
    assert 'placeholder="CUIL de un afiliado"' in HTML
    assert "EXP — se numera al enviar" not in HTML
    assert "Área que lo recibe por defecto" not in HTML
    assert '<label for="tt-area-default">Área que lo recibe *' in HTML


# ---------------------------------------------------------------- Encuestas

def test_lista_de_encuestas_una_accion_principal_y_la_toma_por_su_numero():
    p = _panel("encuestas")
    assert "toma nueva de #" not in p
    assert "2.ª toma de «Clima laboral»" in p and "3.ª toma de «Clima laboral»" in p
    assert 'class="enc-chip' not in p                              # estados con las pastillas de la casa
    assert '<span class="tag tag-neutra">borrador</span>' in p
    assert 'class="mini lnk"' in p and 'class="mini enc-publicar"' in p
    assert 'class="peligro mini" type="submit">Borrar' in p


def test_encuesta_cerrada_en_gris_y_respuestas_con_porcentaje():
    # Una encuesta publicada con destinatarios: se arma la fila a mano.
    with db.get_session() as s:
        e = s.get(db.Encuesta, ENC_RAIZ)
        e.publicada = True
        e.cerrada_en = "2026-10-10 10:00"
        e.cantidad_destinatarios = 4
        s.add(e); s.commit()
    html = _operador().get("/admin").text
    ini = html.index('id="panel-encuestas"')
    p = html[ini:html.find('id="panel-empleadores"', ini)]
    assert '<span class="tag tag-neutra">cerrada</span>' in p
    assert re.search(r'0 de 4 <span class="lst-pct">· 0 %</span><span class="lst-barra"', p)
    assert 'class="btn-mini pri" href="/admin/encuesta/' in p


def test_constructor_de_encuestas_es_la_hoja_de_trabajo():
    p = _panel("encuestas")
    for pieza in ('class="card ct-card ct-ancho"', 'id="enc-riel"', 'class="ct-area"', 'id="enc-submit-riel"'):
        assert pieza in p, pieza
    for n in range(1, 5):
        assert f'id="enc-paso-{n}"' in p
    # el botón principal al pie de la hoja, no en la columna de preguntas
    pie = p[p.index('<div class="ct-guardar">'):]
    assert pie.index('id="enc-submit"') < pie.index("</div>")
    assert p.index('id="enc-paso-4"') < p.index('<div class="ct-guardar">') < p.index('class="ct-der"')
    # la ayuda del umbral y de los resultados vive en un «?»
    assert 'class="muted" style="font-size:11.5px; margin:0 0 8px;">\n          Sin esto, los resultados' not in p
    assert "data-ayuda=\"Sin esto, los resultados son solo totales generales." in p


def test_el_modo_no_viene_elegido_y_su_ayuda_dice_la_consecuencia():
    p = _panel("encuestas")
    sel = p[p.index('<select name="modo" id="enc-modo"'):]
    sel = sel[:sel.index("</select>")]
    assert " required" in sel and "selected" not in sel
    assert sel.index('<option value="">Elegí una…</option>') < sel.index('value="nominal"')
    assert "vas a ver el nombre y el CUIL de cada respuesta" in HTML
    assert "nadie, ni el sindicato, puede saber quién respondió qué" in HTML


def test_el_servidor_no_crea_una_encuesta_sin_modo():
    c = _operador()
    antes = len(db.encuestas_del_sindicato(SID)) if hasattr(db, "encuestas_del_sindicato") else None
    r = c.post("/admin/encuesta", data={"titulo": "Sin modo", "preguntas_json": json.dumps(PREGUNTAS)},
               follow_redirects=False)
    assert r.status_code == 303 and "error=encuesta" in r.headers["location"]
    assert "an%C3%B3nima" in r.headers["location"] or "anónima" in r.headers["location"]
    if antes is not None:
        assert len(db.encuestas_del_sindicato(SID)) == antes
    # con modo, como siempre
    r = c.post("/admin/encuesta", data={"titulo": "Con modo", "modo": "nominal",
                                        "preguntas_json": json.dumps(PREGUNTAS)}, follow_redirects=False)
    assert r.headers["location"] == "/admin#encuestas"


# ---------------------------------------------------------------- Empleadores

def test_empleadores_sin_columna_estado_y_nivel_en_palabras():
    p = _panel("empleadores")
    tabla = p[p.index("Empleadores cargados"):]
    assert "<th>Estado</th>" not in tabla[:tabla.index("</tr>")]
    assert ">sin cuenta</span>" in tabla
    assert '<span class="tag tag-neutra">dada de baja</span>' in tabla
    # la importación, con la lista y su ayuda
    cab = p[p.index('<div class="lst-cab">'):]
    assert cab.index("Importar CUIT de Conceptos") < cab.index("</div>")
    assert 'data-ayuda="Suma como empresas los CUIT' in cab


def test_empleadores_mensaje_con_ayuda_y_vacios_que_invitan():
    p = _panel("empleadores")
    assert 'placeholder="Puede incluir URLs' not in p
    assert "Podés pegar enlaces: se muestran como link." in p
    assert "Todavía no enviaste ninguna notificación a empleadores. Escribila arriba" in p
    assert "<th>Leídos</th>" not in p                          # sin filas, sin encabezados
    assert "Las empresas inician trámites desde los formularios externos que crees." in p
    assert 'onclick="abrirCrearFormulariosEmpresa()">Crear un formulario</button>' in p
    assert 'id="f-tramitesemp-cuit"' not in p                   # sin trámites no hay filtros


# ---------------------------------------------------------------- Seccionales y Listas

def test_seccionales_alcance_como_casilla_y_manual_en_verde():
    p = _panel("seccionales")
    assert '<label class="chk-suelta" for="sec-ve-todas">' in p
    assert 'class="chk-seccional" style="margin-top:10px;"' not in p
    assert re.search(r"#panel-seccionales \.geo-punto\.manual i[^{]*\{ background:#0d7a5f; \}", HTML)


def test_listas_plantillas_como_filas_y_columnas_en_pastillas():
    p = _panel("listas")
    assert 'class="pl-filas"' in p and 'class="pl-fila"' in p
    assert 'style="border:1px solid var(--linea, #e4e7ec); border-radius:10px; padding:12px;"' not in p
    assert '<span class="pl-col">cuil<span class="clave">· clave 1</span></span>' in p
    assert '<code>cuil</code>' not in p
    assert "Subir otra con el mismo nombre la reemplaza entera." not in p   # pasó al «?»
    assert 'class="lst-h3">Subir una lista' in p


# ---------------------------------------------------------------- Áreas y Usuarios

def test_areas_grupo_como_subtitulo_con_marcar_todas():
    p = _panel("administradores")
    assert 'class="chk-grupo"' not in p
    assert "Marcar todas</button>" in p and "Desmarcar</button>" in p


def test_usuarios_matriz_plegada_y_rol_en_la_misma_pastilla():
    p = _panel("administradores")
    assert '<details class="usu-ajustes" id="usu-ajustes">' in p
    assert "Sin ajustes: hereda todo del área." in p and "Elegí un área para ver qué hereda." in p
    assert 'class="toque"' in p
    assert '<span class="tag tag-rol fuerte">general</span>' in p
    assert 'tag-pend">de seccional' not in p


# ---------------------------------------------------------------- Apariencia

def test_apariencia_un_boton_por_formulario_al_pie_y_aviso_de_cambios():
    p = _panel("apariencia")
    ap = p[p.index('id="ap-form"'):p.index("</form>")]
    assert 'class="ap-guardar"' in ap and ">Guardar apariencia</button>" in ap
    assert 'id="ap-form-sucio"' in ap and 'id="td-config-sucio"' in p
    assert "Tenés cambios sin guardar" in p
    assert 'class="ap-dos"' in p


def test_apariencia_prueba_de_lectura_sin_jerga_y_tu_dia_rotulado():
    p = _panel("apariencia")
    # los números quedan en el title, no en el texto
    assert not re.search(r">\s*\(\d+,\d+:1; hace falta", p)
    assert "Así lo vamos a mostrar donde haga falta" in p or "pasan la prueba de lectura" in p
    assert ">Van siempre</span>" in p
    assert 'class="td-llave td-chica" name="politicas"' in p


# ---------------------------------------------------------------- las hojas de los modelos

def _bloque(hoja: str) -> str:
    css = Path(f"static/temas/{hoja}").read_text(encoding="utf-8")
    assert "/* Bloque 5c: panel B (auditoría 2026-10) */" in css, hoja
    return css[css.index("/* Bloque 5c: panel B (auditoría 2026-10) */"):]


def test_las_hojas_suman_su_bloque_y_cada_selector_es_de_su_modelo():
    for hoja, modelo in (("laguna-panel.css", "laguna"), ("noticiero-panel.css", "noticiero")):
        bloque = re.sub(r"/\*.*?\*/", "", _bloque(hoja), flags=re.S)
        for regla in re.findall(r"([^{}]+)\{", bloque):
            for sel in regla.split(","):
                sel = sel.strip()
                if sel and not sel.startswith("@"):
                    assert sel.startswith(f'html[data-tema="{modelo}"]'), (hoja, sel)
        assert ".tag-neutra" in bloque and ".tag-espera" in bloque and "lst-pastilla.activa" in bloque


def test_laguna_interruptores_en_el_azul_y_noticiero_alinea_el_rotulo():
    assert 'html[data-tema="laguna"] .td-llave:checked { background: var(--lg-azul); }' in _bloque("laguna-panel.css")
    noti = _bloque("noticiero-panel.css")
    assert "#tt-paso-2 .grid2 { align-items: end; }" in noti
    assert "button.pri-riel:not(#riel) { white-space: nowrap;" in noti
