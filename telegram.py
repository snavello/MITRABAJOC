"""Avisos por Telegram al equipo: errores no previstos al instante y el
resumen del día. Pedido de Sd (2026-09-23): "algo simple y que no agregue
costos". Telegram tiene una API oficial gratuita que se usa con un solo POST;
WhatsApp exige cuenta de empresa aprobada y cobra por conversación, y los SMS
se pagan uno por uno.

Reglas:
- **Sin librerías**: `urllib` y un POST a `api.telegram.org`. Sin claves en el
  repo: `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` vienen del entorno y se leen
  en cada llamada (así un test puede simularlas). Sin las dos, `configurado()`
  es False y todo lo demás no hace nada, en silencio: igual que Web Push.
- **Nunca lanza y nunca demora un request**: `enviar()` atrapa todo y devuelve
  False; el aviso de error sale en un hilo aparte (`enviar_en_segundo_plano`),
  porque se dispara desde el handler global y una persona está esperando la
  respuesta.
- **Misma política de privacidad que Sentry**: código, referencia de ocho
  caracteres, patrón de ruta, rol y ID del sindicato. Nunca un nombre, un CUIL
  ni el cuerpo de un pedido.
- **Freno por código** (`FRENO_SEGUNDOS`): un error que se repite manda UN
  mensaje cada diez minutos, no uno por request. Vive en memoria del proceso:
  con dos workers pueden salir dos, que es tolerable.
- El texto va en HTML de Telegram (negritas), escapado con `html.escape`.

La regla 0 de observabilidad sigue en pie: si la app está caída no puede
avisar, y para eso Grafana Cloud tiene su propio punto de contacto de Telegram
(`observabilidad/aplicar_grafana.py`), fuera de la app.
"""
import html
import json
import os
import threading
import time
import urllib.request

import fechas

API = "https://api.telegram.org"
FRENO_SEGUNDOS = 600
HORA_RESUMEN_DEFAULT = "21:00"

_candado = threading.Lock()
_ultimo_por_codigo: dict[str, float] = {}


def token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def chat_id() -> str:
    return os.getenv("TELEGRAM_CHAT_ID", "").strip()


def configurado() -> bool:
    return bool(token() and chat_id())


def hora_resumen() -> str:
    """HH:MM de Buenos Aires a la que sale el resumen (TELEGRAM_RESUMEN_HORA)."""
    h = os.getenv("TELEGRAM_RESUMEN_HORA", "").strip()
    if len(h) == 5 and h[2] == ":" and h[:2].isdigit() and h[3:].isdigit() \
            and 0 <= int(h[:2]) < 24 and 0 <= int(h[3:]) < 60:
        return h
    return HORA_RESUMEN_DEFAULT


def estado() -> dict:
    """Lo que la pestaña Observabilidad muestra: si está configurado, a qué chat
    (solo los últimos dígitos) y a qué hora sale el resumen. Sin el token."""
    c = chat_id()
    return {
        "configurado": configurado(),
        "chat_id_oculto": ("…" + c[-3:]) if c else "",
        "hora_resumen": hora_resumen(),
        "freno_minutos": FRENO_SEGUNDOS // 60,
    }


