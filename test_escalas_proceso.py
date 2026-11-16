"""La actualización automática de la grilla (escalas_proceso.py): buscar, leer
(simulado), controlar, publicar o retener, avisar, el hilo y las correcciones
a mano. Red e IA simuladas con las respuestas REALES de labancaria.org
guardadas en fixtures/escalas/ y la grilla de agosto de 2026 escalada con el
factor del comunicado real de septiembre.

Correr con: python -m pytest test_escalas_proceso.py -q
"""
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

os.environ["ENTORNO"] = "pruebas"   # antes de importar main: se lee al importar
os.environ["PIN_ENTORNOS"] = "13572468"

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select, text

import auth
import db
import entorno
import escalas_controles as ctl
import escalas_fuente as fuente
import escalas_lectura as lectura
import escalas_proceso as proc
import grilla_bancaria
import main
import telegram
from test_escalas_controles import AGOSTO, DATOS_AGOSTO, SEPT, septiembre_real   # datos compartidos

db.crear_tablas()
FIX = Path(__file__).parent / "fixtures" / "escalas"
API = "/api/entornos/herramientas/escalas"
SEPT_DATOS = SEPT
_REAL_LISTAR = fuente.listar_novedades          # la de verdad: el fixture la reemplaza en cada test


# ---------------------------------------------------------------- utilidades
def _get_fixture(url, sin=()):
    nombre = "busqueda_grillas.json" if "search=grillas" in url else "busqueda_actualizacion.json"
    return [p for p in json.loads((FIX / nombre).read_text(encoding="utf-8")) if p["id"] not in sin]


def novedades(sin=()):
    return _REAL_LISTAR(get_json=lambda u: _get_fixture(u, sin))


def lecturas_de(datos_a, datos_b=None, periodo_impreso="2026-09"):
    usos = [{"modelo": "claude-sonnet-5-5", "tokens_entrada": 25000, "tokens_salida": 1800, "duracion_ms": 4000,
             "tokens_cache_lectura": 0, "tokens_cache_escritura": 0}] * 4
    mk = lambda d: {"contenido": json.loads(json.dumps(d)), "notas": [], "periodo_impreso": periodo_impreso, "usos": list(usos)}
    return [mk(datos_a), mk(datos_a if datos_b is None else datos_b)]


@pytest.fixture(autouse=True)
def entorno_limpio(monkeypatch):
    with Session(db.engine) as s:
        s.exec(text("DELETE FROM grillasalarial"))
        s.exec(text("DELETE FROM escalanovedad"))
        s.exec(text("DELETE FROM avisoenviado WHERE clave LIKE 'escalas-%'"))
        s.exec(text("DELETE FROM casoherramienta WHERE herramienta = 'escalas'"))
        s.commit()
    db.sembrar_grillas()
    grilla_bancaria.registrar(db.grillas_publicadas())
    proc._TAREAS["actual"] = None
    avisos, llamadas = [], []
    monkeypatch.setattr(telegram, "enviar_en_segundo_plano", lambda t: avisos.append(t))
    monkeypatch.setattr(fuente, "listar_novedades", lambda *a, **k: novedades())
    monkeypatch.setattr(fuente, "descargar_pdf", lambda url: b"%PDF-1.7 simulado")
    monkeypatch.setattr(lectura, "disponible", lambda: (True, ""))

    def leer(pdf, plantilla, modelo, veces=2):
        llamadas.append((pdf, modelo))
        return lecturas_de(SEPT_DATOS)
    monkeypatch.setattr(lectura, "leer", leer)
    yield SimpleNamespaceLike(avisos=avisos, llamadas=llamadas, monkeypatch=monkeypatch)
    grilla_bancaria.registrar(db.grillas_publicadas() or {"2026-08": AGOSTO})


class SimpleNamespaceLike:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def estados():
    return {(g["periodo"], g["estado"]) for g in db.listar_grillas()}


def usos_ia():
    with Session(db.engine) as s:
        return len(s.exec(text("SELECT id FROM usoia WHERE tipo = 'herramienta' AND modelo = 'claude-sonnet-5-5' AND tokens_entrada = 25000")).all())


# ---------------------------------------------------------------- el camino feliz
def test_una_grilla_que_pasa_los_seis_controles_se_publica_sola_y_avisa(entorno_limpio):
    e = entorno_limpio
    antes = usos_ia()
    r = proc.pasada()
    assert r["ok"] and [x["estado"] for x in r["leidas"]] == ["publicada"], r
    assert ("2026-09", "publicada") in estados() and ("2026-08", "publicada") in estados()
    g = next(x for x in db.listar_grillas() if x["periodo"] == "2026-09")
    assert g["origen"] == "automatica" and g["resuelta_por"] == "automático"
    assert [x["pasa"] for x in g["controles"]["resultados"]] == [True] * 6
    assert g["fuente_pdf"].endswith("grillas-del-acuerdo.pdf") and g["publicada_sindicato"] == "2026-10-20"
    assert any("publicada" in a and "Septiembre 2026" in a for a in e.avisos)
    assert usos_ia() - antes == 8                                  # el gasto de IA queda registrado
    # La calculadora ya usa la nueva, sin reiniciar nada.
    assert grilla_bancaria.PERIODO_VIGENTE == "2026-09"
    guardada = db.grilla_publicada("2026-09")
    assert guardada["firmada"] == "2026-10-20" and guardada["nombre"] == "Septiembre 2026"
    assert ctl.forma_valida(guardada) == []


def test_una_nota_ya_leida_no_se_vuelve_a_leer(entorno_limpio):
    proc.pasada()
    proc.pasada()
    proc.pasada()
    assert len(entorno_limpio.llamadas) == 1


def test_lo_visto_queda_en_la_base_para_la_consulta(entorno_limpio):
    proc.pasada()
    est = db.estado_de_actualizacion()
    assert est["vigente"] == "2026-09"
    # El comunicado de octubre (publicado hoy, 16-11) todavía no tiene su grilla.
    assert est["comunicado_nuevo"] == {"periodo": "2026-10", "publicada": "2026-11-16"}
    tipos = {(n["tipo"], n["periodo"]) for n in db.listar_novedades()}
    assert ("comunicado", "2026-10") in tipos and ("grillas", "2026-09") in tipos


