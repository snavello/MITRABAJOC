# -*- coding: utf-8 -*-
"""Fixtures del entorno E2E.

OJO con el orden de los conftest: el de la RAÍZ fuerza DATABASE_URL=""
(SQLite aislado) para la suite unitaria. Acá lo revertimos leyendo .env de
nuevo con override: los E2E hablan con el MISMO Postgres local que usa el
servidor que están probando -- si no, las verificaciones y preparaciones
de datos mirarían una base distinta a la de la app.
"""
import html
import os
import re
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import pytest

# pytest agrega e2e/ al sys.path (import mode "prepend"), así que este
# import simple funciona sin convertir la carpeta en paquete.
import ventanas
import fechas


@pytest.fixture
def nuevo_actor(browser, pytestconfig, request):
    """Fábrica de "personas": cada llamada devuelve una página en su propio
    contexto de navegador (sesión y cookies separadas, como dos usuarios
    reales en dos máquinas).

    Existe porque los contextos creados a mano con browser.new_context() NO
    heredan la grabación que arma pytest-playwright para la fixture `page`:
    con --video/--tracing, el robot no dejaba ningún artefacto. Acá se leen
    esos flags y se aplican a cada actor, guardando video y traza en
    --output con el nombre del test y del actor.
    """
    video_on = (pytestconfig.getoption("--video") or "off") != "off"
    trace_on = (pytestconfig.getoption("--tracing") or "off") != "off"
    headed = bool(pytestconfig.getoption("--headed"))
    salida = Path(pytestconfig.getoption("--output") or "test-results")
    base = re.sub(r"[^A-Za-z0-9_.-]+", "-", request.node.name)
    creados = []

    def crear(nombre_actor: str):
        kwargs = {}
        if video_on:
            kwargs["record_video_dir"] = str(salida / f"{base}-{nombre_actor}")
        previas = ventanas.ventanas_del_navegador() if headed else set()
        ctx = browser.new_context(**kwargs)
        if trace_on:
            ctx.tracing.start(name=f"{base}-{nombre_actor}", screenshots=True,
                              snapshots=True, sources=True)
        creados.append((nombre_actor, ctx))
        page = ctx.new_page()
        if headed:
            # La ventana se abre DETRÁS de todo y bring_to_front() no alcanza:
            # Windows no deja robar el primer plano. Se la fija SIEMPRE ENCIMA
            # y en su franja de pantalla (ver e2e/ventanas.py). Cada actor
            # ocupa una mitad: se ve el ida y vuelta sin tocar nada.
            hwnd = ventanas.esperar_ventana_nueva(previas)
            ventanas.acomodar(hwnd, len(creados) - 1, total=2)
            try:
                page.bring_to_front()
            except Exception:
                pass
        return page

    yield crear

    for nombre_actor, ctx in creados:
        if trace_on:
            salida.mkdir(parents=True, exist_ok=True)
            ctx.tracing.stop(path=str(salida / f"{base}-{nombre_actor}-trace.zip"))
        ctx.close()   # el video se escribe recién al cerrar el contexto


# ---------------------------------------------------------------------------
# Informe final: cada robot cuenta qué fue haciendo (informe.paso/dato) y al
# terminar la corrida se arma una ficha HTML con el resultado, los pasos, los
# datos que dejó en la app y los videos/trazas. Con --headed se abre sola.
# ---------------------------------------------------------------------------
_INFORMES = {}     # nodeid -> _Informe
_RESULTADOS = {}   # nodeid -> {"estado", "duracion", "error"}


class _Informe:
    def __init__(self, nombre: str):
        self.nombre = nombre
        self.inicio = time.time()
        self.pasos = []      # (segundos, texto)
        self.datos = []      # (clave, valor)

    def paso(self, texto: str):
        """Un hito del guion, con el segundo en que ocurrió."""
        self.pasos.append((time.time() - self.inicio, texto))

    def dato(self, clave: str, valor):
        """Un dato verificable que el robot dejó en la app (ej. el número de
        expediente), para poder ir a mirarlo después."""
        self.datos.append((clave, str(valor)))


