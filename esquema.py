"""Los indicadores de la Sala de mando (`/entornos/esquema`): el esquema
físico de la plataforma con los números reales del entorno que lo sirve.

Pedido de Sd (2026-09-21): el esquema en papel pasó a HTML y después a una
pieza de venta ("command center"); las cifras de negocio de arriba tienen
que salir de la base, no estar escritas. Este módulo calcula esas cifras.

Reglas:
- **Todo en SQL agrupado**, mismo criterio que `dashboard.py` y
  `db.actividad_resumen()`: nunca se traen filas crudas para contar en
  Python. La única lista que se recorre es la de lecturas de IA de HOY (para
  costear cada una con su precio congelado), que son decenas, no miles.
- **Recibe la sesión, no la abre** (regla de una sesión por request,
  2026-09-19): quien llama abre `db.get_session()` y la pasa.
- "Usuarios en línea" es una aproximación honesta: los logins de los
  últimos 15 minutos (`auth.IDLE_TIMEOUT_SEGUNDOS`, lo que dura una sesión
  sin actividad). No hay registro de cada request, así que no hay forma de
  saber quién sigue mirando la pantalla; la tarjeta lo dice.
- Las fechas se comparan como texto "AAAA-MM-DD HH:MM" en hora de Buenos
  Aires (`fechas.py`), igual que en toda la app.
"""
from datetime import timedelta

from sqlalchemy import text

import auth
import fechas
import precios_ia

# Los tres tipos de lectura que el panel "Uso de IA" cuenta como gasto de
# recibos (el bot del convenio y el Asistente no registran ahí).
TIPOS_LECTURA = ("recibo", "aportes", "aprendizaje")


def kpis(s, ahora=None) -> dict:
    """Los indicadores de negocio del entorno, con la sesión que se recibe."""
    ahora = ahora or fechas.ahora()
    hoy = ahora.strftime("%Y-%m-%d")
    hace_sesion = (ahora - timedelta(seconds=auth.IDLE_TIMEOUT_SEGUNDOS)).strftime("%Y-%m-%d %H:%M")

    def uno(sql: str, **p) -> int:
        return int(s.execute(text(sql), p).one()[0] or 0)

    recibos_total = uno("SELECT COUNT(*) FROM reciboverificado")
    recibos_hoy = uno("SELECT COUNT(*) FROM reciboverificado WHERE procesado_en LIKE :d", d=hoy + "%")

    tipos = ", ".join(f"'{t}'" for t in TIPOS_LECTURA)   # constantes del módulo, no entrada de usuario
    lecturas = s.execute(text(
        "SELECT modelo, tokens_entrada, tokens_salida, precio_entrada, precio_salida "
        f"FROM usoia WHERE fecha >= :d AND tipo IN ({tipos})"
    ), {"d": hoy}).all()
    costo_hoy = 0.0
    for modelo, t_in, t_out, p_in, p_out in lecturas:
        if p_in or p_out:
            costo_hoy += precios_ia.costo(t_in or 0, t_out or 0, p_in or 0.0, p_out or 0.0)
        else:
            costo_hoy += precios_ia.costo_estimado(modelo or "", t_in or 0, t_out or 0) or 0.0

    en_linea = {rol: int(n or 0) for rol, n in s.execute(text(
        "SELECT rol, COUNT(*) FROM accesolog WHERE fecha >= :d GROUP BY rol"), {"d": hace_sesion}).all()}

    tramites_abiertos = uno("SELECT COUNT(*) FROM tramite WHERE estado <> 'terminado'")
    tramites_esperan = uno("SELECT COUNT(*) FROM tramite WHERE estado = 'iniciado'")

    sindicatos = [n for (n,) in s.execute(text(
        "SELECT nombre FROM sindicato WHERE activo ORDER BY nombre")).all()]
    padron = uno("SELECT COUNT(*) FROM trabajador WHERE activo")
    registrados = uno("SELECT COUNT(*) FROM trabajador WHERE activo AND registrado")

    return {
        "recibos_total": recibos_total,
        "recibos_hoy": recibos_hoy,
        "lecturas_hoy": len(lecturas),
        "costo_hoy_usd": round(costo_hoy, 2),
        "en_linea": en_linea,
        "en_linea_total": sum(en_linea.values()),
        "minutos_en_linea": auth.IDLE_TIMEOUT_SEGUNDOS // 60,
        "tramites_abiertos": tramites_abiertos,
        "tramites_esperan": tramites_esperan,
        "sindicatos": sindicatos,
        "padron": padron,
        "registrados": registrados,
        "porcentaje_registrados": round(100 * registrados / padron) if padron else 0,
        "hoy": hoy,
    }
