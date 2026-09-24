"""Reportes unificados (2026-09-24): la pestaña Reportes del panel del
sindicato absorbe a Cotizantes y suma los recibos que el afiliado verificó y
NO envió, anonimizados, detrás de la cláusula de confidencialidad que carga
plataforma.

Cubre:
- Privacidad en el SQL: un recibo no enviado no expone nombre, CUIL ni
  empresa en ninguna respuesta (lista ni modal).
- Compuerta: sin la cláusula firmada, los no enviados no se listan ni se
  abren; la lista dice cuántos quedaron afuera.
- La búsqueda por CUIL o por nombre no encuentra recibos no enviados (si los
  encontrara, el filtro identificaría la fila anónima).
- Aislamiento de tenant, recorte por seccional y permiso de sección.
- Plataforma: la cláusula exige el contrato cargado, registra quién y cuándo,
  y el contrato solo lo baja plataforma.

Correr con: .venv/Scripts/python.exe -m pytest test_reportes_unificados.py -q
"""
import os

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import auth
import db
import permisos
from db import (Sindicato, UsuarioSindicato, UsuarioPlataforma, Trabajador, Seccional,
                Empleador, ReciboVerificado, Area, PermisoArea)
import main
from fastapi.testclient import TestClient

db.crear_tablas()

CUIL_ENV, CUIL_PRIV, CUIL_OTRA_SEC, CUIL_AJENO = "20411111113", "27422222228", "20433333331", "20444444449"


def _recibo(sid, cuil, enviado, estado, cuando, cuit, nombre, empresa):
    return ReciboVerificado(
        sindicato_id=sid, cuil=cuil, periodo="2026-08", fecha=cuando,
        estado=estado, enviado_sindicato=enviado,
        detalle={"recibo": {"empleado": {"apellido_nombre": nombre, "cuil": cuil, "legajo": "L-777"},
                            "empleador": {"nombre": empresa, "cuit": cuit},
                            "lineas": [{"descripcion": "Sueldo básico", "importe": 800000.0}]},
                 "resultado": {"cuil": cuil, "estado": estado,
                               "totales": {"ingresos": 800000.0, "descuentos": 0.0}}},
        procesado_en="2026-09-0" + cuando[1] + " 10:00", cuit_empleador=cuit,
        monto_diferencia=0.0 if estado == "OK" else 1000.0)


