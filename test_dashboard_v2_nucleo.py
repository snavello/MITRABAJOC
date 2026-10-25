"""Panel Sindical, el núcleo sin pantalla (PLAN_DASHBOARD_V2.md, bloque 2).

`static/panel_v2/estado.js` y `api.js` no tocan el DOM, así que se prueban
corriéndolos de verdad con Node.

Mientras la v1 existió, la línea roja 3 del plan se probaba **contra la v1
misma**: se sacaban de static/dashboard.js las funciones que arman y sanean
el estado y se corrían al lado de las de la v2 con miles de direcciones al
azar. La v1 se retiró el 2026-10-25: los casos de abajo son **lo que la v1
producía** para cada dirección (sacado corriéndola por última vez, con sus
rarezas incluidas), con un solo cambio a propósito: el período por defecto y
el de "Reiniciar" pasaron de "Hoy" a los últimos 30 días (G7-02). Una
dirección guardada de la v1 sigue abriendo igual. Las direcciones al azar
quedan para lo que no depende de un caso: que la salida sea siempre un
período válido y que releerla dé lo mismo.

Además: la cola nunca pasa de 4 en vuelo, el 503 se reintenta dos veces con
la espera de siempre, el 403 manda a /admin, el 422 trae su motivo, y una
ronda abortada corta también la espera del reintento.

Sin Node instalado, los tests se saltean.

Correr con: .venv/bin/python -m pytest test_dashboard_v2_nucleo.py -q
"""
import json
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import parse_qsl

import pytest

RAIZ = Path(__file__).parent
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="Node no está instalado")


def _correr(js: str, tmp_path: Path, modulos=("estado", "api")) -> dict:
    """Copia los módulos del panel como .mjs (así cualquier Node los toma como
    módulos ES) y corre `js`, que tiene que imprimir un JSON."""
    for m in modulos:
        (tmp_path / f"{m}.mjs").write_text(
            (RAIZ / "static" / "panel_v2" / f"{m}.js").read_text(encoding="utf-8"),
            encoding="utf-8")
    programa = tmp_path / "prueba.mjs"
    programa.write_text(js, encoding="utf-8")
    r = subprocess.run([NODE, str(programa)], capture_output=True, text=True, timeout=120,
                       env={"TZ": "America/Argentina/Buenos_Aires", "PATH": "/usr/bin:/bin"})
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# Generador de direcciones al azar, sembrado: valores válidos mezclados con
# todo lo que una dirección editada a mano puede traer.
_AZAR = r"""
let semilla = 20261012;
function azar() { semilla = (semilla * 1103515245 + 12345) % 2147483648; return semilla / 2147483648; }
function uno(lista) { return lista[Math.floor(azar() * lista.length)]; }
const FECHAS = ["2026-10-12", "2026-10-01", "2026-09-15", "2026-03-01", "2025-12-31", "2026-02-30",
                "2026-10-13", "2027-01-01", "2026-1-5", "abc", "", "2026-10", "0026-01-01", " 2026-10-11"];
const IDS = ["1", "2", "3", "7", "0", "-4", "1.5", "abc", "", "3"];
const SAL = ["", "abc", "400", "0", "1200000", "1250000", "3700000", "9000000", "1250499", "-50000"];
function direccion() {
  const q = new URLSearchParams();
  if (azar() < 0.9) q.set("desde", uno(FECHAS));
  if (azar() < 0.9) q.set("hasta", uno(FECHAS));
  const ns = Math.floor(azar() * 4); for (let i = 0; i < ns; i++) q.append("seccionales", uno(IDS));
  const ne = Math.floor(azar() * 3); for (let i = 0; i < ne; i++) q.append("empresas", uno(IDS));
  if (azar() < 0.4) q.set("formato", uno(["viejo", "nuevo", "otro", ""]));
  if (azar() < 0.5) q.set("sal_min", uno(SAL));
  if (azar() < 0.5) q.set("sal_max", uno(SAL));
  if (azar() < 0.4) q.set("resultado", uno(["ok", "con_diferencias", "x"]));
  if (azar() < 0.4) q.set("estado_tramite", uno(["abierto", "en_proceso", "resuelto", "cerrado"]));
  if (azar() < 0.3) q.set("tipo_notif", uno(["manual", "sistema", "push"]));
  if (azar() < 0.3) q.set("tema", uno(["licencias", "", "vacaciones pagas"]));
  if (azar() < 0.3) q.set("afiliado", uno(IDS));
  if (azar() < 0.4) q.set("tab", uno(["recibos", "tramites", "notificaciones", "consultas", "nada"]));
  return q.toString();
}
const LIMITES = [{ min: null, max: null }, { min: 1150, max: 3700 }, { min: 0, max: 50 }];
"""

