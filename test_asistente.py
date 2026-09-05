"""Asistente del Panel Sindical (docs/ASISTENTE_PANEL.md) — Bloque 1.

Todo el circuito (ruta, gate, validación con parsear_filtros, agregados,
bucle de herramienta) se prueba con un cliente de Anthropic FALSO que sigue
un guion: no gasta créditos y no depende de la red. Lo que sí se verifica
de verdad es lo que le llega al modelo (catálogo, estado actual, tool
results con los números reales) y que jamás viaje una persona.

Correr con: .venv/Scripts/python.exe test_asistente.py
"""
import json
import os
import tempfile
from datetime import date, timedelta
from types import SimpleNamespace

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE
os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"
# El extractor construye su cliente al importarse: con una clave de mentira
# alcanza. El asistente NUNCA llega a usarla: cada test inyecta el falso.
os.environ.setdefault("ANTHROPIC_API_KEY", "clave-de-prueba")

import auth
import db
from db import (Sindicato, UsuarioSindicato, Trabajador, Seccional, Empleador,
                Notificacion, NotificacionDestinatario)
import asistente
import main
from fastapi.testclient import TestClient

db.crear_tablas()

HOY = date.today()


def _ts(dias_atras=0, hora="10:00"):
    return (HOY - timedelta(days=dias_atras)).isoformat() + " " + hora


def _dia(dias_atras=0):
    return (HOY - timedelta(days=dias_atras)).isoformat()


with db.get_session() as s:
    sind_a = Sindicato(nombre="UOM Asistente", slug="uom-asist", color_base="#0f1b2d",
                       modulos_habilitados=["dashboard", "notificaciones"])
    sind_b = Sindicato(nombre="Ajeno Asistente", slug="ajeno-asist", color_base="#0d2027",
                       modulos_habilitados=["dashboard"])
    sind_c = Sindicato(nombre="Sin Panel", slug="sin-panel", color_base="#111111",
                       modulos_habilitados=["recibos"])
    s.add(sind_a); s.add(sind_b); s.add(sind_c)
    s.commit(); s.refresh(sind_a); s.refresh(sind_b); s.refresh(sind_c)
    SID_A, SID_B, SID_C = sind_a.id, sind_b.id, sind_c.id

    s.add(UsuarioSindicato(sindicato_id=SID_A, usuario="20111111110", nombre="Admin A",
                            clave_hash=auth.hashear_clave("a-demo"), debe_cambiar_clave=False))
    s.add(UsuarioSindicato(sindicato_id=SID_C, usuario="20333333330", nombre="Admin C",
                            clave_hash=auth.hashear_clave("c-demo"), debe_cambiar_clave=False))

    rosario = Seccional(sindicato_id=SID_A, nombre="Rosario")
    cordoba = Seccional(sindicato_id=SID_A, nombre="Córdoba")
    ajena = Seccional(sindicato_id=SID_B, nombre="Ajena")
    s.add(rosario); s.add(cordoba); s.add(ajena)
    s.commit(); s.refresh(rosario); s.refresh(cordoba); s.refresh(ajena)
    SECC_ROSARIO, SECC_CORDOBA, SECC_AJENA = rosario.id, cordoba.id, ajena.id

    emp = Empleador(sindicato_id=SID_A, cuit="30111111117", razon_social="Metalsur SA")
    emp2 = Empleador(sindicato_id=SID_A, cuit="30222222225", razon_social="Textil Sur")
    s.add(emp); s.add(emp2); s.commit(); s.refresh(emp); s.refresh(emp2)
    EMP_METALSUR, EMP_TEXTIL = emp.id, emp2.id

    CUIL_R1, CUIL_R2, CUIL_C = "20111111119", "20222222227", "20333333335"
    CUIL_R3, CUIL_AJENA = "20444444443", "20999999995"
    s.add(Trabajador(sindicato_id=SID_A, cuil=CUIL_R1, nombre="Juan Rosarino",
                      registrado=True, seccional_id=SECC_ROSARIO, cuit_empleador="30111111117"))
    s.add(Trabajador(sindicato_id=SID_A, cuil=CUIL_R2, nombre="Ana Rosarina",
                      registrado=True, seccional_id=SECC_ROSARIO, cuit_empleador="30111111117"))
    s.add(Trabajador(sindicato_id=SID_A, cuil=CUIL_C, nombre="Beto Cordobés",
                      registrado=False, seccional_id=SECC_CORDOBA))
    # Homónimo de Juan en otra seccional y otra empresa: para desempatar.
    s.add(Trabajador(sindicato_id=SID_A, cuil=CUIL_R3, nombre="Juan Rosarino",
                      registrado=True, seccional_id=SECC_CORDOBA, cuit_empleador="30-22222222-5"))
    s.add(Trabajador(sindicato_id=SID_B, cuil=CUIL_AJENA, nombre="Zoe Ajena", registrado=True))

    # n1 (manual, hace 3 días) a los tres: R1 y C la leyeron, R2 no.
    n1 = Notificacion(sindicato_id=SID_A, remitente="CD", texto="Asamblea",
                       criterio="seccional", criterio_valores=[], origen="manual",
                       enviado_en=_ts(3), cantidad_destinatarios=3)
    # n2 (sistema, ayer) solo a R1, sin leer.
    n2 = Notificacion(sindicato_id=SID_A, remitente="Sistema", texto="Cambio de trámite",
                       criterio="cuil", criterio_valores=[CUIL_R1], origen="sistema",
                       enviado_en=_ts(1), cantidad_destinatarios=1)
    s.add(n1); s.add(n2); s.commit(); s.refresh(n1); s.refresh(n2)
    s.add(NotificacionDestinatario(notificacion_id=n1.id, cuil=CUIL_R1, leida_en=_ts(2)))
    s.add(NotificacionDestinatario(notificacion_id=n1.id, cuil=CUIL_R2))
    s.add(NotificacionDestinatario(notificacion_id=n1.id, cuil=CUIL_C, leida_en=_ts(2)))
    s.add(NotificacionDestinatario(notificacion_id=n2.id, cuil=CUIL_R1))
    s.commit()

