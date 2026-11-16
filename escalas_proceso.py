# -*- coding: utf-8 -*-
"""La actualización automática de la grilla salarial: buscar, leer, controlar,
publicar y avisar (PLAN_CONVENIO_ESCALAS.md, D9, D19, D20, D23).

Una pasada hace, en orden:

1. **Buscar** en labancaria.org (`escalas_fuente`) las notas de grillas y los
   comunicados, y guardar lo visto (`db.EscalaNovedad`).
2. **Aparear** cada nota de grillas con su comunicado: el período de la grilla
   es el MES del comunicado (la nota del 20-10-26 es septiembre).
3. **Leer** el PDF dos veces con la IA (`escalas_lectura`), solo si la nota es
   de un mes POSTERIOR al de la grilla vigente y no se leyó antes.
4. **Controlar** (`escalas_controles`, C1 a C6).
5. **Publicar** si pasan los seis; si falla alguno, **retener** con el detalle.
   En los dos casos avisa por Telegram. Una grilla que no pasa nunca queda
   publicada: antes de escribir se vuelve a exigir `todos_pasan` y la forma.

Reglas que importan:
- **No gasta IA de más**: una nota con una grilla de cualquier estado, o que ya
  agotó sus intentos, no se vuelve a leer; el derecho a leer se reclama con un
  INSERT condicional (`db.reclamar_lectura`), así que dos instancias (o el botón
  «Buscar ahora» y una pasada) no leen la misma nota a la vez.
- **Un salto de período no se lee**: si llegó la nota de octubre y falta la de
  septiembre, no se gasta IA en una grilla que C6 va a retener; se avisa una vez.
- **Nunca tumba el arranque ni el hilo**: todo atrapa y avisa.
- **Hilo diario** (patrón de `resumen_diario.py`): prendido SOLO con
  `ESCALAS_AUTO=1` y en el entorno `pruebas`; pasadas a las horas de
  `ESCALAS_HORAS` (default «10:00,16:00», hora de Buenos Aires). Cada pasada se
  reclama con `db.reclamar_aviso_diario` (clave por fecha y hora).
- Los avisos de problema salen UNA vez por día y causa (mismo candado).
"""
import html
import math
import os
import threading
import time
import traceback
from datetime import timedelta

import db
import escalas_controles as ctl
import escalas_fuente as fuente
import escalas_lectura as lectura
import fechas
import telegram

CONVENIO = db.CONVENIO_BANCARIO
HORAS_DEFAULT = "10:00,16:00"
DIA_ALERTA_FALTA = 21
INTERVALO_SEGUNDOS = 60
CLAVE_PASADA = "escalas-pasada"
HERRAMIENTA = "escalas"          # CasoHerramienta.herramienta de los ensayos

_hilo = None
_candado = threading.Lock()


# ---------------------------------------------------------------- configuración del hilo
def horas() -> list:
    """Las horas HH:MM de Buenos Aires de las pasadas (ESCALAS_HORAS). Una hora
    mal escrita se ignora; sin ninguna válida, las de siempre."""
    ok = []
    for h in os.getenv("ESCALAS_HORAS", "").split(","):
        h = h.strip()
        if len(h) == 5 and h[2] == ":" and h[:2].isdigit() and h[3:].isdigit() \
                and 0 <= int(h[:2]) < 24 and 0 <= int(h[3:]) < 60:
            ok.append(h)
    return sorted(set(ok)) or HORAS_DEFAULT.split(",")


def debe_correr(entorno_actual: str) -> tuple:
    if os.getenv("ESCALAS_AUTO", "").strip() != "1":
        return False, "falta ESCALAS_AUTO=1"
    if entorno_actual != "pruebas":
        return False, f"solo corre en Pruebas (esto es {entorno_actual or 'sin entorno'})"
    return True, ""


def pasada_que_toca(ahora, lista: list = None) -> str | None:
    """La hora (HH:MM) de la pasada que corresponde AHORA: la última de las
    configuradas que ya llegó hoy. Si el proceso estuvo caído y despierta a las
    17:00, es la de las 16:00 (no se corren dos seguidas)."""
    hm = ahora.strftime("%H:%M")
    llegadas = [h for h in (lista or horas()) if hm >= h]
    return llegadas[-1] if llegadas else None