# Lo que la v1 armaba para cada dirección: (dirección, límites del slider de
# salario, carril de consultas, parámetros|pestaña|período rápido). Hoy es el
# 2026-10-12; sin un período válido, el panel abre en los últimos 30 días.
CASOS_V1 = [
    ('', None, False, 'desde=2026-09-13&hasta=2026-10-12|tab=recibos|preset=30'),
    ('desde=2026-10-01&hasta=2026-10-12', None, False, 'desde=2026-10-01&hasta=2026-10-12|tab=recibos|preset=null'),
    ('desde=2026-10-12&hasta=2026-10-12', None, False, 'desde=2026-10-12&hasta=2026-10-12|tab=recibos|preset=hoy'),
    ('desde=2026-10-06&hasta=2026-10-12', None, False, 'desde=2026-10-06&hasta=2026-10-12|tab=recibos|preset=7'),
    ('desde=2026-07-15&hasta=2026-10-12', None, False, 'desde=2026-07-15&hasta=2026-10-12|tab=recibos|preset=90'),
    ('desde=2026-10-01&hasta=2026-10-13&seccionales=3', None, False, 'desde=2026-09-13&hasta=2026-10-12|tab=recibos|preset=30'),
    ('desde=2026-10-12&hasta=2026-10-01&seccionales=3', None, False, 'desde=2026-09-13&hasta=2026-10-12|tab=recibos|preset=30'),
    ('desde=2026-02-30&hasta=2026-10-12&formato=nuevo', None, False, 'desde=2026-03-02&hasta=2026-10-12&formato=nuevo|tab=recibos|preset=null'),
    ('desde=abc&hasta=2026-10-12&seccionales=3', None, False, 'desde=2026-09-13&hasta=2026-10-12|tab=recibos|preset=30'),
    ('hasta=2026-10-12&empresas=4', None, False, 'desde=2026-09-13&hasta=2026-10-12|tab=recibos|preset=30'),
    ('desde=+2026-10-11&hasta=2026-10-12', None, False, 'desde=2026-10-11&hasta=2026-10-12|tab=recibos|preset=null'),
    ('desde=2026-1-5&hasta=2026-10-12', None, False, 'desde=2026-01-05&hasta=2026-10-12|tab=recibos|preset=null'),
    ('desde=0026-01-01&hasta=2026-10-12', None, False, 'desde=1926-01-01&hasta=2026-10-12|tab=recibos|preset=null'),
    ('desde=2026-10-01&hasta=2026-10-12&seccionales=3&seccionales=0&seccionales=abc&seccionales=-4&seccionales=1.5&seccionales=3&seccionales=', None, False, 'desde=2026-10-01&hasta=2026-10-12&seccionales=3&seccionales=-4&seccionales=1.5|tab=recibos|preset=null'),
    ('desde=2026-10-01&hasta=2026-10-12&empresas=9&empresas=0&empresas=2&empresas=9', None, False, 'desde=2026-10-01&hasta=2026-10-12&empresas=9&empresas=2|tab=recibos|preset=null'),
    ('desde=2026-10-01&hasta=2026-10-12&formato=nuevo', None, False, 'desde=2026-10-01&hasta=2026-10-12&formato=nuevo|tab=recibos|preset=null'),
    ('desde=2026-10-01&hasta=2026-10-12&formato=otro', None, False, 'desde=2026-10-01&hasta=2026-10-12|tab=recibos|preset=null'),
    ('desde=2026-10-01&hasta=2026-10-12&sal_min=1250000&sal_max=3000000', {'min': 1150, 'max': 3700}, False, 'desde=2026-10-01&hasta=2026-10-12&sal_min=1250000&sal_max=3000000|tab=recibos|preset=null'),
    ('desde=2026-10-01&hasta=2026-10-12&sal_min=1250499', None, False, 'desde=2026-10-01&hasta=2026-10-12|tab=recibos|preset=null'),
    ('desde=2026-10-01&hasta=2026-10-12&sal_min=-50000&sal_max=9000000', {'min': 1150, 'max': 3700}, False, 'desde=2026-10-01&hasta=2026-10-12|tab=recibos|preset=null'),
    ('desde=2026-10-01&hasta=2026-10-12&sal_max=2000000', {'min': 1150, 'max': 3700}, False, 'desde=2026-10-01&hasta=2026-10-12|tab=recibos|preset=null'),
    ('desde=2026-10-01&hasta=2026-10-12&sal_min=abc&sal_max=2000000', {'min': 1150, 'max': 3700}, False, 'desde=2026-10-01&hasta=2026-10-12&sal_max=2000000|tab=recibos|preset=null'),
    ('desde=2026-10-01&hasta=2026-10-12&sal_min=400&sal_max=0', {'min': 0, 'max': 50}, False, 'desde=2026-10-01&hasta=2026-10-12|tab=recibos|preset=null'),
    ('desde=2026-10-01&hasta=2026-10-12&resultado=ok', None, False, 'desde=2026-10-01&hasta=2026-10-12&resultado=ok|tab=recibos|preset=null'),
    ('desde=2026-10-01&hasta=2026-10-12&resultado=x', None, False, 'desde=2026-10-01&hasta=2026-10-12|tab=recibos|preset=null'),
    ('desde=2026-10-01&hasta=2026-10-12&estado_tramite=en_proceso', None, False, 'desde=2026-10-01&hasta=2026-10-12&estado_tramite=en_proceso|tab=recibos|preset=null'),
    ('desde=2026-10-01&hasta=2026-10-12&estado_tramite=cerrado', None, False, 'desde=2026-10-01&hasta=2026-10-12|tab=recibos|preset=null'),
    ('desde=2026-10-01&hasta=2026-10-12&tipo_notif=sistema', None, False, 'desde=2026-10-01&hasta=2026-10-12&tipo_notif=sistema|tab=recibos|preset=null'),
    ('desde=2026-10-01&hasta=2026-10-12&tipo_notif=push', None, False, 'desde=2026-10-01&hasta=2026-10-12|tab=recibos|preset=null'),
    ('desde=2026-10-01&hasta=2026-10-12&tema=vacaciones+pagas', None, False, 'desde=2026-10-01&hasta=2026-10-12&tema=vacaciones+pagas|tab=recibos|preset=null'),
    ('desde=2026-10-01&hasta=2026-10-12&afiliado=12', None, False, 'desde=2026-10-01&hasta=2026-10-12&afiliado=12|tab=recibos|preset=null'),
    ('desde=2026-10-01&hasta=2026-10-12&afiliado=abc', None, False, 'desde=2026-10-01&hasta=2026-10-12|tab=recibos|preset=null'),
    ('desde=2026-10-01&hasta=2026-10-12&afiliado=-4', None, False, 'desde=2026-10-01&hasta=2026-10-12&afiliado=-4|tab=recibos|preset=null'),
    ('desde=2026-10-01&hasta=2026-10-12&tab=tramites', None, False, 'desde=2026-10-01&hasta=2026-10-12|tab=tramites|preset=null'),
    ('desde=2026-10-01&hasta=2026-10-12&tab=consultas', None, False, 'desde=2026-10-01&hasta=2026-10-12|tab=recibos|preset=null'),
    ('desde=2026-10-01&hasta=2026-10-12&tab=consultas', None, True, 'desde=2026-10-01&hasta=2026-10-12|tab=consultas|preset=null'),
    ('desde=2026-10-01&hasta=2026-10-12&tab=nada', None, True, 'desde=2026-10-01&hasta=2026-10-12|tab=recibos|preset=null'),
    ('desde=2026-09-13&hasta=2026-10-12&seccionales=2&empresas=7&formato=viejo&sal_min=1200000&sal_max=3500000&resultado=con_diferencias&estado_tramite=abierto&tipo_notif=manual&tema=licencias&afiliado=3&tab=notificaciones', {'min': 1150, 'max': 3700}, False, 'desde=2026-09-13&hasta=2026-10-12&seccionales=2&empresas=7&formato=viejo&sal_min=1200000&sal_max=3500000&resultado=con_diferencias&estado_tramite=abierto&tipo_notif=manual&tema=licencias&afiliado=3|tab=notificaciones|preset=30'),
]

