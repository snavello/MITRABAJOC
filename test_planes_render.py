"""Solapa "Planes" de /entornos: subir y bajar el plan del servicio web y de
Postgres, y programarlo por día y hora.

Nada de esto toca la API real de Render: se monkeypatchea render_admin. Lo
que sí se prueba de verdad es el catálogo (data/render_planes.json, que sale
de actualizar_planes_render.py), el candado del planificador y el gate de
acceso de las rutas.

Correr con: python -m pytest test_planes_render.py
"""
import os
import tempfile
from datetime import datetime

from zoneinfo import ZoneInfo

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE
os.environ["ENTORNO"] = "pruebas"
os.environ["PIN_ENTORNOS"] = "13571357"
os.environ["PLANIFICADOR"] = "off"   # el hilo no arranca dentro de los tests

import db
import main
import planificador
import render_admin
import render_planes
from fastapi.testclient import TestClient

BA = ZoneInfo("America/Argentina/Buenos_Aires")

db.crear_tablas()
client = TestClient(main.app)
assert client.post("/entornos/pin", data={"pin": "13571357"},
                   follow_redirects=False).status_code == 303


# ------------------------- catálogo -------------------------
def test_el_catalogo_sale_del_archivo_y_trae_los_identificadores_de_render():
    """Los planes tienen que ser los MISMOS identificadores que devuelve la
    API de Render ("4c-8g"), no nombres inventados: es lo que se manda en el
    PATCH. Pedir "starter" en vez de "0.5c-512mb" mandó el servicio a un plan
    distinto el 2026-09-10."""
    c = render_planes.catalogo()
    assert c["disponible"], "falta data/render_planes.json"
    ids_web = {p["id"] for p in c["web"]}
    ids_db = {p["id"] for p in c["db"]}
    # Los cinco planes que se usaron en los ocho tests de carga.
    assert {"0.5c-512mb", "2c-4g", "4c-8g", "8c-16g"} <= ids_web
    assert {"0.1c-256mb", "2c-4g", "4c-16g"} <= ids_db
    assert c["leido_utc"], "el catálogo tiene que decir cuándo se leyó"


def test_cada_plan_trae_precio_y_capacidad_coherentes():
    c = render_planes.catalogo()
    for tipo in ("web", "db"):
        for p in c[tipo]:
            assert p["usd_mes"] > 0
            assert p["vcpu"] > 0 and p["ram_mb"] > 0
            assert p["etiqueta"] and p["precio_txt"].startswith("US$")
    # El identificador manda: "4c-8g" son 4 vCPU y 8 GB, se lea como se lea.
    web = {p["id"]: p for p in c["web"]}
    assert web["4c-8g"]["vcpu"] == 4 and web["4c-8g"]["ram_mb"] == 8192
    # Y más caro siempre es más grande dentro de la misma cantidad de CPU.
    assert web["4c-16g"]["usd_mes"] > web["4c-8g"]["usd_mes"]


def test_los_workers_acompanan_al_plan_uno_por_nucleo():
    """La regla que costó dos tests descubrir: un worker por núcleo. Sumar
    workers sin CPU empeora (test 2) y sumar CPU sin workers no se usa."""
    assert render_planes.workers_para("0.5c-512mb") == 1
    assert render_planes.workers_para("2c-4g") == 2
    assert render_planes.workers_para("4c-8g") == 4
    assert render_planes.workers_para("8c-16g") == 8
    # Un plan que no existe no puede devolver un número grande por accidente.
    assert render_planes.workers_para("no-existe") == 1


def test_un_plan_fuera_del_catalogo_no_llega_a_la_api(monkeypatch):
    llamadas = []
    monkeypatch.setattr(render_admin, "_peticion",
                        lambda *a, **k: llamadas.append(a) or {})
    monkeypatch.setattr(render_admin, "configurado", lambda: True)
    monkeypatch.setenv("RENDER_WEB_SERVICE_ID", "srv-x")
    res = render_admin.aplicar_plan_web("plan-inventado")
    assert "error" in res and not llamadas