# Rosario: 3 enviadas (R1 n1, R2 n1, R1 n2), 1 leída -> 2 sin leer.
# Todo el sindicato: 4 enviadas, 2 leídas -> 2 sin leer.
ROSARIO_ENVIADAS, ROSARIO_SIN_LEER = 3, 2
TOTAL_ENVIADAS = 4
PERSONAS = ["Juan", "Ana", "Beto", "Zoe", CUIL_R1, CUIL_R2, CUIL_C, CUIL_R3, CUIL_AJENA]


def _id_trabajador(cuil):
    from sqlmodel import select
    with db.get_session() as s:
        return s.exec(select(Trabajador).where(Trabajador.cuil == cuil)).first().id


def _login(usuario, clave):
    c = TestClient(main.app)
    c.post("/admin/login", data={"usuario": usuario, "clave": clave})
    return c


admin_a = _login("20111111110", "a-demo")
admin_c = _login("20333333330", "c-demo")

ESTADO_BASE = {"desde": _dia(30), "hasta": _dia(0), "seccionales": [], "empresas": [],
               "formato": "", "resultado": "", "estado_tramite": "", "tipo_notif": "",
               "sal_min": None, "sal_max": None, "tema": "", "tab": "recibos"}


# ---------- Cliente falso ----------

def _texto(t):
    return SimpleNamespace(type="text", text=t)


def _herramienta(entrada, id_="tu_1"):
    return SimpleNamespace(type="tool_use", id=id_, name="fijar_filtros", input=entrada)


def _respuesta(*bloques):
    return SimpleNamespace(content=list(bloques), stop_reason="end_turn",
                           usage=SimpleNamespace(input_tokens=10, output_tokens=5))


class ClienteFalso:
    """messages.create() devuelve, en orden, las respuestas del guion y
    guarda cada pedido para poder inspeccionarlo."""

    def __init__(self, guion, error=None):
        self.guion = list(guion)
        self.error = error
        self.llamadas = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.llamadas.append(kwargs)
        if self.error:
            raise self.error
        return self.guion.pop(0)