def test_el_estado_para_la_consulta_sale_de_la_base_sin_llamar_al_sitio(entorno_limpio):
    entorno_limpio.monkeypatch.setattr(fuente, "listar_novedades", lambda *a, **k: pytest.fail("no debe llamar al sitio"))
    assert db.estado_de_actualizacion() == {"vigente": "2026-08", "vigente_publicada_sindicato": "2026-09-11", "comunicado_nuevo": None}


# ---------------------------------------------------------------- lo que NO se publica
def _con_lecturas(e, datos_a, datos_b=None, impreso="2026-09"):
    e.monkeypatch.setattr(lectura, "leer", lambda pdf, pl, m, veces=2: (e.llamadas.append(1), lecturas_de(datos_a, datos_b, impreso))[1])


def test_una_grilla_adulterada_queda_retenida_nunca_publicada(entorno_limpio):
    e = entorno_limpio
    mala = ctl.asignar(SEPT_DATOS, "ramas.administrativa.categorias.10.basico", 9_999_999.0)
    _con_lecturas(e, mala)
    r = proc.pasada()
    assert r["leidas"][0]["estado"] == "retenida" and "C4" in r["leidas"][0]["fallan"]
    assert estados() == {("2026-08", "publicada"), ("2026-09", "retenida")}
    assert db.periodo_vigente() == "2026-08" and grilla_bancaria.PERIODO_VIGENTE == "2026-08"
    assert any("RETENIDA" in a for a in e.avisos)
    g = next(x for x in db.listar_grillas() if x["estado"] == "retenida")
    assert g["resuelta_por"] == "" and not ctl.todos_pasan(g["controles"]["resultados"])
    # Una retenida no se vuelve a leer sola en cada pasada.
    proc.pasada()
    assert len(e.llamadas) == 1


@pytest.mark.parametrize("nombre, adulterar, falla", [
    ("categoría faltante", lambda d: (d["ramas"]["maestranza"]["categorias"].pop(5), d)[1], "C1"),
    ("porcentaje distinto en un adicional", lambda d: ctl.asignar(d, "adicionales.guarderia", d["adicionales"]["guarderia"] * 1.05), "C4"),
    ("una celda cambiada", lambda d: ctl.asignar(d, "ramas.ordenanza.categorias.20.basico", 1.0), "C4"),
    ("ROE que no es el del comunicado", lambda d: ctl.asignar(d, "roe.filas.0.anual.1", 900000.0), "C3"),
])
def test_cada_adulteracion_retiene_con_su_control(entorno_limpio, nombre, adulterar, falla):
    import copy
    e = entorno_limpio
    _con_lecturas(e, adulterar(copy.deepcopy(SEPT_DATOS)))
    r = proc.pasada()
    assert r["leidas"][0]["estado"] == "retenida", nombre
    assert falla in r["leidas"][0]["fallan"], (nombre, r["leidas"][0]["fallan"])
    assert ("2026-09", "publicada") not in estados()


def test_dos_lecturas_que_no_coinciden_retienen_y_guardan_la_segunda(entorno_limpio):
    e = entorno_limpio
    b = ctl.asignar(SEPT_DATOS, "adicionales.guarderia", SEPT_DATOS["adicionales"]["guarderia"] + 0.01)
    _con_lecturas(e, SEPT_DATOS, b)
    r = proc.pasada()
    assert r["leidas"][0]["estado"] == "retenida" and r["leidas"][0]["fallan"] == ["C2"]
    g = db.grilla_completa(next(x["id"] for x in db.listar_grillas() if x["estado"] == "retenida"))
    assert g["controles"]["lectura_b"]["adicionales"]["guarderia"] == b["adicionales"]["guarderia"]
    assert g["controles"]["resultados"][1]["detalle"][0]["ruta"] == "adicionales.guarderia"


def test_un_mes_salteado_no_gasta_ia_y_avisa_una_vez(entorno_limpio):
    e = entorno_limpio
    # La vigente es mayo: llegaron las notas de julio a septiembre y falta la de junio.
    with Session(db.engine) as s:
        s.exec(text("DELETE FROM grillasalarial"))
        s.commit()
    mayo = {**AGOSTO, "periodo": "2026-05", "nombre": "Mayo 2026"}
    db.guardar_grilla("2026-05", mayo, estado="publicada", origen="manual")
    r = proc.pasada()
    r2 = proc.pasada()
    assert r["leidas"] == [] and not e.llamadas
    assert any("salto" in m for m in r["mensajes"])
    assert sum("falta un mes" in a for a in e.avisos) == 1          # una vez, no en cada pasada
    assert db.periodo_vigente() == "2026-05"


def test_la_ultima_guarda_impide_publicar_una_forma_rota_aunque_los_controles_digan_que_si(entorno_limpio):
    e = entorno_limpio
    rota = json.loads(json.dumps(SEPT_DATOS))
    rota["ramas"].pop("administrativa")
    _con_lecturas(e, rota)
    e.monkeypatch.setattr(ctl, "controlar", lambda *a, **k: [{"control": f"C{i}", "nombre": "x", "pasa": True, "resumen": "", "detalle": []} for i in range(1, 7)])
    r = proc.pasada()
    assert r["leidas"][0]["estado"] == "retenida"
    assert ("2026-09", "publicada") not in estados()


# ---------------------------------------------------------------- la fuente y la IA fallan
def test_fuente_caida_no_publica_y_avisa_una_sola_vez_por_dia(entorno_limpio):
    e = entorno_limpio
    e.monkeypatch.setattr(fuente, "listar_novedades", lambda *a, **k: {"ok": False, "motivo": "no se pudo consultar labancaria.org (TimeoutError)"})
    r1, r2 = proc.pasada(), proc.pasada()
    assert r1["ok"] is False and r2["ok"] is False and not e.llamadas
    assert estados() == {("2026-08", "publicada")}
    assert sum("no se pudo consultar" in a for a in e.avisos) == 1