# Los cambios que la v1 tenía como función propia (período rápido, seccional,
# reiniciar y aplicar filtros del Asistente), en orden, con lo que quedaba
# después de cada uno. "Aplicar" con un período inválido conserva el anterior.
SECUENCIAS_V1 = [
    ('desde=2026-10-01&hasta=2026-10-12&seccionales=3&formato=nuevo', None, [
        (['preset', '7'], 'desde=2026-10-06&hasta=2026-10-12&seccionales=3&formato=nuevo|tab=recibos|preset=7'),
        (['seccional', 2], 'desde=2026-10-06&hasta=2026-10-12&seccionales=3&seccionales=2&formato=nuevo|tab=recibos|preset=7'),
        (['seccional', 3], 'desde=2026-10-06&hasta=2026-10-12&seccionales=2&formato=nuevo|tab=recibos|preset=7'),
        (['seccional', 2], 'desde=2026-10-06&hasta=2026-10-12&formato=nuevo|tab=recibos|preset=7'),
        (['preset', 'hoy'], 'desde=2026-10-12&hasta=2026-10-12&formato=nuevo|tab=recibos|preset=hoy'),
        (['reiniciar'], 'desde=2026-09-13&hasta=2026-10-12|tab=recibos|preset=30')]),
    ('desde=2026-10-01&hasta=2026-10-12&sal_min=1250000', {'min': 1150, 'max': 3700}, [
        (['preset', '90'], 'desde=2026-07-15&hasta=2026-10-12&sal_min=1250000|tab=recibos|preset=90'),
        (['aplicar', {'desde': '2026-09-01', 'hasta': '2026-09-30', 'seccionales': [4], 'resultado': 'ok', 'tab': 'tramites'}], 'desde=2026-09-01&hasta=2026-09-30&seccionales=4&resultado=ok|tab=tramites|preset=null'),
        (['aplicar', {'seccionales': [2]}], 'desde=2026-09-01&hasta=2026-09-30|tab=recibos|preset=null'),
        (['aplicar', {'desde': '2026-10-01', 'hasta': '2026-10-13', 'formato': 'nuevo'}], 'desde=2026-09-01&hasta=2026-09-30|tab=recibos|preset=null'),
        (['aplicar', {'desde': '2026-10-05', 'hasta': '2026-10-12', 'sal_min': '', 'sal_max': 2000000, 'formato': 'x'}], 'desde=2026-10-05&hasta=2026-10-12&sal_max=2000000|tab=recibos|preset=null'),
        (['reiniciar'], 'desde=2026-09-13&hasta=2026-10-12|tab=recibos|preset=30')]),
    ('', None, [
        (['seccional', 5], 'desde=2026-09-13&hasta=2026-10-12&seccionales=5|tab=recibos|preset=30'),
        (['preset', '30'], 'desde=2026-09-13&hasta=2026-10-12&seccionales=5|tab=recibos|preset=30'),
        (['aplicar', {'desde': '2026-10-12', 'hasta': '2026-10-12', 'tab': 'consultas'}], 'desde=2026-10-12&hasta=2026-10-12|tab=recibos|preset=hoy'),
        (['reiniciar'], 'desde=2026-09-13&hasta=2026-10-12|tab=recibos|preset=30')]),
]