# ---------------------------------------------------------------- avisos
def _avisar(texto: str) -> None:
    try:
        telegram.enviar_en_segundo_plano(texto)
    except Exception as e:
        print(f"[escalas] no se pudo avisar: {type(e).__name__}: {e}")


def _avisar_una_vez(causa: str, cuando: str, texto: str) -> bool:
    """Un aviso de problema por causa y por `cuando` (fecha o período): la misma
    falla no manda un mensaje en cada pasada."""
    try:
        if db.reclamar_aviso_diario(f"escalas-aviso-{causa}", cuando):
            _avisar(texto)
            return True
    except Exception as e:
        print(f"[escalas] no se pudo reclamar el aviso {causa}: {type(e).__name__}: {e}")
    return False


def _t(x) -> str:
    return html.escape(str(x))


def texto_publicada(periodo: str, resultados: list) -> str:
    return (f"📈 <b>Grilla salarial de {_t(fuente.nombre_del_periodo(periodo))} publicada</b>\n"
            f"Pasaron los seis controles (doble lectura, estructura, anclas, factor, coherencia y período). "
            f"La Calculadora bancaria ya la usa.")


def texto_retenida(periodo: str, resultados: list, grilla_id: int) -> str:
    malos = ", ".join(f"{r['control']} {r['nombre']}" for r in resultados if r.get("pasa") is not True)
    return (f"⚠️ <b>Grilla salarial de {_t(fuente.nombre_del_periodo(periodo))} RETENIDA</b>\n"
            f"No pasó: {_t(malos)}. La vigente sigue siendo la anterior. "
            f"Se resuelve en /entornos → Herramientas → Convenio y escalas → Estado (grilla #{grilla_id}).")


# ---------------------------------------------------------------- piezas
def _registrar_usos(usos: list) -> None:
    for u in usos or []:
        try:
            db.registrar_uso_ia(None, "", "herramienta", u["modelo"], u["tokens_entrada"], u["tokens_salida"],
                                u.get("duracion_ms", 0), u.get("tokens_cache_lectura", 0), u.get("tokens_cache_escritura", 0))
        except Exception as e:
            print(f"[escalas] no se registró un uso de IA: {type(e).__name__}: {e}")


def _refrescar_calculadora() -> None:
    """Después de publicar: la Calculadora de ESTE proceso pasa a la grilla nueva
    sin esperar la revisión por sello (los otros procesos la ven por el sello)."""
    try:
        import grilla_bancaria
        publicadas = db.grillas_publicadas(CONVENIO)
        if publicadas:
            grilla_bancaria.registrar(publicadas)
    except Exception as e:
        print(f"[escalas] no se refrescó la calculadora ({type(e).__name__}: {e})")


def armar_contenido(datos: dict, periodo: str, firmada: str, fuentes: list, modelo: str, hoy: str) -> dict:
    """La grilla con la forma de data/grillas_bancarias/AAAA-MM.json: los datos
    leídos más los metadatos, que los pone el proceso y no la IA."""
    return {"periodo": periodo, "nombre": fuente.nombre_del_periodo(periodo), "firmada": firmada,
            "fuentes": [u for u in fuentes if u],
            "transcripta": f"{hoy}, leída por IA ({modelo}) dos veces y controlada por el sistema (ver los controles de la grilla)",
            **datos}


def _datos_comunicado(c: dict | None) -> dict | None:
    if not c:
        return None
    return {k: c.get(k) for k in ("inicial", "roe", "total", "porcentaje", "dia_bancario_minimo", "periodo", "publicada", "url")}


def _resumen_usos(usos: list) -> dict:
    return {"llamadas": len(usos), "tokens_entrada": sum(u.get("tokens_entrada", 0) for u in usos),
            "tokens_salida": sum(u.get("tokens_salida", 0) for u in usos)}