# ------------------------- orden de plan y workers -------------------------
def _falso_render(monkeypatch, plan_actual="4c-8g", instancias=1, workers=4):
    """Simula la API de Render y devuelve la lista de llamadas en orden."""
    hechas = []
    estado = {"plan": plan_actual, "numInstances": instancias,
              "cmd": f"uvicorn main:app --host 0.0.0.0 --port $PORT --workers {workers}"}

    def peticion(path, metodo="GET", body=None):
        hechas.append((metodo, path, body))
        if metodo == "GET":
            return {"id": "srv-x", "suspended": "not_suspended",
                    "serviceDetails": {"plan": estado["plan"],
                                       "numInstances": estado["numInstances"],
                                       "envSpecificDetails": {"startCommand": estado["cmd"]}}}
        return {}

    monkeypatch.setattr(render_admin, "_peticion", peticion)
    monkeypatch.setattr(render_admin, "configurado", lambda: True)
    monkeypatch.setenv("RENDER_WEB_SERVICE_ID", "srv-x")
    monkeypatch.setenv("RENDER_DB_ID", "dpg-x")
    return hechas


def _orden(hechas):
    """Los cambios que se mandaron, en orden, resumidos."""
    out = []
    for metodo, path, body in hechas:
        if metodo == "GET":
            continue
        det = (body or {}).get("serviceDetails", {})
        if "plan" in det:
            out.append(("plan", det["plan"]))
        elif "envSpecificDetails" in det:
            out.append(("workers", det["envSpecificDetails"]["startCommand"].split("--workers ")[-1]))
        elif "numInstances" in (body or {}):
            out.append(("instancias", body["numInstances"]))
    return out


def test_al_bajar_de_plan_los_workers_bajan_primero(monkeypatch):
    """El estado intermedio "muchos workers sobre poca CPU" es la peor
    combinación medida en todo el informe de carga (test 2). El servicio no
    puede pasar por ahí, ni siquiera los minutos que tarda el reinicio."""
    hechas = _falso_render(monkeypatch, plan_actual="4c-8g", workers=4)
    render_admin.aplicar_plan_web("0.5c-512mb", workers=1)
    pasos = _orden(hechas)
    assert pasos.index(("workers", "1")) < pasos.index(("plan", "0.5c-512mb"))


def test_al_subir_de_plan_los_workers_suben_despues(monkeypatch):
    """Al revés: primero la CPU, después los workers que la van a usar."""
    hechas = _falso_render(monkeypatch, plan_actual="0.5c-512mb", workers=1)
    render_admin.aplicar_plan_web("4c-8g", workers=4)
    pasos = _orden(hechas)
    assert pasos.index(("plan", "4c-8g")) < pasos.index(("workers", "4"))


def test_el_start_command_conserva_las_otras_banderas():
    """Se edita el comando real, no se reescribe entero: si alguien agregó
    una bandera a mano, no se la puede comer un cambio de plan."""
    cmd = "uvicorn main:app --host 0.0.0.0 --port $PORT --timeout-keep-alive 65 --workers 2"
    nuevo = render_admin._start_command_con_workers(cmd, 8)
    assert "--timeout-keep-alive 65" in nuevo and "--workers 8" in nuevo
    assert "--workers 2" not in nuevo
    # Y si no había bandera, se agrega sin romper el resto.
    sin = render_admin._start_command_con_workers("uvicorn main:app --port $PORT", 4)
    assert sin.endswith("--workers 4") and "uvicorn main:app --port $PORT" in sin


# ------------------------- estado y rutas -------------------------
def test_la_solapa_muestra_el_plan_actual_y_si_esta_activo(monkeypatch):
    _falso_render(monkeypatch, plan_actual="4c-8g", instancias=2, workers=4)
    monkeypatch.setattr(render_admin, "_peticion", lambda path, metodo="GET", body=None: (
        {"id": "srv-x", "name": "web", "suspended": "not_suspended",
         "serviceDetails": {"plan": "4c-8g", "numInstances": 2,
                            "envSpecificDetails": {"startCommand": "uvicorn m:a --workers 4"}}}
        if "/services/" in path else
        {"id": "dpg-x", "name": "db", "plan": "4c-16g", "status": "available",
         "suspended": "not_suspended", "diskSizeGB": 15}))
    e = render_admin.estado_planes()
    assert e["web"]["plan"] == "4c-8g" and e["web"]["instancias"] == 2
    assert e["web"]["workers"] == 4 and e["web"]["activo"] is True
    assert e["db"]["plan"] == "4c-16g" and e["db"]["activo"] is True
    assert e["db"]["disco_gb"] == 15


