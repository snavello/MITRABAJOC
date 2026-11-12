"""Entradas de la Fiesta de Fin de Año: el motor PURO (PLAN_FIESTA.md).

No importa `db`: reglas de cupo y de topes, vencimiento, ventana de habilitación
de la entrada, el contenido del QR, el parseo del CSV del padrón y los textos.
Se prueba solo y rápido; `db.py` lo usa para decidir y guardar.

Las fechas del evento viajan como texto ISO ("2026-11-14T21:00") y los sellos
de tiempo como "AAAA-MM-DD HH:MM:SS" de Buenos Aires: ordenan y se comparan
como texto, igual que en el resto de la app. La hora la da `fechas.py`; acá no
se llama a `datetime.now()` ni a `date.today()`.
"""
import csv
import io
import re
import secrets
from datetime import datetime, timedelta

import fechas

# Estados de una reserva.
PENDIENTE, PAGADA, VENCIDA, ANULADA = "pendiente", "pagada", "vencida", "anulada"
ESTADOS = (PENDIENTE, PAGADA, VENCIDA, ANULADA)
TIPOS = ("afiliado", "cortesia")
ROLES = ("admin", "puerta")

LEYENDA_CORTESIA = "Invitado Especial"

DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre")

_RE_DNI = re.compile(r"^\d{7,8}$")


# ---------- Identidad: DNI y legajo ----------
def solo_digitos(texto) -> str:
    return re.sub(r"\D", "", str(texto or ""))


def normalizar_dni(texto) -> str:
    """El DNI como dígitos pelados ("12.345.678" -> "12345678")."""
    return solo_digitos(texto)


def dni_valido(texto) -> bool:
    return bool(_RE_DNI.match(normalizar_dni(texto)))


def normalizar_legajo(texto) -> str:
    return str(texto or "").strip()


def nuevo_token() -> str:
    """Opaco e impredecible: es la llave de la entrada (22 caracteres)."""
    return secrets.token_urlsafe(16)


def numero_reserva(reserva_id: int) -> str:
    return f"R-{int(reserva_id):06d}"


# ---------- Fechas ----------
def parsear(iso: str):
    """datetime naive de "2026-11-14T21:00" (o con espacio, o con segundos).
    None si no se entiende."""
    txt = (iso or "").strip().replace(" ", "T")
    for formato in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(txt, formato)
        except ValueError:
            continue
    return None


def fecha_texto(iso: str) -> str:
    """«viernes 14 de noviembre, 21:00». Sin hora ("2026-11-14") sale sin ella."""
    d = parsear(iso)
    if not d:
        return iso or ""
    base = f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}"
    return base if len(iso.strip()) <= 10 else f"{base}, {d.strftime('%H:%M')}"


def fecha_corta(iso: str) -> str:
    """«13/11 a las 21:00», para «se habilita el…»."""
    d = parsear(iso)
    if not d:
        return iso or ""
    return f"{d.day:02d}/{d.month:02d} a las {d.strftime('%H:%M')}"


def sello(momento: datetime = None) -> str:
    """"AAAA-MM-DD HH:MM:SS" de Buenos Aires: el sello de las reservas."""
    return (momento or fechas.ahora()).strftime("%Y-%m-%d %H:%M:%S")


def vence_en(minutos: int, desde: datetime = None) -> str:
    return sello((desde or fechas.ahora()) + timedelta(minutes=max(0, int(minutos))))


def vencida(vence: str, ahora: str = None) -> bool:
    """¿La reserva pendiente ya pasó su vencimiento? Vacío = no vence."""
    if not vence:
        return False
    return vence < (ahora or sello())


def vence_iso_con_zona(vence: str) -> str:
    """Para MercadoPago: "2026-11-12T20:30:00.000-03:00"."""
    d = parsear(vence)
    return d.strftime("%Y-%m-%dT%H:%M:%S.000-03:00") if d else ""


def segundos_restantes(vence: str, ahora: datetime = None) -> int:
    d = parsear(vence)
    if not d:
        return 0
    return max(0, int((d - (ahora or fechas.ahora())).total_seconds()))


# ---------- Cupo ----------
def _val(r, clave):
    return r.get(clave) if isinstance(r, dict) else getattr(r, clave, None)


def cuenta(r, ahora: str = None) -> bool:
    """¿Esta reserva ocupa lugar? Pagadas y pendientes que no vencieron. Las
    vencidas y anuladas devuelven el cupo."""
    estado = _val(r, "estado")
    if estado == PAGADA:
        return True
    if estado == PENDIENTE:
        return not vencida(_val(r, "vence") or "", ahora)
    return False


def ocupadas(reservas, ahora: str = None) -> int:
    ahora = ahora or sello()
    return sum(int(_val(r, "cantidad") or 0) for r in reservas if cuenta(r, ahora))


def disponibles(tope_general: int, reservas, ahora: str = None) -> int:
    """Lo que queda del tope general. Nunca negativo (un sobrecupo por un pago
    tardío, D9, no se muestra como menos uno)."""
    return max(0, int(tope_general) - ocupadas(reservas, ahora))