def _guion(*respuestas, error=None):
    falso = ClienteFalso(respuestas, error=error)
    asistente.usar_cliente(falso)
    return falso


def _filtros(**cambios):
    """Una entrada válida de la herramienta, con cambios puntuales."""
    base = {"desde": _dia(30), "hasta": _dia(0), "seccionales": [], "empresas": [],
            "formato": "", "resultado": "", "estado_tramite": "", "tipo_notif": "",
            "sal_min": None, "sal_max": None, "tema": "", "persona": "", "afiliado": None,
            "tab": "recibos", "motivo": "prueba"}
    base.update(cambios)
    return base


def _preguntar(cliente, pregunta="notificaciones no leidas de rosario", **extra):
    cuerpo = {"pregunta": pregunta, "filtros": ESTADO_BASE}
    cuerpo.update(extra)
    return cliente.post("/admin/dashboard/asistente", json=cuerpo)


def _tool_results(llamada):
    """Los tool_result que viajaron en el último mensaje de usuario de una llamada."""
    ultimo = llamada["messages"][-1]
    return ultimo["content"] if isinstance(ultimo["content"], list) else []


def _todo_lo_enviado(falso) -> str:
    return json.dumps([ll for ll in falso.llamadas], ensure_ascii=False, default=str)


# ---------- Acceso ----------

def test_sin_sesion_y_sin_modulo_403():
    _guion(_respuesta(_texto("no debería llegar")))
    assert _preguntar(TestClient(main.app)).status_code == 403
    assert _preguntar(admin_c).status_code == 403
    print("OK  test_sin_sesion_y_sin_modulo_403")


def test_pregunta_vacia_o_larga_422():
    falso = _guion(_respuesta(_texto("no debería llegar")))
    assert _preguntar(admin_a, pregunta="   ").status_code == 422
    assert _preguntar(admin_a, pregunta="x" * (asistente.MAX_PREGUNTA + 1)).status_code == 422
    assert falso.llamadas == []
    print("OK  test_pregunta_vacia_o_larga_422")


def test_sin_cliente_503():
    clave = os.environ.get("ANTHROPIC_API_KEY", "")
    os.environ["ANTHROPIC_API_KEY"] = ""
    asistente.usar_cliente(None)
    try:
        assert _preguntar(admin_a).status_code == 503
    finally:
        os.environ["ANTHROPIC_API_KEY"] = clave
    print("OK  test_sin_cliente_503")


# ---------- Flujo feliz ----------

def test_flujo_feliz_notificaciones_rosario():
    falso = _guion(
        _respuesta(_herramienta(_filtros(seccionales=[SECC_ROSARIO], tab="notificaciones"))),
        _respuesta(_texto("Rosario tiene 2 notificaciones sin leer de 3 enviadas.")),
    )
    r = _preguntar(admin_a)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["aplicar"] is True
    assert d["respuesta"] == "Rosario tiene 2 notificaciones sin leer de 3 enviadas."
    assert d["filtros"]["seccionales"] == [SECC_ROSARIO]
    assert d["filtros"]["tab"] == "notificaciones"
    assert d["filtros"]["desde"] == _dia(30) and d["filtros"]["hasta"] == _dia(0)

    # Dos llamadas: herramienta y redacción.
    assert len(falso.llamadas) == 2
    primera, segunda = falso.llamadas
    assert primera["model"] == asistente.MODELO
    assert primera["tools"][0]["name"] == "fijar_filtros"
    assert primera["tools"][0]["strict"] is True
    assert primera["system"][0]["cache_control"] == {"type": "ephemeral"}
    sistema = primera["system"][0]["text"]
    assert "UOM Asistente" in sistema
    assert f"{SECC_ROSARIO}: Rosario" in sistema and f"{SECC_CORDOBA}: Córdoba" in sistema
    assert f"{EMP_METALSUR}: Metalsur SA" in sistema
    assert "Ajena" not in sistema                  # catálogo de OTRO sindicato, jamás
    assert "Estado actual del panel" in primera["messages"][-1]["content"]

    # El tool_result lleva los números REALES calculados por dashboard.py.
    resultados = _tool_results(segunda)
    assert len(resultados) == 1 and not resultados[0].get("is_error")
    datos = json.loads(resultados[0]["content"])
    assert datos["filtros_aplicados"]["seccionales"] == ["Rosario"]
    assert datos["filtros_aplicados"]["pestaña"] == "notificaciones"
    assert datos["notificaciones"]["enviadas"] == ROSARIO_ENVIADAS
    assert datos["notificaciones"]["sin_leer"] == ROSARIO_SIN_LEER
    assert datos["kpis_del_periodo"]["notif_enviadas"] == ROSARIO_ENVIADAS
    print("OK  test_flujo_feliz_notificaciones_rosario")


