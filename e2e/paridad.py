# -*- coding: utf-8 -*-
"""Robot de paridad del Panel Sindical (PLAN_DASHBOARD_V2.md, bloques 0 y 7).

La v2 del panel solo reemplaza a la v1 si, con los mismos filtros, muestra
los mismos números (D9). Este módulo es la mitad que no depende de la
versión: arma las combinaciones de filtros, abre el panel, espera a que
termine de cargar y devuelve una LECTURA, un diccionario con lo que el
panel está mostrando. La otra mitad es el lector de cada versión
(`LECTORES`), el único lugar que conoce el HTML de cada una.

Qué entra en una lectura:
- Los KPIs, los contadores de las pestañas del explorador, las filas de la
  tabla, el semáforo, las burbujas del mapa y los filtros activos.
- Los datos de cada gráfico, leídos de la instancia de Chart.js con
  `Chart.getChart` (los gráficos son canvas: no hay texto que mirar).
- **Los pedidos que hizo al servidor**, con sus parámetros ordenados. Es la
  línea roja 3 del plan: la v2 tiene que hablarle al servidor igual que la
  v1, así que las dos tienen que pedir exactamente lo mismo.
- **Cuántos pedidos tuvo en vuelo a la vez, como máximo**: el cupo del
  servidor es de 4 (el cuelgue de Pruebas del 2026-09-18) y acá se mide en
  un navegador de verdad, no sobre el código.

Los textos se comparan por sus NÚMEROS, no por su formato (`numeros`): la
v2 puede escribir "$ 1.234" donde la v1 escribe "$1.234" sin que eso sea
una diferencia de datos (D5: la estética puede cambiar, los números no).

Se corre con prefers-reduced-motion: así ni la v1 (que hace "flash" en los
KPIs) ni la v2 (con animaciones, D5) dejan un valor a medio camino cuando
se lee.
"""
import json
import os
import re
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pytest

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:8000")

RUTAS = {"v1": "/admin/dashboard", "v2": "/admin/dashboard-v2"}

ADMIN_UOM = {"usuario": "20111111120", "clave": "uom-demo"}

COMO_PREPARAR_DEMO = ("Falta la demo. Corré: python cargar_marca_plataforma.py && "
                      "python cargar_demo.py")
COMO_PREPARAR_LOTE = ('Falta el lote de la UOM. Corré: python cargar_lote_sindicato.py '
                      '--sindicato "Unión Obrera Metalúrgica"')

RESULTADOS = Path(__file__).parent / "resultados" / "paridad"

# Los endpoints de datos del panel. El Asistente queda afuera: es una
# consulta puntual a pedido, no parte de la ronda, y no tiene cupo.
_PREFIJO_DATOS = "/admin/dashboard/"
_FUERA_DE_LA_RONDA = ("/admin/dashboard/asistente",)


# ---------------------------------------------------------------------------
# Combinaciones de filtros
# ---------------------------------------------------------------------------
# Los nombres son fijos (pytest los usa para parametrizar). Los valores se
# arman en el momento, con la fecha de hoy del SERVIDOR y el catálogo real
# del sindicato: el lote es relativo a la fecha en que se cargó.
NOMBRES = (
    "inicial",
    "90-dias",
    "90-dias-seccional-salario",
    "30-dias-empresa-ley-27802",
    "rango-que-cruza-meses-con-diferencias",
    "180-dias-tramites-abiertos",
    "url-con-fecha-futura",
)