with db.get_session() as s:
    sind = Sindicato(nombre="Rep Unif", slug="rep-unif", color_base="#0f1b2d",
                     modulos_habilitados=["recibos"])
    otro = Sindicato(nombre="Rep Ajeno", slug="rep-ajeno", color_base="#0f1b2d",
                     modulos_habilitados=["recibos"])
    sin_recibos = Sindicato(nombre="Rep Sin Modulo", slug="rep-sin-mod", color_base="#0f1b2d",
                            modulos_habilitados=[])
    s.add(sind); s.add(otro); s.add(sin_recibos); s.commit()
    s.refresh(sind); s.refresh(otro); s.refresh(sin_recibos)
    SID, SID_OTRO, SID_SIN = sind.id, otro.id, sin_recibos.id

    sec_1 = Seccional(sindicato_id=SID, nombre="Rosario")
    sec_2 = Seccional(sindicato_id=SID, nombre="Mendoza")
    s.add(sec_1); s.add(sec_2); s.commit(); s.refresh(sec_1); s.refresh(sec_2)
    SEC_1, SEC_2 = sec_1.id, sec_2.id

    s.add(Empleador(sindicato_id=SID, cuit="30555555553", razon_social="Aceros Visible SA"))
    s.add(Empleador(sindicato_id=SID, cuit="30666666664", razon_social="Oculta Textil SRL"))

    for cuil, nombre, sec in ((CUIL_ENV, "Carla Enviadora", SEC_1),
                              (CUIL_PRIV, "Pedro Reservado", SEC_1),
                              (CUIL_OTRA_SEC, "Marta Mendocina", SEC_2)):
        s.add(Trabajador(sindicato_id=SID, cuil=cuil, registrado=True, seccional_id=sec))
        db.guardar_datos_personales(s, cuil, nombre=nombre)
    s.add(Trabajador(sindicato_id=SID_OTRO, cuil=CUIL_AJENO, registrado=True))
    db.guardar_datos_personales(s, CUIL_AJENO, nombre="Ajeno Total")

    s.add(_recibo(SID, CUIL_ENV, True, "CON_DISCREPANCIAS", "01/09/2026 10:00",
                  "30555555553", "Carla Enviadora", "Aceros Visible SA"))
    s.add(_recibo(SID, CUIL_PRIV, False, "OK", "02/09/2026 10:00",
                  "30666666664", "Pedro Reservado", "Oculta Textil SRL"))
    s.add(_recibo(SID, CUIL_OTRA_SEC, False, "CON_DISCREPANCIAS", "03/09/2026 10:00",
                  "30666666664", "Marta Mendocina", "Oculta Textil SRL"))
    s.add(_recibo(SID_OTRO, CUIL_AJENO, True, "OK", "04/09/2026 10:00",
                  "30777777775", "Ajeno Total", "Ajena SA"))

    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20455555550", nombre="Super",
                           clave_hash=auth.hashear_clave("super-demo"),
                           debe_cambiar_clave=False, es_super_admin=True))
    area = Area(sindicato_id=SID, seccional_id=SEC_1, nombre="Tesorería Rosario")
    area_sin = Area(sindicato_id=SID, seccional_id=SEC_1, nombre="Prensa Rosario")
    s.add(area); s.add(area_sin); s.commit(); s.refresh(area); s.refresh(area_sin)
    s.add(PermisoArea(area_id=area.id, seccion="reportes"))
    s.add(PermisoArea(area_id=area_sin.id, seccion="trabajadores"))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20466666661", nombre="Tesorera",
                           clave_hash=auth.hashear_clave("teso-demo"), debe_cambiar_clave=False,
                           area_id=area.id, seccional_id=SEC_1))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20477777772", nombre="Prensa",
                           clave_hash=auth.hashear_clave("prensa-demo"), debe_cambiar_clave=False,
                           area_id=area_sin.id, seccional_id=SEC_1))
    s.add(UsuarioSindicato(sindicato_id=SID_SIN, usuario="20488888883", nombre="Sin",
                           clave_hash=auth.hashear_clave("sin-demo"),
                           debe_cambiar_clave=False, es_super_admin=True))
    s.add(UsuarioPlataforma(usuario="opera", nombre="Operadora",
                            clave_hash=auth.hashear_clave("claveLarga2026"), rol="superadmin",
                            debe_cambiar_clave=False, debe_completar_datos=False, creado_por="test"))
    s.commit()


def _admin(usuario, clave):
    c = TestClient(main.app)
    c.post("/admin/login", data={"usuario": usuario, "clave": clave})
    return c


def _plataforma():
    c = TestClient(main.app)
    r = c.post("/plataforma/login", data={"usuario": "opera", "clave": "claveLarga2026"},
               follow_redirects=False)
    assert r.status_code == 303, r.text
    return c


def _clausula(valor: bool):
    with db.get_session() as s:
        sd = s.get(Sindicato, SID)
        sd.clausula_confidencialidad = valor
        s.add(sd); s.commit()


def _lista(c, **params):
    r = c.get("/admin/reportes/lista", params=params)
    assert r.status_code == 200, r.text
    return r


def _id_de(cuil):
    with db.get_session() as s:
        return s.query(ReciboVerificado).filter(ReciboVerificado.cuil == cuil).one().id


SUPER = _admin("20455555550", "super-demo")


def _sin_rastros(texto: str, *cuiles):
    """Ningún dato que identifique al trabajador o a la empresa de un recibo
    no enviado aparece en el texto de la respuesta."""
    for cuil in cuiles:
        assert cuil not in texto
    for dato in ("Pedro", "Reservado", "Marta", "Mendocina", "Oculta", "30666666664", "L-777"):
        assert dato not in texto, dato


# ---------- Compuerta de la cláusula ----------

def test_sin_clausula_solo_ve_los_enviados():
    _clausula(False)
    r = _lista(SUPER)
    d = r.json()
    assert d["clausula"] is False
    assert d["total"] == 1 and [x["cuil"] for x in d["items"]] == [CUIL_ENV]
    assert d["ocultos_sin_clausula"] == 2
    _sin_rastros(r.text, CUIL_PRIV, CUIL_OTRA_SEC)
    # El modal tampoco abre un recibo no enviado.
    assert SUPER.get(f"/admin/reportes/recibo/{_id_de(CUIL_PRIV)}").status_code == 404
    # Y el explorador del Panel, tampoco (mismo criterio en las dos vistas).
    import dashboard
    assert dashboard.detalle_recibo(SID, _id_de(CUIL_PRIV)) is None
    print("OK  test_sin_clausula_solo_ve_los_enviados")


