"""Sentry (sentry_config.py): errores no previstos, con contexto y SIN datos personales.

Los errores viajan a un tercero y esta app maneja recibos de sueldo y CUIL, así que lo que
más se prueba es lo que NO sale. Todo con un transporte falso que captura el evento tal como
se mandaría: no se toca la red.

Correr con: .venv/Scripts/python.exe -m pytest test_sentry.py -q
"""
import json
import os

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import pytest
import sentry_sdk
from sentry_sdk.transport import Transport

import auth
import db
import main
import sentry_config as sc
from fastapi.testclient import TestClient

DSN = "https://clavepublica@o1.ingest.us.sentry.io/1"
CUIL = "20111111119"
CUIT = "30-71234567-8"


class TransporteFalso(Transport):
    def __init__(self):
        super().__init__()
        self.eventos = []

    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.type == "event":
                self.eventos.append(item.payload.json)


@pytest.fixture
def sentry():
    transporte = TransporteFalso()
    sc._recientes.clear()
    assert sc.iniciar(DSN, "pruebas", release="abc1234", transport=transporte)
    yield transporte
    sentry_sdk.init(dsn="")             # apagar: que no se filtre a los otros tests
    sc._recientes.clear()


db.crear_tablas()


def _evento_sucio():
    """Un evento como lo armaría el SDK, con todo lo que NO tiene que salir."""
    return {
        "event_id": "e1", "level": "error", "platform": "python", "release": "abc1234", "environment": "pruebas",
        "transaction": "/perfil-foto/{cuil}", "server_name": "srv-render-interno",
        "user": {"id": "7", "email": "juan@gremio.org", "ip_address": "190.1.2.3", "username": "Juan Pérez"},
        "request": {"method": "POST", "url": f"https://x.onrender.com/perfil-foto/{CUIL}?nombre=Juan&cuit={CUIT}",
                    "query_string": f"cuil={CUIL}", "cookies": {"sesion_trabajador": "SECRETO"},
                    "headers": {"Authorization": "Bearer TOKEN", "Cookie": "sesion=SECRETO", "User-Agent": "x"},
                    "data": {"cuil": CUIL, "empleado": {"apellido_nombre": "PEREZ, JUAN"}, "neto": 812345},
                    "env": {"REMOTE_ADDR": "190.1.2.3"}},
        "exception": {"values": [{"type": "ValueError", "value": f"importe raro del CUIL {CUIL} (juan@gremio.org)",
                                  "stacktrace": {"frames": [{"filename": "main.py", "function": "validar", "lineno": 10,
                                                             "vars": {"cuil": CUIL, "recibo": {"neto": 1}},
                                                             "context_line": f'cuil = "{CUIL}"'}]}}]},
        "breadcrumbs": {"values": [{"category": "query", "message": f"SELECT ... {CUIL}", "level": "info",
                                    "data": {"cuil": CUIL}, "timestamp": 1}]},
        "contexts": {"os": {"name": "Linux"}}, "extra": {"cuil": CUIL}, "modules": {"pip": "1"},
        "tags": {"ruta": "/perfil-foto/{cuil}", "sindicato_id": "7"},
    }


# ------------------------- limpieza -------------------------
def test_los_mails_se_borran_de_cualquier_texto():
    assert sc.limpiar_texto("escribí a juan.perez+x@gremio.org o a ana@x.com.ar") == "escribí a [filtrado] o a [filtrado]"


def test_un_cuil_o_cuit_suelto_es_dato_publico_y_se_deja_para_poder_diagnosticar():
    """Decisión de SDN (2026-09-20): sin contexto no es un dato sensible, y saber de qué CUIL
    falló algo es justo lo que sirve. Lo sensible es el sueldo, el recibo y los nombres."""
    for texto in (f"falló el recibo del CUIL {CUIL}", f"empresa {CUIT}", "20-11111111-9", "2026-09-19", "recibo 12345"):
        assert sc.limpiar_texto(texto) == texto, texto


def test_el_evento_sale_sin_nada_personal():
    e = sc.limpiar_evento(_evento_sucio())
    texto = json.dumps(e, ensure_ascii=False)
    for prohibido in ("juan@gremio.org", "Juan Pérez", "PEREZ", "SECRETO", "TOKEN", "190.1.2.3",
                      "812345", "srv-render-interno", "Bearer", "nombre=Juan"):
        assert prohibido not in texto, f"salió: {prohibido}"


def test_de_la_peticion_solo_quedan_el_metodo_y_la_ruta_sin_parametros():
    e = sc.limpiar_evento(_evento_sucio())
    assert e["request"] == {"method": "POST", "url": f"https://x.onrender.com/perfil-foto/{CUIL}"}   # sin ?nombre=...&cuit=...
    assert "user" not in e


