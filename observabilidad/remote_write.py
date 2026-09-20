"""Escribir métricas en Prometheus (Grafana Cloud) por remote write, solo con la
biblioteca estándar.

Remote write manda un mensaje protobuf comprimido con snappy. Para no sumar
dependencias (el colector corre en GitHub Actions y en la PC, y no debe instalar
nada), acá se codifica a mano:

- protobuf: solo los cuatro mensajes que hacen falta (WriteRequest, TimeSeries,
  Label, Sample), que son triviales;
- snappy: se usa el formato de bloque SIN compresión (solo "literales"), que es
  válido y lo descomprime cualquier receptor. Se pierde el ahorro de ancho de
  banda, que acá no importa: son unos pocos KB por corrida.

Los tests de test_observabilidad_metricas.py decodifican lo escrito con un lector
mínimo de protobuf y de snappy, para que el formato no dependa de la fe.
"""
import base64
import ssl
import struct
import urllib.error
import urllib.request


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _campo_bytes(numero: int, datos: bytes) -> bytes:
    return _varint((numero << 3) | 2) + _varint(len(datos)) + datos


def codificar_etiqueta(nombre: str, valor: str) -> bytes:
    return _campo_bytes(1, nombre.encode("utf-8")) + _campo_bytes(2, valor.encode("utf-8"))


def codificar_muestra(valor: float, timestamp_ms: int) -> bytes:
    return bytes([(1 << 3) | 1]) + struct.pack("<d", float(valor)) + \
        bytes([(2 << 3) | 0]) + _varint(timestamp_ms)


def codificar_serie(etiquetas: dict, muestras: list) -> bytes:
    """`etiquetas` incluye __name__; `muestras` es una lista (timestamp_ms, valor).
    Prometheus exige las etiquetas ordenadas por nombre y las muestras por tiempo."""
    cuerpo = b"".join(_campo_bytes(1, codificar_etiqueta(k, str(v))) for k, v in sorted(etiquetas.items()))
    cuerpo += b"".join(_campo_bytes(2, codificar_muestra(v, t)) for t, v in sorted(muestras))
    return cuerpo


def codificar_write_request(series: list) -> bytes:
    """`series`: lista de (etiquetas, muestras)."""
    return b"".join(_campo_bytes(1, codificar_serie(e, m)) for e, m in series)


def snappy_sin_compresion(datos: bytes) -> bytes:
    """Bloque snappy hecho solo de literales."""
    salida = bytearray(_varint(len(datos)))
    for i in range(0, len(datos), 65536):
        trozo = datos[i:i + 65536]
        n = len(trozo) - 1
        if n < 60:
            salida.append(n << 2)
        else:
            salida.append(61 << 2)                       # longitud en 2 bytes little-endian
            salida += struct.pack("<H", n)
        salida += trozo
    return bytes(salida)


def _contexto_tls():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return None


def escribir(url: str, usuario: str, token: str, series: list, timeout: int = 30) -> tuple:
    """Manda las series. Devuelve (status, texto). No lanza por un 4xx/5xx: el que
    llama decide qué hacer con cada caso."""
    cuerpo = snappy_sin_compresion(codificar_write_request(series))
    req = urllib.request.Request(url, data=cuerpo, method="POST")
    req.add_header("Content-Encoding", "snappy")
    req.add_header("Content-Type", "application/x-protobuf")
    req.add_header("X-Prometheus-Remote-Write-Version", "0.1.0")
    req.add_header("User-Agent", "colm3na-colector/1")
    autenticacion = base64.b64encode(f"{usuario}:{token}".encode("utf-8")).decode("ascii")
    req.add_header("Authorization", f"Basic {autenticacion}")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_contexto_tls()) as r:
            return r.status, r.read().decode("utf-8", "replace")[:400]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:400]
