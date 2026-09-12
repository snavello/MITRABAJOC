"""Mapa de seccionales del Panel Sindical (GET /admin/dashboard/seccionales-geo).

Lo que se verifica, en orden de importancia:

- **Aislamiento**: el mapa de un sindicato no muestra la seccional de otro,
  ni pidiéndola por id en la query.
- **Privacidad**: la respuesta son SEIS NÚMEROS por seccional y nada más. El
  mapa no puede ser un explorador con otra cara, así que se barre el JSON
  crudo buscando cualquier nombre o CUIL del padrón.
- **Los agregados dan bien**, incluidos los dos que son foto del padrón y no
  se mueven con el período.
- **El mapa ignora su propio filtro de seccional** (es el selector) pero
  respeta período y empresa.
- Las seccionales sin coordenadas viajan aparte, no desaparecen.

Correr con: .venv/bin/python -m pytest test_panel_seccionales_geo.py -q
"""
from datetime import timedelta

import auth
import db
import fechas
import geo
import main
from db import (Sindicato, UsuarioSindicato, Trabajador, Seccional, Empleador,
                ReciboVerificado, TipoTramite, Tramite, Notificacion,
                NotificacionDestinatario)
from fastapi.testclient import TestClient

db.crear_tablas()

HOY = fechas.hoy()


def _dia(atras=0):
    return (HOY - timedelta(days=atras)).isoformat()


def _ts(atras=0, hora="10:00"):
    return _dia(atras) + " " + hora


RANGO = {"desde": _dia(30), "hasta": _dia(0)}

DOM_ROSARIO = geo.campos_para_guardar(
    {"calle": "San Martín", "numero": "850", "localidad": "Rosario", "provincia": "Santa Fe"},
    precision="exacta", lat=-32.947338, lon=-60.636893)
DOM_CORDOBA = geo.campos_para_guardar(
    {"calle": "Boulevard San Juan", "numero": "430", "localidad": "Córdoba", "provincia": "Córdoba"},
    precision="manual", lat=-31.419157, lon=-64.191904)