@pytest.fixture
def informe(request):
    inf = _Informe(request.node.name)
    _INFORMES[request.node.nodeid] = inf
    return inf


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    reporte = yield
    if reporte.when == "call":
        _RESULTADOS[item.nodeid] = {
            "estado": reporte.outcome,
            "duracion": reporte.duration,
            "error": (str(reporte.longrepr)[-1500:] if reporte.failed else ""),
        }
    return reporte


_PLANTILLA = """<!doctype html>
<meta charset="utf-8"><title>Robots E2E — Mi Trabajo</title>
<style>
 :root {{ --ok:#0d7a5f; --mal:#c0392b; --tinta:#152238; --gris:#5b6478;
         --linea:#e4e7ec; --papel:#f6f7f9; }}
 * {{ box-sizing:border-box; margin:0 }}
 body {{ font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
         background:var(--papel); color:var(--tinta); line-height:1.5; padding:26px 18px 60px }}
 .wrap {{ max-width:840px; margin:0 auto }}
 h1 {{ font-size:26px; letter-spacing:-.01em }}
 .sub {{ color:var(--gris); font-size:13px; margin-top:2px }}
 .totales {{ display:flex; gap:10px; margin:18px 0 22px; flex-wrap:wrap }}
 .caja {{ background:#fff; border:1px solid var(--linea); border-radius:12px;
          padding:12px 16px; min-width:120px }}
 .caja .n {{ font-size:26px; font-weight:700; font-variant-numeric:tabular-nums }}
 .caja .t {{ font-size:10.5px; text-transform:uppercase; letter-spacing:.6px; color:var(--gris); font-weight:700 }}
 .test {{ background:#fff; border:1px solid var(--linea); border-left:5px solid var(--lc);
          border-radius:12px; padding:16px 18px; margin-bottom:14px }}
 .test h2 {{ font-size:17px; display:flex; align-items:center; gap:9px; flex-wrap:wrap }}
 .chip {{ font-size:11px; font-weight:700; padding:2px 10px; border-radius:99px; color:#fff; background:var(--lc) }}
 .dur {{ font-size:12px; color:var(--gris); font-weight:400 }}
 .sec {{ font-size:10.5px; text-transform:uppercase; letter-spacing:.6px;
         color:var(--gris); font-weight:700; margin:15px 0 7px }}
 ol {{ margin:0; padding-left:20px; font-size:13.5px }}
 ol li {{ margin-bottom:5px }}
 ol li span {{ color:var(--gris); font-family:ui-monospace,Consolas,monospace; font-size:11.5px }}
 table {{ border-collapse:collapse; width:100%; font-size:13px }}
 td {{ padding:5px 0; border-bottom:1px solid var(--linea); vertical-align:top }}
 td:first-child {{ color:var(--gris); width:190px }}
 td.v {{ font-family:ui-monospace,Consolas,monospace }}
 a {{ color:#1a3d6b }}
 pre {{ background:#fff5f4; border:1px solid #f0c8c2; border-radius:9px; padding:10px 12px;
        font-size:11.5px; overflow-x:auto; white-space:pre-wrap; color:#8a2b1f }}
 footer {{ color:var(--gris); font-size:11.5px; text-align:center; margin-top:26px }}
</style>
<div class="wrap">
 <h1>Robots E2E — Mi Trabajo</h1>
 <div class="sub">{fecha} · {modo}</div>
 <div class="totales">
  <div class="caja"><div class="n" style="color:{color_total}">{aprobados}/{total}</div><div class="t">Robots en verde</div></div>
  <div class="caja"><div class="n">{duracion:.1f}s</div><div class="t">Duración total</div></div>
 </div>
 {cuerpo}
 <footer>Generado por la flota E2E · e2e/README.md</footer>
</div>
"""


