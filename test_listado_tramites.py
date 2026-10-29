"""El listado de trámites con sus respuestas (CSV desde la pestaña Trámites,
2026-10-28; cierra la brecha «exportar» del Asistente de trámites, BACKLOG
«seis brechas» 4). Desde el 2026-10-29 el CSV baja lo que la bandeja tiene
filtrado (SDN: «ponés los filtros para todo el listado y con lo filtrado
bajás a CSV»): formulario, estado o pastilla, seccional, nombre o CUIL y
expediente son filtros de la tabla, y con un formulario elegido sale una
columna por pregunta. Dentro del alcance del operador, y cada descarga
registrada.

Correr con: python -m pytest test_listado_tramites.py -q
"""
import db
import auth
from db import Sindicato, UsuarioSindicato, Trabajador, Seccional, Area, DescargaListado
from modulos import MODULOS_INICIALES
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()

GENERAL, LOCAL = "20111111120", "20555555556"
ANA, FABIAN = "27222222228", "20888888889"

with db.get_session() as s:
    sind = Sindicato(nombre="Sindicato Listado", slug="listado", color_base="#0f1b2d",
                     modulos_habilitados=list(MODULOS_INICIALES) + ["tramites", "notificaciones"])
    otro = Sindicato(nombre="Otro Listado", slug="otro-listado", color_base="#0f1b2d",
                     modulos_habilitados=list(MODULOS_INICIALES) + ["tramites"])
    s.add(sind); s.add(otro); s.commit(); s.refresh(sind); s.refresh(otro)
    SID, OTRO = sind.id, otro.id
    central = Seccional(sindicato_id=SID, nombre="Sede Central", ve_todas=True)
    ros = Seccional(sindicato_id=SID, nombre="Rosario")
    cba = Seccional(sindicato_id=SID, nombre="Córdoba")
    s.add(central); s.add(ros); s.add(cba); s.commit(); s.refresh(central); s.refresh(ros); s.refresh(cba)
    SEC_ROS, SEC_CBA = ros.id, cba.id
    area = Area(sindicato_id=SID, seccional_id=central.id, nombre="Acción Social")
    s.add(area); s.commit(); s.refresh(area)
    AREA = area.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=GENERAL, cuil=GENERAL, nombre="General",
                           clave_hash=auth.hashear_clave("gen"), debe_cambiar_clave=False, es_super_admin=True))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=LOCAL, cuil=LOCAL, nombre="Local Rosario",
                           clave_hash=auth.hashear_clave("loc"), debe_cambiar_clave=False,
                           es_admin_seccional=True, seccional_id=SEC_ROS))
    for cuil, nombre, sec in ((ANA, "Ana Rosario", SEC_ROS), (FABIAN, "Fabián Córdoba", SEC_CBA)):
        s.add(Trabajador(sindicato_id=SID, cuil=cuil, seccional_id=sec, activo=True, registrado=True))
        db.guardar_datos_personales(s, cuil, nombre=nombre)
    s.commit()

TIPO = db.crear_tipo_tramite(SID, "Kit escolar", "KIT", [
    {"etiqueta": "Datos", "tipo_dato": "separador", "obligatorio": False, "validaciones": []},
    {"etiqueta": "Nombre del chico", "tipo_dato": "texto", "obligatorio": True, "validaciones": []},
    {"etiqueta": "DNI del chico", "tipo_dato": "archivo", "obligatorio": True,
     "tipos_archivo_permitidos": "pdf", "validaciones": []},
], area_destino_default_id=AREA)
AJENO = db.crear_tipo_tramite(OTRO, "Ajeno", "AJ", [
    {"etiqueta": "Dato", "tipo_dato": "texto", "obligatorio": True, "validaciones": []}])


def _cliente(usuario, clave):
    c = TestClient(main.app)
    c.post("/admin/login", data={"usuario": usuario, "clave": clave})
    return c


def _afiliado(cuil):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=SID, ident=cuil))
    c.cookies.set("cuil_trab", cuil)
    return c


def _campo(etiqueta):
    return next(c["id"] for c in db.tipo_tramite_por_id(TIPO)["campos"] if c["etiqueta"] == etiqueta)


def _enviar(cuil, chico):
    r = _afiliado(cuil).post("/api/tramite", data={"tipo_tramite_id": TIPO, f"campo_{_campo('Nombre del chico')}": chico},
                             files={f"archivo_{_campo('DNI del chico')}": (f"dni-{chico}.pdf", b"%PDF-1.4 x", "application/pdf")})
    assert r.status_code == 200, r.text
    return r.json()


def _filas(texto):
    lineas = [l for l in texto.lstrip("﻿").splitlines() if l]
    return lineas[0].split(";"), [l.split(";") for l in lineas[1:]]