def guardar_resultado(par: dict, lecturas: list, usos: list, modelo: str, previa: dict, vigente_periodo: str,
                      tolerancias: dict = None, hoy: str = "") -> dict:
    """Controla las lecturas y guarda la grilla: publicada si pasan los seis,
    retenida si no. Devuelve {"grilla_id", "estado", "controles"}."""
    periodo, g, c = par["periodo"], par["grilla"], par["comunicado"]
    com = _datos_comunicado(c)
    resultados = ctl.controlar(lecturas, previa, com, periodo, vigente_periodo, tolerancias)
    datos = lecturas[0]["contenido"]
    contenido = armar_contenido(datos, periodo, g["fecha"], [g["url"], c["url"] if c else ""], modelo, hoy or fechas.hoy_texto())
    controles = {"resultados": resultados, "periodo_impreso": lecturas[0].get("periodo_impreso"),
                 "notas_lectura": [n for l in lecturas for n in l.get("notas", [])], "modelo": modelo,
                 "ia": _resumen_usos(usos), "comunicado": com, "medidas_c4": next((r.get("medidas") for r in resultados if r["control"] == "C4"), None)}
    if not ctl.todos_pasan(resultados):
        # Para decidir a mano hace falta lo que leyó la segunda lectura.
        controles["lectura_b"] = lecturas[1]["contenido"] if len(lecturas) > 1 else None
    # Última guarda: aunque algo de arriba cambie, una grilla sin los seis controles
    # o con la forma rota NO se publica.
    puede = ctl.todos_pasan(resultados) and not ctl.forma_valida(contenido)
    estado = "publicada" if puede else "retenida"
    grilla_id = db.guardar_grilla(
        periodo, contenido, estado=estado, origen="automatica", controles=controles,
        fuente_nota=g["url"], fuente_pdf=g["pdf_url"], publicada_sindicato=g["fecha"],
        quien="automático" if puede else "",
        nota="" if puede else "Retenida: " + ", ".join(ctl.fallan(resultados)))
    if puede:
        _refrescar_calculadora()
    return {"grilla_id": grilla_id, "estado": estado, "controles": resultados}


# ---------------------------------------------------------------- la pasada
def procesar_par(par: dict, vigente: dict, vigente_periodo: str, forzar: bool = False, ahora=None) -> dict:
    """Lee y guarda UNA grilla (un par nota-comunicado). Devuelve
    {"estado": ..., "motivo": ...}; nunca levanta."""
    g, c, periodo = par["grilla"], par["comunicado"], par["periodo"]
    hoy = (ahora or fechas.ahora()).strftime("%Y-%m-%d")
    intento = db.reclamar_lectura(g["post_id"], CONVENIO, forzar=forzar)
    if not intento:
        return {"estado": "omitida", "motivo": "otra instancia la está leyendo o agotó sus intentos"}
    modelo = db.modelo_ia("grilla_salarial")
    usos = []
    try:
        pdf = fuente.descargar_pdf(g["pdf_url"])
        lecturas = lectura.leer(pdf, lectura.plantilla_sin_importes(vigente), modelo)
        for l in lecturas:
            usos.extend(l["usos"])
        _registrar_usos(usos)
        r = guardar_resultado(par, lecturas, usos, modelo, vigente, vigente_periodo, hoy=hoy)
    except lectura.ErrorLectura as e:
        _registrar_usos(e.usos)
        return _fallo(g, periodo, f"la lectura falló: {e}", hoy)
    except fuente.ErrorFuente as e:
        return _fallo(g, periodo, f"no se pudo bajar el PDF: {e}", hoy)
    except Exception as e:
        traceback.print_exc()
        return _fallo(g, periodo, f"error inesperado ({type(e).__name__}: {e})", hoy)
    db.marcar_novedad("grillas", g["post_id"], CONVENIO, resultado=r["estado"], grilla_id=r["grilla_id"], ultimo_error="")
    if r["estado"] == "publicada":
        _avisar(texto_publicada(periodo, r["controles"]))
    else:
        _avisar(texto_retenida(periodo, r["controles"], r["grilla_id"]))
    return {"estado": r["estado"], "grilla_id": r["grilla_id"], "periodo": periodo,
            "fallan": ctl.fallan(r["controles"])}