_V2_IMPORTS = """
import { desdeParams, conLimites, aDireccion, crearReductor, limitesSalario,
         estadoInicial, presetActivo, filtrosActivos, estadoPlano, comoParams } from "./estado.mjs";
const HOY = "2026-10-12";
function salidaV2(e, lim) {
  return aDireccion(e, lim).toString().replace(/&?tab=[^&]*/, "") + "|tab=" + e.tab + "|preset=" + presetActivo(e, HOY);
}
"""


def test_cada_direccion_arma_lo_que_armaba_la_v1(tmp_path):
    js = _V2_IMPORTS + f"""
const CASOS = {json.dumps(CASOS_V1)};
const distintas = [];
for (const [qs, lim0, consultas, esperado] of CASOS) {{
  const lim = lim0 || {{ min: null, max: null }};
  const v2 = salidaV2(conLimites(desdeParams(new URLSearchParams(qs), {{ hoy: HOY, consultas }}), lim), lim);
  if (v2 !== esperado) distintas.push({{ qs, lim0, consultas, esperado, v2 }});
}}
console.log(JSON.stringify({{ casos: CASOS.length, distintas }}));
"""
    r = _correr(js, tmp_path, modulos=("estado",))
    assert r["casos"] == len(CASOS_V1)
    assert not r["distintas"], "una dirección no arma lo de siempre:\n" + json.dumps(r["distintas"], indent=1)