def disponibles_afiliado(tope_por_afiliado: int, reservas_del_afiliado, ahora: str = None) -> int:
    """El tope por afiliado es ACUMULADO: cuatro en total aunque reserve dos
    veces (D5)."""
    return max(0, int(tope_por_afiliado) - ocupadas(reservas_del_afiliado, ahora))


def maximo_reservable(tope_general, tope_por_afiliado, reservas, reservas_del_afiliado,
                      ahora: str = None) -> int:
    return min(disponibles(tope_general, reservas, ahora),
               disponibles_afiliado(tope_por_afiliado, reservas_del_afiliado, ahora))


def cantidad_valida(valor) -> int:
    """Entero positivo o 0 si no sirve."""
    if isinstance(valor, bool) or (isinstance(valor, float) and not valor.is_integer()):
        return 0
    try:
        n = int(valor)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


# ---------- Entrada ----------
def ventana_entrada(fecha_hora: str, horas_antes: int, ahora: datetime = None) -> tuple:
    """(habilitada, desde_iso): la entrada se habilita `horas_antes` del evento.
    Un evento sin fecha entendible queda siempre habilitado."""
    evento = parsear(fecha_hora)
    if not evento:
        return True, ""
    desde = evento - timedelta(hours=max(0, int(horas_antes or 0)))
    return (ahora or fechas.ahora()) >= desde, desde.strftime("%Y-%m-%dT%H:%M")


def contenido_qr(base: str, token: str, codigo: str) -> str:
    """Lo que va adentro del QR: la app del sindicato saca `token` y `k`."""
    return f"{base.rstrip('/')}/fiesta/e/{token}?k={codigo}"


def leer_qr(texto: str) -> tuple:
    """(token, k) de lo que escaneó la puerta. Acepta la URL entera o
    "token?k=codigo" suelto. ("", "") si no se entiende."""
    txt = (texto or "").strip()
    m = re.search(r"/fiesta/e/([A-Za-z0-9_\-]+)\?(?:[^#]*&)?k=([0-9A-Za-z.]+)", txt)
    if not m:
        m = re.match(r"^([A-Za-z0-9_\-]+)\?k=([0-9A-Za-z.]+)$", txt)
    return (m.group(1), m.group(2)) if m else ("", "")


def leyenda_entrada(tipo: str, leyenda_cortesia: str = "") -> str:
    """El texto de la banda del ticket: vacío en las de afiliado."""
    if tipo == "cortesia":
        return (leyenda_cortesia or LEYENDA_CORTESIA).strip()
    return ""


def texto_estado(estado: str) -> str:
    return {PENDIENTE: "Pendiente de pago", PAGADA: "Pagada",
            VENCIDA: "Vencida", ANULADA: "Anulada"}.get(estado, estado)


# ---------- CSV del padrón ----------
def parsear_padron(texto: str) -> dict:
    """legajo;dni;nombre;mail, separador `;` o `,`, con o sin cabecera.

    Devuelve {"filas": [{linea, legajo, dni, nombre, mail}], "errores":
    [{linea, motivo}]}. Fila por fila: una mala no frena las demás, y el
    ensayo y la carga usan este mismo parseo. Un legajo repetido dentro del
    archivo queda como error (la segunda aparición)."""
    texto = (texto or "").lstrip("﻿")
    muestra = texto.split("\n", 1)[0]
    sep = ";" if muestra.count(";") >= muestra.count(",") and ";" in muestra else ","
    filas, errores, vistos = [], [], set()
    for n, campos in enumerate(csv.reader(io.StringIO(texto), delimiter=sep), start=1):
        campos = [c.strip() for c in campos]
        if not any(campos):
            continue
        if n == 1 and campos[0].lower() in ("legajo", "n legajo", "nro legajo", "numero"):
            continue                       # cabecera
        if len(campos) < 3:
            errores.append({"linea": n, "motivo": "Faltan columnas: legajo;dni;nombre;mail."})
            continue
        legajo, dni, nombre = normalizar_legajo(campos[0]), normalizar_dni(campos[1]), campos[2]
        mail = campos[3] if len(campos) > 3 else ""
        motivo = validar_fila(legajo, dni, nombre, mail)
        if motivo:
            errores.append({"linea": n, "motivo": motivo})
        elif legajo in vistos:
            errores.append({"linea": n, "motivo": f"El legajo {legajo} está repetido en el archivo."})
        else:
            vistos.add(legajo)
            filas.append({"linea": n, "legajo": legajo, "dni": dni, "nombre": nombre, "mail": mail})
    return {"filas": filas, "errores": errores}


_RE_MAIL = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")


def validar_fila(legajo: str, dni: str, nombre: str, mail: str = "") -> str:
    """El motivo por el que una fila del padrón no sirve, o "" si está bien.
    La usan el CSV y el alta de a uno (E-FIESTA-11)."""
    if not legajo:
        return "Falta el legajo."
    if not dni_valido(dni):
        return "El DNI tiene que tener 7 u 8 dígitos."
    if not (nombre or "").strip():
        return "Falta el nombre."
    if mail and not _RE_MAIL.match(mail):
        return "El mail no parece un mail."
    return ""