def test_de_cada_linea_del_traceback_no_sale_el_valor_de_las_variables():
    e = sc.limpiar_evento(_evento_sucio())
    (cuadro,) = e["exception"]["values"][0]["stacktrace"]["frames"]
    assert "vars" not in cuadro
    assert cuadro["function"] == "validar" and cuadro["lineno"] == 10          # lo útil para diagnosticar se conserva
    assert "PEREZ" not in json.dumps(cuadro)


def test_se_conserva_lo_que_sirve_para_diagnosticar():
    e = sc.limpiar_evento(_evento_sucio())
    assert e["exception"]["values"][0]["type"] == "ValueError"
    assert e["tags"] == {"ruta": "/perfil-foto/{cuil}", "sindicato_id": "7"}
    assert e["release"] == "abc1234" and e["environment"] == "pruebas" and e["level"] == "error"


def test_las_migas_de_pan_quedan_sin_datos():
    (m,) = sc.limpiar_evento(_evento_sucio())["breadcrumbs"]["values"]
    assert "data" not in m


def test_los_pedidos_http_salientes_no_dejan_miga():
    assert sc.limpiar_miga({"category": "httplib", "message": "GET https://api.render.com/..."}) is None
    assert sc.limpiar_miga({"category": "query", "message": "x"}) == {"category": "query", "message": "x"}


def test_un_campo_personal_se_filtra_por_su_nombre_aunque_no_tenga_forma_de_cuil():
    assert sc.limpiar_valor({"nombre": "Ana", "apellido": "Gómez", "periodo": "2026-08", "clave": "1234"}) == \
        {"nombre": sc.FILTRADO, "apellido": sc.FILTRADO, "periodo": "2026-08", "clave": sc.FILTRADO}


def test_tope_de_eventos_por_minuto_para_no_comerse_la_cuota(monkeypatch):
    sc._recientes.clear()
    salidos = [sc.limpiar_evento(_evento_sucio()) for _ in range(sc.MAX_EVENTOS_POR_MINUTO + 5)]
    assert sum(1 for s in salidos if s) == sc.MAX_EVENTOS_POR_MINUTO and salidos[-1] is None
    monkeypatch.setattr(sc.time, "monotonic", lambda: 10 ** 6)                # pasó más de un minuto
    assert sc.limpiar_evento(_evento_sucio()) is not None
    sc._recientes.clear()


# ------------------------- configuración -------------------------
def test_sin_dsn_no_hace_nada_y_capturar_no_rompe():
    sentry_sdk.init(dsn="")
    assert sc.iniciar("", "pruebas") is False
    sc.capturar(ValueError("x"), ruta="/r", rol="trabajador", sindicato_id=1, ref="abc", codigo="E-INTERNO-00")


def test_el_sdk_arranca_sin_pii_sin_variables_locales_y_sin_rendimiento(sentry):
    o = sentry_sdk.get_client().options
    assert o["send_default_pii"] is False and o["include_local_variables"] is False
    assert o["traces_sample_rate"] == 0.0 and o["environment"] == "pruebas" and o["release"] == "abc1234"


def test_main_inicia_sentry_antes_de_crear_la_app_y_el_sdk_esta_pinneado():
    fuente = open("main.py", encoding="utf-8").read()
    assert fuente.index("sentry_config.iniciar_desde_el_entorno") < fuente.index("app = FastAPI(")
    assert "sentry-sdk==" in open("requirements.txt", encoding="utf-8").read()


def test_el_dsn_no_esta_escrito_en_ningun_archivo_del_repo():
    for archivo in ("sentry_config.py", "main.py", "observabilidad/config.json"):
        assert "eff18e99" not in open(archivo, encoding="utf-8").read(), archivo


# ------------------------- de punta a punta por la app -------------------------
from db import Sindicato, Trabajador, UsuarioSindicato

with db.get_session() as s:
    sind = Sindicato(nombre="Sentry Test", slug="sentry-test", modulos_habilitados=["dashboard"])
    s.add(sind)
    s.commit()
    s.refresh(sind)
    SID = sind.id
    s.add(Trabajador(sindicato_id=SID, cuil=CUIL, nombre="Juan Pérez", activo=True, registrado=True))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20777777770", nombre="Admin Sentry",
                           clave_hash=auth.hashear_clave("s-demo"), debe_cambiar_clave=False, es_super_admin=True))
    s.commit()


def _trabajador():
    c = TestClient(main.app, raise_server_exceptions=False)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0))
    c.cookies.set("cuil_trab", CUIL)
    return c


def _admin():
    c = TestClient(main.app, raise_server_exceptions=False)
    c.post("/admin/login", data={"usuario": "20777777770", "clave": "s-demo"})
    assert c.cookies.get(main.COOKIE_SINDICATO), "el login del admin de prueba no dejó cookie"
    return c