def _foto_esperada(salida: str) -> dict:
    """La foto que viaja al Asistente, armada de los parámetros (así la armaba
    `estadoPlano` de la v1: de los mismos parámetros que van al servidor)."""
    params, tab = salida.split("|")[0], salida.split("|")[1][len("tab="):]
    q = parse_qsl(params, keep_blank_values=True)
    uno = lambda k: next((v for c, v in q if c == k), "")
    numero = lambda k: int(uno(k)) if uno(k) else None
    return {"desde": uno("desde"), "hasta": uno("hasta"),
            "seccionales": [float(v) if "." in v else int(v) for c, v in q if c == "seccionales"],
            "empresas": [int(v) for c, v in q if c == "empresas"],
            "formato": uno("formato"), "resultado": uno("resultado"),
            "estado_tramite": uno("estado_tramite"), "tipo_notif": uno("tipo_notif"),
            "sal_min": numero("sal_min"), "sal_max": numero("sal_max"),
            "tema": uno("tema"), "afiliado": numero("afiliado"), "tab": tab}


def test_los_cambios_dan_lo_que_daban_en_la_v1(tmp_path):
    """Después de cargar una dirección, una serie de los cambios que la v1
    tenía como función propia. Tras cada paso, los mismos parámetros y la
    misma foto del estado que viaja al Asistente."""
    js = _V2_IMPORTS + f"""
const SEC = {json.dumps(SECUENCIAS_V1)};
const reducir = crearReductor({{ hoy: HOY, consultas: false }});
const pasos = [];
for (const [qs, lim0, ops] of SEC) {{
  const lim = lim0 || {{ min: null, max: null }};
  let e = conLimites(desdeParams(new URLSearchParams(qs), {{ hoy: HOY }}), lim);
  for (const [op, esperado] of ops) {{
    if (op[0] === "preset") e = reducir(e, {{ tipo: "preset", valor: op[1] }});
    else if (op[0] === "seccional") e = reducir(e, {{ tipo: "alternar", campo: "seccionales", id: op[1] }});
    else if (op[0] === "reiniciar") e = reducir(e, {{ tipo: "reiniciar", lim }});
    else e = reducir(e, {{ tipo: "aplicar", params: comoParams(op[1]), lim }});
    pasos.push({{ qs, op, esperado, v2: salidaV2(e, lim), foto: estadoPlano(e, lim) }});
  }}
}}
console.log(JSON.stringify({{ pasos }}));
"""
    r = _correr(js, tmp_path, modulos=("estado",))
    assert len(r["pasos"]) == sum(len(ops) for _, _, ops in SECUENCIAS_V1)
    for p in r["pasos"]:
        assert p["v2"] == p["esperado"], p
        assert p["foto"] == _foto_esperada(p["esperado"]), p


