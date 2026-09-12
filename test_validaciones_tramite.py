"""Capa de validaciones de Trámites (Fase 1: fija + consistencia).

Cubre: el motor puro (saneo al guardar, evaluación, bloquea vs. avisa),
el alta del tipo con validaciones y reglas por las rutas reales, el envío
del trabajador rechazado con errores_campos, las advertencias persistidas
en el trámite, el banco de pruebas del admin (misma función que el envío
real) y el espejo de empleadores.

Correr con: .venv/Scripts/python.exe -m pytest test_validaciones_tramite.py -q
"""
import json


import db
import auth
import validaciones_tramite as vt
from db import Sindicato, UsuarioSindicato, Trabajador, Empleador, Seccional, Area
from modulos import MODULOS_INICIALES
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select
import fechas

db.crear_tablas()

MODULOS = list(MODULOS_INICIALES) + ["tramites", "notificaciones", "empleadores"]

with db.get_session() as s:
    uom = Sindicato(nombre="UOM Validaciones", slug="uom-validaciones",
                    modulos_habilitados=MODULOS)
    s.add(uom); s.commit(); s.refresh(uom)
    SID = uom.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20111111110", nombre="Admin",
                            clave_hash=auth.hashear_clave("uom-demo"), debe_cambiar_clave=False, es_super_admin=True))
    s.add(Trabajador(sindicato_id=SID, cuil="20111111119", nombre="Juan",
                     activo=True, registrado=True))
    # El destino por defecto es obligatorio desde la Fase 3 (decisión N6).
    sec = Seccional(sindicato_id=SID, nombre="Sede Central", ve_todas=True)
    s.add(sec); s.commit(); s.refresh(sec)
    mesa = Area(sindicato_id=SID, seccional_id=sec.id, nombre="Mesa de Entradas")
    s.add(mesa); s.commit(); s.refresh(mesa)
    AREA = mesa.id
    s.commit()

admin = TestClient(main.app)
admin.post("/admin/login", data={"usuario": "20111111110", "clave": "uom-demo"})


def _sesion_trabajador(cuil):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0))
    c.cookies.set("cuil_trab", cuil)
    return c


# ---------- Motor puro ----------

def test_saneo_de_validaciones():
    # Operador inválido, fuente desconocida y valor no comparable se descartan.
    crudas = [
        {"fuente": "fija", "operador": "<=", "valor": "180", "mensaje": "Máximo 180."},
        {"fuente": "fija", "operador": "<>", "valor": "1"},           # operador inválido
        {"fuente": "marciana", "operador": "<=", "valor": "1"},        # fuente desconocida
        {"fuente": "fija", "operador": "<=", "valor": "banana"},       # valor no numérico
        {"fuente": "fija", "operador": ">", "valor": "0"},             # sin mensaje -> default
    ]
    validas = vt.validaciones_saneadas(crudas, "numero")
    assert len(validas) == 2
    assert validas[0]["mensaje"] == "Máximo 180."
    assert validas[1]["mensaje"]  # se generó un mensaje por defecto
    # Sobre un tipo no comparable no se guarda ninguna.
    assert vt.validaciones_saneadas(crudas, "texto") == []
    # Fecha: el valor tiene que ser AAAA-MM-DD.
    assert len(vt.validaciones_saneadas(
        [{"fuente": "fija", "operador": ">=", "valor": "2026-01-01"}], "fecha")) == 1
    assert vt.validaciones_saneadas(
        [{"fuente": "fija", "operador": ">=", "valor": "01/01/2026"}], "fecha") == []
    print("OK  test_saneo_de_validaciones")


