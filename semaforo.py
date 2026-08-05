"""Lógica del semáforo de aportes.

Recibe el estado mensual (extraído por IA del comprobante de ARCA que sube el
trabajador) y calcula el color global y los conteos por rubro.

Estados por mes y rubro: pagado | parcial | impago | no_presentada | no_declarado
"""
import re

MALOS = ("impago", "no_presentada", "no_declarado")
MESES_ATRASO_ALERTA = 3


def calcular_semaforo(datos: dict) -> dict:
    """Devuelve el color global y el detalle para pintar el semáforo.

    Reglas del color global:
      verde    : todos los meses pagados (jubilación y obra social)
      amarillo : hay parciales pero ningún mes 'malo'
      rojo     : hay al menos un mes impago / no presentado / no declarado
    """
    meses = datos.get("meses", [])
    hay_malo = False
    hay_parcial = False

    for m in meses:
        for rubro in ("jubilacion", "obra_social"):
            estado = m.get(rubro, "")
            if estado in MALOS:
                hay_malo = True
            elif estado == "parcial":
                hay_parcial = True

    if hay_malo:
        color = "rojo"
    elif hay_parcial:
        color = "amarillo"
    elif meses:
        color = "verde"
    else:
        color = "gris"

    total = len(meses)
    jub_ok = sum(1 for m in meses if m.get("jubilacion") == "pagado")
    os_ok = sum(1 for m in meses if m.get("obra_social") == "pagado")

    textos = {
        "verde": ("Todo al día", "Tu empleador depositó jubilación y obra social todos los meses."),
        "amarillo": ("Hay pagos parciales", "Algunos meses figuran como pago parcial. Conviene revisarlo."),
        "rojo": ("Hay meses sin aportar", "Faltan aportes en algunos meses. Podés reportarlo al sindicato."),
        "gris": ("Sin datos", "Subí tu comprobante de ARCA para ver el estado."),
    }
    titulo, desc = textos[color]

    return {
        "color": color,
        "titulo": titulo,
        "descripcion": desc,
        "total_meses": total,
        "jubilacion_ok": jub_ok,
        "obra_social_ok": os_ok,
        "cuil": datos.get("cuil", ""),
        "desde": datos.get("desde", ""),
        "hasta": datos.get("hasta", ""),
        "meses": meses,
    }


def _parsear_fecha_ar(fecha: str):
    """DD/MM/AAAA (o D/M/AAAA) impreso en el recibo -> (año, mes), o None si no matchea."""
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", (fecha or "").strip())
    if not m:
        return None
    mes = int(m.group(2))
    if not 1 <= mes <= 12:
        return None
    return int(m.group(3)), mes


def advertencia_ultimo_deposito(recibo: dict) -> dict | None:
    """Señal temprana y COMPLEMENTARIA a ARCA (Dto-Ley 17.250/67): si el último
    depósito de aportes que declara el propio recibo es de varios meses antes de
    su período, alerta sobre un posible atraso del empleador. No reemplaza la
    consulta real a ARCA — es útil mientras el trabajador todavía no la hizo."""
    periodo = re.match(r"^(\d{4})-(\d{2})$", (recibo.get("periodo") or "").strip())
    deposito = _parsear_fecha_ar((recibo.get("ultimo_deposito") or {}).get("fecha"))
    if not periodo or not deposito:
        return None
    anio_periodo, mes_periodo = int(periodo.group(1)), int(periodo.group(2))
    anio_dep, mes_dep = deposito
    meses_atraso = (anio_periodo * 12 + mes_periodo) - (anio_dep * 12 + mes_dep)
    if meses_atraso < MESES_ATRASO_ALERTA:
        return None
    return {
        "meses_atraso": meses_atraso,
        "mensaje": f"El recibo declara último depósito de aportes en "
                   f"{mes_dep:02d}/{anio_dep} ({meses_atraso} meses antes del período "
                   f"{mes_periodo:02d}/{anio_periodo}). Puede indicar un atraso del "
                   "empleador: conviene confirmarlo en ARCA.",
    }
