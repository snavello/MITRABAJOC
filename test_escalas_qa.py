"""QA independiente del bloque 5 (grillas): intentos de colar una grilla mala, de
hacer algo dos veces o de tumbar la app. Cada test afirma lo que DEBERÍA pasar;
un test rojo es un defecto. Correr: python -m pytest test_escalas_qa.py -q"""
import copy
import json
import threading
import time
from datetime import datetime, timedelta

import pytest
from sqlmodel import Session, text

import db
import escalas_controles as ctl
import escalas_fuente as fuente
import escalas_lectura as lectura
import escalas_proceso as proc
import fechas
from test_escalas_proceso import (API, SEPT_DATOS, _con_lecturas, _con_pase, _retenida, entorno_limpio,  # noqa: F401
                                  estados, lecturas_de, novedades)
from test_escalas_controles import DATOS_AGOSTO, lectura as lect, escalar


_DESCARGAR_REAL = fuente.descargar_pdf
_LISTAR_REAL = fuente.listar_novedades


# ------------------------------------------------------------- controles
def _com(g, pct=2.0, per="2026-12"):
    return {"inicial": g["ramas"]["administrativa"]["categorias"][0]["conformado"],
            "roe": round(g["roe"]["filas"][0]["anual"][1] / 12, 2), "porcentaje": pct,
            "dia_bancario_minimo": g["dia_bancario"]["minimo"], "periodo": per}


def test_conectividad_de_un_trimestre_nuevo_se_controla_contra_algo():
    """En diciembre entra un trimestre nuevo de conectividad: hoy no la mira ningún control
    salvo que sea monótona. Un importe 30 veces mayor NO debería pasar."""
    nov = escalar(DATOS_AGOSTO, 1.019)
    dic = escalar(nov, 1.02)
    d = 99999.0
    dic["conectividad"] = copy.deepcopy(nov["conectividad"]) + [
        {"meses": ["2026-12", "2027-01", "2027-02"], "diario": d, "mas_de_4_dias": d * 9, "mensual": d * 22}]
    r = ctl.controlar([lect(dic, "2026-12")] * 2, nov, _com(dic), "2026-12", "2026-11")
    assert not ctl.todos_pasan(r), "conectividad nueva 30 veces mayor pasó los seis controles"


def test_una_entrada_de_conectividad_inventada_no_pasa():
    sept = escalar(DATOS_AGOSTO, 1.019)
    sept["conectividad"].append({"meses": ["2026-12"], "diario": 1.0, "mas_de_4_dias": 2.0, "mensual": 3.0})
    com = _com(sept, 1.9, "2026-09")
    r = ctl.controlar([lect(sept)] * 2, DATOS_AGOSTO, com, "2026-09", "2026-08")
    assert not ctl.todos_pasan(r), "una entrada de conectividad de otro trimestre, con 1/2/3 pesos, pasó"


def test_error_de_un_centavo_en_ambas_lecturas_no_pasa():
    sept = escalar(DATOS_AGOSTO, 1.019)
    mala = ctl.asignar(sept, "ramas.administrativa.categorias.10.basico", round(sept["ramas"]["administrativa"]["categorias"][10]["basico"] + 0.02, 2))
    com = _com(sept, 1.9, "2026-09")
    r = ctl.controlar([lect(mala)] * 2, DATOS_AGOSTO, com, "2026-09", "2026-08")
    assert not ctl.todos_pasan(r), "+2 centavos sistemático en un básico pasó"


def test_tope_hasta_alterado_en_un_peso_no_pasa():
    sept = escalar(DATOS_AGOSTO, 1.019)
    h = sept["roe"]["filas"][0]["hasta"]
    mala = ctl.asignar(sept, "roe.filas.0.hasta", h + 1)
    com = _com(sept, 1.9, "2026-09")
    r = ctl.controlar([lect(mala)] * 2, DATOS_AGOSTO, com, "2026-09", "2026-08")
    assert not ctl.todos_pasan(r), "tope hasta +1 peso pasó"