def test_saneo_de_reglas():
    campos = [
        {"etiqueta": "Desde", "tipo_dato": "fecha"},
        {"etiqueta": "Hasta", "tipo_dato": "fecha"},
        {"etiqueta": "Días", "tipo_dato": "numero"},
        {"etiqueta": "Nombre", "tipo_dato": "texto"},
    ]
    crudas = [
        {"campo_a": 1, "operador": ">", "campo_b": 0},                # ok fecha-fecha
        {"campo_a": 2, "operador": ">", "campo_b": 0},                # tipos distintos
        {"campo_a": 3, "operador": ">", "campo_b": 3},                # texto y a==b
        {"campo_a": 9, "operador": ">", "campo_b": 0},                # fuera de rango
        {"campo_a": "1", "operador": "%", "campo_b": 0},              # operador inválido
    ]
    validas = vt.reglas_saneadas(crudas, campos)
    assert len(validas) == 1
    assert validas[0]["campo_a"] == 1 and validas[0]["campo_b"] == 0
    assert "Hasta" in validas[0]["mensaje"]  # mensaje por defecto con etiquetas
    print("OK  test_saneo_de_reglas")


def test_evaluar_envio_fija_consistencia_y_avisa():
    campos = [
        {"id": 10, "etiqueta": "Desde", "tipo_dato": "fecha", "validaciones": []},
        {"id": 11, "etiqueta": "Hasta", "tipo_dato": "fecha", "validaciones": []},
        {"id": 12, "etiqueta": "Días", "tipo_dato": "numero", "validaciones": [
            {"fuente": "fija", "operador": "<=", "valor": "180",
             "mensaje": "El máximo es 180 días.", "bloquea": True},
            {"fuente": "fija", "operador": "<=", "valor": "30",
             "mensaje": "Más de 30 días requiere revisión.", "bloquea": False},
        ]},
    ]
    reglas = [{"campo_a": 1, "operador": ">", "campo_b": 0,
               "mensaje": "El fin tiene que ser posterior al inicio.", "bloquea": True}]

    # Todo mal: 200 días y fechas invertidas.
    v = vt.evaluar_envio(campos, reglas, {10: "2026-09-10", 11: "2026-09-01", 12: "200"})
    assert len(v["errores"]) == 2
    assert v["errores_campos"][12] == "El máximo es 180 días."
    assert v["errores_campos"][11] == "El fin tiene que ser posterior al inicio."
    # el "avisa" de 30 días también saltó, pero como advertencia
    assert any("revisión" in a for a in v["advertencias"])

    # Corregido: 90 días -> solo la advertencia de los 30.
    v = vt.evaluar_envio(campos, reglas, {10: "2026-09-01", 11: "2026-09-10", 12: "90"})
    assert v["errores"] == [] and v["errores_campos"] == {}
    assert len(v["advertencias"]) == 1

    # 20 días: nada que decir.
    v = vt.evaluar_envio(campos, reglas, {10: "2026-09-01", 11: "2026-09-10", 12: "20"})
    assert v["errores"] == [] and v["advertencias"] == []

    # Campo vacío no dispara validaciones (de eso se ocupa "obligatorio").
    v = vt.evaluar_envio(campos, reglas, {12: ""})
    assert v["errores"] == [] and v["advertencias"] == []
    print("OK  test_evaluar_envio_fija_consistencia_y_avisa")


# ---------- Rutas reales ----------

CAMPOS_UI = [
    {"etiqueta": "Fecha desde", "tipo_dato": "fecha", "obligatorio": True},
    {"etiqueta": "Fecha hasta", "tipo_dato": "fecha", "obligatorio": True,
     "validaciones": []},
    {"etiqueta": "Días solicitados", "tipo_dato": "numero", "obligatorio": True,
     "validaciones": [
         {"fuente": "fija", "operador": "<=", "valor": "180",
          "mensaje": "El máximo para esta licencia es 180 días.", "bloquea": True},
         {"fuente": "fija", "operador": "<=", "valor": "30",
          "mensaje": "Más de 30 días pasa a revisión manual.", "bloquea": False},
     ]},
]
REGLAS_UI = [{"campo_a": 1, "operador": ">", "campo_b": 0,
              "mensaje": "La fecha de fin tiene que ser posterior al inicio."}]