def test_sin_filtro_de_seccional_cuenta_todo():
    falso = _guion(
        _respuesta(_herramienta(_filtros(tab="notificaciones"))),
        _respuesta(_texto("Hay 2 sin leer de 4.")),
    )
    assert _preguntar(admin_a, pregunta="cuántas no leyeron?").status_code == 200
    datos = json.loads(_tool_results(falso.llamadas[1])[0]["content"])
    assert datos["notificaciones"]["enviadas"] == TOTAL_ENVIADAS
    assert datos["filtros_aplicados"]["seccionales"] == "todas"
    print("OK  test_sin_filtro_de_seccional_cuenta_todo")


def test_privacidad_ninguna_persona_viaja_al_modelo():
    falso = _guion(
        _respuesta(_herramienta(_filtros(seccionales=[SECC_ROSARIO], tab="notificaciones"))),
        _respuesta(_texto("Listo.")),
    )
    assert _preguntar(admin_a).status_code == 200
    enviado = _todo_lo_enviado(falso)
    for persona in PERSONAS:
        assert persona not in enviado, persona
    print("OK  test_privacidad_ninguna_persona_viaja_al_modelo")


# ---------- Validación y aislamiento ----------

def test_fecha_futura_se_rechaza_y_el_modelo_corrige():
    manana = (HOY + timedelta(days=1)).isoformat()
    falso = _guion(
        _respuesta(_herramienta(_filtros(hasta=manana), id_="tu_1")),
        _respuesta(_herramienta(_filtros(), id_="tu_2")),
        _respuesta(_texto("Corregido.")),
    )
    r = _preguntar(admin_a, pregunta="recibos de mañana")
    assert r.status_code == 200
    assert len(falso.llamadas) == 3
    rechazo = _tool_results(falso.llamadas[1])[0]
    assert rechazo["is_error"] is True and rechazo["tool_use_id"] == "tu_1"
    assert "futura" in rechazo["content"]
    assert r.json()["filtros"]["hasta"] == _dia(0)
    print("OK  test_fecha_futura_se_rechaza_y_el_modelo_corrige")


def test_id_de_seccional_ajena_se_descarta():
    falso = _guion(
        _respuesta(_herramienta(_filtros(seccionales=[SECC_AJENA, SECC_ROSARIO],
                                         empresas=[9999, EMP_METALSUR], tab="notificaciones"))),
        _respuesta(_texto("Listo.")),
    )
    r = _preguntar(admin_a)
    assert r.status_code == 200
    assert r.json()["filtros"]["seccionales"] == [SECC_ROSARIO]
    assert r.json()["filtros"]["empresas"] == [EMP_METALSUR]
    datos = json.loads(_tool_results(falso.llamadas[1])[0]["content"])
    assert datos["filtros_aplicados"]["seccionales"] == ["Rosario"]
    assert datos["notificaciones"]["enviadas"] == ROSARIO_ENVIADAS
    print("OK  test_id_de_seccional_ajena_se_descarta")