def _fallo(g: dict, periodo: str, motivo: str, hoy: str) -> dict:
    try:
        db.marcar_novedad("grillas", g["post_id"], CONVENIO, resultado="error", ultimo_error=motivo[:500])
    except Exception:
        pass
    _avisar_una_vez(f"lectura-{g['post_id']}", hoy,
                    f"🔴 <b>Grilla salarial de {_t(fuente.nombre_del_periodo(periodo))}: no se pudo cargar</b>\n"
                    f"{_t(motivo[:400])}\nNo se publicó nada; la vigente sigue siendo la anterior.")
    return {"estado": "error", "motivo": motivo, "periodo": periodo}


def _persistir_lo_visto(res: dict) -> None:
    items = []
    for c in res["comunicados"]:
        items.append({"tipo": "comunicado", "post_id": c["post_id"], "titulo": c["titulo"], "url": c["url"],
                      "publicada": c["publicada"], "periodo": c["periodo"],
                      "datos": {k: c.get(k) for k in ("porcentaje", "inicial", "roe", "total", "dia_bancario_minimo", "motivo")}})
    periodos = {p["grilla"]["post_id"]: p["periodo"] for p in res["pares"]}
    for g in res["grillas"]:
        items.append({"tipo": "grillas", "post_id": g["post_id"], "titulo": g["titulo"], "url": g["url"],
                      "publicada": g["publicada"], "periodo": periodos.get(g["post_id"]) or "",
                      "datos": {"pdf_url": g["pdf_url"], "fecha": g["fecha"], "motivo": g["motivo"]}})
    db.guardar_novedades(items, CONVENIO)


def pasada(ahora=None, forzar_periodo: str = None) -> dict:
    """UNA pasada completa. `forzar_periodo` (la lectura que pide una persona con
    «Buscar ahora») vuelve a leer ESA nota aunque ya tenga una grilla o haya
    agotado los intentos. Devuelve un resumen; nunca levanta."""
    ahora = ahora or fechas.ahora()
    hoy = ahora.strftime("%Y-%m-%d")
    resumen = {"ok": True, "motivo": "", "leidas": [], "mensajes": []}
    try:
        res = fuente.listar_novedades()
        if not res.get("ok"):
            resumen.update(ok=False, motivo=res.get("motivo", "sin respuesta"))
            _avisar_una_vez("fuente", hoy, f"🔴 <b>Grillas salariales: no se pudo consultar labancaria.org</b>\n"
                                           f"{_t(resumen['motivo'])}\nNo se publicó nada.")
            return resumen
        _persistir_lo_visto(res)
        vigente_periodo = db.periodo_vigente(CONVENIO)
        if not vigente_periodo:
            resumen.update(ok=False, motivo="no hay una grilla vigente de la cual partir")
            return resumen
        pares = [p for p in res["pares"] if p["periodo"] and p["comunicado"]]
        pares.sort(key=lambda p: p["periodo"])
        reciente = (ahora.date() - timedelta(days=45)).isoformat()
        for p in res["pares"]:
            if not p["periodo"] and p["grilla"]["publicada"] >= reciente:
                resumen["mensajes"].append(f"{p['grilla']['titulo']}: {p['motivo']}")
        for par in pares:
            periodo = par["periodo"]
            forzar = bool(forzar_periodo and forzar_periodo == periodo)
            if periodo <= vigente_periodo and not forzar:
                continue
            existentes = db.grillas_de_la_nota(par["grilla"]["url"], CONVENIO)
            if existentes and not forzar:
                continue
            esperado = fuente.mes_siguiente(vigente_periodo)
            if periodo != esperado and not forzar:
                db.marcar_novedad("grillas", par["grilla"]["post_id"], CONVENIO, resultado="salto")
                _avisar_una_vez(f"salto-{periodo}", periodo,
                                f"⚠️ <b>Grillas salariales: falta un mes</b>\nLa vigente es {_t(vigente_periodo)} y llegó la de "
                                f"{_t(periodo)}: falta la de {_t(esperado)}. No se leyó nada; cargala a mano.")
                resumen["mensajes"].append(f"{periodo}: salto (falta {esperado})")
                break
            if not par["grilla"]["pdf_url"]:
                _fallo(par["grilla"], periodo, f"la nota no trae un PDF utilizable ({par['grilla']['motivo']})", hoy)
                resumen["mensajes"].append(f"{periodo}: sin PDF utilizable")
                continue
            if par["comunicado"].get("motivo") or not par["comunicado"].get("inicial"):
                _fallo(par["grilla"], periodo, f"no se pudo leer el comunicado ({par['comunicado'].get('motivo')})", hoy)
                resumen["mensajes"].append(f"{periodo}: comunicado ilegible")
                continue
            ok, motivo = lectura.disponible()
            if not ok:
                _avisar_una_vez("sin-ia", hoy, f"⚠️ <b>Grillas salariales: hay una grilla nueva pero no se puede leer</b>\n{_t(motivo)}")
                resumen["mensajes"].append(f"{periodo}: {motivo}")
                break
            vigente = db.grilla_publicada(vigente_periodo, CONVENIO)
            if not vigente:
                break
            r = procesar_par(par, vigente, vigente_periodo, forzar=forzar, ahora=ahora)
            resumen["leidas"].append({"periodo": periodo, **r})
            if r["estado"] == "publicada":
                vigente_periodo = periodo
            else:
                break                       # lo que sigue depende de esta: no se lee encima de una retenida
        _alertar_si_falta(ahora, vigente_periodo, resumen)
    except Exception as e:
        traceback.print_exc()
        resumen.update(ok=False, motivo=f"error inesperado ({type(e).__name__}: {e})")
        _avisar_una_vez("pasada", hoy, f"🔴 <b>Grillas salariales: falló la pasada</b>\n{_t(resumen['motivo'])}")
    return resumen