def test_las_direcciones_al_azar_dan_siempre_un_periodo_valido(tmp_path):
    """Miles de direcciones al azar, rotas a propósito: la salida es siempre
    un período válido que no termina en el futuro, y abrir la dirección que
    el panel escribe deja el panel igual (un enlace compartido abre lo mismo
    que se estaba mirando), salvo el salario por la rareza de abajo."""
    js = _V2_IMPORTS + _AZAR + """
const malas = [];
for (const consultas of [false, true]) {
  for (let i = 0; i < 2000; i++) {
    const qs = direccion(), lim = uno(LIMITES);
    const e = conLimites(desdeParams(new URLSearchParams(qs), { hoy: HOY, consultas }), lim);
    const iso = /^\\d{4}-\\d{2}-\\d{2}$/;
    const valida = iso.test(e.desde) && iso.test(e.hasta) && e.desde <= e.hasta && e.hasta <= HOY;
    const otra = conLimites(desdeParams(aDireccion(e, lim), { hoy: HOY, consultas }), lim);
    /* El salario queda afuera de la comparación por la rareza de la v1 que
       se conservó (BACKLOG.md, D10): sin `sal_min`, el `sal_max` se pierde al
       releer. Se arregla en el núcleo, no acá. */
    const sinSal = (x) => x.replace(/&?sal_(min|max)=[^&|]*/g, "");
    if ((!valida || sinSal(salidaV2(otra, lim)) !== sinSal(salidaV2(e, lim))) && malas.length < 5)
      malas.push({ qs, lim, una: salidaV2(e, lim), otra: salidaV2(otra, lim), valida });
  }
}
console.log(JSON.stringify({ malas }));
"""
    r = _correr(js, tmp_path, modulos=("estado",))
    assert not r["malas"], json.dumps(r["malas"], indent=1)


def test_los_cambios_propios_de_los_graficos(tmp_path):
    """Lo que en la v1 vivía adentro de cada onClick de gráfico: se prueba
    contra lo que decían esos onClick."""
    js = _V2_IMPORTS + """
const r = crearReductor({ hoy: HOY, consultas: false });
let e = estadoInicial(HOY);
const res = {};
// Dona de validación: el mismo segmento otra vez apaga el filtro.
e = r(e, [{ tipo: "alternarValor", campo: "resultado", valor: "ok" }, { tipo: "tab", valor: "recibos" }]);
res.dona1 = e.resultado;
e = r(e, { tipo: "alternarValor", campo: "resultado", valor: "ok" });
res.dona2 = e.resultado;
// Barra de trámites: seccional Y estado; la misma barra otra vez saca los dos.
e = r(e, { tipo: "tramiteSeccional", seccional: 3, estado: "abierto" });
res.tram1 = [e.seccionales, e.estadoTramite];
e = r(e, { tipo: "tramiteSeccional", seccional: 3, estado: "resuelto" });
res.tram2 = [e.seccionales, e.estadoTramite];
e = r(e, { tipo: "tramiteSeccional", seccional: 3, estado: "resuelto" });
res.tram3 = [e.seccionales, e.estadoTramite];
e = r(e, { tipo: "tramiteSeccional", seccional: null, estado: "abierto" });
res.tram4 = [e.seccionales, e.estadoTramite];
// Una pestaña que no existe no se elige; "ver más" suma página y un filtro la vuelve a 1.
e = r(e, { tipo: "tab", valor: "tramites" });
e = r(e, { tipo: "tab", valor: "consultas" });
res.tab = e.tab;
e = r(e, [{ tipo: "verMas" }, { tipo: "verMas" }]);
res.paginas1 = e.paginas;
e = r(e, { tipo: "alternar", campo: "empresas", id: 9 });
res.paginas2 = e.paginas;
res.lim = [limitesSalario(1180000, 3650000), limitesSalario(null, 5), limitesSalario(5, 5)];
console.log(JSON.stringify(res));
"""
    r = _correr(js, tmp_path, modulos=("estado",))
    assert r["dona1"] == "ok" and r["dona2"] == ""
    assert r["tram1"] == [[3], "abierto"]
    assert r["tram2"] == [[3], "resuelto"], "otra barra de la misma seccional cambia el estado"
    assert r["tram3"] == [[], ""], "la misma barra otra vez saca seccional y estado"
    assert r["tram4"] == [[], "abierto"], "la barra sin seccional filtra solo el estado"
    assert r["tab"] == "tramites", "con consultas apagado esa pestaña no existe"
    assert r["paginas1"] == 3 and r["paginas2"] == 1
    assert r["lim"] == [{"min": 1150, "max": 3650}, {"min": None, "max": None},
                        {"min": None, "max": None}]


