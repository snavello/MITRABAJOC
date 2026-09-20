"""Métricas de Render en Grafana: colector, remote write, tablero y alertas
(observabilidad/colector_render.py, remote_write.py, aplicar_tablero.py,
aplicar_alertas_metricas.py, reglas.py y .github/workflows/metricas-render.yml).
Plan en docs/chat/2026-09-19-plan-observabilidad.md.

Sin red. Lo delicado:
- el formato de remote write se prueba DECODIFICANDO lo escrito con un lector mínimo
  de protobuf y de snappy escrito acá, distinto del codificador: si el formato
  estuviera mal, Grafana lo rechazaría en silencio;
- un valor nulo de Render no se manda como 0 (un cero inventado se confunde con
  "el CPU está en cero");
- las alertas de métricas no gritan cuando falta el colector (para eso hay una
  propia), y la del colector sí grita por la falta de datos;
- el workflow no expone secretos, no corre en pull requests y no corre en forks.

Correr con: .venv/Scripts/python.exe -m pytest test_observabilidad_metricas.py -q
"""
import copy
import json
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).parent
sys.path.insert(0, str(RAIZ / "observabilidad"))
import aplicar_alertas_metricas as am
import aplicar_grafana as ag
import aplicar_tablero as at
import colector_render as cr
import reglas
import remote_write as rw

CFG = ag.cargar_config()


# ------------------------- lectores mínimos (independientes del codificador) -------------------------
def _leer_varint(b, i):
    n, desplaz = 0, 0
    while True:
        byte = b[i]
        i += 1
        n |= (byte & 0x7F) << desplaz
        if not byte & 0x80:
            return n, i
        desplaz += 7


def _campos(b):
    """Recorre un mensaje protobuf: devuelve [(numero, tipo_de_cable, valor)]."""
    i, out = 0, []
    while i < len(b):
        clave, i = _leer_varint(b, i)
        num, tipo = clave >> 3, clave & 7
        if tipo == 2:
            n, i = _leer_varint(b, i)
            out.append((num, tipo, b[i:i + n]))
            i += n
        elif tipo == 1:
            out.append((num, tipo, b[i:i + 8]))
            i += 8
        elif tipo == 0:
            v, i = _leer_varint(b, i)
            out.append((num, tipo, v))
        else:
            raise AssertionError(f"tipo de cable inesperado {tipo}")
    return out


def _desde_snappy(b):
    """Descomprime un bloque snappy (literales y copias) — el formato completo, no
    solo lo que produce nuestro codificador."""
    total, i = _leer_varint(b, 0)
    out = bytearray()
    while i < len(b):
        tag = b[i]
        i += 1
        if tag & 3 == 0:                                    # literal
            n = tag >> 2
            if n >= 60:
                nbytes = n - 59
                n = int.from_bytes(b[i:i + nbytes], "little")
                i += nbytes
            n += 1
            out += b[i:i + n]
            i += n
        else:
            raise AssertionError("el codificador no debería producir copias")
    assert len(out) == total, (len(out), total)
    return bytes(out)


def _decodificar_write_request(cuerpo_snappy):
    series = []
    for num, _, ts in _campos(_desde_snappy(cuerpo_snappy)):
        assert num == 1
        etiquetas, muestras = {}, []
        for n2, _, v in _campos(ts):
            if n2 == 1:
                par = {n3: x for n3, _, x in _campos(v)}
                etiquetas[par[1].decode()] = par[2].decode()
            elif n2 == 2:
                m = {n3: x for n3, _, x in _campos(v)}
                muestras.append((m[2], struct.unpack("<d", m[1])[0]))
        series.append((etiquetas, muestras))
    return series


# ------------------------- remote write -------------------------
def test_lo_que_se_escribe_se_decodifica_igual():
    series = [({"__name__": "render_cpu_cores", "entorno": "pruebas", "servicio": "web"},
               [(1789863820000, 0.0044), (1789863880000, 0.5)]),
              ({"__name__": "render_instance_count", "entorno": "pruebas"}, [(1789863820000, 1.0)])]
    crudo = rw.snappy_sin_compresion(rw.codificar_write_request(series))
    assert _decodificar_write_request(crudo) == [(e, sorted(m)) for e, m in series]


def test_las_etiquetas_van_ordenadas_y_las_muestras_por_tiempo():
    """Prometheus rechaza una serie con etiquetas desordenadas o muestras fuera de orden."""
    serie = rw.codificar_serie({"zeta": "1", "__name__": "m", "alfa": "2"}, [(20, 2.0), (10, 1.0)])
    nombres, tiempos = [], []
    for num, _, v in _campos(serie):
        if num == 1:
            nombres.append(_campos(v)[0][2].decode())
        else:
            tiempos.append({n: x for n, _, x in _campos(v)}[2])
    assert nombres == ["__name__", "alfa", "zeta"] and tiempos == [10, 20]


