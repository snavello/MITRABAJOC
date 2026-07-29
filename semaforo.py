"""Lógica del semáforo de aportes.

Recibe el estado mensual (extraído por IA del comprobante de ARCA que sube el
trabajador) y calcula el color global y los conteos por rubro.

Estados por mes y rubro: pagado | parcial | impago | no_presentada | no_declarado
"""

MALOS = ("impago", "no_presentada", "no_declarado")


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