def test_los_pedidos_al_servidor(tmp_path):
    js = """
import { crearPedir, enCola, esperar, BASE, MAX_EN_VUELO, ESPERA_503_MS } from "./api.mjs";
function respuesta(status, cuerpo) {
  return { status, ok: status >= 200 && status < 300,
           json: () => cuerpo === undefined ? Promise.reject(new Error("no json")) : Promise.resolve(cuerpo) };
}
function guion(estados) {      // un fetch falso que contesta en orden
  const urls = [];
  const fetch = (url) => { urls.push(url); const [s, c] = estados.shift(); return Promise.resolve(respuesta(s, c)); };
  return { fetch, urls };
}
const res = { base: BASE, max: MAX_EN_VUELO, esperas: ESPERA_503_MS };
async function caso(nombre, estados, extra = {}) {
  const g = guion(estados), esperas = [];
  let salio = false;
  const pedir = crearPedir({ fetch: g.fetch, esperar: (ms) => { esperas.push(ms); return Promise.resolve(); },
                             alPerderSesion: () => { salio = true; }, ...extra });
  const q = new URLSearchParams("desde=2026-10-01&hasta=2026-10-12");
  try { res[nombre] = { ok: await pedir("kpis", q), urls: g.urls, esperas, salio }; }
  catch (e) { res[nombre] = { error: e.message, status: e.status, detalle: e.detalle, urls: g.urls, esperas, salio }; }
}
await caso("bien", [[200, { a: 1 }]]);
await caso("ocupado_dos_veces", [[503, {}], [503, {}], [200, { a: 2 }]]);
await caso("ocupado_tres_veces", [[503, {}], [503, {}], [503, { detail: "cupo" }]]);
await caso("sesion", [[403, {}]]);
await caso("rechazo", [[422, { detail: "El rango no puede terminar en el futuro." }]]);
await caso("sin_json", [[500]]);

// Una ronda abortada corta también la espera del reintento: no hay segundo pedido.
{
  const g = guion([[503, {}], [200, {}]]);
  const pedir = crearPedir({ fetch: g.fetch });
  const ac = new AbortController();
  setTimeout(() => ac.abort(), 20);
  try { await pedir("kpis", null, ac.signal); res.abortado = "no se abortó"; }
  catch (e) { res.abortado = { nombre: e.name, pedidos: g.urls.length }; }
}
{
  const ac = new AbortController(); ac.abort();
  try { await esperar(10, ac.signal); res.ya_abortado = "esperó"; } catch (e) { res.ya_abortado = e.name; }
}

// La cola: nunca más de 4 en vuelo y termina todo, aunque alguna tarea falle.
{
  let vuelo = 0, pico = 0, hechas = 0;
  const tareas = Array.from({ length: 13 }, (_, i) => () => {
    vuelo++; pico = Math.max(pico, vuelo);
    return new Promise((ok, mal) => setTimeout(() => { vuelo--; hechas++; (i % 5 === 0 ? mal : ok)(); }, 5 + (i % 3) * 7));
  });
  await enCola(tareas);
  await enCola([]);
  res.cola = { pico, hechas };
}
console.log(JSON.stringify(res));
"""
    r = _correr(js, tmp_path, modulos=("api",))
    assert r["base"] == "/admin/dashboard/" and r["max"] == 4 and r["esperas"] == [700, 1500]
    assert r["bien"]["ok"] == {"a": 1}
    assert r["bien"]["urls"] == ["/admin/dashboard/kpis?desde=2026-10-01&hasta=2026-10-12"]
    assert r["ocupado_dos_veces"]["ok"] == {"a": 2}
    assert r["ocupado_dos_veces"]["esperas"] == [700, 1500]
    assert r["ocupado_tres_veces"]["status"] == 503 and len(r["ocupado_tres_veces"]["urls"]) == 3, \
        "el tercer 503 no se reintenta: se muestra"
    assert r["ocupado_tres_veces"]["detalle"] == "cupo"
    assert r["sesion"]["error"] == "sesion" and r["sesion"]["salio"] is True
    assert r["rechazo"]["status"] == 422
    assert r["rechazo"]["detalle"] == "El rango no puede terminar en el futuro."
    assert r["sin_json"]["status"] == 500 and r["sin_json"]["detalle"] == ""
    assert r["abortado"] == {"nombre": "AbortError", "pedidos": 1}
    assert r["ya_abortado"] == "AbortError"
    assert r["cola"] == {"pico": 4, "hechas": 13}


