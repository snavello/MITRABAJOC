"""La hora de Buenos Aires, en un solo lugar.

El servidor de Render corre en UTC: `datetime.now()` ahí da TRES HORAS DE
MÁS y `date.today()` cambia de día a las 21:00 de Argentina. Eso no es un
detalle cosmético, porque toda la app compara fechas como texto:

- una Noticia vigente "hasta el 30" dejaba de verse a las 21:00 del 30;
- lo mismo Beneficios y cualquier vigencia por fecha;
- una notificación enviada a las 22:30 quedaba guardada con la fecha del
  día siguiente.

Se notaba poco justamente porque solo pasa entre las 21:00 y la medianoche.
Apareció medido el 2026-09-11 con los planes de Render ("la regla decía
22:02 y la bitácora 01:02", ver db._ahora_ba en su momento), se arregló
ahí nomás para esas dos tablas, y este módulo lo lleva a toda la app.

**`ahora()` devuelve un datetime SIN zona (naive) con la hora de Buenos
Aires**, no uno con tzinfo. Es a propósito: la app guarda fechas como texto
("AAAA-MM-DD HH:MM") y hay valores ya escritos así en la base. Un datetime
con zona arrastraría el offset a `isoformat()` ("...-03:00") y rompería el
formato de lo ya guardado, además de reventar cualquier comparación contra
un datetime naive parseado de la base. Acá la zona es un dato de entrada
para saber qué hora es, no algo que viaje con el valor.

REGLA: en el código de la app no se llama más a `datetime.now()` ni a
`date.today()` -- se usa este módulo. Lo verifica `test_fechas.py`, que
recorre los archivos y falla nombrando al que se salte la regla.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

ZONA = ZoneInfo("America/Argentina/Buenos_Aires")


def ahora() -> datetime:
    """La fecha y hora de Buenos Aires, como datetime naive."""
    return datetime.now(ZONA).replace(tzinfo=None)


def hoy() -> date:
    """El día de hoy en Buenos Aires. Reemplaza a date.today()."""
    return ahora().date()


def hoy_texto() -> str:
    """Hoy como "AAAA-MM-DD" -- el formato de <input type=date> y el que se
    compara contra fecha_desde/fecha_hasta en toda la app."""
    return ahora().strftime("%Y-%m-%d")


def ahora_texto() -> str:
    """Fecha y hora como "AAAA-MM-DD HH:MM" -- el sello de tiempo estándar
    del proyecto (enviado_en, creada, leida_en, actualizado)."""
    return ahora().strftime("%Y-%m-%d %H:%M")


def ahora_con_segundos() -> str:
    """Igual que ahora_texto() pero con segundos, para bitácoras donde dos
    eventos del mismo minuto tienen que quedar ordenados."""
    return ahora().strftime("%Y-%m-%d %H:%M:%S")


def dia_legible(iso: str) -> str:
    """"2026-10-12" -> "12/10/2026", para los textos que lee una persona.

    Una fecha ISO es el formato de la base y de <input type=date>, no el
    que se le muestra a un afiliado: "Se puede responder hasta el
    2026-10-12" se lee como un mensaje del sistema. Si no viene en ISO se
    devuelve tal cual: es texto para una pantalla, nunca vale romperla.
    """
    try:
        return datetime.strptime((iso or "").strip(), "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return iso or ""


MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre")


def periodo_legible(periodo: str) -> str:
    """"2026-07" -> "Julio 2026", para los textos que lee una persona.

    El período de un recibo se guarda "AAAA-MM" porque así ordena solo y
    se compara como texto; mostrárselo crudo al afiliado es mostrarle el
    formato de la base. Igual que `dia_legible`, si no viene en ese formato
    se devuelve tal cual: es texto para una pantalla, nunca vale romperla.
    """
    partes = (periodo or "").strip().split("-")
    if len(partes) != 2 or not partes[0].isdigit() or not partes[1].isdigit():
        return periodo or ""
    mes = int(partes[1])
    if not 1 <= mes <= 12:
        return periodo
    return MESES[mes - 1].capitalize() + " " + partes[0]