# ------------------------------------------------------------- correcciones a mano
@pytest.mark.parametrize("cambios", [["x"], [1], [None], [[]], [{"ruta": ["a"], "valor": 1}]])
def test_corregir_con_elementos_que_no_son_objeto_da_4xx_no_500(entorno_limpio, cambios):
    gid = _retenida(entorno_limpio)
    c = _con_pase()
    c.raise_server_exceptions = False
    r = c.post(f"{API}/grillas/{gid}/corregir", json={"cambios": cambios})
    assert r.status_code in (400, 422), (cambios, r.status_code)


@pytest.mark.parametrize("crudo", ['{"cambios":[{"ruta":"adicionales.guarderia","valor":NaN}]}',
                                   '{"cambios":[{"ruta":"adicionales.guarderia","valor":Infinity}]}',
                                   '{"cambios":[{"ruta":"adicionales.guarderia","valor":1e999}]}'])
def test_corregir_con_nan_o_infinito_no_corrompe_ni_da_500(entorno_limpio, crudo):
    gid = _retenida(entorno_limpio)
    c = _con_pase()
    c.raise_server_exceptions = False
    r = c.post(f"{API}/grillas/{gid}/corregir", content=crudo, headers={"content-type": "application/json"})
    assert r.status_code in (400, 422), (crudo, r.status_code, r.text[:200])
    assert c.get(f"{API}/grillas/{gid}").status_code == 200


def test_corregir_un_nodo_no_hoja_no_deja_la_retenida_inservible(entorno_limpio):
    gid = _retenida(entorno_limpio)
    c = _con_pase()
    c.raise_server_exceptions = False
    r = c.post(f"{API}/grillas/{gid}/corregir", json={"cambios": [{"ruta": "ramas.administrativa", "valor": 5}]})
    assert r.status_code in (400, 422), r.status_code
    assert c.get(f"{API}/grillas/{gid}").status_code == 200
    assert c.get(API + "/grillas").status_code == 200


def test_corregir_el_nombre_de_una_categoria_con_un_numero_no_se_acepta(entorno_limpio):
    gid = _retenida(entorno_limpio)
    c = _con_pase()
    c.raise_server_exceptions = False
    r = c.post(f"{API}/grillas/{gid}/corregir", json={"cambios": [{"ruta": "ramas.administrativa.categorias.0.nombre", "valor": 5}]})
    assert r.status_code in (400, 422), r.status_code


@pytest.mark.parametrize("gid", ["99999999999", "-1", "0", "abc"])
def test_ids_raros_dan_404_o_422_nunca_500(entorno_limpio, gid):
    c = _con_pase()
    c.raise_server_exceptions = False
    for m, ruta in (("get", f"{API}/grillas/{gid}"), ("post", f"{API}/grillas/{gid}/corregir"),
                    ("post", f"{API}/grillas/{gid}/publicar"), ("post", f"{API}/grillas/{gid}/descartar"),
                    ("get", f"{API}/ensayos/{gid}")):
        r = getattr(c, m)(ruta, json={"cambios": [{"ruta": "a", "valor": 1}]}) if m == "post" else c.get(ruta)
        assert r.status_code in (404, 422), (ruta, r.status_code)


@pytest.mark.parametrize("cuerpo", ["[]", '"x"', "5"])
def test_cuerpos_que_no_son_objeto_no_dan_500(entorno_limpio, cuerpo):
    gid = _retenida(entorno_limpio)
    c = _con_pase()
    c.raise_server_exceptions = False
    for ruta in (f"/grillas/{gid}/corregir", f"/grillas/{gid}/publicar", f"/grillas/{gid}/descartar", "/buscar", "/ensayo"):
        r = c.post(API + ruta, content=cuerpo, headers={"content-type": "application/json"})
        assert r.status_code in (400, 422), (ruta, cuerpo, r.status_code)