def test_el_nucleo_no_toca_el_dom():
    """estado.js y api.js se prueban en Node justamente porque no dependen
    del navegador: que siga siendo así."""
    for nombre in ("estado.js", "api.js", "formato.js"):
        js = re.sub(r"/\*.*?\*/", "", (RAIZ / "static" / "panel_v2" / nombre).read_text(encoding="utf-8"),
                    flags=re.S)
        for prohibido in ("document.", "window.", "localStorage", "sessionStorage"):
            assert prohibido not in js, f"{nombre} usa {prohibido}"
        assert "import " not in js, f"{nombre} importa algo: el núcleo no depende de nadie"


def test_las_pastillas_de_filtros_dicen_lo_mismo_que_en_la_v1(tmp_path):
    """Los textos y el orden de `pintarChips` de la v1 (los de siempre), y
    cada pastilla trae la acción que la saca."""
    js = _V2_IMPORTS + """
const r = crearReductor({ hoy: HOY });
const catalogo = { seccionales: [{ id: 3, nombre: "Córdoba" }], empresas: [{ id: 9, nombre: "Metalsur SA" }] };
const lim = { min: 1150, max: 3700 };
let e = Object.assign(estadoInicial(HOY), { seccionales: [3, 77], empresas: [9], formato: "nuevo",
  resultado: "con_diferencias", estadoTramite: "en_proceso", tipoNotif: "sistema", tema: "licencias",
  afiliado: 12, salMin: 1200, salMax: 3700 });
const f = filtrosActivos(e, { catalogo, lim, afiliados: { 12: { nombre: "Diego Sosa" } } });
const sin = f.reduce((x, p) => r(x, p.accion), e);
const sinAfiliado = filtrosActivos(Object.assign({}, e, { afiliado: 5 }), { catalogo, lim });
console.log(JSON.stringify({ textos: f.map((p) => p.txt), quedan: filtrosActivos(sin, { catalogo, lim }).length,
  salario: [sin.salMin, sin.salMax], sinNombre: sinAfiliado.find((p) => p.txt.startsWith("Afiliado")).txt,
  sinLimites: filtrosActivos(e, { catalogo }).some((p) => p.txt.startsWith("Bruto")) }));
"""
    r = _correr(js, tmp_path, modulos=("estado",))
    assert r["textos"] == [
        "Seccional: Córdoba", "Seccional: #77", "Empresa: Metalsur SA", "Formato: Ley 27.802",
        "Resultado: Con diferencias", "Trámites: En proceso", "Notif.: Trámites", "Tema: licencias",
        "Afiliado: Diego Sosa", "Bruto: $1.200k – $3.700k"]
    assert r["quedan"] == 0, "sacar cada pastilla con su acción deja el panel sin filtros"
    assert r["salario"] == [1150, 3700], "sacar el salario lo vuelve a los límites"
    assert r["sinNombre"] == "Afiliado: #5", "sin el nombre todavía, el id"
    assert r["sinLimites"] is False, "sin slider no hay pastilla de salario"


def test_los_formatos_son_los_de_la_v1(tmp_path):
    (tmp_path / "formato.mjs").write_text(
        (RAIZ / "static" / "panel_v2" / "formato.js").read_text(encoding="utf-8"), encoding="utf-8")
    js = """
import { fmtN, fmtM, fmtPct, fFecha, fechaLarga, deltaRecibos } from "./formato.mjs";
console.log(JSON.stringify({
  n: [fmtN(4707), fmtN(null), fmtN(0)], m: [fmtM(25217857.29), fmtM(undefined)],
  pct: [fmtPct(20.8), fmtPct(20), fmtPct(null)], fecha: [fFecha("2026-10-12 18:15"), fFecha("")],
  larga: fechaLarga("2026-10-12"),
  delta: [deltaRecibos(4707, 293), deltaRecibos(90, 100), deltaRecibos(5, 0)],
}));
"""
    r = _correr(js, tmp_path, modulos=())
    assert r["n"] == ["4.707", "—", "0"]
    assert r["m"] == ["$ 25.217.857", "—"]
    assert r["pct"] == ["20,8 %", "20 %", "—"]
    assert r["fecha"] == ["12/10/2026", "—"]
    assert r["larga"] == "lunes, 12 de octubre de 2026"
    assert r["delta"] == [{"clase": "up", "texto": "▲ 1506% vs período anterior"},
                          {"clase": "down", "texto": "▼ 10% vs período anterior"},
                          {"clase": "neu", "texto": "s/d período anterior"}]

