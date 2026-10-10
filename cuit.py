"""CUIL y CUIT: el dígito verificador (módulo 11 de AFIP), en un solo lugar.

Por qué existe (2026-10-10, PLAN_CUIT_MOD11.md): el CUIL/CUIT es el campo más
importante del modelo -- identifica a la persona en todas las tablas, y entre
tablas se une por texto, sin claves foráneas --, y hasta acá la app solo le
pedía 11 dígitos. Nadie miraba el verificador. Este módulo es la ÚNICA
implementación: las puertas de alta, el enmascarado, la herramienta de
regularización y los scripts de demo lo usan a él. `test_cuit.py` recorre el
código con `ast` y falla si alguien vuelve a escribir los pesos por su cuenta.

Puro a propósito (no importa `db`, como `fechas.py` o `encuestas.py`): se
prueba solo y rápido, y lo puede importar cualquiera sin arrastrar la base.

El algoritmo: pesos 5 4 3 2 7 6 5 4 3 2 sobre los diez primeros dígitos;
r = 11 - (suma mod 11); r = 11 -> el verificador es 0; r = 10 -> ese prefijo
no tiene verificador posible y AFIP le asigna otro (23 a las personas, 33 a
las empresas), que es lo que hace `corregir`.

Lo que NO hace este módulo: decidir dónde se exige. La regla (decisión D2 del
plan) es que el verificador se exige donde un número NACE -- altas, registro,
carga masiva -- y que donde se REFERENCIA uno que ya existe -- los logins,
los filtros, las búsquedas -- se busca tal cual, para que los números que ya
estaban cargados (los sintéticos de los lotes, por ejemplo) sigan andando.
"""
import re
from typing import Iterable, Optional

PESOS = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)

# Personas: 20, 23, 24, 27 y también 25 y 26 (decisión 5 del plan, SDN
# 2026-10-10: se mantienen los que ya aceptaba el enmascarado).
PREFIJOS_PERSONA = frozenset({"20", "23", "24", "25", "26", "27"})
# Empresas (personas jurídicas).
PREFIJOS_EMPRESA = frozenset({"30", "33", "34"})

PERSONA = "persona"
EMPRESA = "empresa"

# [^0-9] y no \D: \D deja pasar dígitos Unicode ("２０" de ancho completo, que
# int() acepta) y el número quedaría guardado con caracteres que ninguna
# búsqueda por texto vuelve a encontrar.
_NO_DIGITO = re.compile(r"[^0-9]")
_SEPARADOR = re.compile(r"\d\D+\d")


def normalizar(valor) -> str:
    """Solo los dígitos, como texto: '20-12345678-3' -> '20123456783'.

    None, vacío o cualquier cosa sin dígitos -> ''. NO corrige ni completa
    nada: un número de 10 dígitos sigue teniendo 10."""
    if valor is None:
        return ""
    return _NO_DIGITO.sub("", str(valor))


def digito_verificador(diez) -> Optional[int]:
    """El verificador que corresponde a los diez primeros dígitos, o None si
    no son diez dígitos o si ese prefijo no admite verificador (r = 10)."""
    d = normalizar(diez)
    if len(d) != 10:
        return None
    r = 11 - sum(int(c) * p for c, p in zip(d, PESOS)) % 11
    if r == 11:
        return 0
    if r == 10:
        return None
    return r


def tipo(numero) -> str:
    """'persona', 'empresa' o '' según el prefijo. No mira el verificador."""
    d = normalizar(numero)
    if len(d) != 11:
        return ""
    if d[:2] in PREFIJOS_PERSONA:
        return PERSONA
    if d[:2] in PREFIJOS_EMPRESA:
        return EMPRESA
    return ""


def es_valido(numero, de: Optional[str] = None) -> bool:
    """¿Es un CUIL/CUIT válido? Once dígitos (los separadores se ignoran), un
    prefijo conocido y el verificador correcto.

    `de` restringe el tipo: `PERSONA` para un CUIL (afiliado, usuario de un
    sindicato o de plataforma), `EMPRESA` para una persona jurídica. Sin `de`
    vale cualquiera de los dos, que es lo que corresponde a un empleador: un
    monotributista con empleados tiene CUIT de persona."""
    d = normalizar(numero)
    t = tipo(d)
    if not t or (de and t != de):
        return False
    return digito_verificador(d[:10]) == int(d[10])


def corregir(numero) -> str:
    """El número válido más cercano a uno inválido: los mismos diez primeros
    dígitos (y con ellos el DNI y el tipo) con el verificador correcto.

    Si esos diez dígitos no admiten verificador (r = 10), hace lo que hace
    AFIP: cambia el prefijo a 23 (persona) o 33 (empresa) y recalcula. Un
    número que ya es válido vuelve igual (normalizado). '' si no hay
    corrección posible: no son 11 dígitos, el prefijo es desconocido, o ya
    era 23/33 y no tiene verificador.

    OJO: dos números que difieren solo en el último dígito se corrigen al
    MISMO número (20111111110 y 20111111119 -> 20111111112). Quien convierta
    datos tiene que verificar colisiones antes de escribir; esta función no
    puede saberlo."""
    d = normalizar(numero)
    t = tipo(d)
    if not t:
        return ""
    dv = digito_verificador(d[:10])
    if dv is not None:
        return d[:10] + str(dv)
    prefijo = "23" if t == PERSONA else "33"
    if d[:2] == prefijo:
        return ""
    diez = prefijo + d[2:10]
    dv = digito_verificador(diez)
    return diez + str(dv) if dv is not None else ""


def siguiente_libre(numero, ocupados: Iterable[str] = ()) -> str:
    """Renumerar: el primer número válido con el MISMO prefijo y un DNI mayor
    que el de `numero` que no esté en `ocupados`. Es la propuesta por defecto
    cuando la corrección de un número choca con otra persona (decisión D4).

    A diferencia de `corregir`, nunca cambia el prefijo: si un DNI no admite
    verificador, pasa al siguiente. '' si el prefijo es desconocido o se
    acabaron los DNI."""
    d = normalizar(numero)
    if not tipo(d):
        return ""
    ocup = {normalizar(o) for o in ocupados}
    dni = int(d[2:10])
    while dni < 99_999_999:
        dni += 1
        diez = f"{d[:2]}{dni:08d}"
        dv = digito_verificador(diez)
        if dv is None:
            continue
        candidato = diez + str(dv)
        if candidato not in ocup:
            return candidato
    return ""


def formatear(numero) -> str:
    """'20123456783' -> '20-12345678-3'. Si no son 11 dígitos, lo devuelve
    tal cual vino (no inventa un formato para un dato roto)."""
    d = normalizar(numero)
    if len(d) != 11:
        return "" if numero is None else str(numero)
    return f"{d[:2]}-{d[2:10]}-{d[10]}"


def con_formato_de(original, nuevo) -> str:
    """`nuevo` escrito como estaba escrito `original`: con guiones si el
    original los tenía ('30-11111111-1'), pelado si no. Para reescribir un
    dato guardado sin cambiarle la forma a quien lo lee (la IA guarda el CUIL
    como lo leyó del recibo; un sindicato puede tener su CUIT con guiones)."""
    if original is not None and _SEPARADOR.search(str(original)):
        return formatear(nuevo)
    return normalizar(nuevo)