def test_snappy_aguanta_cuerpos_mas_grandes_que_un_bloque():
    grande = bytes(range(256)) * 700                        # 179.200 bytes: 3 bloques de literales
    assert _desde_snappy(rw.snappy_sin_compresion(grande)) == grande
    assert _desde_snappy(rw.snappy_sin_compresion(b"")) == b""
    assert _desde_snappy(rw.snappy_sin_compresion(b"x" * 60)) == b"x" * 60
    assert _desde_snappy(rw.snappy_sin_compresion(b"x" * 61)) == b"x" * 61


def test_caracteres_no_ascii_en_etiquetas_sobreviven():
    crudo = rw.snappy_sin_compresion(rw.codificar_write_request(
        [({"__name__": "m", "nota": "Córdoba · ñandú"}, [(1, 1.0)])]))
    assert _decodificar_write_request(crudo)[0][0]["nota"] == "Córdoba · ñandú"


# ------------------------- conversión de lo que devuelve Render -------------------------
BASE = {"entorno": "pruebas", "servicio": "web", "recurso": "srv-x"}


def _serie_render(etiquetas, valores):
    return {"labels": [{"field": k, "value": v} for k, v in etiquetas.items()],
            "values": [{"timestamp": t, "value": v} for t, v in valores], "unit": "cpu"}


def test_convertir_renombra_etiquetas_y_descarta_las_redundantes():
    render = [_serie_render({"instance": "srv-x-9x8pg", "service": "srv-x", "resource": "srv-x"},
                            [("2026-09-20T00:03:35Z", 0.0042)])]
    (etiquetas, muestras), = cr.convertir("render_cpu_cores", render, BASE)
    assert etiquetas == {"__name__": "render_cpu_cores", "entorno": "pruebas", "servicio": "web",
                         "recurso": "srv-x", "instance": "srv-x-9x8pg"}      # sin `service` ni `resource`
    assert muestras == [(cr.a_milisegundos("2026-09-20T00:03:35Z"), 0.0042)]


def test_los_pedidos_http_traen_codigo_de_estado_y_host():
    render = [_serie_render({"host": "mitrabajo-pruebas.onrender.com", "resource": "srv-x", "statusCode": "503"},
                            [("2026-09-20T00:03:35Z", 4)])]
    (etiquetas, _), = cr.convertir("render_http_requests", render, BASE)
    assert etiquetas["status_code"] == "503" and etiquetas["host"] == "mitrabajo-pruebas.onrender.com"


def test_un_valor_nulo_no_se_manda_como_cero():
    render = [_serie_render({"resource": "srv-x"},
                            [("2026-09-20T00:00:00Z", None), ("2026-09-20T00:01:00Z", 0.5)])]
    (_, muestras), = cr.convertir("render_cpu_cores", render, BASE)
    assert [v for _, v in muestras] == [0.5]
    assert cr.convertir("render_cpu_cores", [_serie_render({}, [("2026-09-20T00:00:00Z", None)])], BASE) == []
    assert cr.convertir("render_cpu_cores", [], BASE) == [] and cr.convertir("render_cpu_cores", None, BASE) == []


def test_las_series_de_salud_del_colector_dicen_cuando_corrio_y_con_cuantos_errores():
    ahora = datetime(2026, 9, 20, 0, 0, 0, tzinfo=timezone.utc)
    (e1, m1), (e2, m2) = cr.series_de_salud(CFG, ahora, {"errores": ["a", "b"]})
    assert e1["__name__"] == "render_colector_ultima_corrida_segundos" and m1[0][1] == ahora.timestamp()
    assert e2["__name__"] == "render_colector_errores" and m2[0][1] == 2.0


def test_una_metrica_que_falla_no_tira_las_demas(monkeypatch):
    llamadas = []

    def falso(clave, metrica, recurso, ini, fin, res, extra):
        llamadas.append(metrica)
        if metrica == "memory":
            raise cr.ErrorRender("memory de x: HTTP 500")
        return [_serie_render({"resource": recurso}, [("2026-09-20T00:00:00Z", 1.0)])]

    monkeypatch.setattr(cr, "pedir_render", falso)
    series, resumen = cr.recolectar(CFG, "clave", pausa=0)
    assert len(resumen["errores"]) == 2                      # memory en web y en db
    assert series and all(s[0]["__name__"] != "render_memory_bytes" for s in series)
    assert "cpu" in llamadas and "active-connections" in llamadas