def test_publicar_a_mano_una_retenida_con_nota_pero_forma_valida_deja_registro(entorno_limpio):
    gid = _retenida(entorno_limpio)
    with pytest.raises(ValueError):
        proc.publicar_a_mano(gid, "x", "   ")
    proc.publicar_a_mano(gid, "snavello", "revisada contra el PDF")
    g = db.grilla_completa(gid)
    assert g["estado"] == "publicada" and g["resuelta_por"] == "snavello" and g["resuelta_en"]
    assert "sin pasar" in g["nota"]


# ------------------------------------------------------------- la IA devuelve cosas raras
def _lect_rota(contenido, **kw):
    return [{"contenido": contenido, "notas": [], "periodo_impreso": "2026-09", "usos": []},
            {"contenido": copy.deepcopy(contenido), "notas": [], "periodo_impreso": "2026-09", "usos": []}]


@pytest.mark.parametrize("nombre, contenido", [
    ("vacío", {}),
    ("sin roe", {k: v for k, v in SEPT_DATOS.items() if k != "roe"}),
    ("ramas None", {**SEPT_DATOS, "ramas": None}),
    ("ramas lista", {**SEPT_DATOS, "ramas": []}),
    ("categorias None", {**SEPT_DATOS, "ramas": {"administrativa": {"nombre": "x", "categorias": None}}}),
    ("adicionales None", {**SEPT_DATOS, "adicionales": None}),
    ("roe filas str", {**SEPT_DATOS, "roe": {"tramos": ["a"], "filas": ["x"]}}),
    ("conectividad str", {**SEPT_DATOS, "conectividad": ["x"]}),
    ("dia None", {**SEPT_DATOS, "dia_bancario": None}),
    ("strings", {**SEPT_DATOS, "adicionales": {"guarderia": "416341.95"}}),
])
def test_estructura_incompleta_de_la_ia_retiene_o_falla_sin_publicar(entorno_limpio, nombre, contenido):
    e = entorno_limpio
    e.monkeypatch.setattr(lectura, "leer", lambda pdf, pl, m, veces=2: _lect_rota(contenido))
    r = proc.pasada()
    assert ("2026-09", "publicada") not in estados(), nombre
    assert r["ok"], r
    assert db.periodo_vigente() == "2026-08"


def test_una_sola_lectura_no_publica(entorno_limpio):
    e = entorno_limpio
    e.monkeypatch.setattr(lectura, "leer", lambda pdf, pl, m, veces=2: lecturas_de(SEPT_DATOS)[:1])
    proc.pasada()
    assert ("2026-09", "publicada") not in estados()


def test_la_ia_que_levanta_cualquier_cosa_no_deja_la_nota_en_leyendo(entorno_limpio):
    e = entorno_limpio

    def boom(*a, **k):
        raise RuntimeError("explotó")
    e.monkeypatch.setattr(lectura, "leer", boom)
    r = proc.pasada()
    n = next(x for x in db.listar_novedades(tipo="grillas") if x["periodo"] == "2026-09")
    assert n["resultado"] == "error" and r["leidas"][0]["estado"] == "error"
    assert estados() == {("2026-08", "publicada")}


