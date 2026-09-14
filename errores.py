"""Códigos de error propios de Mi Trabajo.

Por qué existe este archivo (2026-08-26): un recibo fallaba al verificarse y
la pantalla decía "No pudimos verificar este recibo. Probá con una foto más
nítida o el PDF." Ese texto era el `detail` del handler global de
excepciones, o sea el mismo mensaje para CUALQUIER error de CUALQUIER ruta.
Mandaba a sacar la foto de nuevo por una fórmula mal cargada, y sobre todo
hacía imposible saber qué pasó sin ir a leer el log del servidor.

La regla, entonces:

- **Cada error que ve una persona lleva un código.** El código dice
  exactamente qué falló; el texto explica qué hacer. Si alguien reporta
  "me sale E-RECIBO-02" ya sabemos dónde mirar, sin pedirle capturas.
- **El mensaje de "probá con otra foto" es SOLO de los dos errores reales de
  lectura** (E-RECIBO-01 y E-RECIBO-02). Ningún otro error puede sugerir eso.
- **E-INTERNO-00 es el único que no sabemos qué es**: es la red de seguridad
  para una excepción no prevista. Por eso, y solo ese, además del código
  lleva una referencia corta (`ref`) que se imprime junto al traceback en el
  log del servidor: con ese `ref` se encuentra el error exacto en Render sin
  tener que adivinar el horario.

Para agregar un código nuevo: sumarlo a MENSAJES con un texto que le sirva a
quien lo lee (qué pasó y qué puede hacer), y lanzarlo con
`raise ErrorApp("E-...")`. El código viaja al frontend en el JSON, junto al
mensaje, y se muestra en chiquito debajo.
"""
from fastapi import HTTPException

# código -> (status HTTP, mensaje para la persona)
MENSAJES = {
    # --- Lectura del recibo (los ÚNICOS que hablan de la foto) -------------
    "E-RECIBO-01": (422, "No pudimos leer el recibo. Probá con una foto más nítida "
                         "o subí el PDF original."),
    "E-RECIBO-02": (422, "La imagen no es lo bastante clara para leerla con seguridad. "
                         "Sacá la foto de nuevo con buena luz, o subí el PDF."),

    # --- Verificación del recibo ------------------------------------------
    "E-RECIBO-03": (500, "No pudimos terminar de verificar este recibo. El recibo se "
                         "leyó bien: el problema está de nuestro lado."),
    # El recibo se leyó bien: el problema es de quién es. No habla de la foto
    # (la foto está perfecta) y no repite el CUIL ajeno, que es dato de otra
    # persona -- lo único que hace falta decir es que ese recibo no es suyo.
    "E-RECIBO-04": (403, "Este recibo no está a tu nombre: el CUIL que figura no es el "
                         "tuyo. Solo podés verificar tus propios recibos. Si es tuyo y "
                         "el CUIL del recibo está mal impreso, avisale a tu sindicato."),

    # --- Comprobante de aportes de ARCA (semáforo) ------------------------
    "E-APORTE-01": (422, "No pudimos leer el comprobante. Probá con una captura más "
                         "nítida o con el PDF que descargaste de ARCA."),
    "E-APORTE-02": (422, "El archivo no parece un comprobante de aportes de ARCA. "
                         "Revisá que hayas subido la pantalla correcta."),
    # Mismo criterio que E-RECIBO-04, para el otro documento que sube el
    # trabajador: el comprobante se leyó bien, no es suyo.
    "E-APORTE-03": (403, "Este comprobante no está a tu nombre: el CUIL que figura no es "
                         "el tuyo. Entrá a ARCA con tu propia clave fiscal y subí tu "
                         "comprobante."),

    # --- Sesión / identidad ------------------------------------------------
    "E-SESION-01": (400, "No pudimos determinar tu sindicato. Volvé a ingresar."),
    "E-SESION-02": (400, "No pudimos determinar tu identidad. Volvé a ingresar."),

    # --- Asistente del Panel Sindical (docs/ASISTENTE_PANEL.md) -----------
    "E-ASISTENTE-01": (502, "El asistente no pudo responder en este momento. Los filtros "
                            "del panel siguen funcionando a mano; probá de nuevo en un rato."),

    # --- Encuestas (SPRINT_ENCUESTAS.md) ----------------------------------
    # El motivo real lo agrega quien lo lanza (ya respondiste, no estás en el
    # padrón, la encuesta cerró, falta una pregunta): son cosas distintas
    # para la persona y todas terminan en "tu respuesta no se guardó".
    "E-ENCUESTA-01": (400, "No se pudo enviar tu respuesta."),
    # La exportación tiene su propio código porque su motivo más común no es
    # un error: es el umbral frenando un grupo demasiado chico, y quien lo
    # pide tiene que entender que el archivo no existe, no que falló algo.
    "E-ENCUESTA-02": (400, "No se pudo exportar esta encuesta."),

    # --- Red de seguridad --------------------------------------------------
    "E-INTERNO-00": (500, "Se produjo un error inesperado y no pudimos completar la "
                          "operación. Probá de nuevo en un momento; si vuelve a "
                          "pasar, pasale este código a tu sindicato."),
}


# Ruta -> código con el que se reporta una excepción NO prevista ocurrida ahí.
# Sirve para que la pantalla diga algo cierto en vez del genérico: si falla
# /api/validar, el recibo YA se leyó bien (eso pasó en /api/leer, antes), así
# que mandar a sacar otra foto es mentira. Lo que no esté acá cae en
# E-INTERNO-00, que no promete saber qué pasó.
CODIGO_POR_RUTA = {
    "/api/validar": "E-RECIBO-03",
}


def codigo_de_ruta(path: str) -> str:
    return CODIGO_POR_RUTA.get(path, "E-INTERNO-00")


class ErrorApp(HTTPException):
    """Un error con código propio. El status y el mensaje salen de MENSAJES,
    así que el mismo error dice siempre lo mismo, se lance desde donde se
    lance. `detalle_extra` agrega contexto al final, cuando hace falta."""

    def __init__(self, codigo: str, detalle_extra: str = ""):
        status, mensaje = MENSAJES[codigo]
        super().__init__(status, f"{mensaje} {detalle_extra}".strip())
        self.codigo = codigo


def cuerpo(codigo: str, detalle: str = None) -> dict:
    """El JSON que recibe el frontend: mensaje + código, siempre igual."""
    return {"detail": detalle or MENSAJES[codigo][1], "codigo": codigo}