def test_consultas_sin_flag_cae_a_recibos():
    falso = _guion(
        _respuesta(_herramienta(_filtros(tab="consultas", tema="Licencias"))),
        _respuesta(_texto("Listo.")),
    )
    r = _preguntar(admin_a, pregunta="consultas sobre licencias")
    assert r.status_code == 200
    assert r.json()["filtros"]["tab"] == "recibos"
    assert r.json()["filtros"]["tema"] == ""
    datos = json.loads(_tool_results(falso.llamadas[1])[0]["content"])
    assert "validacion_de_recibos" in datos and "consultas_por_tema" not in datos
    print("OK  test_consultas_sin_flag_cae_a_recibos")


# ---------- Cuando el modelo no filtra ----------

def test_respuesta_sin_herramienta_no_aplica_nada():
    falso = _guion(_respuesta(_texto("¿Rosario la seccional o la empresa Rosario SRL?")))
    r = _preguntar(admin_a, pregunta="lo de rosario")
    assert r.status_code == 200
    d = r.json()
    assert d["aplicar"] is False and d["filtros"] is None
    assert d["respuesta"].startswith("¿Rosario")
    assert len(falso.llamadas) == 1
    print("OK  test_respuesta_sin_herramienta_no_aplica_nada")


def test_vueltas_agotadas_devuelve_lo_ultimo_valido():
    falso = _guion(*[_respuesta(_herramienta(_filtros(seccionales=[SECC_ROSARIO]), id_=f"tu_{i}"))
                     for i in range(asistente.MAX_VUELTAS)])
    r = _preguntar(admin_a)
    assert r.status_code == 200
    assert len(falso.llamadas) == asistente.MAX_VUELTAS
    assert r.json()["aplicar"] is True
    assert r.json()["filtros"]["seccionales"] == [SECC_ROSARIO]
    assert r.json()["respuesta"] == "Apliqué los filtros en el panel."
    print("OK  test_vueltas_agotadas_devuelve_lo_ultimo_valido")


def test_historial_viaja_recortado():
    falso = _guion(_respuesta(_texto("Sigo acá.")))
    historial = [{"pregunta": f"p{i}", "respuesta": f"r{i}"} for i in range(6)]
    historial.append({"pregunta": "sin respuesta", "respuesta": ""})   # se ignora
    r = _preguntar(admin_a, pregunta="y ahora?", historial=historial)
    assert r.status_code == 200
    mensajes = falso.llamadas[0]["messages"]
    # 4 intercambios previos (los últimos) + la pregunta actual.
    assert len(mensajes) == asistente.MAX_HISTORIAL * 2 + 1
    assert [m["role"] for m in mensajes] == ["user", "assistant"] * asistente.MAX_HISTORIAL + ["user"]
    assert mensajes[0]["content"] == "p2"
    assert "y ahora?" in mensajes[-1]["content"]
    print("OK  test_historial_viaja_recortado")


# ---------- Persona (docs/ASISTENTE_PANEL.md §9) ----------

def test_persona_unica_aplica_el_afiliado_sin_mandar_el_padron():
    ana = _id_trabajador(CUIL_R2)
    falso = _guion(
        _respuesta(_herramienta(_filtros(persona="ana rosarina", tab="notificaciones"))),
        _respuesta(_texto("Tiene 1 notificación sin leer.")),
    )
    r = _preguntar(admin_a, pregunta="las notificaciones de ana rosarina")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["aplicar"] is True and d["filtros"]["afiliado"] == ana
    assert d["afiliado"]["nombre"] == "Ana Rosarina" and d["candidatos"] == []
    datos = json.loads(_tool_results(falso.llamadas[1])[0]["content"])
    assert datos["notificaciones"]["enviadas"] == 1 and datos["notificaciones"]["sin_leer"] == 1
    assert datos["filtros_aplicados"]["afiliado"].startswith("uno elegido")
    assert "ficha" in datos["filtros_aplicados"]["afiliado"]     # el modelo sabe que el panel la muestra
    assert d["afiliado"]["seccional"] == "Rosario" and d["afiliado"]["empresa"] == "Metalsur SA"
    # Al modelo no le llega ni el nombre ni el CUIL de la persona resuelta.
    al_modelo = _tool_results(falso.llamadas[1])[0]["content"] + falso.llamadas[0]["system"][0]["text"]
    assert "Rosarina" not in al_modelo and CUIL_R2 not in al_modelo
    print("OK  test_persona_unica_aplica_el_afiliado_sin_mandar_el_padron")