def test_respuesta_vacia_y_formato_cambiado_no_publican_y_avisan(entorno_limpio):
    e = entorno_limpio
    otra_cosa = [{"id": 1, "date": "2026-11-01T10:00:00", "link": "x", "title": {"rendered": "Otra cosa"}, "content": {"rendered": ""}}]
    for dia, respuesta in ((16, []), (17, otra_cosa), (18, {"code": "rest_no_route"})):
        e.monkeypatch.setattr(fuente, "listar_novedades", lambda *a, r=respuesta, **k: _REAL_LISTAR(get_json=lambda u: r))
        r = proc.pasada(datetime(2026, 11, dia, 10, 0))
        assert r["ok"] is False and not e.llamadas, respuesta
        assert estados() == {("2026-08", "publicada")}
    assert sum("labancaria.org" in a for a in e.avisos) == 3          # una por día, tres días


def test_comunicado_ilegible_no_se_lee_ni_se_publica(entorno_limpio):
    e = entorno_limpio

    def sin_numeros(*a, **k):
        r = novedades()
        for p in r["pares"]:
            if p["comunicado"] and p["periodo"] == "2026-09":
                p["comunicado"] = {**p["comunicado"], "motivo": "el comunicado no trae «Salario Inicial + ROE = total»"}
                p["comunicado"].pop("inicial", None)
        return r
    e.monkeypatch.setattr(fuente, "listar_novedades", sin_numeros)
    r = proc.pasada()
    assert not e.llamadas and ("2026-09", "publicada") not in estados()
    assert any("comunicado" in m for m in r["mensajes"]) and any("no se pudo cargar" in a for a in e.avisos)


def test_la_ia_que_falla_no_publica_registra_lo_gastado_y_reintenta_hasta_tres_veces(entorno_limpio):
    e = entorno_limpio
    gastado = [{"modelo": "claude-sonnet-5-5", "tokens_entrada": 25000, "tokens_salida": 1800, "duracion_ms": 5}]

    def falla(pdf, pl, m, veces=2):
        e.llamadas.append(1)
        raise lectura.ErrorLectura("la respuesta se cortó en el tope de 8000 tokens de salida", gastado)
    e.monkeypatch.setattr(lectura, "leer", falla)
    antes = usos_ia()
    for _ in range(5):
        proc.pasada()
    assert len(e.llamadas) == db.MAX_INTENTOS_LECTURA == 3          # no gasta IA para siempre
    assert usos_ia() - antes == 3                                    # cada intento pagado quedó registrado
    assert estados() == {("2026-08", "publicada")}
    n = next(x for x in db.listar_novedades(tipo="grillas") if x["periodo"] == "2026-09")
    assert n["resultado"] == "error" and "tope" in n["ultimo_error"]
    assert sum("no se pudo cargar" in a for a in e.avisos) == 1


def test_un_pdf_que_no_se_baja_no_gasta_ia(entorno_limpio):
    e = entorno_limpio

    def cae(url):
        raise fuente.ErrorFuente("HTTPError: 404")
    e.monkeypatch.setattr(fuente, "descargar_pdf", cae)
    proc.pasada()
    assert not e.llamadas and ("2026-09", "publicada") not in estados()
    assert any("no se pudo bajar el PDF" in a for a in e.avisos)


def test_sin_ia_disponible_avisa_y_no_lee(entorno_limpio):
    e = entorno_limpio
    e.monkeypatch.setattr(lectura, "disponible", lambda: (False, "MOCK_EXTRACTOR=1: no se llama a la API de Anthropic"))
    r = proc.pasada()
    assert not e.llamadas and ("2026-09", "publicada") not in estados() and any("MOCK_EXTRACTOR" in m for m in r["mensajes"])


