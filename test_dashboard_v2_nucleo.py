"""Panel Sindical v2, bloque 2: el núcleo sin pantalla (PLAN_DASHBOARD_V2.md).

`static/panel_v2/estado.js` y `api.js` no tocan el DOM, así que se prueban
corriéndolos de verdad con Node. Lo central es la línea roja 3 del plan: la v2
tiene que pedirle al servidor EXACTAMENTE lo mismo que la v1. Por eso no se
compara la v2 contra lo que uno cree que hace la v1, sino **contra la v1
misma**: se sacan de static/dashboard.js las funciones que arman y sanean el
estado (como hace test_dashboard_cola_front.py con `enCola`), se corren al
lado de las de la v2 con miles de direcciones al azar, rotas a propósito, y
tienen que dar los mismos parámetros.

Además: la cola nunca pasa de 4 en vuelo, el 503 se reintenta dos veces con
la espera de la v1, el 403 manda a /admin, el 422 trae su motivo, y una ronda
abortada corta también la espera del reintento.

Sin Node instalado, los tests se saltean (igual que test_dashboard_cola_front).

Correr con: .venv/bin/python -m pytest test_dashboard_v2_nucleo.py -q
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).parent
V1 = (RAIZ / "static" / "dashboard.js").read_text(encoding="utf-8")
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="Node no está instalado")


def _funcion_v1(nombre):
    m = re.search(rf"  function {nombre}\(.*?\n  \}}\n", V1, re.S)
    assert m, f"no encontré function {nombre} en dashboard.js"
    return m.group(0)


def _trozo_v1(patron, que):
    m = re.search(patron, V1, re.S)
    assert m, f"no encontré {que} en dashboard.js"
    return m.group(0)


def _v1_como_js(consultas: bool) -> str:
    """Las piezas de la v1 que deciden qué parámetros viajan, con lo mínimo
    alrededor para que corran fuera del navegador."""
    s_inicial = _trozo_v1(r"  var S = \{.*?\n  \};\n", "el estado inicial S")
    fiso = _trozo_v1(r"  var fISO = function \(d\) \{.*?\n  \};\n", "fISO")
    deiso = _trozo_v1(r"  var deISO = [^\n]*\n", "deISO")
    encaje = _trozo_v1(r"if \(S\.salMin === null\) \{[^\n]*\n\s*else \{[^\n]*\}",
                       "el encaje del salario de initCatalogo")
    funciones = "".join(_funcion_v1(n) for n in (
        "paramsDeEstado", "estadoDeParams", "setPreset", "reiniciar",
        "alternarSeccional", "aplicarEstado"))
    return f"""