def _bloque_test(nombre, res, inf, artefactos):
    ok = res["estado"] == "passed"
    color = "#0d7a5f" if ok else "#c0392b"
    partes = [f'<div class="test" style="--lc:{color}">',
              f'<h2>{html.escape(nombre)} <span class="chip">'
              f'{"PASÓ" if ok else "FALLÓ"}</span>'
              f'<span class="dur">{res["duracion"]:.1f}s</span></h2>']
    if inf and inf.pasos:
        partes.append('<div class="sec">Lo que hizo</div><ol>')
        for segundos, texto in inf.pasos:
            partes.append(f'<li>{html.escape(texto)} <span>({segundos:.1f}s)</span></li>')
        partes.append("</ol>")
    if inf and inf.datos:
        partes.append('<div class="sec">Lo que dejó en la app</div><table>')
        for clave, valor in inf.datos:
            partes.append(f'<tr><td>{html.escape(clave)}</td>'
                          f'<td class="v">{html.escape(valor)}</td></tr>')
        partes.append("</table>")
    if artefactos:
        partes.append('<div class="sec">Grabaciones</div><table>')
        for etiqueta, ruta in artefactos:
            uri = Path(ruta).resolve().as_uri()
            partes.append(f'<tr><td>{html.escape(etiqueta)}</td>'
                          f'<td><a href="{uri}">{html.escape(Path(ruta).name)}</a></td></tr>')
        partes.append("</table>")
    if not ok and res["error"]:
        partes.append('<div class="sec">Dónde se rompió</div>'
                      f'<pre>{html.escape(res["error"])}</pre>')
    partes.append("</div>")
    return "\n".join(partes)


def pytest_sessionfinish(session, exitstatus):
    if not _RESULTADOS:
        return
    config = session.config
    salida = Path(config.getoption("--output") or "test-results")
    headed = bool(config.getoption("--headed"))
    total = len(_RESULTADOS)
    aprobados = sum(1 for r in _RESULTADOS.values() if r["estado"] == "passed")
    duracion = sum(r["duracion"] for r in _RESULTADOS.values())

    cuerpo = []
    for nodeid, res in _RESULTADOS.items():
        inf = _INFORMES.get(nodeid)
        nombre = inf.nombre if inf else nodeid.split("::")[-1]
        base = re.sub(r"[^A-Za-z0-9_.-]+", "-", nombre)
        artefactos = []
        if salida.exists():
            for ruta in sorted(salida.glob(f"{base}*/*.webm")):
                artefactos.append((f"Video · {ruta.parent.name.split('--')[-1]}", ruta))
            for ruta in sorted(salida.glob(f"{base}*-trace.zip")):
                artefactos.append((f"Traza · {ruta.stem.split('--')[-1].replace('-trace', '')}", ruta))
        cuerpo.append(_bloque_test(nombre, res, inf, artefactos))

    salida.mkdir(parents=True, exist_ok=True)
    destino = salida / "informe.html"
    destino.write_text(_PLANTILLA.format(
        fecha=fechas.ahora().strftime("%d/%m/%Y %H:%M"),
        modo="con ventana visible" if headed else "modo silencioso",
        aprobados=aprobados, total=total, duracion=duracion,
        color_total="#0d7a5f" if aprobados == total else "#c0392b",
        cuerpo="\n".join(cuerpo)), encoding="utf-8")

    # Resumen en la terminal (siempre) + la ficha abierta (solo si mirabas).
    # La consola de Windows usa cp1252: sin esto, cada acento del resumen
    # sale como "?" (mismo problema que resuelven los scripts de la raíz).
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    def escribir(texto):
        codificacion = sys.stdout.encoding or "utf-8"
        print(texto.encode(codificacion, errors="replace").decode(codificacion))

    escribir(f"\n{'=' * 62}\n  RESULTADO: {aprobados}/{total} robots en verde · {duracion:.1f}s")
    for nodeid, res in _RESULTADOS.items():
        inf = _INFORMES.get(nodeid)
        marca = "OK   " if res["estado"] == "passed" else "FALLÓ"
        escribir(f"  {marca} {inf.nombre if inf else nodeid.split('::')[-1]} ({res['duracion']:.1f}s)")
        for segundos, texto in (inf.pasos if inf else []):
            escribir(f"         · {texto}")
        for clave, valor in (inf.datos if inf else []):
            escribir(f"         {clave}: {valor}")
    escribir(f"  Informe: {destino.resolve()}\n{'=' * 62}")
    if headed:
        try:
            webbrowser.open(destino.resolve().as_uri())
        except Exception:
            pass