def test_alta_tipo_con_validaciones_y_reglas():
    r = admin.post("/admin/tramite-tipo", data={
        "titulo": "Licencia por cuidado de familiar", "codigo": "F07 UOM",
        "campos_json": json.dumps(CAMPOS_UI), "area_destino_default_id": str(AREA), "reglas_json": json.dumps(REGLAS_UI),
    }, follow_redirects=False)
    assert r.status_code == 303
    tipos = db.tipos_tramite_del_sindicato(SID)
    tipo = next(t for t in tipos if t["codigo"] == "F07 UOM")
    global TIPO_ID
    TIPO_ID = tipo["id"]
    assert len(tipo["reglas_consistencia"]) == 1
    dias = next(c for c in tipo["campos"] if c["etiqueta"] == "Días solicitados")
    assert len(dias["validaciones"]) == 2
    assert dias["validaciones"][1]["bloquea"] is False
    # Las validaciones viajan al trabajador en /api/tramites/tipos (las usa
    # la validación en vivo del formulario).
    trab = _sesion_trabajador("20111111119")
    data = trab.get("/api/tramites/tipos").json()
    t = next(t for t in data["tipos"] if t["id"] == TIPO_ID)
    assert t["reglas_consistencia"] and any(c["validaciones"] for c in t["campos"])
    print("OK  test_alta_tipo_con_validaciones_y_reglas")


def _ids():
    tipo = db.tipo_tramite_por_id(TIPO_ID)
    return {c["etiqueta"]: c["id"] for c in tipo["campos"]}


def test_envio_bloqueado_con_errores_campos():
    ids = _ids()
    trab = _sesion_trabajador("20111111119")
    r = trab.post("/api/tramite", data={
        "tipo_tramite_id": TIPO_ID,
        f'campo_{ids["Fecha desde"]}': "2026-09-10",
        f'campo_{ids["Fecha hasta"]}': "2026-09-01",
        f'campo_{ids["Días solicitados"]}': "200",
    })
    assert r.status_code == 422
    data = r.json()
    assert len(data["errores"]) == 2
    assert data["errores_campos"][str(ids["Días solicitados"])] == \
        "El máximo para esta licencia es 180 días."
    assert str(ids["Fecha hasta"]) in data["errores_campos"]
    # No se creó nada.
    assert db.tramites_de_trabajador("20111111119", SID) == []
    print("OK  test_envio_bloqueado_con_errores_campos")


def test_envio_ok_guarda_advertencias():
    ids = _ids()
    trab = _sesion_trabajador("20111111119")
    r = trab.post("/api/tramite", data={
        "tipo_tramite_id": TIPO_ID,
        f'campo_{ids["Fecha desde"]}': "2026-09-01",
        f'campo_{ids["Fecha hasta"]}': "2026-12-01",
        f'campo_{ids["Días solicitados"]}': "90",
    })
    assert r.status_code == 200
    detalle = db.tramite_detalle(r.json()["id"])
    assert detalle["advertencias"] == ['"Días solicitados": Más de 30 días pasa a revisión manual.']
    print("OK  test_envio_ok_guarda_advertencias")


def test_banco_de_pruebas_misma_funcion():
    # El banco de pruebas evalúa el formulario SIN guardarlo, referenciando
    # campos por índice, y tiene que dar lo mismo que el envío real.
    r = admin.post("/admin/tramite-tipo/probar", json={
        "campos": CAMPOS_UI, "reglas": REGLAS_UI,
        "valores": {"0": "2026-09-10", "1": "2026-09-01", "2": "200"},
    })
    assert r.status_code == 200
    data = r.json()
    assert len(data["errores"]) == 2
    assert data["errores_campos"]["2"] == "El máximo para esta licencia es 180 días."
    r = admin.post("/admin/tramite-tipo/probar", json={
        "campos": CAMPOS_UI, "reglas": REGLAS_UI,
        "valores": {"0": "2026-09-01", "1": "2026-12-01", "2": "90"},
    })
    assert r.json()["errores"] == [] and len(r.json()["advertencias"]) == 1
    print("OK  test_banco_de_pruebas_misma_funcion")