def parametros(nombre: str, hoy, catalogo: dict) -> dict:
    """Los query params de una combinación. Son los mismos para las dos
    versiones: comparten el formato de la URL (línea roja 3)."""
    def hace(dias):
        return (hoy - timedelta(days=dias)).isoformat()

    secc = catalogo["seccionales"][0]["id"] if catalogo["seccionales"] else None
    emp = catalogo["empresas"][0]["id"] if catalogo["empresas"] else None

    if nombre == "inicial":
        # Sin parámetros: la vista con la que abre el panel ("Hoy").
        return {}
    if nombre == "90-dias":
        return {"desde": hace(89), "hasta": hoy.isoformat()}
    if nombre == "90-dias-seccional-salario":
        if secc is None:
            pytest.skip("El sindicato no tiene seccionales. " + COMO_PREPARAR_LOTE)
        p = {"desde": hace(89), "hasta": hoy.isoformat(), "seccionales": secc}
        piso = _piso_del_slider(catalogo)
        if piso is not None:
            # 50 mil por encima del piso del slider: el panel solo manda
            # `sal_min` cuando difiere del límite.
            p["sal_min"] = (piso + 50) * 1000
        return p
    if nombre == "30-dias-empresa-ley-27802":
        if emp is None:
            pytest.skip("El sindicato no tiene empresas. " + COMO_PREPARAR_LOTE)
        return {"desde": hace(29), "hasta": hoy.isoformat(), "empresas": emp,
                "formato": "nuevo"}
    if nombre == "rango-que-cruza-meses-con-diferencias":
        # Del día 15 antes de empezar este mes al día 10 de este mes (o hoy,
        # si todavía no llegó): el calendario tiene que cruzar de mes.
        primero = hoy.replace(day=1)
        hasta = min(hoy, primero + timedelta(days=9))
        return {"desde": (primero - timedelta(days=15)).isoformat(),
                "hasta": hasta.isoformat(), "resultado": "con_diferencias"}
    if nombre == "180-dias-tramites-abiertos":
        return {"desde": hace(179), "hasta": hoy.isoformat(),
                "estado_tramite": "abierto", "tab": "tramites"}
    if nombre == "url-con-fecha-futura":
        # Una URL editada a mano con un `hasta` futuro: el panel la descarta y
        # abre como "inicial" (saneo de §3.1). Si no la descartara, el
        # servidor contestaría 422 a todo.
        return {"desde": hace(10), "hasta": (hoy + timedelta(days=3)).isoformat()}
    raise ValueError(nombre)