with db.get_session() as s:
    a = Sindicato(nombre="UOM Geo", slug="uom-geo", color_base="#0f1b2d",
                  modulos_habilitados=["dashboard", "tramites", "notificaciones"])
    b = Sindicato(nombre="Fega Geo", slug="fega-geo", color_base="#0d2027",
                  modulos_habilitados=["dashboard"])
    s.add(a); s.add(b); s.commit(); s.refresh(a); s.refresh(b)
    SID_A, SID_B = a.id, b.id

    s.add(UsuarioSindicato(sindicato_id=SID_A, usuario="20111111110", nombre="Admin A",
                           clave_hash=auth.hashear_clave("a-demo"),
                           debe_cambiar_clave=False, es_super_admin=True))
    s.add(UsuarioSindicato(sindicato_id=SID_B, usuario="20222222220", nombre="Admin B",
                           clave_hash=auth.hashear_clave("b-demo"),
                           debe_cambiar_clave=False, es_super_admin=True))

    # Rosario ubicada, Córdoba ubicada, "Sin Ubicar" sin coordenadas: los tres
    # casos que la pantalla tiene que distinguir.
    ros = Seccional(sindicato_id=SID_A, nombre="Rosario", **DOM_ROSARIO)
    cba = Seccional(sindicato_id=SID_A, nombre="Córdoba", **DOM_CORDOBA)
    nada = Seccional(sindicato_id=SID_A, nombre="Sin Ubicar")
    ajena = Seccional(sindicato_id=SID_B, nombre="Seccional Ajena", **DOM_ROSARIO)
    s.add(ros); s.add(cba); s.add(nada); s.add(ajena)
    s.commit()
    for x in (ros, cba, nada, ajena):
        s.refresh(x)
    SEC_ROS, SEC_CBA, SEC_NADA, SEC_AJENA = ros.id, cba.id, nada.id, ajena.id

    s.add(Empleador(sindicato_id=SID_A, cuit="30111111117", razon_social="Metalsur SA"))
    s.add(Empleador(sindicato_id=SID_A, cuit="30222222225", razon_social="Textil Belgrano"))
    s.commit()

    # Padrón: 3 en Rosario (2 registrados), 1 en Córdoba (0 registrados).
    # Los nombres son rebuscados a propósito: se los busca después en el JSON
    # crudo de la respuesta para probar que NO viajan.
    s.add(Trabajador(sindicato_id=SID_A, cuil="20111111119", nombre="Zoltan Kerekes",
                     registrado=True, seccional_id=SEC_ROS, cuit_empleador="30111111117"))
    s.add(Trabajador(sindicato_id=SID_A, cuil="20222222227", nombre="Hipolita Quiroga",
                     registrado=True, seccional_id=SEC_ROS, cuit_empleador="30222222225"))
    s.add(Trabajador(sindicato_id=SID_A, cuil="20333333336", nombre="Bartolome Nunez",
                     registrado=False, seccional_id=SEC_ROS, cuit_empleador="30111111117"))
    s.add(Trabajador(sindicato_id=SID_A, cuil="20444444440", nombre="Casilda Etchevarne",
                     registrado=False, seccional_id=SEC_CBA, cuit_empleador="30111111117"))
    # Sin seccional: no tiene que aparecer en ninguna fila del mapa.
    s.add(Trabajador(sindicato_id=SID_A, cuil="20555555553", nombre="Nadie Sinseccional",
                     registrado=True, cuit_empleador="30111111117"))
    s.add(Trabajador(sindicato_id=SID_B, cuil="20999999995", nombre="Ajeno Total",
                     registrado=True, seccional_id=SEC_AJENA))

    # Recibos: 3 en Rosario (1 con diferencias), 1 en Córdoba (OK), y uno
    # VIEJO en Rosario fuera del rango, para que el período se note.
    def recibo(cuil, estado, atras, cuit="30111111117"):
        return ReciboVerificado(
            sindicato_id=SID_A, cuil=cuil, estado=estado, fecha=_ts(atras),
            procesado_en=_ts(atras), cuit_empleador=cuit, bruto=800000,
            monto_diferencia=1500 if estado == "CON_DISCREPANCIAS" else 0,
            formato="nuevo", categoria="Oficial", detalle={}, enviado_sindicato=False)
    s.add(recibo("20111111119", "OK", 5))
    s.add(recibo("20222222227", "OK", 6, cuit="30222222225"))
    s.add(recibo("20333333336", "CON_DISCREPANCIAS", 7))
    s.add(recibo("20444444440", "OK", 8))
    s.add(recibo("20111111119", "OK", 200))          # fuera del rango de 30 días

    tt = TipoTramite(sindicato_id=SID_A, codigo="UOMGEO-01", titulo="Trámite geo", activo=True)
    s.add(tt); s.commit(); s.refresh(tt)
    s.add(Tramite(sindicato_id=SID_A, tipo_tramite_id=tt.id, cuil="20111111119",
                  numero_expediente="UOMGEO-01-0001", estado="iniciado",
                  creado=_ts(3), actualizado=_ts(3), datos={}))
    s.add(Tramite(sindicato_id=SID_A, tipo_tramite_id=tt.id, cuil="20222222227",
                  numero_expediente="UOMGEO-01-0002", estado="terminado",
                  creado=_ts(4), actualizado=_ts(2), resuelto_en=_ts(2), datos={}))

    n = Notificacion(sindicato_id=SID_A, titulo="Aviso", cuerpo="x", origen="manual",
                     criterio="cuil", valores=[], enviado_en=_ts(3))
    s.add(n); s.commit(); s.refresh(n)
    s.add(NotificacionDestinatario(notificacion_id=n.id, cuil="20111111119", leida_en=_ts(2)))
    s.add(NotificacionDestinatario(notificacion_id=n.id, cuil="20222222227"))
    s.commit()

cliente_a = TestClient(main.app)
cliente_a.post("/admin/login", data={"usuario": "20111111110", "clave": "a-demo"})
cliente_b = TestClient(main.app)
cliente_b.post("/admin/login", data={"usuario": "20222222220", "clave": "b-demo"})