const V1 = (() => {{
  var HOY = new Date(2026, 9, 12);
  var CONSULTAS_ON = {str(consultas).lower()};
  var LIM = {{ min: null, max: null }};
  var calVista = null, calEligiendo = false;
  function refrescar() {{}}  function cambio() {{}}  function etiquetarAfiliado() {{}}
  {fiso}{deiso}
  {s_inicial.replace("var S =", "var S; function nuevoS() { return", 1).rstrip().rstrip(";")} ; }}
  {funciones}
  function encajar() {{ if (LIM.min !== null && LIM.max !== null) {{ {encaje} }} }}
  function salida() {{ return paramsDeEstado().toString() + "|tab=" + S.tab; }}
  return {{
    cargar(qs, lim) {{ S = nuevoS(); LIM = lim; estadoDeParams(new URLSearchParams(qs)); encajar(); return salida(); }},
    preset(p) {{ setPreset(p); return salida(); }},
    alternarSeccional(id) {{ alternarSeccional(id); return salida(); }},
    reiniciar() {{ reiniciar(); return salida(); }},
    aplicar(filtros) {{ aplicarEstado(filtros); return salida(); }},
  }};
}})();
"""


def _correr(js: str, tmp_path: Path, modulos=("estado", "api")) -> dict:
    """Copia los módulos de la v2 como .mjs (así cualquier Node los toma como
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

_V2_IMPORTS = """
import { desdeParams, conLimites, aDireccion, crearReductor, limitesSalario,
         estadoInicial } from "./estado.mjs";
const HOY = "2026-10-12";
function salidaV2(e, lim) { return aDireccion(e, lim).toString().replace(/&?tab=[^&]*/, "") + "|tab=" + e.tab; }
"""


@pytest.mark.parametrize("consultas", [False, True])
def test_la_v2_arma_los_mismos_parametros_que_la_v1(tmp_path, consultas):
    js = _V2_IMPORTS + _v1_como_js(consultas) + _AZAR + f"""
const distintas = [];
let casos = 0;
for (let i = 0; i < 4000; i++) {{
  const qs = direccion(), lim = uno(LIMITES);
  const v1 = V1.cargar(qs, lim);
  const v2 = salidaV2(conLimites(desdeParams(new URLSearchParams(qs), {{ hoy: HOY, consultas: {str(consultas).lower()} }}), lim), lim);
  casos++;
  if (v1 !== v2 && distintas.length < 5) distintas.push({{ qs, lim, v1, v2 }});
}}
console.log(JSON.stringify({{ casos, distintas }}));
"""
    r = _correr(js, tmp_path, modulos=("estado",))
    assert r["casos"] == 4000
    assert not r["distintas"], "la v2 no arma lo mismo que la v1:\n" + json.dumps(r["distintas"], indent=1)


def test_los_cambios_de_la_v2_dan_lo_mismo_que_los_de_la_v1(tmp_path):
    """Después de cargar una dirección, una serie al azar de los cambios que
    la v1 tiene como función propia: período rápido, seccional, reiniciar y
    aplicar filtros (el Asistente). Tras cada paso, mismos parámetros."""
    js = _V2_IMPORTS + _v1_como_js(False) + _AZAR + """
const reducir = crearReductor({ hoy: HOY, consultas: false });
function filtrosAzar() {
  // Como los manda el Asistente: un objeto plano, a veces sin fechas.
  const f = {};
  if (azar() < 0.7) { f.desde = uno(FECHAS); f.hasta = uno(FECHAS); }
  if (azar() < 0.5) f.seccionales = [Math.floor(azar() * 5)];
  if (azar() < 0.4) f.formato = uno(["viejo", "nuevo", "x"]);
  if (azar() < 0.4) f.sal_min = uno([null, "", 1250000, 900000]);
  if (azar() < 0.4) f.sal_max = uno([null, 2000000, 9000000]);
  if (azar() < 0.4) f.resultado = uno(["ok", "", "con_diferencias"]);
  if (azar() < 0.3) f.tab = uno(["tramites", "notificaciones", "consultas"]);
  return f;
}
function comoParams(filtros) {   // el armado de `aplicarEstado` de la v1
  const q = new URLSearchParams();
  Object.keys(filtros).forEach((k) => {
    const v = filtros[k];
    if (v === null || v === undefined || v === "") return;
    if (Array.isArray(v)) v.forEach((x) => q.append(k, x)); else q.set(k, v);
  });
  return q;
}
const distintas = [];
let pasos = 0;
for (let i = 0; i < 600; i++) {
  const qs = direccion(), lim = uno(LIMITES);
  V1.cargar(qs, lim);
  let e = conLimites(desdeParams(new URLSearchParams(qs), { hoy: HOY }), lim);
  for (let j = 0; j < 6; j++) {
    const op = uno(["preset", "seccional", "reiniciar", "aplicar"]);
    let v1, nombre;
    if (op === "preset") {
      const p = uno(["hoy", "7", "30", "90"]); nombre = "preset " + p;
      v1 = V1.preset(p); e = reducir(e, { tipo: "preset", valor: p });
    } else if (op === "seccional") {
      const id = 1 + Math.floor(azar() * 4); nombre = "seccional " + id;
      v1 = V1.alternarSeccional(id); e = reducir(e, { tipo: "alternar", campo: "seccionales", id });
    } else if (op === "reiniciar") {
      nombre = "reiniciar";
      v1 = V1.reiniciar(); e = reducir(e, { tipo: "reiniciar", lim });
    } else {
      const f = filtrosAzar(); nombre = "aplicar " + JSON.stringify(f);
      v1 = V1.aplicar(f); e = reducir(e, { tipo: "aplicar", params: comoParams(f), lim });
    }
    pasos++;
    const v2 = salidaV2(e, lim);
    if (v1 !== v2 && distintas.length < 5) distintas.push({ qs, lim, paso: nombre, v1, v2 });
  }
}
console.log(JSON.stringify({ pasos, distintas }));
"""
    r = _correr(js, tmp_path, modulos=("estado",))
    assert r["pasos"] == 3600
    assert not r["distintas"], "un cambio da distinto en la v2:\n" + json.dumps(r["distintas"], indent=1)


def test_los_cambios_propios_de_los_graficos(tmp_path):
    """Lo que en la v1 vive adentro de cada onClick de gráfico y no se puede
    extraer como función: se prueba contra lo que dicen esos onClick."""
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
    for nombre in ("estado.js", "api.js"):
        js = re.sub(r"/\*.*?\*/", "", (RAIZ / "static" / "panel_v2" / nombre).read_text(encoding="utf-8"),
                    flags=re.S)
        for prohibido in ("document.", "window.", "localStorage", "sessionStorage"):
            assert prohibido not in js, f"{nombre} usa {prohibido}"
        assert "import " not in js, f"{nombre} importa algo: el núcleo no depende de nadie"