def test_con_clausula_ve_todos_anonimizados():
    _clausula(True)
    r = _lista(SUPER)
    d = r.json()
    assert d["clausula"] is True and d["ocultos_sin_clausula"] == 0
    assert d["total"] == 3
    por_env = {x["enviado"]: x for x in d["items"]}
    env = por_env[True]
    assert env["cuil"] == CUIL_ENV and env["nombre"] == "Carla Enviadora"
    assert env["empresa"] == "Aceros Visible SA" and env["con_diferencias"] is True
    anonimos = [x for x in d["items"] if not x["enviado"]]
    assert len(anonimos) == 2
    for x in anonimos:
        assert x["cuil"] is None and x["nombre"] is None and x["empresa"] is None
    # Del más nuevo al más viejo.
    assert [x["fecha"][:2] for x in d["items"]] == ["03", "02", "01"]
    _sin_rastros(r.text, CUIL_PRIV, CUIL_OTRA_SEC)
    print("OK  test_con_clausula_ve_todos_anonimizados")


def test_modal_de_no_enviado_sale_anonimizado():
    _clausula(True)
    r = SUPER.get(f"/admin/reportes/recibo/{_id_de(CUIL_PRIV)}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["enviado"] is False and d["empresa"] == "—"
    assert d["trabajador_cuil"] is None and d["trabajador_nombre"] is None
    assert d["recibo"]["empleador"] == {}
    assert d["recibo"]["lineas"][0]["importe"] == 800000.0
    _sin_rastros(r.text, CUIL_PRIV)
    # El enviado, en cambio, llega identificado.
    d2 = SUPER.get(f"/admin/reportes/recibo/{_id_de(CUIL_ENV)}").json()
    assert d2["trabajador_cuil"] == CUIL_ENV and d2["empresa"] == "Aceros Visible SA"
    print("OK  test_modal_de_no_enviado_sale_anonimizado")


# ---------- Filtros ----------

def test_buscar_por_cuil_o_nombre_no_delata_a_un_no_enviado():
    _clausula(True)
    for params in ({"cuil": CUIL_PRIV}, {"cuil": CUIL_PRIV[2:8]},
                   {"nombre": "pedro"}, {"nombre": "Reservado"}):
        d = _lista(SUPER, **params).json()
        assert d["total"] == 0, params
    # El enviado sí se encuentra, por CUIL con guiones y por nombre sin tilde.
    assert _lista(SUPER, cuil="20-41111111-3").json()["total"] == 1
    assert _lista(SUPER, nombre="carla enviadora").json()["total"] == 1
    print("OK  test_buscar_por_cuil_o_nombre_no_delata_a_un_no_enviado")


def test_filtros_de_resultado_enviado_y_fecha():
    _clausula(True)
    assert _lista(SUPER, resultado="ok").json()["total"] == 1
    assert _lista(SUPER, resultado="con_diferencias").json()["total"] == 2
    assert _lista(SUPER, enviado="si").json()["total"] == 1
    assert _lista(SUPER, enviado="no").json()["total"] == 2
    assert _lista(SUPER, desde="2026-09-02", hasta="2026-09-02").json()["total"] == 1
    assert SUPER.get("/admin/reportes/lista", params={"desde": "02/09/2026"}).status_code == 422
    print("OK  test_filtros_de_resultado_enviado_y_fecha")


# ---------- Aislamiento, alcance y permisos ----------

def test_aislamiento_de_tenant():
    _clausula(True)
    r = _lista(SUPER)
    assert CUIL_AJENO not in r.text and "Ajeno" not in r.text
    assert SUPER.get(f"/admin/reportes/recibo/{_id_de(CUIL_AJENO)}").status_code == 404
    print("OK  test_aislamiento_de_tenant")


def test_usuario_de_area_ve_solo_su_seccional():
    _clausula(True)
    teso = _admin("20466666661", "teso-demo")
    d = _lista(teso).json()
    assert d["total"] == 2   # Rosario: el enviado y el anónimo; Mendoza no
    assert teso.get(f"/admin/reportes/recibo/{_id_de(CUIL_OTRA_SEC)}").status_code == 404
    assert teso.get(f"/admin/reportes/recibo/{_id_de(CUIL_PRIV)}").status_code == 200
    print("OK  test_usuario_de_area_ve_solo_su_seccional")


def test_sin_permiso_de_reportes_403():
    prensa = _admin("20477777772", "prensa-demo")
    assert prensa.get("/admin/reportes/lista").status_code == 403
    assert prensa.get(f"/admin/reportes/recibo/{_id_de(CUIL_ENV)}").status_code == 403
    print("OK  test_sin_permiso_de_reportes_403")


def test_sin_modulo_recibos_403():
    sin = _admin("20488888883", "sin-demo")
    assert sin.get("/admin/reportes/lista").status_code == 403
    print("OK  test_sin_modulo_recibos_403")


def test_cotizantes_ya_no_es_una_seccion_ni_una_pestana():
    assert "cotizantes" not in permisos.SECCIONES
    html = SUPER.get("/admin").text
    assert 'data-panel="reportes"' in html
    assert 'data-panel="cotizantes"' not in html
    # Los recibos ya no viajan en el HTML del panel (las personas sí, en el
    # padrón de Trabajadores, que es otra cosa).
    assert "L-777" not in html and "Sueldo básico" not in html
    print("OK  test_cotizantes_ya_no_es_una_seccion_ni_una_pestana")


# ---------- Plataforma: cláusula y contrato ----------

def _form_edicion(**extra):
    datos = {"id": str(SID), "nombre": "Rep Unif", "color_base": "#0f1b2d",
             "modulos_habilitados": ["recibos"]}
    datos.update(extra)
    return datos


def test_clausula_sin_contrato_se_rechaza():
    _clausula(False)
    c = _plataforma()
    r = c.post("/plataforma/sindicato/editar",
               data=_form_edicion(clausula_confidencialidad="true"), follow_redirects=False)
    assert r.status_code == 303 and "error=clausula" in r.headers["location"]
    with db.get_session() as s:
        assert s.get(Sindicato, SID).clausula_confidencialidad is False
    print("OK  test_clausula_sin_contrato_se_rechaza")


def test_contrato_invalido_se_rechaza():
    c = _plataforma()
    r = c.post("/plataforma/sindicato/editar", data=_form_edicion(),
               files={"contrato": ("contrato.exe", b"MZ...", "application/octet-stream")},
               follow_redirects=False)
    assert "error=contrato" in r.headers["location"]
    print("OK  test_contrato_invalido_se_rechaza")


def test_clausula_con_contrato_registra_quien_y_cuando():
    _clausula(False)
    c = _plataforma()
    r = c.post("/plataforma/sindicato/editar",
               data=_form_edicion(clausula_confidencialidad="true"),
               files={"contrato": ("Convenio firmado ñandú.pdf", b"%PDF-1.4 prueba", "application/pdf")},
               follow_redirects=False)
    assert r.status_code == 303 and "error" not in r.headers["location"], r.headers["location"]
    with db.get_session() as s:
        sd = s.get(Sindicato, SID)
        assert sd.clausula_confidencialidad is True
        assert sd.clausula_aceptada_por == "opera" and sd.clausula_aceptada_en
        assert sd.contrato_mime == "application/pdf"
        fecha = sd.clausula_aceptada_en
    # Volver a guardar la ficha no reescribe la fecha de aceptación.
    c.post("/plataforma/sindicato/editar", data=_form_edicion(clausula_confidencialidad="true"))
    with db.get_session() as s:
        assert s.get(Sindicato, SID).clausula_aceptada_en == fecha
    # El contrato lo baja plataforma; un admin del sindicato, no.
    r = c.get(f"/plataforma/sindicato/{SID}/contrato")
    assert r.status_code == 200 and r.content == b"%PDF-1.4 prueba"
    assert SUPER.get(f"/plataforma/sindicato/{SID}/contrato",
                     follow_redirects=False).status_code in (302, 303, 401, 403)
    # Destildarla borra quién y cuándo.
    c.post("/plataforma/sindicato/editar", data=_form_edicion())
    with db.get_session() as s:
        sd = s.get(Sindicato, SID)
        assert sd.clausula_confidencialidad is False
        assert sd.clausula_aceptada_por == "" and sd.clausula_aceptada_en == ""
        assert sd.contrato_datos   # el contrato queda cargado
    print("OK  test_clausula_con_contrato_registra_quien_y_cuando")