def test_persona_homonima_devuelve_candidatos_sin_segunda_llamada():
    falso = _guion(_respuesta(_herramienta(_filtros(persona="juan rosarino", tab="recibos"))))
    r = _preguntar(admin_a, pregunta="los recibos de juan rosarino")
    d = r.json()
    assert r.status_code == 200 and d["aplicar"] is False and d["filtros"] is None
    assert len(falso.llamadas) == 1                       # el padrón no vuelve al modelo
    assert [c["nombre"] for c in d["candidatos"]] == ["Juan Rosarino", "Juan Rosarino"]
    assert sorted(c["seccional"] for c in d["candidatos"]) == ["Córdoba", "Rosario"]
    assert d["filtros_pendientes"]["tab"] == "recibos" and d["filtros_pendientes"]["afiliado"] is None
    assert "2 afiliados" in d["respuesta"]
    print("OK  test_persona_homonima_devuelve_candidatos_sin_segunda_llamada")


def test_persona_con_empresa_desempata_homonimos():
    juan_textil = _id_trabajador(CUIL_R3)
    _guion(
        _respuesta(_herramienta(_filtros(persona="juan rosarino", empresas=[EMP_TEXTIL], tab="tramites"))),
        _respuesta(_texto("Listo.")),
    )
    d = _preguntar(admin_a, pregunta="los trámites de juan rosarino, el de textil sur").json()
    assert d["aplicar"] is True and d["filtros"]["afiliado"] == juan_textil
    assert d["afiliado"]["empresa"] == "Textil Sur" and d["afiliado"]["seccional"] == "Córdoba"
    print("OK  test_persona_con_empresa_desempata_homonimos")


def test_persona_no_encontrada_avisa_al_modelo():
    falso = _guion(
        _respuesta(_herramienta(_filtros(persona="galmarini"))),
        _respuesta(_texto("No encontré a ningún afiliado llamado Galmarini.")),
    )
    d = _preguntar(admin_a, pregunta="las notificaciones de galmarini").json()
    assert d["aplicar"] is False and d["filtros"] is None and d["candidatos"] == []
    aviso = _tool_results(falso.llamadas[1])[0]
    assert "No encontré" in aviso["content"] and "galmarini" in aviso["content"] and not aviso.get("is_error")
    assert d["respuesta"].startswith("No encontré")
    print("OK  test_persona_no_encontrada_avisa_al_modelo")


def test_afiliado_elegido_se_conserva_y_el_ajeno_se_descarta():
    juan, zoe = _id_trabajador(CUIL_R1), _id_trabajador(CUIL_AJENA)
    falso = _guion(_respuesta(_herramienta(_filtros(afiliado=juan, tab="tramites"))),
                   _respuesta(_texto("Listo.")))
    r = _preguntar(admin_a, pregunta="y sus trámites?", filtros=dict(ESTADO_BASE, afiliado=juan))
    assert r.json()["filtros"]["afiliado"] == juan and r.json()["afiliado"]["nombre"] == "Juan Rosarino"
    # El estado actual le llega al modelo como "afiliado elegido: id N", nunca el nombre.
    estado = falso.llamadas[0]["messages"][-1]["content"]
    assert ("afiliado elegido: id %d" % juan) in estado and "Juan" not in estado
    _guion(_respuesta(_herramienta(_filtros(afiliado=zoe))), _respuesta(_texto("Listo.")))
    r = _preguntar(admin_a, pregunta="recibos de esa persona")
    assert r.json()["filtros"]["afiliado"] is None and r.json()["afiliado"] is None
    print("OK  test_afiliado_elegido_se_conserva_y_el_ajeno_se_descarta")