@pytest.fixture(scope="session")
def entorno_aefip():
    """Garantiza lo que el robot de AEFIP necesita y devuelve los accesos:
    - El sindicato AEFIP con el lote sintético cargado (no lo carga él:
      tarda minutos -- si falta, avisa cómo cargarlo).
    - Un admin de AEFIP (lo crea si no existe; en producción ya existe).
    - El tipo de trámite "Reintegro de guardería" con sus campos.
    - Un trabajador del lote con cuenta (clave = 5 primeros dígitos del CUIL).
    """
    from dotenv import load_dotenv
    load_dotenv(override=True)
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("Sin DATABASE_URL en .env: el E2E necesita el Postgres local (docker compose up -d)")

    import auth
    import db
    from db import Sindicato, UsuarioSindicato, Trabajador, CuentaTrabajador, TipoTramite
    from sqlmodel import select

    with db.get_session() as s:
        sind = s.exec(select(Sindicato).where(Sindicato.nombre.ilike("%AEFIP%"))).first()
        if not sind:
            pytest.skip("AEFIP no está en la base local.")
        sid = sind.id

        admin = s.exec(select(UsuarioSindicato).where(
            UsuarioSindicato.sindicato_id == sid, UsuarioSindicato.activo == True)).first()
        if not admin:
            s.add(UsuarioSindicato(sindicato_id=sid, usuario="20999000019", nombre="Admin AEFIP",
                                   clave_hash=auth.hashear_clave("aefip-demo"),
                                   debe_cambiar_clave=False, es_super_admin=True))
            s.commit()
            admin_usuario, admin_clave = "20999000019", "aefip-demo"
        elif admin.usuario == "20999000019":
            admin_usuario, admin_clave = "20999000019", "aefip-demo"
        else:
            pytest.skip("AEFIP tiene un admin con otra clave: el robot no puede loguearse.")

        if not s.exec(select(TipoTramite).where(TipoTramite.sindicato_id == sid,
                                                TipoTramite.codigo == "AEFIP-GUARD")).first():
            db.crear_tipo_tramite(sid, "Reintegro de guardería", "AEFIP-GUARD", [
                {"etiqueta": "Nombre del hijo/a", "tipo_dato": "texto", "longitud_maxima": 80},
                {"etiqueta": "Edad", "tipo_dato": "numero"},
                {"etiqueta": "Jardín o guardería", "tipo_dato": "texto", "longitud_maxima": 120},
                {"etiqueta": "Monto mensual", "tipo_dato": "numero", "decimales": 2},
            ])

        # Un trabajador del lote: registrado, con cuenta, y cuya clave sea
        # efectivamente la regla del lote (se verifica contra el hash real).
        trabajador = None
        for t in s.exec(select(Trabajador).where(Trabajador.sindicato_id == sid,
                                                 Trabajador.registrado == True,
                                                 Trabajador.activo == True)).all():
            cuenta = s.exec(select(CuentaTrabajador).where(
                CuentaTrabajador.cuil == t.cuil)).first()
            if cuenta and auth.verificar_clave(t.cuil[:5], cuenta.clave_hash):
                trabajador = {"cuil": t.cuil, "clave": t.cuil[:5], "nombre": t.nombre}
                break
        if not trabajador:
            pytest.skip("AEFIP no tiene el lote sintético: correr "
                        "`python cargar_lote_sindicato.py --sindicato AEFIP`.")

    return {"admin": {"usuario": admin_usuario, "clave": admin_clave},
            "trabajador": trabajador}