# ------------------------- configuración -------------------------
def test_la_configuracion_del_repo_es_valida():
    assert ag.validar(CFG) == []
    assert cr.validar_config(CFG) == []
    assert am.validar_alertas(CFG) == []
    assert at.validar_tablero(CFG) == []


def test_valores_invalidos_del_colector_se_rechazan():
    def con(**cambios):
        c = copy.deepcopy(CFG)
        c["metricas_render"].update(cambios)
        return cr.validar_config(c)
    assert con(ventana_min=1) and con(ventana_min=500) and con(resolucion_s=5)
    assert con(recursos={"web": "x", "db": "dpg-1"})
    assert con(remote_write={"url": "http://inseguro", "usuario": "1"})


def test_cubre_todo_lo_que_render_expone_util_del_web_y_de_la_base():
    web = {m for m, _, _ in cr.WEB}
    db = {m for m, _, _ in cr.DB}
    assert {"cpu", "cpu-limit", "memory", "memory-limit", "http-requests", "http-latency", "instance-count"} <= web
    assert {"cpu", "cpu-limit", "memory", "memory-limit", "active-connections", "disk-usage",
            "disk-capacity", "instance-count"} <= db
    nombres = [n for _, n, _ in cr.WEB + cr.DB]
    assert all(n.startswith("render_") for n in nombres)


# ------------------------- alertas -------------------------
def _alerta(id_):
    return next(a for a in CFG["metricas_render"]["alertas"] if a["id"] == id_)


def test_los_eventos_3_y_4_estan_con_los_umbrales_acordados():
    e5xx, cpu, mem = _alerta("5xx"), _alerta("cpu"), _alerta("memoria")
    assert (e5xx["operador"], e5xx["umbral"]) == ("gt", 5) and "[10m]" in e5xx["expr"]
    assert (cpu["operador"], cpu["umbral"], cpu["para_min"]) == ("gt", 95, 30)       # 95 % por más de 30 min
    assert (mem["operador"], mem["umbral"], mem["para_min"]) == ("gt", 95, 30)


def test_el_5xx_exige_un_minimo_de_pedidos_para_no_gritar_por_uno_de_diez():
    expr = _alerta("5xx")["expr"]
    assert ">= 20" in expr and "or vector(0)" in expr       # sin errores: 0 %, no "sin datos"


def test_las_alertas_de_metricas_no_gritan_por_falta_de_datos_pero_la_del_colector_si():
    for id_ in ("5xx", "cpu", "memoria"):
        assert am.payload_regla(CFG, _alerta(id_))["noDataState"] == "OK"
    colector = am.payload_regla(CFG, _alerta("colector"))
    assert colector["noDataState"] == "Alerting"
    assert "[3h]" in colector["data"][0]["model"]["expr"]   # tolera hasta 3 h de silencio antes de "sin datos"
    assert colector["data"][2]["model"]["conditions"][0]["evaluator"] == {"params": [30], "type": "gt"}


def test_toda_regla_de_metricas_filtra_por_entorno_y_vive_en_la_carpeta_de_pruebas():
    for a in CFG["metricas_render"]["alertas"]:
        r = am.payload_regla(CFG, a)
        assert 'entorno="pruebas"' in r["data"][0]["model"]["expr"] and am.MARCA_ENTORNO not in r["data"][0]["model"]["expr"]
        assert r["folderUID"] == "colm3na-pruebas" and r["labels"]["entorno"] == "pruebas"
        assert r["uid"] == f"colm3na-pruebas-{a['evento']}"
        assert r["condition"] == "C" and r["ruleGroup"] == "metricas"


def test_una_alerta_sin_filtro_de_entorno_se_rechaza():
    c = copy.deepcopy(CFG)
    c["metricas_render"]["alertas"][0]["expr"] = "sum(render_http_requests)"
    assert any("entorno" in e for e in am.validar_alertas(c))
    c = copy.deepcopy(CFG)
    c["metricas_render"]["alertas"][1]["evento"] = c["metricas_render"]["alertas"][0]["evento"]
    assert any("repetido" in e for e in am.validar_alertas(c))


def test_la_pieza_compartida_rechaza_valores_invalidos():
    base = dict(uid="u", titulo="t", grupo="g", carpeta_uid="c", expr="e", umbral=1, para_minutos=1,
                labels={}, resumen="r", descripcion="d")
    for malo in ({"operador": "eq", "sin_datos": "OK"}, {"operador": "gt", "sin_datos": "quizas"}):
        try:
            reglas.regla_umbral(**base, **malo)
            assert False, "tendría que haber rechazado " + str(malo)
        except ValueError:
            pass