def _alertar_si_falta(ahora, vigente_periodo: str, resumen: dict) -> None:
    """Desde el día 21, si no hay grilla del mes que ya debería haber salido
    (el comunicado de un mes sale entre el 11 y el 20 del siguiente), avisa UNA
    vez por mes esperado."""
    if ahora.day < DIA_ALERTA_FALTA:
        return
    a, m = ahora.year, ahora.month
    esperado = f"{a - 1:04d}-12" if m == 1 else f"{a:04d}-{m - 1:02d}"
    if vigente_periodo < esperado:
        if _avisar_una_vez("falta", esperado,
                           f"⚠️ <b>Grillas salariales: no se encontró la de {_t(fuente.nombre_del_periodo(esperado))}</b>\n"
                           f"Ya pasó el día {DIA_ALERTA_FALTA} y la vigente sigue siendo {_t(vigente_periodo)}."):
            resumen["mensajes"].append(f"aviso: falta la grilla de {esperado}")


def intentar(ahora=None) -> dict | None:
    """Un ciclo del hilo: si toca una pasada y nadie la reclamó, la hace."""
    ahora = ahora or fechas.ahora()
    slot = pasada_que_toca(ahora)
    if not slot:
        return None
    if not db.reclamar_aviso_diario(CLAVE_PASADA, f"{ahora.strftime('%Y-%m-%d')} {slot}"):
        return None
    r = pasada(ahora)
    print(f"[escalas] pasada {ahora.strftime('%Y-%m-%d')} {slot}: ok={r['ok']} leidas={len(r['leidas'])} {r['motivo']}")
    return r


def _bucle(intervalo: int) -> None:
    while True:
        try:
            intentar()
        except Exception:
            traceback.print_exc()
        time.sleep(intervalo)


def arrancar(entorno_actual: str, intervalo: int = INTERVALO_SEGUNDOS) -> bool:
    """Lanza el hilo una sola vez. Devuelve True si arrancó. No arranca fuera de
    Pruebas ni sin ESCALAS_AUTO=1, y nunca levanta."""
    global _hilo
    ok, motivo = debe_correr(entorno_actual)
    if not ok:
        print(f"[escalas] el hilo no arranca: {motivo}")
        return False
    with _candado:
        if _hilo is not None and _hilo.is_alive():
            return False
        _hilo = threading.Thread(target=_bucle, args=(intervalo,), name="escalas-grillas", daemon=True)
        _hilo.start()
    print(f"[escalas] hilo en marcha: pasadas a las {', '.join(horas())} de Buenos Aires")
    return True