def test_validacion_rota_no_se_guarda():
    # Un request armado a mano con basura en las validaciones no rompe el
    # alta: lo mal formado se descarta y el resto se guarda.
    campos = [{"etiqueta": "Monto", "tipo_dato": "numero", "obligatorio": True,
               "validaciones": [
                   {"fuente": "fija", "operador": "<=", "valor": "no-numero"},
                   "esto-ni-es-dict",
                   {"fuente": "fija", "operador": ">=", "valor": "100"},
               ]}]
    r = admin.post("/admin/tramite-tipo", data={
        "titulo": "Saneo", "codigo": "F99 UOM", "campos_json": json.dumps(campos), "area_destino_default_id": str(AREA),
        "reglas_json": json.dumps([{"campo_a": 0, "operador": ">", "campo_b": 5}]),
    }, follow_redirects=False)
    assert r.status_code == 303
    tipo = next(t for t in db.tipos_tramite_del_sindicato(SID) if t["codigo"] == "F99 UOM")
    assert len(tipo["campos"][0]["validaciones"]) == 1
    assert tipo["campos"][0]["validaciones"][0]["valor"] == "100"
    assert tipo["reglas_consistencia"] == []
    print("OK  test_validacion_rota_no_se_guarda")


def test_espejo_empleadores():
    with db.get_session() as s:
        s.add(Empleador(sindicato_id=SID, cuit="30999888776",
                        razon_social="Metal SRL", activo=True))
        s.commit()
    r = admin.post("/admin/tramite-tipo-empresa", data={
        "titulo": "Declaración de nómina", "codigo": "E01 UOM",
        "campos_json": json.dumps(CAMPOS_UI), "area_destino_default_id": str(AREA), "reglas_json": json.dumps(REGLAS_UI),
    }, follow_redirects=False)
    assert r.status_code == 303
    tipo = next(t for t in db.tipos_tramite_empleador_del_sindicato(SID)
                if t["codigo"] == "E01 UOM")
    assert len(tipo["reglas_consistencia"]) == 1
    ids = {c["etiqueta"]: c["id"] for c in tipo["campos"]}

    emp_cli = TestClient(main.app)
    emp_cli.cookies.set(main.COOKIE_EMPLEADOR, auth.crear_sesion("empleador", sindicato_id=0))
    emp_cli.cookies.set("cuit_emp", "30999888776")
    r = emp_cli.post("/api/empresa/tramite", data={
        "tipo_tramite_id": tipo["id"],
        f'campo_{ids["Fecha desde"]}': "2026-09-10",
        f'campo_{ids["Fecha hasta"]}': "2026-09-01",
        f'campo_{ids["Días solicitados"]}': "200",
    })
    assert r.status_code == 422
    assert len(r.json()["errores"]) == 2
    r = emp_cli.post("/api/empresa/tramite", data={
        "tipo_tramite_id": tipo["id"],
        f'campo_{ids["Fecha desde"]}': "2026-09-01",
        f'campo_{ids["Fecha hasta"]}': "2026-12-01",
        f'campo_{ids["Días solicitados"]}': "90",
    })
    assert r.status_code == 200
    detalle = db.tramite_empleador_detalle(r.json()["id"])
    assert len(detalle["advertencias"]) == 1
    print("OK  test_espejo_empleadores")


def test_limite_dinamico_hoy():
    # "hoy±N" se acepta al guardar y se resuelve al evaluar (fecha del envío).
    from datetime import date, timedelta
    validas = vt.validaciones_saneadas([
        {"fuente": "fija", "operador": ">=", "valor": "hoy"},
        {"fuente": "fija", "operador": ">=", "valor": "hoy+10"},
        {"fuente": "fija", "operador": "<=", "valor": "hoy-3"},
        {"fuente": "fija", "operador": ">=", "valor": "pasado"},   # basura: afuera
    ], "fecha")
    assert [v["valor"] for v in validas] == ["hoy", "hoy+10", "hoy-3"]
    assert "el día del envío" in validas[0]["mensaje"]
    assert "10 días después del envío" in validas[1]["mensaje"]
    # sobre números "hoy" no significa nada
    assert vt.validaciones_saneadas(
        [{"fuente": "fija", "operador": ">=", "valor": "hoy"}], "numero") == []

    campos = [{"id": 1, "etiqueta": "Fecha de reserva", "tipo_dato": "fecha",
               "validaciones": [{"fuente": "fija", "operador": ">=", "valor": "hoy",
                                 "mensaje": "No se puede antedatar.", "bloquea": True}]}]
    ayer = (fechas.hoy() - timedelta(days=1)).isoformat()
    maniana = (fechas.hoy() + timedelta(days=1)).isoformat()
    v = vt.evaluar_envio(campos, [], {1: ayer})
    assert v["errores_campos"][1] == "No se puede antedatar."
    v = vt.evaluar_envio(campos, [], {1: maniana})
    assert v["errores"] == []
    # hoy+10: reservar a 5 días no alcanza, a 15 sí
    campos[0]["validaciones"][0].update({"valor": "hoy+10", "mensaje": "Mínimo 10 días de anticipación."})
    v = vt.evaluar_envio(campos, [], {1: (fechas.hoy() + timedelta(days=5)).isoformat()})
    assert v["errores_campos"][1] == "Mínimo 10 días de anticipación."
    v = vt.evaluar_envio(campos, [], {1: (fechas.hoy() + timedelta(days=15)).isoformat()})
    assert v["errores"] == []
    print("OK  test_limite_dinamico_hoy")