def test_reinicio_de_filtros_sin_modelo():
    """Visto por Sd en Pruebas: 'limpiá los filtros' contestado con 'listo'
    sin llamar la herramienta dejaba la seccional puesta. El reinicio total
    ahora es determinista: ni una llamada al modelo."""
    for frase in ("limpiá los filtros", "Sacá todos los filtros.", "borra filtros", "empezá de nuevo",
                  "arrancar de cero", "sin filtros", "reiniciar los filtros!"):
        falso = _guion(_respuesta(_texto("no debería llegar")))
        d = _preguntar(admin_a, pregunta=frase, filtros=dict(ESTADO_BASE, seccionales=[SECC_ROSARIO])).json()
        assert falso.llamadas == [], frase
        assert d["aplicar"] is True and d["filtros"]["seccionales"] == [] and d["filtros"]["afiliado"] is None, frase
        assert d["filtros"]["desde"] == (HOY - timedelta(days=29)).isoformat() and d["filtros"]["tab"] == "recibos", frase
        assert d["respuesta"].startswith("Listo, reinicié")
    # Un pedido parcial sigue yendo al modelo, que es quien sabe qué conservar.
    for frase in ("sacá el filtro de seccional", "quitá la empresa", "limpiá los filtros de rosario"):
        falso = _guion(_respuesta(_texto("Hecho.")))
        assert _preguntar(admin_a, pregunta=frase).status_code == 200
        assert len(falso.llamadas) == 1, frase
    fila = _ultima_consulta()
    assert fila.pregunta == "limpiá los filtros de rosario"
    print("OK  test_reinicio_de_filtros_sin_modelo")


def test_con_filtro_de_resultado_no_viaja_el_porcentaje():
    """Con resultado=con_diferencias el % da 100 por construcción y el
    modelo lo citaba como porcentaje de la seccional (visto en Postgres
    con la UOM). Sin ese filtro, el % sí viaja."""
    falso = _guion(_respuesta(_herramienta(_filtros(resultado="con_diferencias"))), _respuesta(_texto("Listo.")))
    assert _preguntar(admin_a, pregunta="recibos con diferencias").status_code == 200
    kpis = json.loads(_tool_results(falso.llamadas[1])[0]["content"])["kpis_del_periodo"]
    assert "pct_con_diferencias" not in kpis and "recibos" in kpis
    falso = _guion(_respuesta(_herramienta(_filtros())), _respuesta(_texto("Listo.")))
    assert _preguntar(admin_a, pregunta="recibos del período").status_code == 200
    assert "pct_con_diferencias" in json.loads(_tool_results(falso.llamadas[1])[0]["content"])["kpis_del_periodo"]
    print("OK  test_con_filtro_de_resultado_no_viaja_el_porcentaje")


def test_basura_del_modelo_en_textos_cuenta_como_vacio():
    """Visto con Sonnet 5 en la prueba real: con dos strings vacíos seguidos
    emitió '</antml_parameter>\\n<parameter name="persona">' en tema y persona,
    y el servidor salió a buscar a esa "persona" tres veces. Ahora eso es
    vacío: se aplica el afiliado ya elegido y listo."""
    juan = _id_trabajador(CUIL_R1)
    basura = '</antml_parameter>\n<parameter name="persona">'
    falso = _guion(
        _respuesta(_herramienta(_filtros(tema=basura, persona="</antml_parameter>\n", afiliado=juan,
                                         tab="notificaciones"))),
        _respuesta(_texto("Tiene 2 notificaciones, 1 sin leer.")),
    )
    d = _preguntar(admin_a, pregunta="y sus notificaciones?", filtros=dict(ESTADO_BASE, afiliado=juan)).json()
    assert d["aplicar"] is True and d["filtros"]["afiliado"] == juan and d["filtros"]["tema"] == ""
    assert len(falso.llamadas) == 2 and not _tool_results(falso.llamadas[1])[0].get("is_error")
    assert asistente._texto_limpio(None) == "" and asistente._texto_limpio("  Pérez ") == "Pérez"
    print("OK  test_basura_del_modelo_en_textos_cuenta_como_vacio")


# ---------- Registro y tope diario (Bloque 5) ----------

def _ultima_consulta():
    from sqlmodel import select
    from db import ConsultaAsistente
    with db.get_session() as s:
        return s.exec(select(ConsultaAsistente).order_by(ConsultaAsistente.id.desc())).first()