# ---------------------------------------------------------------- corregir una retenida
VALOR_MAXIMO_CORRECCION = 1e10          # ningún importe de la grilla se le acerca (el mayor ronda los 6e6)


def _cambios_validos(contenido: dict, cambios: list) -> dict:
    """Aplica las correcciones sobre una copia. Solo se corrige una celda que YA existe y es
    una hoja numérica (o vacía) del contenido: no se crea estructura, no se pisa un nodo con
    hijos ni un texto (nombres de categorías, meses de la conectividad, tramos de ROE)."""
    nuevo = contenido
    for c in cambios:
        if not isinstance(c, dict):
            raise ValueError("cada corrección tiene que ser un objeto con la ruta y el valor de la celda")
        ruta, valor = c.get("ruta"), c.get("valor")
        if not isinstance(ruta, str) or not ruta:
            raise ValueError("una corrección no trae la ruta de la celda")
        if valor is not None:
            if isinstance(valor, bool) or not isinstance(valor, (int, float)):
                raise ValueError(f"{ruta}: el valor tiene que ser un número (o vacío)")
            if not math.isfinite(valor) or not 0 < valor < VALOR_MAXIMO_CORRECCION:
                raise ValueError(f"{ruta}: el valor tiene que ser un importe mayor que cero y razonable")
        if ruta.split(".")[0] not in ctl.CLAVES_DATOS:
            raise ValueError(f"{ruta}: solo se corrigen celdas de la grilla, no los metadatos")
        hojas = ctl.plano(nuevo)
        actual = hojas.get(ruta, _NO_EXISTE)
        if actual is _NO_EXISTE or not (actual is None or (isinstance(actual, (int, float)) and not isinstance(actual, bool))):
            raise ValueError(f"{ruta}: la celda no existe o no es un importe")
        try:
            nuevo = ctl.asignar(nuevo, ruta, None if valor is None else round(float(valor), 2))
        except (KeyError, IndexError, ValueError) as e:
            raise ValueError(f"{ruta}: la celda no existe") from e
    return nuevo


_NO_EXISTE = object()


def recontrolar(contenido: dict, controles_previos: dict, periodo: str, quien: str, tolerancias: dict = None) -> list:
    """Vuelve a pasar los controles que NO dependen de la doble lectura sobre una
    grilla corregida a mano (C1, C3, C4, C5, C6); C2 queda como «resuelta a mano»
    (`pasa: None`) con quién la resolvió. Los datos que hacen falta (el
    comunicado, la grilla anterior) salen de lo guardado."""
    vigente_periodo = db.periodo_vigente(CONVENIO)
    previa = db.grilla_publicada(vigente_periodo, CONVENIO) if vigente_periodo else None
    # Si ya está publicada la del mismo período (se está reemplazando), la anterior es la del mes previo.
    if vigente_periodo and vigente_periodo >= periodo:
        anterior = [p for p in sorted(db.grillas_publicadas(CONVENIO)) if p < periodo]
        vigente_periodo = anterior[-1] if anterior else None
        previa = db.grilla_publicada(vigente_periodo, CONVENIO) if vigente_periodo else None
    com = (controles_previos or {}).get("comunicado")
    datos = {k: contenido.get(k) for k in ctl.CLAVES_DATOS}
    lect = {"contenido": datos, "notas": [], "periodo_impreso": (controles_previos or {}).get("periodo_impreso")}
    resultados = ctl.controlar([lect, lect], previa, com, periodo, vigente_periodo, tolerancias)
    resultados[1] = {"control": "C2", "nombre": "Doble lectura", "pasa": None,
                     "resumen": f"Resuelta a mano por {quien}: la corrección reemplaza a la doble lectura.", "detalle": [], "mas": 0}
    return resultados