def test_editar_tipo_con_tramites_no_rompe_fk():
    # Antes la edición borraba y recreaba los campos; con un trámite ya
    # presentado, RespuestaTramite referencia esos campos y en Postgres el
    # DELETE revienta (E-INTERNO-00 reportado por Sd). Ahora sincroniza por
    # id: los campos que vuelven conservan SU id, uno quitado con respuestas
    # queda `retirado` (fuera del formulario, etiqueta viva en el detalle).
    tipo_antes = db.tipo_tramite_por_id(TIPO_ID)
    ids_antes = {c["etiqueta"]: c["id"] for c in tipo_antes["campos"]}

    # editar conservando los ids (como manda el constructor), sin "Fecha desde"
    campos_editados = [dict(c) for c in tipo_antes["campos"] if c["etiqueta"] != "Fecha desde"]
    campos_editados[0]["etiqueta"] = "Fecha hasta (renombrada)"
    r = admin.post("/admin/tramite-tipo", data={
        "id": TIPO_ID, "titulo": "Licencia editada", "codigo": "F07 UOM", "activo": "si",
        "campos_json": json.dumps(campos_editados), "area_destino_default_id": str(AREA), "reglas_json": "[]",
    }, follow_redirects=False)
    assert r.status_code == 303 and "error" not in (r.headers.get("location") or "")

    tipo_despues = db.tipo_tramite_por_id(TIPO_ID)
    ids_despues = {c["etiqueta"]: c["id"] for c in tipo_despues["campos"]}
    # el campo renombrado conservó su id (las respuestas viejas siguen suyas)
    assert ids_despues["Fecha hasta (renombrada)"] == ids_antes["Fecha hasta"]
    # "Fecha desde" ya no está en el formulario...
    assert "Fecha desde" not in ids_despues
    # ...pero como tenía respuestas quedó retirado, no borrado: el detalle
    # del trámite viejo conserva su etiqueta
    from db import CampoTramite
    with Session(db.engine) as s:
        fila = s.get(CampoTramite, ids_antes["Fecha desde"])
        assert fila is not None and fila.retirado is True
    tramites = db.tramites_de_trabajador("20111111119", SID)
    detalle = db.tramite_detalle(tramites[0]["id"])
    assert any(resp["etiqueta"] == "Fecha desde" for resp in detalle["respuestas"])
    print("OK  test_editar_tipo_con_tramites_no_rompe_fk")


if __name__ == "__main__":
    test_saneo_de_validaciones()
    test_saneo_de_reglas()
    test_evaluar_envio_fija_consistencia_y_avisa()
    test_alta_tipo_con_validaciones_y_reglas()
    test_envio_bloqueado_con_errores_campos()
    test_envio_ok_guarda_advertencias()
    test_banco_de_pruebas_misma_funcion()
    test_validacion_rota_no_se_guarda()
    test_espejo_empleadores()
    test_limite_dinamico_hoy()
    test_editar_tipo_con_tramites_no_rompe_fk()
    print("\nTodo OK — validaciones de trámites.")