def _pedir(cliente=None, **extra):
    r = (cliente or cliente_a).get("/admin/dashboard/seccionales-geo",
                                   params={**RANGO, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _por_nombre(datos):
    return {s["nombre"]: s for s in datos["seccionales"]}


# ------------------------------------------------------------- aislamiento

def test_no_aparece_la_seccional_de_otro_sindicato():
    todas = _por_nombre(_pedir())
    assert "Seccional Ajena" not in todas
    assert set(todas) == {"Rosario", "Córdoba"}
    print("OK  test_no_aparece_la_seccional_de_otro_sindicato")


def test_pedir_una_seccional_ajena_por_id_no_la_trae():
    # El filtro de seccional lo ignora el mapa (es el selector), así que un
    # id ajeno no puede colarse ni como filtro ni como fila.
    datos = _pedir(seccionales=str(SEC_AJENA))
    assert "Seccional Ajena" not in _por_nombre(datos)
    assert set(_por_nombre(datos)) == {"Rosario", "Córdoba"}
    print("OK  test_pedir_una_seccional_ajena_por_id_no_la_trae")


def test_el_otro_sindicato_ve_solo_lo_suyo():
    datos = _pedir(cliente_b)
    assert set(_por_nombre(datos)) == {"Seccional Ajena"}
    print("OK  test_el_otro_sindicato_ve_solo_lo_suyo")


def test_sin_el_modulo_dashboard_no_hay_mapa():
    with db.get_session() as s:
        sind = Sindicato(nombre="Sin Dash Geo", slug="sin-dash-geo", color_base="#101010",
                         modulos_habilitados=["recibos"])
        s.add(sind); s.commit(); s.refresh(sind)
        s.add(UsuarioSindicato(sindicato_id=sind.id, usuario="20777777770", nombre="Admin",
                               clave_hash=auth.hashear_clave("sd-demo"),
                               debe_cambiar_clave=False, es_super_admin=True))
        s.commit()
    c = TestClient(main.app)
    c.post("/admin/login", data={"usuario": "20777777770", "clave": "sd-demo"})
    r = c.get("/admin/dashboard/seccionales-geo", params=RANGO)
    assert r.status_code == 403, r.status_code
    print("OK  test_sin_el_modulo_dashboard_no_hay_mapa")


def test_sin_sesion_no_hay_mapa():
    r = TestClient(main.app).get("/admin/dashboard/seccionales-geo", params=RANGO,
                                follow_redirects=False)
    assert r.status_code in (303, 403), r.status_code
    print("OK  test_sin_sesion_no_hay_mapa")


# -------------------------------------------------------------- privacidad

def test_la_respuesta_no_lleva_ni_un_dato_de_una_persona():
    """El mapa son seis números por seccional. Si alguna vez alguien le suma
    "y de paso el listado", este test lo frena."""
    crudo = cliente_a.get("/admin/dashboard/seccionales-geo", params=RANGO).text
    for nombre in ("Zoltan", "Kerekes", "Hipolita", "Quiroga", "Bartolome",
                   "Casilda", "Etchevarne", "Nadie"):
        assert nombre not in crudo, f"se filtró el nombre {nombre}"
    for cuil in ("20111111119", "20222222227", "20333333336", "20444444440"):
        assert cuil not in crudo, f"se filtró el CUIL {cuil}"
    # Tampoco CUITs de empresa ni números de expediente.
    assert "30111111117" not in crudo
    assert "UOMGEO" not in crudo
    print("OK  test_la_respuesta_no_lleva_ni_un_dato_de_una_persona")


def test_las_claves_de_cada_fila_son_las_esperadas():
    esperadas = {"id", "nombre", "direccion_texto", "provincia", "localidad", "lat", "lon",
                 "precision_geo", "afiliados", "ingresaron", "pct_ingresaron", "recibos",
                 "con_diferencias", "pct_con_diferencias", "tramites_abiertos",
                 "notif_enviadas", "tasa_lectura"}
    for fila in _pedir()["seccionales"]:
        assert set(fila) == esperadas, set(fila) ^ esperadas
    print("OK  test_las_claves_de_cada_fila_son_las_esperadas")


# --------------------------------------------------------------- agregados

def test_agregados_por_seccional():
    todas = _por_nombre(_pedir())
    ros, cba = todas["Rosario"], todas["Córdoba"]

    assert ros["afiliados"] == 3
    assert ros["ingresaron"] == 2
    assert ros["pct_ingresaron"] == 66.7
    assert ros["recibos"] == 3, "el recibo de hace 200 días queda fuera del rango"
    assert ros["con_diferencias"] == 1
    assert ros["pct_con_diferencias"] == 33.3
    assert ros["tramites_abiertos"] == 1, "el terminado no cuenta como abierto"
    assert ros["notif_enviadas"] == 2
    assert ros["tasa_lectura"] == 50.0

    assert cba["afiliados"] == 1 and cba["ingresaron"] == 0
    assert cba["pct_ingresaron"] == 0.0
    assert cba["recibos"] == 1 and cba["con_diferencias"] == 0
    # Sin notificaciones la tasa es None y no 0: un 0% afirmaría que nadie
    # leyó, cuando lo que pasa es que no se mandó nada.
    assert cba["tasa_lectura"] is None
    print("OK  test_agregados_por_seccional")


def test_el_trabajador_sin_seccional_no_se_suma_a_ninguna():
    todas = _por_nombre(_pedir())
    assert todas["Rosario"]["afiliados"] + todas["Córdoba"]["afiliados"] == 4
    print("OK  test_el_trabajador_sin_seccional_no_se_suma_a_ninguna")


def test_el_periodo_recorta_recibos_pero_no_el_padron():
    """Dos de los seis indicadores son una foto del padrón (misma decisión que
    el KPI "Afiliados registrados"): no se mueven al cambiar el período."""
    corto = _por_nombre(_pedir(desde=_dia(1), hasta=_dia(0)))["Rosario"]
    assert corto["recibos"] == 0, "ningún recibo en las últimas 24 h"
    assert corto["afiliados"] == 3, "el padrón es foto, no depende del período"
    assert corto["ingresaron"] == 2
    print("OK  test_el_periodo_recorta_recibos_pero_no_el_padron")


def test_el_filtro_de_empresa_si_aplica():
    with db.get_session() as s:
        from sqlmodel import select as sel
        emp = s.exec(sel(Empleador).where(Empleador.sindicato_id == SID_A,
                                          Empleador.cuit == "30222222225")).first()
        emp_id = emp.id
    ros = _por_nombre(_pedir(empresas=str(emp_id)))["Rosario"]
    assert ros["recibos"] == 1, "solo el recibo de Textil Belgrano"
    assert ros["afiliados"] == 1, "y un solo afiliado de esa empresa"
    print("OK  test_el_filtro_de_empresa_si_aplica")


def test_el_mapa_ignora_su_propio_filtro_de_seccional():
    """El mapa ES el selector: si respetara el filtro, tocar un marcador
    dejaría el mapa con un punto y no habría forma de volver."""
    datos = _pedir(seccionales=str(SEC_ROS))
    assert set(_por_nombre(datos)) == {"Rosario", "Córdoba"}
    # Y los números de Rosario no cambian por estar "seleccionada".
    assert _por_nombre(datos)["Rosario"]["recibos"] == 3
    print("OK  test_el_mapa_ignora_su_propio_filtro_de_seccional")


# ------------------------------------------------------------- sin ubicar

def test_las_sin_coordenadas_van_aparte_y_no_desaparecen():
    datos = _pedir()
    assert [s["nombre"] for s in datos["sin_ubicar"]] == ["Sin Ubicar"]
    assert "Sin Ubicar" not in _por_nombre(datos), "no puede ir al mapa sin coordenadas"
    print("OK  test_las_sin_coordenadas_van_aparte_y_no_desaparecen")


def test_una_seccional_sin_actividad_aparece_con_ceros():
    """Con ceros y no ausente: "no hay recibos en Salta" es información."""
    with db.get_session() as s:
        s.add(Seccional(sindicato_id=SID_A, nombre="Quieta",
                        **geo.campos_para_guardar({"localidad": "Salta", "provincia": "Salta"},
                                                  precision="manual", lat=-24.78, lon=-65.41)))
        s.commit()
    fila = _por_nombre(_pedir())["Quieta"]
    assert fila["afiliados"] == 0 and fila["recibos"] == 0
    assert fila["pct_ingresaron"] is None and fila["tasa_lectura"] is None
    print("OK  test_una_seccional_sin_actividad_aparece_con_ceros")


def test_el_enlace_para_georreferenciar_depende_del_permiso():
    """Ver el mapa (sección "dashboard") y cargar una dirección (sección
    "seccionales") son permisos distintos: ofrecerle el botón a quien va a
    recibir un 403 es peor que no ofrecérselo."""
    datos = _pedir()
    assert datos["puede_georreferenciar"] is True, "el Super Admin puede"

    with db.get_session() as s:
        from db import Area
        area = Area(sindicato_id=SID_A, seccional_id=SEC_ROS, nombre="Solo Tablero")
        s.add(area); s.commit(); s.refresh(area)
        db.set_permisos_area(area.id, ["dashboard"], SID_A)
        s.add(UsuarioSindicato(sindicato_id=SID_A, usuario="20666666665", nombre="Mirón",
                               clave_hash=auth.hashear_clave("m-demo"), debe_cambiar_clave=False,
                               es_super_admin=False, seccional_id=SEC_ROS, area_id=area.id))
        s.commit()
    c = TestClient(main.app)
    c.post("/admin/login", data={"usuario": "20666666665", "clave": "m-demo"})
    r = c.get("/admin/dashboard/seccionales-geo", params=RANGO)
    assert r.status_code == 200, r.text
    assert r.json()["puede_georreferenciar"] is False
    print("OK  test_el_enlace_para_georreferenciar_depende_del_permiso")