RANGO = {"desde": "2026-01-01", "hasta": "2026-01-02"}
CUERPO = {"recibo": {"periodo": "2026-08", "empleado": {"cuil": CUIL, "apellido_nombre": "PEREZ, JUAN"},
                     "empleador": {"nombre": "Metalsur", "cuit": CUIT}, "lineas": [], "totales_impresos": {}},
          "conceptos_nuevos": []}


def _romper(monkeypatch, donde, nombre, mensaje):
    def roto(*a, **k):
        raise ValueError(mensaje)
    monkeypatch.setattr(donde, nombre, roto)


def test_un_error_no_previsto_llega_con_su_referencia_rol_y_sindicato(sentry, monkeypatch):
    _romper(monkeypatch, main.dashboard, "kpis", "consulta rota")
    r = _admin().get("/admin/dashboard/kpis", params=RANGO)
    assert r.status_code == 500 and r.json()["ref"]
    (e,) = sentry.eventos
    assert e["tags"]["ref"] == r.json()["ref"], "la persona ve esta referencia: tiene que ser la del evento en Sentry"
    assert e["tags"]["codigo"] == "E-INTERNO-00" and e["tags"]["ruta"] == "/admin/dashboard/kpis"
    assert e["tags"]["rol"] == "sindicato" and e["tags"]["sindicato_id"] == str(SID)
    # La lista trae la cadena de excepciones; la principal, la que Sentry muestra, es la ÚLTIMA.
    assert e["exception"]["values"][-1]["type"] == "ValueError"
    assert e["release"] == "abc1234" and e["environment"] == "pruebas"


def test_una_excepcion_envuelta_en_un_grupo_se_manda_desenvuelta(sentry):
    sc.capturar(ExceptionGroup("envoltorio", [KeyError("el de adentro")]), ruta="/r", ref="abc")
    (e,) = sentry.eventos
    assert e["exception"]["values"][0]["type"] == "KeyError"


def test_un_error_del_trabajador_lleva_el_codigo_propio_de_su_ruta(sentry, monkeypatch):
    _romper(monkeypatch, main, "validar", "importe no numérico")
    r = _trabajador().post("/api/validar", json=CUERPO)
    assert r.status_code == 500
    (e,) = sentry.eventos
    assert e["tags"]["codigo"] == "E-RECIBO-03" and e["tags"]["ruta"] == "/api/validar"
    assert e["tags"]["rol"] == "trabajador" and e["tags"]["ref"] == r.json()["ref"]


def test_ese_evento_no_lleva_el_cuerpo_del_recibo_ni_el_nombre_ni_la_cookie(sentry, monkeypatch):
    _romper(monkeypatch, main, "validar", f"importe no numérico del CUIL {CUIL}")
    c = _trabajador()
    c.post("/api/validar", json=CUERPO)
    (e,) = sentry.eventos
    texto = json.dumps(e, ensure_ascii=False)
    cookie = c.cookies.get(main.COOKIE_TRABAJADOR)
    # Lo que viaja en el CUERPO del pedido (nombre, empleador, CUIT, todo el recibo) no sale. El CUIL
    # suelto del texto de la excepción sí puede salir: es dato público y sirve para diagnosticar.
    for prohibido in (CUIT, "PEREZ", "JUAN", "Metalsur", cookie, "totales_impresos", "Juan Pérez"):
        assert prohibido not in texto, f"salió: {prohibido}"
    assert "cookies" not in e["request"] and "data" not in e["request"] and "headers" not in e["request"]


def test_una_respuesta_de_error_deliberada_no_viaja_a_sentry(sentry):
    assert TestClient(main.app, raise_server_exceptions=False).get("/admin/dashboard/kpis", params=RANGO).status_code == 403
    assert _admin().get("/admin/dashboard/kpis", params={"desde": "no-es-fecha", "hasta": "2026-01-02"}).status_code == 422
    assert sentry.eventos == []


def test_el_503_de_servidor_ocupado_no_viaja_a_sentry(sentry, monkeypatch):
    """Es una respuesta de defensa de la app, no un defecto: llenaría la cuota con ruido."""
    from sqlalchemy.exc import TimeoutError as PoolTimeoutError

    c = _admin()

    def agotado(*a, **k):
        raise PoolTimeoutError("QueuePool limit reached")

    monkeypatch.setattr(main.dashboard, "kpis", agotado)
    assert c.get("/admin/dashboard/kpis", params=RANGO).status_code == 503
    assert sentry.eventos == []


def test_sin_sindicato_en_la_sesion_el_error_llega_sin_esa_etiqueta_pero_llega(sentry, monkeypatch):
    _romper(monkeypatch, main, "validar", "importe no numérico")
    _trabajador().post("/api/validar", json=CUERPO)
    (e,) = sentry.eventos
    assert "sindicato_id" not in e["tags"] and e["tags"]["ref"]