# ---------------------------------------------------------------- concurrencia
def test_dos_instancias_a_la_vez_no_leen_ni_publican_dos_veces(entorno_limpio):
    e = entorno_limpio

    def lenta(pdf, pl, m, veces=2):
        e.llamadas.append(1)
        time.sleep(0.4)
        return lecturas_de(SEPT_DATOS)
    e.monkeypatch.setattr(lectura, "leer", lenta)
    salidas = []
    hilos = [threading.Thread(target=lambda: salidas.append(proc.pasada())) for _ in range(3)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert len(e.llamadas) == 1
    publicadas = [g for g in db.listar_grillas() if g["periodo"] == "2026-09" and g["estado"] == "publicada"]
    assert len(publicadas) == 1 and len(db.listar_grillas(estados=("retenida",))) == 0


def test_el_reclamo_de_la_pasada_deja_pasar_a_una_sola_instancia(entorno_limpio):
    ahora = datetime(2026, 11, 16, 10, 5)
    r = []
    hilos = [threading.Thread(target=lambda: r.append(proc.intentar(ahora))) for _ in range(4)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert sum(x is not None for x in r) == 1


# ---------------------------------------------------------------- el hilo
def test_el_hilo_no_arranca_fuera_de_pruebas_ni_sin_la_variable(monkeypatch):
    monkeypatch.setattr(proc, "_bucle", lambda i: None)
    proc._hilo = None
    monkeypatch.setenv("ESCALAS_AUTO", "1")
    for entorno_nombre in ("demo", "prod", "local", ""):
        assert proc.arrancar(entorno_nombre) is False
    monkeypatch.delenv("ESCALAS_AUTO")
    assert proc.arrancar("pruebas") is False
    monkeypatch.setenv("ESCALAS_AUTO", "0")
    assert proc.arrancar("pruebas") is False
    assert proc._hilo is None
    monkeypatch.setenv("ESCALAS_AUTO", "1")
    assert proc.arrancar("pruebas") is True
    proc._hilo.join(timeout=2)
    proc._hilo = None


def test_horas_de_las_pasadas(monkeypatch):
    monkeypatch.delenv("ESCALAS_HORAS", raising=False)
    assert proc.horas() == ["10:00", "16:00"]
    monkeypatch.setenv("ESCALAS_HORAS", "09:30, 18:00,basura,25:00")
    assert proc.horas() == ["09:30", "18:00"]
    monkeypatch.setenv("ESCALAS_HORAS", "basura")
    assert proc.horas() == ["10:00", "16:00"]
    assert proc.pasada_que_toca(datetime(2026, 11, 16, 9, 59), ["10:00", "16:00"]) is None
    assert proc.pasada_que_toca(datetime(2026, 11, 16, 10, 0), ["10:00", "16:00"]) == "10:00"
    assert proc.pasada_que_toca(datetime(2026, 11, 16, 17, 30), ["10:00", "16:00"]) == "16:00"


def test_cada_pasada_se_reclama_una_vez_por_fecha_y_hora(entorno_limpio):
    assert proc.intentar(datetime(2026, 11, 16, 10, 5)) is not None
    assert proc.intentar(datetime(2026, 11, 16, 10, 40)) is None            # la misma pasada de las 10:00
    assert proc.intentar(datetime(2026, 11, 16, 16, 1)) is not None          # la de las 16:00
    assert proc.intentar(datetime(2026, 11, 17, 10, 0)) is not None          # otro día


def test_desde_el_dia_21_avisa_una_vez_si_falta_la_grilla_del_mes(entorno_limpio):
    e = entorno_limpio
    e.monkeypatch.setattr(lectura, "disponible", lambda: (False, "sin IA"))
    e.monkeypatch.setattr(fuente, "listar_novedades", lambda *a, **k: novedades(sin=(43495,)))     # sin la nota de grillas de septiembre
    # Octubre, día 20: todavía puede salir.
    proc.pasada(datetime(2026, 10, 20, 10, 0))
    assert not any("no se encontró" in a for a in e.avisos)
    r = proc.pasada(datetime(2026, 10, 22, 10, 0))
    proc.pasada(datetime(2026, 10, 23, 10, 0))
    assert sum("no se encontró la de Septiembre 2026" in a for a in e.avisos) == 1
    assert any("aviso: falta la grilla de 2026-09" in m for m in r["mensajes"])


# ---------------------------------------------------------------- corregir y publicar a mano
def _retenida(e, mala_ruta="ramas.administrativa.categorias.10.basico", valor=9_999_999.0):
    _con_lecturas(e, ctl.asignar(SEPT_DATOS, mala_ruta, valor))
    proc.pasada()
    return next(g["id"] for g in db.listar_grillas() if g["estado"] == "retenida")


def test_corregir_la_celda_mala_hace_pasar_los_controles_y_se_puede_publicar(entorno_limpio):
    e = entorno_limpio
    gid = _retenida(e)
    ruta = "ramas.administrativa.categorias.10.basico"
    correcto = ctl.plano(SEPT_DATOS)[ruta]
    out = proc.corregir(gid, [{"ruta": ruta, "valor": correcto}], "snavello", "dígito mal leído")
    por = {r["control"]: r for r in out["controles"]}
    assert all(por[c]["pasa"] is True for c in ("C1", "C3", "C4", "C5", "C6"))
    assert por["C2"]["pasa"] is None and "snavello" in por["C2"]["resumen"]
    g = db.grilla_completa(gid)
    assert "Corregida a mano por snavello" in g["nota"] and g["controles"]["correcciones"][0]["celdas"] == [ruta]
    assert proc.publicar_a_mano(gid, "snavello") == {"ok": True, "forzada": False}
    assert db.grilla_publicada("2026-09")["ramas"]["administrativa"]["categorias"][10]["basico"] == correcto
    assert grilla_bancaria.PERIODO_VIGENTE == "2026-09"
    g = db.grilla_completa(gid)
    assert g["estado"] == "publicada" and g["resuelta_por"] == "snavello" and g["resuelta_en"]


def test_publicar_sin_corregir_exige_decir_por_que(entorno_limpio):
    gid = _retenida(entorno_limpio)
    with pytest.raises(ValueError, match="por qué"):
        proc.publicar_a_mano(gid, "snavello", "")
    assert proc.publicar_a_mano(gid, "snavello", "el sindicato confirmó el valor por teléfono")["forzada"] is True
    assert "controles sin pasar" in db.grilla_completa(gid)["nota"]


def test_una_forma_rota_no_se_publica_ni_con_nota(entorno_limpio):
    gid = _retenida(entorno_limpio)
    g = db.grilla_completa(gid)
    roto = json.loads(json.dumps(g["contenido"]))
    roto["roe"]["filas"] = []
    assert db.corregir_grilla_retenida(gid, roto, g["controles"], "x")
    with pytest.raises(ValueError, match="forma"):
        proc.publicar_a_mano(gid, "snavello", "igual")
    assert ("2026-09", "publicada") not in estados()


def test_las_correcciones_solo_tocan_celdas_existentes_y_numeros(entorno_limpio):
    gid = _retenida(entorno_limpio)
    for cambios in ([{"ruta": "ramas.administrativa.categorias.999.basico", "valor": 1}],
                    [{"ruta": "periodo", "valor": 1}],
                    [{"ruta": "adicionales.guarderia", "valor": "mucho"}],
                    [{"valor": 1}]):
        with pytest.raises(ValueError):
            proc.corregir(gid, cambios, "x")


def test_una_publicada_no_se_corrige_ni_se_publica_de_nuevo(entorno_limpio):
    proc.pasada()
    gid = next(g["id"] for g in db.listar_grillas() if g["periodo"] == "2026-09")
    with pytest.raises(ValueError):
        proc.corregir(gid, [{"ruta": "adicionales.guarderia", "valor": 1}], "x")
    with pytest.raises(ValueError):
        proc.publicar_a_mano(gid, "x", "nota")


def test_publicar_reemplaza_la_publicada_del_mismo_periodo(entorno_limpio):
    e = entorno_limpio
    gid = _retenida(e)
    proc.publicar_a_mano(gid, "snavello", "confirmado")
    # Sale otra lectura retenida del mismo período y se la publica: la anterior pasa a reemplazada.
    otra = db.guardar_grilla("2026-09", db.grilla_publicada("2026-09"), estado="retenida", origen="manual")
    assert db.publicar_grilla(otra, "snavello")
    assert [g["estado"] for g in db.listar_grillas() if g["periodo"] == "2026-09"].count("publicada") == 1


# ---------------------------------------------------------------- ensayo de lectura
def test_el_ensayo_compara_celda_por_celda_sin_publicar_nada(entorno_limpio):
    e = entorno_limpio
    ago = lecturas_de(DATOS_AGOSTO, periodo_impreso="2026-08")
    e.monkeypatch.setattr(lectura, "leer", lambda pdf, pl, m, veces=2: (e.llamadas.append(pl), ago)[1])
    antes = usos_ia()
    r = proc.ensayo("2026-08", "snavello")
    assert r["distintas_a"] == 0 and r["distintas_b"] == 0 and r["celdas"] > 600
    # La plantilla que recibió la IA es la estructura de agosto SIN importes.
    assert "basico" not in json.dumps(e.llamadas[0]) and e.llamadas[0]["ramas"]["administrativa"]["categorias"][0] == {"nombre": "Inicial", "anios": 0}
    assert estados() == {("2026-08", "publicada")} and usos_ia() - antes == 8
    caso = db.caso_herramienta("escalas", r["caso_id"])
    assert caso.grilla == "2026-08" and caso.distintos == 0 and caso.quien == "snavello"
    assert caso.diferencias["lectura_a"]["celdas"] == r["celdas"]


def test_el_ensayo_lista_las_celdas_distintas(entorno_limpio):
    e = entorno_limpio
    mala = ctl.asignar(DATOS_AGOSTO, "adicionales.falla_caja", 1.0)
    mala = ctl.asignar(mala, "ramas.ordenanza.categorias.3.basico", None)
    e.monkeypatch.setattr(lectura, "leer", lambda pdf, pl, m, veces=2: lecturas_de(mala, DATOS_AGOSTO, "2026-08"))
    r = proc.ensayo("2026-08", "snavello")
    assert r["distintas_a"] == 2 and r["distintas_b"] == 0
    assert {d["etiqueta"] for d in r["lectura_a"]["detalle"]} == {"Adicional · falla caja", "Ordenanza · 3 años · básico"}
    assert db.caso_herramienta("escalas", r["caso_id"]).distintos == 2
    assert estados() == {("2026-08", "publicada")}


def test_el_ensayo_necesita_una_grilla_publicada_y_una_nota(entorno_limpio):
    with pytest.raises(ValueError, match="publicada"):
        proc.ensayo("2026-03", "x")
    with pytest.raises(ValueError, match="nota"):
        db.guardar_grilla("2026-05", {**AGOSTO, "periodo": "2026-05"}, estado="publicada", origen="manual")
        proc.ensayo("2026-05", "x")


# ---------------------------------------------------------------- rutas
def _con_pase():
    """Una sesión de plataforma nominal: lo mismo que usan las otras herramientas."""
    c = TestClient(main.app)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", id_usuario=1, ident="snavello"))
    return c


def test_las_rutas_exigen_el_pase_y_no_existen_en_la_demo(monkeypatch):
    anonimo = TestClient(main.app)
    assert anonimo.get(API + "/grillas").status_code == 403
    assert anonimo.post(API + "/buscar", json={}).status_code == 403
    r = anonimo.get("/entornos/herramientas/convenio-escalas/estado", headers={"Accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/entornos")
    c = _con_pase()
    assert c.get("/entornos/herramientas/convenio-escalas/estado").status_code == 200
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", False)
    assert c.get(API + "/grillas").status_code == 404
    assert c.get("/entornos/herramientas/convenio-escalas/estado").status_code == 404


def test_la_vista_lista_las_grillas_con_sus_controles_y_lo_visto(entorno_limpio):
    e = entorno_limpio
    _retenida(e)
    c = _con_pase()
    d = c.get(API + "/grillas").json()
    assert {g["estado"] for g in d["grillas"]} == {"publicada", "retenida"}
    ret = next(g for g in d["grillas"] if g["estado"] == "retenida")
    assert [x["control"] for x in ret["controles"]["resultados"]] == ["C1", "C2", "C3", "C4", "C5", "C6"]
    assert "lectura_b" not in ret["controles"]                  # la lista no arrastra la segunda lectura entera
    assert any(n["tipo"] == "comunicado" and n["periodo"] == "2026-10" for n in d["novedades"])
    assert d["config"]["horas"] == ["10:00", "16:00"] and d["config"]["modelo"] == "claude-sonnet-5-5"
    assert d["actualizacion"]["vigente"] == "2026-08"
    det = c.get(f"{API}/grillas/{ret['id']}").json()
    assert det["contenido"]["periodo"] == "2026-09" and det["celdas_con_etiqueta"]["adicionales.guarderia"] == "Adicional · guarderia"
    assert c.get(f"{API}/grillas/999999").status_code == 404
    assert c.get(API + "/estado").json()["vigente"] == "2026-08"


def test_resolver_una_retenida_por_la_api(entorno_limpio):
    e = entorno_limpio
    gid = _retenida(e)
    c = _con_pase()
    ruta = "ramas.administrativa.categorias.10.basico"
    assert c.post(f"{API}/grillas/{gid}/corregir", json={"cambios": []}).status_code == 422
    assert c.post(f"{API}/grillas/{gid}/corregir", json={"cambios": [{"ruta": "nada.nada", "valor": 1}]}).status_code == 422
    r = c.post(f"{API}/grillas/{gid}/corregir", json={"cambios": [{"ruta": ruta, "valor": ctl.plano(SEPT_DATOS)[ruta]}], "nota": "ok"})
    assert r.status_code == 200 and r.json()["controles"][3]["pasa"] is True
    assert c.post(f"{API}/grillas/{gid}/publicar", json={}).status_code == 200
    assert c.post(f"{API}/grillas/{gid}/publicar", json={}).status_code == 422          # ya no está retenida
    assert db.grilla_completa(gid)["resuelta_por"] == "snavello"


def test_descartar_una_retenida_por_la_api(entorno_limpio):
    gid = _retenida(entorno_limpio)
    c = _con_pase()
    assert c.post(f"{API}/grillas/{gid}/descartar", json={"nota": "no corresponde"}).status_code == 200
    g = db.grilla_completa(gid)
    assert g["estado"] == "descartada" and g["resuelta_por"] == "snavello" and g["nota"] == "no corresponde"
    assert c.post(f"{API}/grillas/{gid}/descartar", json={}).status_code == 404         # ya no está retenida
    assert db.periodo_vigente() == "2026-08"


def test_buscar_ahora_corre_en_segundo_plano_y_una_a_la_vez(entorno_limpio):
    e = entorno_limpio
    c = _con_pase()
    assert c.post(API + "/buscar", json={"periodo": "no"}).status_code == 422
    r = c.post(API + "/buscar", json={})
    assert r.status_code == 200 and r.json()["lanzada"] == "buscar"
    for _ in range(100):
        t = proc.tarea_actual()
        if t and t["estado"] != "corriendo":
            break
        time.sleep(0.05)
    assert t["estado"] == "terminada" and t["resultado"]["leidas"][0]["estado"] == "publicada"
    assert ("2026-09", "publicada") in estados()
    # Dos pedidos dentro del mismo minuto: el segundo se frena (cada lectura gasta IA).
    assert c.post(API + "/buscar", json={}).status_code == 429


def test_el_ensayo_por_la_api_valida_antes_de_gastar(entorno_limpio):
    c = _con_pase()
    assert c.post(API + "/ensayo", json={"periodo": "x"}).status_code == 422
    assert c.post(API + "/ensayo", json={"periodo": "2026-03"}).status_code == 422
    entorno_limpio.monkeypatch.setattr(lectura, "disponible", lambda: (False, "sin clave"))
    assert c.post(API + "/ensayo", json={"periodo": "2026-08"}).status_code == 503
    entorno_limpio.monkeypatch.setattr(lectura, "disponible", lambda: (True, ""))
    entorno_limpio.monkeypatch.setattr(lectura, "leer", lambda pdf, pl, m, veces=2: lecturas_de(DATOS_AGOSTO, periodo_impreso="2026-08"))
    assert c.post(API + "/ensayo", json={"periodo": "2026-08"}).status_code == 200
    for _ in range(100):
        t = proc.tarea_actual()
        if t and t["estado"] != "corriendo":
            break
        time.sleep(0.05)
    assert t["resultado"]["distintas_a"] == 0
    ens = c.get(API + "/grillas").json()["ensayos"]
    assert ens and ens[0]["periodo"] == "2026-08" and ens[0]["distintas_a"] == 0
    assert c.get(f"{API}/ensayos/{ens[0]['id']}").json()["diferencias"]["lectura_a"]["distintas"] == 0


# ---------------------------------------------------------------- la pantalla
def test_la_pantalla_no_usa_innerhtml_y_carga_sus_archivos_con_sello():
    js = (Path(__file__).parent / "static" / "escalas_estado.js").read_text(encoding="utf-8")
    html = (Path(__file__).parent / "templates" / "escalas_estado.html").read_text(encoding="utf-8")
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js and "document.write" not in js
    assert "sello_static('escalas_estado.js')" in html and "sello_static('escalas_estado.css')" in html and "sello_static('fonts/" in html
    c = _con_pase()
    cuerpo = c.get("/entornos/herramientas/convenio-escalas/estado").text
    assert "/static/escalas_estado.js?v=" in cuerpo and "/static/escalas_estado.css?v=" in cuerpo and "Estado de las grillas" in cuerpo


# ------------------------------------------------- D26 y D27: la primera grilla real (septiembre 2026)
def test_la_septiembre_real_se_publica_sola_y_conserva_el_trimestre_de_conectividad_vencido(entorno_limpio):
    e = entorno_limpio
    _con_lecturas(e, septiembre_real())
    r = proc.pasada()
    assert [x["estado"] for x in r["leidas"]] == ["publicada"], r
    g = db.grilla_completa(next(x for x in db.listar_grillas() if x["periodo"] == "2026-09")["id"])
    meses = [x["meses"][0] for x in g["contenido"]["conectividad"]]
    assert meses == ["2026-06", "2026-09"]                                       # D27: conservada, en orden cronológico
    assert g["contenido"]["conectividad"][0] == DATOS_AGOSTO["conectividad"][0]
    assert "Conectividad 2026-06 a 2026-08: conservada de la grilla anterior, el PDF ya no la trae" in g["nota"]
    assert g["controles"]["conectividad_conservada"] == [["2026-06", "2026-07", "2026-08"]]
    assert [x["pasa"] for x in g["controles"]["resultados"]] == [True] * 6
    assert ctl.forma_valida(g["contenido"]) == []
    assert grilla_bancaria.PERIODO_VIGENTE == "2026-09"


def test_retenida_descartada_y_pasada_forzada_publica_sola_avisa_y_refresca_la_calculadora(entorno_limpio):
    """El camino de SDN: la primera lectura quedó retenida; se descarta y «Buscar ahora» vuelve a leer la nota."""
    e = entorno_limpio
    mala = ctl.asignar(septiembre_real(), "roe.filas.0.hasta", 3337836)           # un tope a 100 pesos (D26 admitía 1 peso; con D30 un tope a 2 pesos ya pasa)
    _con_lecturas(e, mala)
    r = proc.pasada()
    assert r["leidas"][0]["estado"] == "retenida" and r["leidas"][0]["fallan"] == ["C4"]
    gid = next(x["id"] for x in db.listar_grillas() if x["estado"] == "retenida")
    assert grilla_bancaria.PERIODO_VIGENTE == "2026-08"
    # Sin forzar, una retenida no se relee sola.
    proc.pasada()
    assert len(e.llamadas) == 1
    assert db.descartar_grilla(gid, "SDN", "lectura con un tope mal leído") is True
    # Aunque agotara los intentos, «Buscar ahora» (forzar) relee la nota.
    with Session(db.engine) as s:
        s.exec(text("UPDATE escalanovedad SET intentos = 3 WHERE tipo = 'grillas'"))
        s.commit()
    avisos_antes = len(e.avisos)
    _con_lecturas(e, septiembre_real())
    r = proc.pasada(forzar_periodo="2026-09")
    assert [x["estado"] for x in r["leidas"]] == ["publicada"], r
    assert len(e.llamadas) == 2
    assert ("2026-09", "publicada") in estados() and ("2026-09", "descartada") in estados()
    assert db.periodo_vigente() == "2026-09" and grilla_bancaria.PERIODO_VIGENTE == "2026-09"      # calculadora refrescada
    assert any("publicada" in a and "Septiembre 2026" in a for a in e.avisos[avisos_antes:])


def test_el_ensayo_no_cuenta_como_distinta_la_conectividad_conservada(entorno_limpio):
    e = entorno_limpio
    _con_lecturas(e, septiembre_real())
    proc.pasada()
    e.monkeypatch.setattr(lectura, "leer", lambda pdf, pl, m, veces=2: lecturas_de(septiembre_real()))
    r = proc.ensayo("2026-09", "SDN")
    assert r["distintas_a"] == 0 and r["distintas_b"] == 0, r["lectura_a"]["detalle"][:3]


# ------------------------------------------------- D28: una celda tapada por una firma se completa por cálculo
RUTA_TAPADA = "ramas.maestranza.categorias.37.basico"           # Maestranza · Capataz Gral. · básico


def _lecturas_d28(datos, parciales=None, notas=None, extra_b=None):
    """Dos lecturas de septiembre con la celda tapada sin leer en las dos (o con `extra_b` en la segunda)."""
    ls = lecturas_de(datos, extra_b)
    for l in ls:
        l["parciales"] = dict(parciales or {})
        l["notas"] = list(notas or [])
    return ls


def _con_d28(e, datos, **kw):
    e.monkeypatch.setattr(lectura, "leer", lambda pdf, pl, m, veces=2: (e.llamadas.append(1), _lecturas_d28(datos, **kw))[1])


def _enmascarada(v):
    t = list(ctl.pesos_ar(v))
    t[[i for i, ch in enumerate(t) if ch.isdigit()][1]] = "?"
    return "".join(t)


def test_d28_una_celda_tapada_en_las_dos_lecturas_se_completa_publica_sola_y_queda_dicho(entorno_limpio):
    e = entorno_limpio
    real = ctl.plano(septiembre_real())[RUTA_TAPADA]
    tapada = ctl.asignar(septiembre_real(), RUTA_TAPADA, None)
    parcial = _enmascarada(real)
    _con_d28(e, tapada, parciales={RUTA_TAPADA: parcial}, notas=["Coef de Subcapataz Gral. y Capataz Gral. parcialmente cubiertos por firma en las tablas del Día del Bancario, "
                                                                              "pero legibles en la tabla de básicos (2,17 y 2,36).",
                                                                              f"Capataz Gral.: el básico está tachado por una firma/sello (se lee '{parcial}'); se deja null."])
    r = proc.pasada()
    assert [x["estado"] for x in r["leidas"]] == ["publicada"], r
    g = db.grilla_completa(next(x for x in db.listar_grillas() if x["periodo"] == "2026-09")["id"])
    calc = ctl.plano(g["contenido"])[RUTA_TAPADA]
    assert abs(calc - real) <= 0.01 and g["estado"] == "publicada"
    assert ctl.forma_valida(g["contenido"]) == []
    [cel] = g["controles"]["celdas_calculadas"]
    assert cel["ruta"] == RUTA_TAPADA and cel["valor_calculado"] == calc and cel["lectura_parcial"] == [parcial]
    c1 = g["controles"]["resultados"][0]
    assert c1["pasa"] is True and c1["detalle"][0]["valor_calculado"] == calc
    assert [x["pasa"] for x in g["controles"]["resultados"]] == [True] * 6
    assert f"Maestranza · Capataz Gral. · básico: $ {ctl.pesos_ar(calc)} calculado (vigente × 1,0189" in g["nota"]
    assert f"se leía «{parcial}»" in g["nota"] and "±1 centavo" in g["nota"]
    aviso = next(a for a in e.avisos if "publicada" in a)
    assert "calcularon" in aviso and "Capataz Gral." in aviso
    # D29: los comentarios de la IA no retuvieron; quedan guardados y van en el aviso.
    assert len(g["controles"]["notas_lectura"]) == 2 and "Comentarios de la lectura: Coef de Subcapataz" in aviso
    assert db.periodo_vigente() == "2026-09" and grilla_bancaria.PERIODO_VIGENTE == "2026-09"
    # La vista de estado recibe la lista de celdas calculadas para marcarlas.
    det = _con_pase().get(f"{API}/grillas/{g['id']}").json()
    assert det["controles"]["celdas_calculadas"][0]["ruta"] == RUTA_TAPADA


def test_d28_sin_lectura_parcial_tambien_se_publica(entorno_limpio):
    e = entorno_limpio
    _con_d28(e, ctl.asignar(septiembre_real(), RUTA_TAPADA, None))
    r = proc.pasada()
    assert [x["estado"] for x in r["leidas"]] == ["publicada"], r


def test_d28_con_una_lectura_parcial_incompatible_la_grilla_queda_retenida(entorno_limpio):
    e = entorno_limpio
    _con_d28(e, ctl.asignar(septiembre_real(), RUTA_TAPADA, None), parciales={RUTA_TAPADA: "9.?22.194,42"})
    r = proc.pasada()
    assert r["leidas"][0]["estado"] == "retenida" and "C1" in r["leidas"][0]["fallan"]
    g = db.grilla_completa(next(x["id"] for x in db.listar_grillas() if x["estado"] == "retenida"))
    assert ctl.plano(g["contenido"])[RUTA_TAPADA] is None and g["controles"]["celdas_calculadas"] == []
    assert "no es compatible con lo que se alcanzaba a ver" in str(g["controles"]["resultados"][0]["detalle"])
    assert g["controles"]["parciales"][0] == {RUTA_TAPADA: "9.?22.194,42"}              # lo que se veía queda guardado para revisar


def test_d28_tres_celdas_sin_leer_retienen(entorno_limpio):
    e = entorno_limpio
    datos = septiembre_real()
    for ruta in (RUTA_TAPADA, "ramas.administrativa.categorias.10.basico", "ramas.ordenanza.categorias.20.basico"):
        datos = ctl.asignar(datos, ruta, None)
    _con_d28(e, datos)
    r = proc.pasada()
    assert r["leidas"][0]["estado"] == "retenida" and ("2026-09", "publicada") not in estados()


def test_d28_corregir_una_retenida_aplica_la_misma_regla_y_completa_el_contenido(entorno_limpio):
    e = entorno_limpio
    datos = septiembre_real()
    for ruta in (RUTA_TAPADA, "ramas.administrativa.categorias.10.basico", "ramas.ordenanza.categorias.20.basico"):
        datos = ctl.asignar(datos, ruta, None)
    _con_d28(e, datos)
    proc.pasada()
    gid = next(x["id"] for x in db.listar_grillas() if x["estado"] == "retenida")
    # La persona carga a mano una de las tres celdas: quedan dos sin valor, y D28 completa las dos.
    resultado = proc.corregir(gid, [{"ruta": "ramas.ordenanza.categorias.20.basico",
                                     "valor": ctl.plano(septiembre_real())["ramas.ordenanza.categorias.20.basico"]}], "SDN", "una a mano")
    g = db.grilla_completa(gid)
    assert [x["pasa"] for x in resultado["controles"]] == [True, None, True, True, True, True]
    assert len(g["controles"]["celdas_calculadas"]) == 2
    assert ctl.plano(g["contenido"])[RUTA_TAPADA] is not None and ctl.forma_valida(g["contenido"]) == []
    assert proc.publicar_a_mano(gid, "SDN")["forzada"] is False


def test_d28_el_ensayo_aplica_la_misma_regla(entorno_limpio):
    e = entorno_limpio
    _con_lecturas(e, septiembre_real())
    proc.pasada()                                                      # septiembre ya publicada
    e.monkeypatch.setattr(lectura, "leer", lambda pdf, pl, m, veces=2: _lecturas_d28(ctl.asignar(septiembre_real(), RUTA_TAPADA, None)))
    r = proc.ensayo("2026-09", "SDN")
    assert [x["pasa"] for x in r["controles"]] == [True] * 6
    assert r["distintas_a"] <= 1                                       # a lo sumo la celda calculada, por un centavo de redondeo


def test_d28_retenida_descartada_y_pasada_forzada_vuelve_a_leer_y_publica(entorno_limpio):
    """El camino de la octubre real: retenida -> db.descartar_grilla -> pasada(forzar_periodo) relee la nota,
    ahora con la regla D28, y publica sola."""
    e = entorno_limpio
    datos = septiembre_real()
    for ruta in (RUTA_TAPADA, "ramas.administrativa.categorias.10.basico", "ramas.ordenanza.categorias.20.basico"):
        datos = ctl.asignar(datos, ruta, None)
    _con_d28(e, datos)
    r = proc.pasada()
    assert r["leidas"][0]["estado"] == "retenida"
    gid = next(x["id"] for x in db.listar_grillas() if x["estado"] == "retenida")
    proc.pasada()
    assert len(e.llamadas) == 1                                        # sin forzar no se relee
    assert db.descartar_grilla(gid, "SDN", "se relee con D28") is True
    _con_d28(e, ctl.asignar(septiembre_real(), RUTA_TAPADA, None))
    r = proc.pasada(forzar_periodo="2026-09")
    assert [x["estado"] for x in r["leidas"]] == ["publicada"], r
    assert len(e.llamadas) == 2 and ("2026-09", "descartada") in estados() and ("2026-09", "publicada") in estados()


# ------------------------------------------------- D29: los comentarios de la IA no retienen
def _con_notas(e, datos, notas, defectos=()):
    def leer(pdf, pl, m, veces=2):
        e.llamadas.append(1)
        ls = lecturas_de(datos)
        for l in ls:
            l["notas"], l["defectos"] = list(notas), list(defectos)
        return ls
    e.monkeypatch.setattr(lectura, "leer", leer)


def test_d29_una_grilla_buena_con_un_comentario_del_modelo_se_publica_y_lo_dice(entorno_limpio):
    e = entorno_limpio
    _con_notas(e, septiembre_real(), ["La firma tapa parte del encabezado, pero las cifras se leen bien."])
    r = proc.pasada()
    assert [x["estado"] for x in r["leidas"]] == ["publicada"], r
    g = db.grilla_completa(next(x for x in db.listar_grillas() if x["periodo"] == "2026-09")["id"])
    assert g["controles"]["notas_lectura"] == ["La firma tapa parte del encabezado, pero las cifras se leen bien."]
    assert any("Comentarios de la lectura: La firma tapa" in a for a in e.avisos)


def test_d29_el_aviso_recorta_los_comentarios_largos():
    txt = proc.texto_publicada("2026-09", [], None, ["x" * 5000])
    assert len(txt) < 1200 and "…" in txt


def test_d29_una_nota_con_una_categoria_faltante_retiene(entorno_limpio):
    e = entorno_limpio
    datos = septiembre_real()
    datos["ramas"]["maestranza"]["categorias"].pop(5)
    _con_notas(e, datos, ["falta una categoría"])
    assert proc.pasada()["leidas"][0]["estado"] == "retenida"


def test_d29_un_defecto_de_la_respuesta_retiene_aunque_la_celda_quede_nula(entorno_limpio):
    e = entorno_limpio
    _con_notas(e, ctl.asignar(septiembre_real(), RUTA_TAPADA, None), [], ["valor no numérico en maestranza/Capataz Gral.: 'mil'"])
    r = proc.pasada()
    assert r["leidas"][0]["estado"] == "retenida" and "C1" in r["leidas"][0]["fallan"]
    g = db.grilla_completa(next(x["id"] for x in db.listar_grillas() if x["estado"] == "retenida"))
    assert g["controles"]["defectos_respuesta"]