def test_registro_de_cada_pregunta():
    _guion(
        _respuesta(_herramienta(_filtros(seccionales=[SECC_ROSARIO], tab="notificaciones"))),
        _respuesta(_texto("Rosario: 2 sin leer.")),
    )
    assert _preguntar(admin_a, pregunta="notificaciones sin leer de rosario").status_code == 200
    fila = _ultima_consulta()
    assert fila.sindicato_id == SID_A and fila.usuario_id            # el admin logueado
    assert fila.pregunta == "notificaciones sin leer de rosario" and fila.respuesta == "Rosario: 2 sin leer."
    assert fila.aplicado is True and fila.tab == "notificaciones"
    assert fila.filtros["seccionales"] == [SECC_ROSARIO]
    assert fila.modelo == asistente.MODELO and fila.llamadas == 2
    assert (fila.tokens_entrada, fila.tokens_salida) == (20, 10)      # 10+5 por llamada del falso
    assert fila.creado[:10] == HOY.isoformat()
    # Una repregunta sin filtros también queda, con aplicado=False.
    _guion(_respuesta(_texto("¿Rosario la seccional o la empresa?")))
    assert _preguntar(admin_a, pregunta="lo de rosario").status_code == 200
    fila = _ultima_consulta()
    assert fila.aplicado is False and fila.filtros is None and fila.tab == "" and fila.llamadas == 1
    assert db.consultas_asistente_hoy(SID_A) >= 2 and db.consultas_asistente_hoy(SID_B) == 0
    print("OK  test_registro_de_cada_pregunta")


def test_tope_diario_429():
    tope = asistente.TOPE_DIARIO
    asistente.TOPE_DIARIO = db.consultas_asistente_hoy(SID_A)     # ya llegamos al tope
    try:
        falso = _guion(_respuesta(_texto("no debería llegar")))
        r = _preguntar(admin_a)
        assert r.status_code == 429 and "tope" in r.json()["detail"]
        assert falso.llamadas == []                                 # no gastó una llamada
    finally:
        asistente.TOPE_DIARIO = tope
    _guion(_respuesta(_texto("Sigo acá.")))
    assert _preguntar(admin_a).status_code == 200                  # con el tope real, sigue
    print("OK  test_tope_diario_429")


def test_error_del_modelo_502_con_codigo():
    _guion(error=RuntimeError("se cayó la API"))
    r = _preguntar(admin_a)
    assert r.status_code == 502, r.text
    assert r.json()["codigo"] == "E-ASISTENTE-01"
    print("OK  test_error_del_modelo_502_con_codigo")


if __name__ == "__main__":
    test_sin_sesion_y_sin_modulo_403()
    test_pregunta_vacia_o_larga_422()
    test_sin_cliente_503()
    test_flujo_feliz_notificaciones_rosario()
    test_sin_filtro_de_seccional_cuenta_todo()
    test_privacidad_ninguna_persona_viaja_al_modelo()
    test_fecha_futura_se_rechaza_y_el_modelo_corrige()
    test_id_de_seccional_ajena_se_descarta()
    test_consultas_sin_flag_cae_a_recibos()
    test_respuesta_sin_herramienta_no_aplica_nada()
    test_vueltas_agotadas_devuelve_lo_ultimo_valido()
    test_historial_viaja_recortado()
    test_persona_unica_aplica_el_afiliado_sin_mandar_el_padron()
    test_persona_homonima_devuelve_candidatos_sin_segunda_llamada()
    test_persona_con_empresa_desempata_homonimos()
    test_persona_no_encontrada_avisa_al_modelo()
    test_afiliado_elegido_se_conserva_y_el_ajeno_se_descarta()
    test_reinicio_de_filtros_sin_modelo()
    test_con_filtro_de_resultado_no_viaja_el_porcentaje()
    test_basura_del_modelo_en_textos_cuenta_como_vacio()
    test_registro_de_cada_pregunta()
    test_tope_diario_429()
    test_error_del_modelo_502_con_codigo()
    print("\nTodos los tests del Asistente pasaron.")