def test_el_listado_trae_una_fila_por_pedido_y_una_columna_por_pregunta():
    _enviar(ANA, "Martina"); _enviar(FABIAN, "Tomás")
    r = _cliente(GENERAL, "gen").get(f"/admin/tramites/listado.csv?tipo_id={TIPO}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'filename="tramites-kit-' in r.headers["content-disposition"]
    cab, filas = _filas(r.text)
    assert cab == ["Expediente", "Iniciado", "Actualizado", "Estado", "Apellido y nombre", "CUIL", "Seccional", "Área a cargo",
                   "Nombre del chico", "DNI del chico"], "el separador no es una columna; el archivo sale con su nombre"
    assert len(filas) == 2
    ana = next(f for f in filas if f[5] == ANA)
    assert ana[3] == "Iniciado" and ana[4] == "Ana Rosario" and ana[6] == "Rosario" and ana[7] == "Acción Social"
    assert ana[8] == "Martina" and ana[9] == "dni-Martina.pdf"
    assert ana[0].startswith("KIT-")


def test_los_filtros_de_estado_y_seccional_recortan():
    c = _cliente(GENERAL, "gen")
    assert len(_filas(c.get(f"/admin/tramites/listado.csv?tipo_id={TIPO}&estado=iniciado").text)[1]) == 2
    assert len(_filas(c.get(f"/admin/tramites/listado.csv?tipo_id={TIPO}&estado=terminado").text)[1]) == 0
    cba = _filas(c.get(f"/admin/tramites/listado.csv?tipo_id={TIPO}&seccional_id={SEC_CBA}").text)[1]
    assert [f[4] for f in cba] == ["Fabián Córdoba"]
    assert c.get(f"/admin/tramites/listado.csv?tipo_id={TIPO}&estado=raro").status_code == 400
    assert c.get(f"/admin/tramites/listado.csv?tipo_id={TIPO}&seccional_id=x").status_code == 400


def test_el_admin_local_baja_solo_su_seccional_y_no_elige_otra():
    c = _cliente(LOCAL, "loc")
    filas = _filas(c.get(f"/admin/tramites/listado.csv?tipo_id={TIPO}").text)[1]
    assert [f[4] for f in filas] == ["Ana Rosario"], "el recorte va en la consulta"
    assert c.get(f"/admin/tramites/listado.csv?tipo_id={TIPO}&seccional_id={SEC_CBA}").status_code == 403
    assert len(_filas(c.get(f"/admin/tramites/listado.csv?tipo_id={TIPO}&seccional_id={SEC_ROS}").text)[1]) == 1


def test_sin_formulario_baja_todo_lo_filtrado_con_la_columna_formulario():
    c = _cliente(GENERAL, "gen")
    r = c.get("/admin/tramites/listado.csv")
    assert r.status_code == 200 and 'filename="tramites-2' in r.headers["content-disposition"]
    cab, filas = _filas(r.text)
    assert cab == ["Expediente", "Formulario", "Iniciado", "Actualizado", "Estado", "Apellido y nombre", "CUIL",
                   "Seccional", "Área a cargo"], "sin formulario no hay columnas de preguntas, y se dice cuál es"
    assert len(filas) == 2 and {f[1] for f in filas} == {"Kit escolar"}
    # Los mismos filtros de la pantalla: nombre o CUIL, expediente y la pastilla.
    assert [f[6] for f in _filas(c.get("/admin/tramites/listado.csv?q=ana").text)[1]] == [ANA]
    assert [f[6] for f in _filas(c.get(f"/admin/tramites/listado.csv?q={FABIAN[:6]}").text)[1]] == [FABIAN]
    assert len(_filas(c.get("/admin/tramites/listado.csv?expediente=KIT-").text)[1]) == 2
    assert len(_filas(c.get("/admin/tramites/listado.csv?expediente=ZZZ").text)[1]) == 0
    assert len(_filas(c.get("/admin/tramites/listado.csv?grupo=sindicato").text)[1]) == 2
    assert len(_filas(c.get("/admin/tramites/listado.csv?grupo=terminados").text)[1]) == 0
    assert c.get("/admin/tramites/listado.csv?grupo=raro").status_code == 400


def test_un_formulario_ajeno_es_404_y_cada_descarga_queda_registrada():
    c = _cliente(GENERAL, "gen")
    assert c.get(f"/admin/tramites/listado.csv?tipo_id={AJENO}").status_code == 404
    assert c.get("/admin/tramites/listado.csv?tipo_id=999999").status_code == 404
    with Session(db.engine) as s:
        regs = s.exec(select(DescargaListado).where(DescargaListado.sindicato_id == SID).order_by(DescargaListado.id)).all()
    assert len(regs) >= 5 and regs[0].filas == 2 and regs[0].filtros == "formulario KIT" and regs[0].fecha
    assert any(r.filtros == "formulario KIT · estado terminado" and r.filas == 0 for r in regs)
    assert any(r.tipo_tramite_id is None and r.filtros == "sin filtros" and r.filas == 2 for r in regs), \
        "la descarga sin formulario también se registra"
    assert any(r.filtros == "busca «ana»" for r in regs)
    assert all(r.usuario_id for r in regs) and all(r.tipo_tramite_id in (TIPO, None) for r in regs)
    assert not any(r.tipo_tramite_id == AJENO for r in regs), "lo que no se bajó no se registra"


def test_la_bandeja_filtra_por_formulario_y_seccional_y_baja_lo_filtrado():
    def bandeja(html):
        i = html.index('id="f-tramites-cuit"')
        return html[i:html.index('id="tr-tabla"', i)]
    html = _cliente(GENERAL, "gen").get("/admin").text
    b = bandeja(html)
    assert 'id="f-tramites-tipo"' in b and 'id="f-tramites-estado"' in b and 'id="f-tramites-seccional"' in b
    assert 'id="tr-descargar"' in b and "descargarListadoTramites()" in b
    assert 'id="tr-listado"' not in html, "no hay un formulario aparte para el CSV: baja lo filtrado"
    assert 'data-tipo="%d"' % TIPO in html and 'data-seccional="%d"' % SEC_ROS in html
    assert "/admin/tramites/listado.csv" in html
    local = _cliente(LOCAL, "loc").get("/admin").text
    assert 'id="f-tramites-seccional"' not in bandeja(local), "con una sola seccional no se elige"
    assert 'id="f-tramites-tipo"' in bandeja(local)