def test_fallas_repetidas_no_avisan_en_cada_pasada(entorno_limpio):
    e = entorno_limpio
    e.monkeypatch.setattr(lectura, "leer", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    for _ in range(3):
        proc.pasada(datetime(2026, 11, 16, 10, 0))
    assert sum("no se pudo cargar" in a for a in e.avisos) == 1


# ------------------------------------------------------------- pasada muerta / no repetir
def test_una_pasada_muerta_a_mitad_no_bloquea_para_siempre(entorno_limpio):
    e = entorno_limpio
    proc.pasada()                         # publica Sept: crea la novedad
    with Session(db.engine) as s:
        s.exec(text("DELETE FROM grillasalarial WHERE periodo = '2026-09'"))
        s.commit()
    n = next(x for x in db.listar_novedades(tipo="grillas") if x["periodo"] == "2026-09")
    hace5 = (fechas.ahora() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    hace30 = (fechas.ahora() - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
    with Session(db.engine) as s:
        s.exec(text("UPDATE escalanovedad SET resultado='leyendo', ultimo_error=:u, intentos=1 WHERE id=:i").bindparams(u=hace5, i=n["id"]))
        s.commit()
    antes = len(e.llamadas)
    proc.pasada()
    assert len(e.llamadas) == antes, "con una lectura de hace 5 minutos en curso no debe leer"
    with Session(db.engine) as s:
        s.exec(text("UPDATE escalanovedad SET ultimo_error=:u WHERE id=:i").bindparams(u=hace30, i=n["id"]))
        s.commit()
    proc.pasada()
    assert len(e.llamadas) == antes + 1, "a los 30 minutos la lectura muerta debe poder reintentarse"


def test_buscar_ahora_con_periodo_no_pisa_una_publicada_vigente(entorno_limpio):
    e = entorno_limpio
    proc.pasada()
    antes = db.grilla_publicada("2026-09")
    r = proc.pasada(forzar_periodo="2026-09")
    assert db.grilla_publicada("2026-09") == antes
    assert db.periodo_vigente() == "2026-09"


def test_dos_buscar_ahora_forzados_simultaneos_una_sola_lectura(entorno_limpio):
    e = entorno_limpio

    def lenta(pdf, pl, m, veces=2):
        e.llamadas.append(1)
        time.sleep(0.5)
        return lecturas_de(SEPT_DATOS)
    e.monkeypatch.setattr(lectura, "leer", lenta)
    hilos = [threading.Thread(target=proc.pasada, kwargs={"forzar_periodo": "2026-09"}) for _ in range(3)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert len(e.llamadas) == 1
    assert sum("publicada" in a and "RETENIDA" not in a for a in e.avisos) == 1


def test_una_pasada_lenta_que_llega_tarde_no_relee_una_nota_ya_publicada(entorno_limpio):
    """B calculó `existentes` antes de que A publicara; cuando B llega a reclamar_lectura la nota
    ya está publicada (resultado 'publicada', intentos 1): no debe darle otro intento."""
    e = entorno_limpio
    proc.pasada()
    n = next(x for x in db.listar_novedades(tipo="grillas") if x["periodo"] == "2026-09")
    assert db.reclamar_lectura(n["post_id"]) == 0, "reclamar_lectura dejó leer otra vez una nota ya publicada"


# ------------------------------------------------------------- hilo
def test_el_bucle_sobrevive_a_la_base_caida_y_a_la_tabla_faltante(monkeypatch):
    llamadas = []

    def mal():
        llamadas.append(1)
        raise RuntimeError("relation avisoenviado does not exist")
    monkeypatch.setattr(proc, "intentar", mal)
    t = threading.Thread(target=proc._bucle, args=(0.01,), daemon=True)
    t.start()
    time.sleep(0.3)
    assert t.is_alive() and len(llamadas) > 3


def test_horas_invalidas_no_rompen(monkeypatch):
    for v in ("", "25:00", "ab:cd", "10:60", "10,16", ",,,", "9:00", "10:00;16:00"):
        monkeypatch.setenv("ESCALAS_HORAS", v)
        h = proc.horas()
        assert h and all(len(x) == 5 for x in h)
        proc.pasada_que_toca(datetime(2026, 11, 16, 11, 0), h)


# ------------------------------------------------------------- fuente
def test_html_o_basura_en_vez_de_json_es_un_error_controlado(monkeypatch):
    for cuerpo in (b"<html>cloudflare</html>", b"", b"{", b"\xff\xfe", b"null", b"5"):
        monkeypatch.setattr(fuente, "_pedir", lambda url, tope, timeout=20, c=cuerpo: c)
        r = _LISTAR_REAL()
        assert r["ok"] is False and r["motivo"], cuerpo


def test_timeout_es_un_error_controlado(monkeypatch):
    def tarda(url, tope, timeout=20):
        raise fuente.ErrorFuente("TimeoutError: timed out")
    monkeypatch.setattr(fuente, "_pedir", tarda)
    assert _LISTAR_REAL()["ok"] is False


@pytest.mark.parametrize("url", ["http://labancaria.org/a.pdf", "https://labancaria.org.evil.com/a.pdf",
                                 "https://evil.com/labancaria.org/a.pdf", "https://labancaria.org@evil.com/a.pdf",
                                 "https://labancaria.org/a.php", "https://user@labancaria.org/a.pdf?x=.pdf#",
                                 "file:///etc/passwd", "https://LABANCARIA.ORG./a.pdf", "https://sub.labancaria.org/a.pdf", ""])
def test_descargar_pdf_solo_del_dominio(monkeypatch, url):
    monkeypatch.setattr(fuente, "_pedir", lambda u, t, timeout=20: b"%PDF-1.4 x")
    try:
        _DESCARGAR_REAL(url)
        ok = True
    except fuente.ErrorFuente:
        ok = False
    # solo el exacto de labancaria.org en https y .pdf puede pasar
    if url.startswith("https://user@labancaria.org/a.pdf"):
        return
    assert not ok, url


def test_pedir_no_sigue_redirecciones_a_otro_dominio():
    """Una redirección a otro host o esquema se rechaza: la validación de dominio de descargar_pdf no la cubre."""
    import http.server
    import socketserver

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/a.pdf":
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{self.server.server_address[1]}/otro")
                self.end_headers()
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"%PDF-otro-host")

        def log_message(self, *a):
            pass
    srv = socketserver.TCPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    p = srv.server_address[1]
    try:
        # misma máquina pero distinto path; demuestra que _pedir no ata el destino final
        with pytest.raises(fuente.ErrorFuente):
            fuente._pedir(f"http://127.0.0.1:{p}/a.pdf", 1000)
    finally:
        srv.shutdown()


# ------------------------------------------------------------- pantalla
def test_la_pantalla_dibuja_con_textcontent_y_sin_html_inyectable():
    js = open("static/escalas_estado.js", encoding="utf-8").read()
    for malo in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "setAttribute('on", "href = "):
        assert malo not in js, malo


def test_una_retenida_ya_danada_no_tumba_la_vista_ni_se_publica(entorno_limpio):
    """Una retenida con un nodo que dejó de ser objeto (dañada antes de que la corrección lo
    rechazara): el detalle y la lista siguen andando y publicarla da 422, no 500."""
    gid = _retenida(entorno_limpio)
    g = db.grilla_completa(gid)
    roto = copy.deepcopy(g["contenido"])
    roto["ramas"]["administrativa"] = 5
    roto["conectividad"] = [7]
    roto["adicionales"] = None
    with Session(db.engine) as s:
        s.exec(text("UPDATE grillasalarial SET contenido = CAST(:c AS jsonb) WHERE id = :i").bindparams(c=json.dumps(roto), i=gid))
        s.commit()
    c = _con_pase()
    c.raise_server_exceptions = False
    assert c.get(f"{API}/grillas/{gid}").status_code == 200
    assert c.get(API + "/grillas").status_code == 200
    r = c.post(f"{API}/grillas/{gid}/publicar", json={"nota": "x"})
    assert r.status_code == 422 and ("2026-09", "publicada") not in estados()


def test_corregir_rechaza_rutas_que_no_son_hojas_numericas_y_no_toca_la_grilla(entorno_limpio):
    gid = _retenida(entorno_limpio)
    antes = db.grilla_completa(gid)["contenido"]
    c = _con_pase()
    c.raise_server_exceptions = False
    for ruta in ("ramas.administrativa", "ramas.administrativa.categorias", "conectividad.0.meses", "roe.tramos.0",
                 "ramas.administrativa.categorias.0.nombre", "ramas.nueva.categorias.0.basico", "nombre", ""):
        r = c.post(f"{API}/grillas/{gid}/corregir", json={"cambios": [{"ruta": ruta, "valor": 5}]})
        assert r.status_code in (400, 422), (ruta, r.status_code)
    for valor in (0, -3, 1e10, 3e12):
        r = c.post(f"{API}/grillas/{gid}/corregir", json={"cambios": [{"ruta": "adicionales.guarderia", "valor": valor}]})
        assert r.status_code == 422, valor
    assert db.grilla_completa(gid)["contenido"] == antes


class _Msg:
    def __init__(self, entrada, stop="tool_use"):
        self.stop_reason = stop
        self.usage = type("U", (), {"input_tokens": 25000, "output_tokens": 1800, "cache_read_input_tokens": 0,
                                     "cache_creation_input_tokens": 0})()
        self.content = [type("B", (), {"type": "tool_use", "input": entrada})()]


class _Cli:
    def __init__(self, respuestas):
        self.respuestas, self.n = respuestas, 0
        self.messages = self

    def create(self, **kw):
        r = self.respuestas[min(self.n, len(self.respuestas) - 1)]
        self.n += 1
        return r


def test_respuesta_de_la_ia_con_tipos_raros_registra_igual_lo_gastado(entorno_limpio):
    """La API contestó (y se pagó) pero la estructura es rara: el gasto tiene que quedar en UsoIA."""
    e = entorno_limpio
    e.monkeypatch.undo()                                   # usa la lectura real con un cliente falso
    import telegram
    e.monkeypatch.setattr(telegram, "enviar_en_segundo_plano", lambda t: e.avisos.append(t))
    e.monkeypatch.setattr(fuente, "listar_novedades", lambda *a, **k: novedades())
    e.monkeypatch.setattr(fuente, "descargar_pdf", lambda u: b"%PDF-1.7 x")
    e.monkeypatch.setattr(lectura, "paginas_a_imagenes", lambda pdf: [("AAAA", "image/png")])
    buena_rama = {"categorias": [], "notas": []}
    cli = _Cli([_Msg(buena_rama), _Msg(buena_rama), _Msg(buena_rama), _Msg({"conectividad": ["x"]})])   # una lista de adicionales ya es una forma válida
    lectura.usar_cliente(cli)
    try:
        with Session(db.engine) as s:
            antes = len(s.exec(text("SELECT id FROM usoia WHERE tipo='herramienta' AND tokens_entrada=25000")).all())
        r = proc.pasada()
        with Session(db.engine) as s:
            despues = len(s.exec(text("SELECT id FROM usoia WHERE tipo='herramienta' AND tokens_entrada=25000")).all())
    finally:
        lectura.usar_cliente(None)
    assert r["leidas"][0]["estado"] == "error"
    assert despues - antes == 4, f"se pagaron 4 llamadas y se registraron {despues - antes}"


# ------------------------------------------------------------- D28 (una celda tapada se completa por cálculo)
def test_d28_un_null_en_una_celda_escalable_sola_ahora_se_completa_pero_nada_mas_se_afloja():
    """Antes de D28 cualquier null retenía. Ahora una celda que escala se completa, y siguen reteniendo:
    tres nulls, un null que no escala, dos lecturas con valores distintos y un valor malo."""
    from test_escalas_controles import F_OCT, OCT, PREV_OCT, RUTA_CAPATAZ, oct_cc, sin_leer
    assert ctl.todos_pasan(oct_cc(sin_leer(RUTA_CAPATAZ))["resultados"])
    otras = ("ramas.administrativa.categorias.10.basico", "ramas.ordenanza.categorias.20.basico")
    assert not ctl.todos_pasan(oct_cc(sin_leer(RUTA_CAPATAZ, *otras))["resultados"])
    assert not ctl.todos_pasan(oct_cc(sin_leer("roe.filas.0.hasta"))["resultados"])
    assert not ctl.todos_pasan(oct_cc(sin_leer(RUTA_CAPATAZ), b=ctl.asignar(OCT, RUTA_CAPATAZ, 1.0))["resultados"])
    assert not ctl.todos_pasan(oct_cc(ctl.asignar(OCT, RUTA_CAPATAZ, 1.0))["resultados"])
    assert F_OCT > 1 and PREV_OCT


def test_d28_la_vista_marca_las_celdas_calculadas_sin_innerhtml():
    js = open("static/escalas_estado.js", encoding="utf-8").read()
    assert "calculada" in js and "celdas_calculadas" in js and "Comentarios de la lectura" in js and "innerHTML" not in js