def test_la_base_actualizandose_no_figura_como_activa(monkeypatch):
    """Durante un cambio de plan Postgres pasa por "updating_instance" y la
    app entera devuelve error 500. Eso no se puede mostrar como "activo"."""
    monkeypatch.setattr(render_admin, "configurado", lambda: True)
    monkeypatch.setenv("RENDER_DB_ID", "dpg-x")
    monkeypatch.setattr(render_admin, "_peticion", lambda path, metodo="GET", body=None: (
        {"serviceDetails": {"plan": "4c-8g", "envSpecificDetails": {}}} if "/services/" in path
        else {"plan": "4c-16g", "status": "updating_instance", "suspended": "not_suspended"}))
    assert render_admin.estado_planes()["db"]["activo"] is False


def test_sin_pin_no_se_puede_ni_mirar_ni_cambiar():
    anonimo = TestClient(main.app)
    assert anonimo.get("/api/entornos/planes").status_code == 403
    assert anonimo.post("/entornos/planes/aplicar",
                        json={"destino": "web", "plan": "4c-8g"}).status_code == 403
    assert anonimo.post("/entornos/planes/programados", json={}).status_code == 403


def test_aplicar_rechaza_un_plan_que_no_existe():
    r = client.post("/entornos/planes/aplicar",
                    json={"destino": "web", "plan": "plan-trucho"})
    assert r.status_code == 400 and "catálogo" in r.json()["detail"]


def test_aplicar_deja_el_cambio_en_la_bitacora(monkeypatch):
    """Render no guarda historial de planes de las bases: si esto no queda
    anotado acá, no hay forma de saber por qué cambió la factura."""
    monkeypatch.setattr(render_admin, "aplicar_plan_db",
                        lambda plan: {"ok": True, "hechos": [f"plan de la base a {plan}"]})
    monkeypatch.setattr(render_admin, "estado_planes",
                        lambda: {"configurado": True, "web": None,
                                 "db": {"plan": "4c-16g"}, "error": ""})
    antes = len(db.cambios_de_plan(50))
    r = client.post("/entornos/planes/aplicar",
                    json={"destino": "db", "plan": "0.1c-256mb"})
    assert r.status_code == 200
    filas = db.cambios_de_plan(50)
    assert len(filas) == antes + 1
    assert filas[0]["plan_anterior"] == "4c-16g"
    assert filas[0]["plan_nuevo"] == "0.1c-256mb"
    assert filas[0]["ok"] and filas[0]["origen"] == "manual"


def test_un_fallo_de_render_queda_registrado_como_fallo(monkeypatch):
    monkeypatch.setattr(render_admin, "aplicar_plan_db",
                        lambda plan: {"error": "Render devolvió HTTP 400."})
    monkeypatch.setattr(render_admin, "estado_planes",
                        lambda: {"configurado": True, "web": None,
                                 "db": {"plan": "4c-16g"}, "error": ""})
    r = client.post("/entornos/planes/aplicar",
                    json={"destino": "db", "plan": "0.1c-256mb"})
    assert r.status_code == 502
    ultimo = db.cambios_de_plan(1)[0]
    assert not ultimo["ok"] and "HTTP 400" in ultimo["error"]


# ------------------------- programación -------------------------
def test_alta_baja_y_pausa_de_una_regla():
    r = client.post("/entornos/planes/programados", json={
        "destino": "web", "plan": "4c-8g", "hora": "08:00",
        "dias": [1, 2, 3, 4, 5], "instancias": 2, "nota": "mañanas"})
    assert r.status_code == 200
    rid = r.json()["id"]
    regla = [x for x in db.planes_programados() if x["id"] == rid][0]
    assert regla["dias"] == [1, 2, 3, 4, 5] and regla["instancias"] == 2
    assert client.post(f"/entornos/planes/programados/{rid}/activo",
                       json={"activo": False}).status_code == 200
    assert [x for x in db.planes_programados() if x["id"] == rid][0]["activo"] is False
    assert client.request("DELETE", f"/entornos/planes/programados/{rid}").status_code == 200
    assert not [x for x in db.planes_programados() if x["id"] == rid]


def test_la_hora_y_los_dias_se_validan():
    base = {"destino": "web", "plan": "4c-8g", "dias": [1]}
    assert client.post("/entornos/planes/programados",
                       json={**base, "hora": "25:00"}).status_code == 400
    assert client.post("/entornos/planes/programados",
                       json={**base, "hora": "8:00"}).status_code == 400
    assert client.post("/entornos/planes/programados",
                       json={"destino": "web", "plan": "4c-8g",
                             "hora": "08:00", "dias": []}).status_code == 400


def _regla(**kw):
    base = {"id": 1, "activo": True, "destino": "web", "dias": [1, 2, 3, 4, 5],
            "hora": "08:00", "plan": "4c-8g", "instancias": None,
            "ajustar_workers": True, "nota": "", "ultimo_disparo": ""}
    return {**base, **kw}