def enviar(texto: str, timeout: int = 6) -> bool:
    """Un mensaje al chat configurado. True si Telegram lo aceptó."""
    if not configurado():
        return False
    datos = json.dumps({"chat_id": chat_id(), "text": texto, "parse_mode": "HTML",
                        "disable_web_page_preview": True}).encode("utf-8")
    pedido = urllib.request.Request(f"{API}/bot{token()}/sendMessage", data=datos,
                                    headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(pedido, timeout=timeout) as r:
            return json.load(r).get("ok") is True
    except Exception as e:                                  # red, 4xx, JSON raro: nunca lanza
        print(f"[telegram] no se pudo mandar: {type(e).__name__}: {e}")
        return False


def enviar_en_segundo_plano(texto: str) -> None:
    threading.Thread(target=enviar, args=(texto,), name="telegram", daemon=True).start()


def frenado(codigo: str, ahora: float = None) -> bool:
    """True si ya salió un aviso de este código hace menos de FRENO_SEGUNDOS.
    Si no, registra este y devuelve False."""
    ahora = time.monotonic() if ahora is None else ahora
    with _candado:
        ultimo = _ultimo_por_codigo.get(codigo)
        if ultimo is not None and ahora - ultimo < FRENO_SEGUNDOS:
            return True
        _ultimo_por_codigo[codigo] = ahora
        return False


def texto_error(codigo: str, ref: str, ruta: str, rol: str, sindicato_id, entorno_nombre: str,
                cuando: str = None) -> str:
    e = html.escape
    return (f"🔴 <b>Error {e(codigo)}</b> en {e(entorno_nombre or '?')}\n"
            f"Ruta: <code>{e(ruta or '(sin ruta)')}</code>\n"
            f"Rol: {e(rol or '—')} · Sindicato: {e(str(sindicato_id) if sindicato_id else '—')}\n"
            f"Ref: <code>{e(ref)}</code>\n"
            f"{e(cuando or fechas.ahora_texto())} · el detalle está en Sentry y en Observación técnica")


def avisar_error(codigo: str, ref: str, ruta: str, rol: str, sindicato_id, entorno_nombre: str) -> bool:
    """Lo llama el handler global (main._capturar_en_sentry). True si se despachó."""
    if not configurado() or frenado(codigo):
        return False
    enviar_en_segundo_plano(texto_error(codigo, ref, ruta, rol, sindicato_id, entorno_nombre))
    return True


def _n(v) -> str:
    return "—" if v is None else f"{v:,}".replace(",", ".")


def texto_resumen(kpis: dict, errores: dict, semaforo: str, entorno_nombre: str, fecha_texto: str,
                  servidor: list = None) -> str:
    """El resumen del día, con lo que ya calcula esquema.py más los errores de
    Sentry y el semáforo de Grafana. `servidor` son las líneas de
    observabilidad/metricas_dia.py (web y base). Solo conteos: nada de personas."""
    e = html.escape
    k = kpis or {}
    l = k.get("en_linea") or {}
    sem = {"verde": "🟢 todo en línea", "amarillo": "🟡 degradado", "rojo": "🔴 con errores",
           "gris": "⚪ sin vigilancia configurada"}.get(semaforo or "", "⚪ sin dato")
    err = errores or {}
    lineas = [
        f"📋 <b>Colm3na · {e(entorno_nombre or '?')} · resumen del {e(fecha_texto)}</b>",
        f"Estado general: {sem}",
        *(servidor or []),
        f"Recibos leídos hoy: <b>{_n(k.get('recibos_hoy'))}</b> (total {_n(k.get('recibos_total'))})",
        f"Lecturas de IA hoy: {_n(k.get('lecturas_hoy'))} · US$ {k.get('costo_hoy_usd', 0):.2f}",
        (f"Ingresos en los últimos {k.get('minutos_en_linea', 15)} min: {_n(k.get('en_linea_total'))} "
         f"(afiliados {_n(l.get('trabajador', 0))} · gremio {_n(l.get('admin', 0))} · "
         f"empresa {_n(l.get('empresa', 0))} · plataforma {_n(l.get('plataforma', 0))})"),
        f"Trámites abiertos: {_n(k.get('tramites_abiertos'))} · sin respuesta del gremio: {_n(k.get('tramites_esperan'))}",
        f"Afiliados registrados: {_n(k.get('registrados'))} de {_n(k.get('padron'))} ({k.get('porcentaje_registrados', 0)}%)",
        f"Sindicatos activos: {_n(len(k.get('sindicatos') or []))}",
        (f"Errores en Sentry: {_n(err.get('errores_24h'))} en 24 h · {_n(err.get('errores_7d'))} en 7 días"
         if err else "Errores en Sentry: sin dato"),
    ]
    return "\n".join(lineas)