def test_las_alertas_del_uptime_siguen_dando_lo_mismo_tras_compartir_la_pieza():
    import aplicar_uptime as up
    r = up.payload_regla(CFG, CFG["uptime"]["checks"][0])
    assert r["noDataState"] == "NoData" and r["for"] == "3m" and r["ruleGroup"] == "uptime"
    assert r["data"][0]["model"]["expr"] == 'max by (job) (probe_success{job="colm3na-pruebas-healthz"})'


# ------------------------- tablero -------------------------
def test_el_tablero_es_coherente():
    t = at.construir_tablero(CFG)
    ids = [p["id"] for p in t["panels"]]
    assert len(ids) == len(set(ids)) == 20
    for p in t["panels"]:
        assert 0 <= p["gridPos"]["x"] and p["gridPos"]["x"] + p["gridPos"]["w"] <= 24, p["title"]
        if p["type"] != "text":
            assert p["targets"] and all(x["datasource"]["uid"] == "grafanacloud-prom" for x in p["targets"]), p["title"]
    assert t["uid"] == "colm3na-pruebas-estado" and t["refresh"] == "1m"


def test_toda_consulta_del_tablero_filtra_por_entorno_o_por_los_checks_de_pruebas():
    for p in at.construir_tablero(CFG)["panels"]:
        for x in p.get("targets", []):
            assert 'entorno="pruebas"' in x["expr"] or "colm3na-pruebas" in x["expr"], (p["title"], x["expr"])


def test_el_tablero_muestra_cero_errores_y_no_sin_datos_cuando_todo_esta_sano():
    p = next(p for p in at.construir_tablero(CFG)["panels"] if "5xx" in p["title"])
    assert "or vector(0)" in p["targets"][0]["expr"]
    assert p["fieldConfig"]["defaults"]["thresholds"]["steps"][-1]["value"] == 5      # línea roja en el 5 %


def test_el_tablero_marca_el_umbral_de_alerta_de_cpu_y_memoria():
    for titulo in ("CPU (% del límite del plan)", "Memoria (% del límite del plan)"):
        p = next(p for p in at.construir_tablero(CFG)["panels"] if p["title"] == titulo)
        assert p["fieldConfig"]["defaults"]["thresholds"]["steps"][-1]["value"] == 95


def test_el_tablero_avisa_si_el_colector_dejo_de_correr():
    p = next(p for p in at.construir_tablero(CFG)["panels"] if p["title"].startswith("Colector"))
    assert "last_over_time" in p["targets"][0]["expr"]            # sigue mostrando minutos, no "sin datos"
    assert p["fieldConfig"]["defaults"]["unit"] == "m"


# ------------------------- el workflow de GitHub Actions -------------------------
FLUJO = (RAIZ / ".github" / "workflows" / "metricas-render.yml").read_text(encoding="utf-8")


def test_el_workflow_corre_cada_5_minutos_y_a_mano():
    assert 'cron: "*/5 * * * *"' in FLUJO and "workflow_dispatch:" in FLUJO


def test_el_workflow_no_corre_en_pull_requests_ni_en_forks_ni_expone_secretos():
    assert "pull_request" not in FLUJO                          # un PR no puede dispararlo ni leer secretos
    assert "github.repository == 'snavello/MITRABAJOC'" in FLUJO
    assert "${{ secrets.RENDER_API_KEY }}" in FLUJO and "${{ secrets.GRAFANA_METRICS_TOKEN }}" in FLUJO
    assert "rnd_" not in FLUJO and "glc_" not in FLUJO
    assert "permissions:\n  contents: read" in FLUJO.replace("\r\n", "\n")   # permisos mínimos


def test_el_workflow_no_se_pisa_a_si_mismo_ni_puede_colgarse():
    assert "concurrency:" in FLUJO and "cancel-in-progress: false" in FLUJO
    assert "timeout-minutes:" in FLUJO


def test_el_colector_y_el_config_no_llevan_ningun_token():
    for archivo in ("colector_render.py", "remote_write.py", "aplicar_tablero.py",
                    "aplicar_alertas_metricas.py", "reglas.py", "config.json"):
        t = (RAIZ / "observabilidad" / archivo).read_text(encoding="utf-8")
        assert "glc_eyJ" not in t and "rnd_oqu" not in t and "glsa_vmk" not in t, archivo