def corregir(grilla_id: int, cambios: list, quien: str, nota: str = "") -> dict:
    """Aplica las correcciones de celdas a una retenida y vuelve a controlar. Devuelve
    {"ok", "controles"} o levanta ValueError con el motivo."""
    g = db.grilla_completa(grilla_id)
    if not g or g["estado"] != "retenida":
        raise ValueError("la grilla no existe o ya no está retenida")
    contenido = _cambios_validos(g["contenido"], cambios)
    controles = dict(g["controles"] or {})
    resultados = recontrolar(contenido, controles, g["periodo"], quien)
    controles["resultados"] = resultados
    controles.setdefault("correcciones", []).append(
        {"quien": quien, "cuando": fechas.ahora_con_segundos(), "celdas": [c["ruta"] for c in cambios], "nota": nota})
    if not db.corregir_grilla_retenida(grilla_id, contenido, controles, quien, nota):
        raise ValueError("la grilla ya no está retenida")
    return {"ok": True, "controles": resultados}


def publicar_a_mano(grilla_id: int, quien: str, nota: str = "") -> dict:
    """Publica una retenida. Exige la forma válida SIEMPRE; si algún control (salvo
    C2, que una persona reemplaza) no pasa, exige una nota que diga por qué se
    publica igual. Devuelve {"ok", "forzada"} o levanta ValueError."""
    g = db.grilla_completa(grilla_id)
    if not g or g["estado"] != "retenida":
        raise ValueError("la grilla no existe o ya no está retenida")
    problemas = ctl.forma_valida(g["contenido"])
    if problemas:
        raise ValueError("la grilla no tiene la forma que necesita la calculadora: " + "; ".join(problemas[:4]))
    resultados = (g["controles"] or {}).get("resultados") or []
    fallan = [r["control"] for r in resultados if r.get("control") != "C2" and r.get("pasa") is not True and r.get("pasa") is not None]
    sin_c2_resuelto = any(r.get("control") == "C2" and r.get("pasa") is False for r in resultados)
    forzada = bool(fallan or sin_c2_resuelto)
    if forzada and not (nota or "").strip():
        raise ValueError("hay controles que no pasan (" + ", ".join(fallan + (["C2"] if sin_c2_resuelto else []))
                         + "): escribí por qué la publicás igual")
    if not db.publicar_grilla(grilla_id, quien, (nota or "").strip() + (" [publicada con controles sin pasar]" if forzada else "")):
        raise ValueError("la grilla ya no está retenida")
    _refrescar_calculadora()
    _avisar(f"📈 Grilla salarial de {_t(fuente.nombre_del_periodo(g['periodo']))} publicada a mano por {_t(quien)}"
            + (" (con controles sin pasar)." if forzada else "."))
    return {"ok": True, "forzada": forzada}