def _piso_del_slider(catalogo: dict):
    """El piso del slider de salario en miles, redondeado a 50 mil igual que
    `initCatalogo` de la v1. None si no hay rango para mover."""
    bmin, bmax = catalogo.get("bruto_min"), catalogo.get("bruto_max")
    if bmin is None or bmax is None or bmax <= bmin:
        return None
    piso = int(bmin // 50000) * 50
    techo = -int(-bmax // 50000) * 50
    return piso if techo - piso >= 100 else None


# ---------------------------------------------------------------------------
# Entrar y abrir el panel
# ---------------------------------------------------------------------------
def entrar_como_admin(page):
    page.goto(f"{BASE}/admin")
    page.fill('input[name="usuario"]', ADMIN_UOM["usuario"])
    page.fill('input[name="clave"]', ADMIN_UOM["clave"])
    page.click('button[type="submit"]')
    try:
        page.wait_for_url("**/admin/inicio", wait_until="commit", timeout=10000)
    except Exception:
        pytest.skip(COMO_PREPARAR_DEMO)


def catalogo(page) -> dict:
    """El catálogo de filtros del sindicato, con la sesión del navegador."""
    r = page.request.get(f"{BASE}/admin/dashboard/filtros")
    if r.status != 200:
        pytest.skip(f"El panel no está habilitado para el admin de la UOM ({r.status}). "
                    + COMO_PREPARAR_LOTE)
    return r.json()


def existe(page, version: str) -> bool:
    return page.request.get(f"{BASE}{RUTAS[version]}").status == 200


class _Monitor:
    """Cuenta los pedidos de datos del panel: cuáles terminaron bien y
    cuántos hubo en vuelo a la vez. Un pedido abortado (cambio de filtros,
    AbortController) no cuenta como hecho, pero sí ocupó lugar mientras
    estuvo en vuelo."""

    def __init__(self, page):
        self.en_vuelo = 0
        self.maximo = 0
        self.hechos = []        # "ruta?a=1&b=2", con los parámetros ordenados
        self.fallidos = []      # (ruta, status) de los que volvieron con error
        page.on("request", self._salio)
        page.on("requestfinished", self._volvio)
        page.on("requestfailed", self._cayo)

    @staticmethod
    def _es_de_la_ronda(url: str) -> bool:
        ruta = urlsplit(url).path
        return ruta.startswith(_PREFIJO_DATOS) and not ruta.startswith(_FUERA_DE_LA_RONDA)

    def _salio(self, req):
        if self._es_de_la_ronda(req.url):
            self.en_vuelo += 1
            self.maximo = max(self.maximo, self.en_vuelo)

    def _volvio(self, req):
        if not self._es_de_la_ronda(req.url):
            return
        self.en_vuelo -= 1
        partes = urlsplit(req.url)
        clave = partes.path + "?" + "&".join(
            f"{k}={v}" for k, v in sorted(parse_qsl(partes.query)))
        resp = req.response()
        if resp is not None and resp.status >= 400:
            self.fallidos.append((clave, resp.status))
        else:
            self.hechos.append(clave)

    def _cayo(self, req):
        if self._es_de_la_ronda(req.url):
            self.en_vuelo -= 1


def abrir(page, version: str, params: dict, timeout_s: float = 40) -> "_Monitor":
    """Abre el panel con esos filtros y espera a que se calme: nada en vuelo
    y ningún panel cargando, durante un segundo seguido (más que la espera de
    400 ms antes de pedir, D8)."""
    lector = LECTORES[version]
    page.emulate_media(reduced_motion="reduce")
    monitor = _Monitor(page)
    query = "&".join(f"{k}={v}" for k, v in params.items())
    page.goto(f"{BASE}{RUTAS[version]}" + (f"?{query}" if query else ""),
              wait_until="domcontentloaded")
    fin = time.time() + timeout_s
    quieto_desde = None
    while time.time() < fin:
        cargando = page.locator(lector["cargando"]).count()
        if monitor.en_vuelo == 0 and cargando == 0 and monitor.hechos:
            quieto_desde = quieto_desde or time.time()
            if time.time() - quieto_desde >= 1.0:
                return monitor
        else:
            quieto_desde = None
        page.wait_for_timeout(100)
    raise AssertionError(f"El panel {version} no terminó de cargar en {timeout_s:.0f} s "
                         f"(en vuelo: {monitor.en_vuelo}, hechos: {len(monitor.hechos)})")


def leer(page, version: str, params: dict) -> dict:
    """Abre el panel y devuelve la lectura completa (ver docstring del módulo)."""
    monitor = abrir(page, version, params)
    lectura = page.evaluate(LECTORES[version]["js"])
    lectura["pedidos"] = sorted(set(monitor.hechos))
    lectura["pedidos_fallidos"] = monitor.fallidos
    lectura["max_en_vuelo"] = monitor.maximo
    lectura["url"] = urlsplit(page.url).query
    return lectura


def guardar(page, version: str, nombre: str, lectura: dict) -> Path:
    """Deja la lectura en JSON y una captura de página entera (sirven de
    material para el mockup de D5). `e2e/resultados/` no se versiona."""
    RESULTADOS.mkdir(parents=True, exist_ok=True)
    base = RESULTADOS / f"{version}-{nombre}"
    base.with_suffix(".json").write_text(
        json.dumps(lectura, ensure_ascii=False, indent=1), encoding="utf-8")
    page.screenshot(path=str(base.with_suffix(".png")), full_page=True)
    return base


# ---------------------------------------------------------------------------
# Lectores: el único lugar que conoce el HTML de cada versión
# ---------------------------------------------------------------------------
# Cada lector devuelve el MISMO diccionario. La v2 suma el suyo en el bloque 7
# del plan; hasta entonces la comparación se saltea diciendo por qué.
_JS_V1 = r"""
() => {
  const q = (s) => document.querySelector(s);
  const texto = (s) => { const e = q(s); return e ? e.textContent.trim() : null; };
  const kpis = {};
  document.querySelectorAll("#kpis .val").forEach((e) => {
    kpis[e.id.replace(/^v-/, "")] = e.textContent.trim();
  });
  const contadores = {};
  document.querySelectorAll("#tabs-datos .tab-d").forEach((b) => {
    const c = b.querySelector(".cnt");
    contadores[b.dataset.t] = c ? c.textContent.trim() : null;
  });
  const activa = q("#tabs-datos .tab-d.act");
  const filas = [...document.querySelectorAll("#tabla-body tr")]
    .filter((tr) => !tr.querySelector(".vacio-exp"));
  const graficos = {};
  document.querySelectorAll("[data-panel] canvas").forEach((cv) => {
    const ch = window.Chart && Chart.getChart(cv);
    if (!ch) return;
    const panel = cv.closest("[data-panel]").dataset.panel;
    graficos[panel] = {
      labels: (ch.data.labels || []).map(String),
      series: ch.data.datasets.map((d) => ({ label: d.label || "", data: d.data })),
    };
  });
  const aviso = q("#aviso-error");
  return {
    version: "v1",
    kpis,
    delta_recibos: texto("#d-recibos"),
    delta_padron: texto("#d-padron"),
    rango: texto("#rango-texto"),
    contadores,
    explorador: {
      pestana: activa ? activa.dataset.t : null,
      filas: filas.length,
      primeras: filas.slice(0, 3).map((tr) => tr.textContent.replace(/\s+/g, " ").trim()),
      total: texto("#tabla-total"),
    },
    graficos,
    semaforo: {
      resumen: texto("#sem-resumen"),
      empresas: document.querySelectorAll("#sem-lista .sem-item").length,
    },
    mapa: { burbujas: document.querySelectorAll('[data-panel="seccionales-geo"] .mt-burbuja').length },
    filtros_activos: [...document.querySelectorAll("#chips .chipf")]
      .map((c) => c.firstChild.textContent.trim()),
    paneles_con_error: [...document.querySelectorAll("[data-panel].con-error")]
      .map((p) => p.dataset.panel),
    aviso: aviso && !aviso.hidden ? aviso.textContent.trim() : "",
  };
}
"""

LECTORES = {
    "v1": {"js": _JS_V1, "cargando": "[data-panel].cargando, #kpis.cargando"},
}


# ---------------------------------------------------------------------------
# Comparar dos lecturas
# ---------------------------------------------------------------------------
_NUMERO = re.compile(r"\d[\d.]*(?:,\d+)?")


def numeros(texto) -> list:
    """Los números de un texto, en formato es-AR (1.234,5 -> 1234.5). Es lo
    que se compara: el formato puede cambiar entre versiones, el número no."""
    if texto is None:
        return []
    salida = []
    for crudo in _NUMERO.findall(str(texto)):
        salida.append(float(crudo.replace(".", "").replace(",", ".")))
    return salida


def comparar(a: dict, b: dict) -> list:
    """Las diferencias de DATOS entre dos lecturas, en castellano. Vacío si
    muestran lo mismo."""
    dif = []

    def igual(nombre, x, y):
        if x != y:
            dif.append(f"{nombre}: {a['version']}={x!r} / {b['version']}={y!r}")

    for clave in sorted(set(a["kpis"]) | set(b["kpis"])):
        igual(f"KPI {clave}", numeros(a["kpis"].get(clave)), numeros(b["kpis"].get(clave)))
    igual("variación de recibos", numeros(a["delta_recibos"]), numeros(b["delta_recibos"]))
    igual("rango de fechas", numeros(a["rango"]), numeros(b["rango"]))
    for clave in sorted(set(a["contadores"]) | set(b["contadores"])):
        igual(f"contador {clave}", numeros(a["contadores"].get(clave)),
              numeros(b["contadores"].get(clave)))
    igual("pestaña del explorador", a["explorador"]["pestana"], b["explorador"]["pestana"])
    igual("filas del explorador", a["explorador"]["filas"], b["explorador"]["filas"])
    igual("total del explorador", numeros(a["explorador"]["total"]),
          numeros(b["explorador"]["total"]))
    for panel in sorted(set(a["graficos"]) | set(b["graficos"])):
        ga, gb = a["graficos"].get(panel), b["graficos"].get(panel)
        if ga is None or gb is None:
            igual(f"gráfico {panel}", ga is not None, gb is not None)
            continue
        igual(f"gráfico {panel}: etiquetas", ga["labels"], gb["labels"])
        igual(f"gráfico {panel}: datos", [s["data"] for s in ga["series"]],
              [s["data"] for s in gb["series"]])
    igual("semáforo: resumen", numeros(a["semaforo"]["resumen"]),
          numeros(b["semaforo"]["resumen"]))
    igual("semáforo: empresas", a["semaforo"]["empresas"], b["semaforo"]["empresas"])
    igual("mapa: burbujas", a["mapa"]["burbujas"], b["mapa"]["burbujas"])
    igual("cantidad de filtros activos", len(a["filtros_activos"]), len(b["filtros_activos"]))
    igual("pedidos al servidor", a["pedidos"], b["pedidos"])
    return dif