def test_una_regla_dispara_en_su_dia_y_su_hora():
    lunes_8 = datetime(2026, 9, 7, 8, 0, tzinfo=BA)   # 2026-09-07 es lunes
    assert planificador.toca(_regla(), lunes_8) == "2026-09-07 08:00"


def test_una_regla_no_dispara_el_dia_que_no_le_toca():
    sabado_8 = datetime(2026, 9, 12, 8, 0, tzinfo=BA)
    assert planificador.toca(_regla(), sabado_8) is None


def test_la_ventana_de_gracia_cubre_un_reinicio_pero_no_mas():
    """Si a las 08:00 el proceso estaba levantando (justo lo que pasa cuando
    la regla anterior cambió el plan del propio web), a las 08:04 la aplica
    igual. A las 08:30 ya no: sería un cambio a destiempo."""
    assert planificador.toca(_regla(), datetime(2026, 9, 7, 8, 4, tzinfo=BA))
    assert planificador.toca(_regla(), datetime(2026, 9, 7, 8, 30, tzinfo=BA)) is None


def test_una_regla_ya_aplicada_no_se_repite():
    ya = _regla(ultimo_disparo="2026-09-07 08:00")
    assert planificador.toca(ya, datetime(2026, 9, 7, 8, 3, tzinfo=BA)) is None
    # Pero al día siguiente sí.
    assert planificador.toca(ya, datetime(2026, 9, 8, 8, 0, tzinfo=BA)) == "2026-09-08 08:00"


def test_una_regla_pausada_nunca_dispara():
    assert planificador.toca(_regla(activo=False),
                             datetime(2026, 9, 7, 8, 0, tzinfo=BA)) is None


def test_una_regla_de_medianoche_dispara_pasado_el_cambio_de_dia():
    """23:55 del domingo con gracia: a las 00:02 del lunes todavía le toca,
    y la marca tiene que ser la del DOMINGO, no la del lunes."""
    regla = _regla(dias=[7], hora="23:55")
    assert planificador.toca(regla, datetime(2026, 9, 14, 0, 2, tzinfo=BA)) == "2026-09-13 23:55"


def test_dos_instancias_no_pueden_aplicar_la_misma_regla():
    """El candado que hace que esto sea seguro con el web escalado: el
    reclamo es un UPDATE condicional, así que la segunda instancia que
    despierte en el mismo minuto actualiza cero filas y se va."""
    rid = db.crear_plan_programado("web", [1], "09:00", "4c-8g")
    assert db.reclamar_plan_programado(rid, "2026-09-07 09:00") is True
    assert db.reclamar_plan_programado(rid, "2026-09-07 09:00") is False
    assert db.reclamar_plan_programado(rid, "2026-09-08 09:00") is True
    db.borrar_plan_programado(rid)


def test_el_tick_aplica_y_anota_en_la_bitacora(monkeypatch):
    aplicados = []
    monkeypatch.setattr(render_admin, "estado_planes",
                        lambda: {"configurado": True, "web": {"plan": "0.5c-512mb"},
                                 "db": None, "error": ""})
    monkeypatch.setattr(render_admin, "aplicar_plan_web",
                        lambda plan, instancias=None, workers=None:
                        aplicados.append((plan, instancias, workers)) or
                        {"ok": True, "hechos": [f"plan a {plan}"]})
    ahora = planificador.ahora_ba()
    rid = db.crear_plan_programado(
        "web", [ahora.isoweekday()], ahora.strftime("%H:%M"), "4c-8g",
        instancias=2, ajustar_workers=True)
    hechas = planificador.tick()
    assert any(a["regla"] == rid for a in hechas)
    # Los workers salieron del plan, no de un valor fijo.
    assert aplicados == [("4c-8g", 2, 4)]
    ultimo = db.cambios_de_plan(1)[0]
    assert ultimo["origen"] == "programado" and ultimo["ok"]
    assert ultimo["plan_anterior"] == "0.5c-512mb"
    # Y una segunda pasada en el mismo minuto no la repite.
    aplicados.clear()
    assert planificador.tick() == [] and aplicados == []
    db.borrar_plan_programado(rid)


def test_el_planificador_no_arranca_sin_credenciales_de_render(monkeypatch):
    monkeypatch.delenv("PLANIFICADOR", raising=False)
    monkeypatch.setattr(render_admin, "configurado", lambda: False)
    assert planificador.arrancar() is False