# ---------------------------------------------------------------- ensayo de lectura
def ensayo(periodo: str, quien: str, ahora=None) -> dict:
    """Lee la nota de un período que YA tiene grilla publicada y compara celda por
    celda contra la publicada, SIN publicar ni escribir ninguna grilla. Es la
    medida de cuánto se puede confiar en la lectura (el bloque 6 lo corre con
    agosto de 2026 contra la transcripta a mano). Gasta IA y lo registra; el
    resultado queda en un `CasoHerramienta` (herramienta «escalas»). Devuelve el
    caso o levanta ValueError con el motivo."""
    publicada = db.grilla_publicada(periodo, CONVENIO)
    if not publicada:
        raise ValueError(f"no hay una grilla publicada de {periodo} con qué comparar")
    ok, motivo = lectura.disponible()
    if not ok:
        raise ValueError(f"no se puede leer: {motivo}")
    res = fuente.listar_novedades()
    if not res.get("ok"):
        raise ValueError(f"no se pudo consultar labancaria.org: {res.get('motivo')}")
    par = next((p for p in res["pares"] if p["periodo"] == periodo), None)
    if not par or not par["comunicado"]:
        raise ValueError(f"el sitio no tiene una nota de grillas con su comunicado para {periodo}")
    if not par["grilla"]["pdf_url"]:
        raise ValueError(f"la nota no trae un PDF utilizable ({par['grilla']['motivo']})")
    modelo = db.modelo_ia("grilla_salarial")
    inicio = time.perf_counter()
    usos = []
    try:
        pdf = fuente.descargar_pdf(par["grilla"]["pdf_url"])
        lecturas = lectura.leer(pdf, lectura.plantilla_sin_importes(publicada), modelo)
    except lectura.ErrorLectura as e:
        _registrar_usos(e.usos)
        raise ValueError(f"la lectura falló: {e}") from e
    except fuente.ErrorFuente as e:
        raise ValueError(f"no se pudo bajar el PDF: {e}") from e
    for l in lecturas:
        usos.extend(l["usos"])
    _registrar_usos(usos)
    anterior = [p for p in sorted(db.grillas_publicadas(CONVENIO)) if p < periodo]
    vig = anterior[-1] if anterior else None
    previa = db.grilla_publicada(vig, CONVENIO) if vig else None
    com = _datos_comunicado(par["comunicado"])
    resultados = ctl.controlar(lecturas, previa, com, periodo, vig)
    comp = [ctl.comparar_con_publicada(l["contenido"], publicada) for l in lecturas]
    distintas = max(c["distintas"] for c in comp)
    caso_id = db.guardar_caso_herramienta(
        herramienta=HERRAMIENTA, quien=quien, grilla=periodo, banco="", nota="",
        entrada={"periodo": periodo, "nota": par["grilla"]["url"], "pdf": par["grilla"]["pdf_url"], "modelo": modelo,
                 "tolerancias": ctl.TOLERANCIAS},
        esperado={"celdas": comp[0]["celdas"], "origen": "grilla publicada (transcripta a mano)"},
        real={"lectura_a": {"distintas": comp[0]["distintas"]}, "lectura_b": {"distintas": comp[1]["distintas"]},
              "ia": _resumen_usos(usos), "segundos": round(time.perf_counter() - inicio, 1),
              "notas": [n for l in lecturas for n in l["notas"]], "periodo_impreso": [l["periodo_impreso"] for l in lecturas]},
        diferencias={"lectura_a": comp[0], "lectura_b": comp[1], "controles": resultados},
        distintos=distintas)
    return {"caso_id": caso_id, "periodo": periodo, "celdas": comp[0]["celdas"], "distintas_a": comp[0]["distintas"],
            "distintas_b": comp[1]["distintas"], "controles": resultados, "ia": _resumen_usos(usos),
            "lectura_a": comp[0], "lectura_b": comp[1]}


# ---------------------------------------------------------------- tareas largas desde la vista
_TAREAS = {"actual": None}
_candado_tarea = threading.Lock()


def tarea_actual() -> dict | None:
    """Lo que está corriendo (o terminó hace poco) en ESTE proceso: una lectura
    tarda minutos y no cabe en un pedido HTTP. Es solo para mostrar el avance;
    el resultado verdadero queda en la base."""
    return dict(_TAREAS["actual"]) if _TAREAS["actual"] else None


def lanzar(nombre: str, funcion, *args, **kwargs) -> bool:
    """Corre `funcion` en un hilo y deja el resultado en `tarea_actual()`. Una sola
    a la vez por proceso (cada una gasta IA); False si ya hay una corriendo."""
    with _candado_tarea:
        t = _TAREAS["actual"]
        if t and t["estado"] == "corriendo":
            return False
        _TAREAS["actual"] = {"nombre": nombre, "estado": "corriendo", "desde": fechas.ahora_con_segundos(),
                             "resultado": None, "error": ""}

    def _correr():
        try:
            r = funcion(*args, **kwargs)
            _TAREAS["actual"].update(estado="terminada", resultado=r if isinstance(r, dict) else None,
                                     hasta=fechas.ahora_con_segundos())
        except Exception as e:
            _TAREAS["actual"].update(estado="error", error=f"{type(e).__name__}: {e}", hasta=fechas.ahora_con_segundos())

    threading.Thread(target=_correr, name=f"escalas-{nombre}", daemon=True).start()
    return True
