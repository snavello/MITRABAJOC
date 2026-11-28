# -*- coding: utf-8 -*-
"""«Preguntame» de XSII (bloque 2, `docs/xsii/API.md`): una consulta acotada a
UN punto del tablero, con herramientas de LECTURA, sin historial.

Genérico: no importa `db` ni nada de la app. Solo el SDK (`anthropic`, perezoso)
y la stdlib. El proyecto le pasa el modelo, el texto del sistema, las
herramientas (`{nombre: (esquema, funcion)}`) y los códigos de tarea que
existen; quien llama registra el consumo (`uso`) y escribe lo que haya que
escribir. El modelo nunca escribe: a lo sumo PROPONE (una herramienta puede
devolver `{"_propuesta": {...}}`, que acá se recoge y NO se le muestra al modelo).

Reglas que no se negocian:
- bucle manual de herramientas con tope de vueltas; `tool_choice` en `auto`
  (los modelos 5.5 rechazan la herramienta forzada), sin `temperature`, sin
  presupuesto de razonamiento, sin prefill; `stop_reason` se mira ANTES del contenido;
  se devuelve `response.content` entero en cada vuelta y todos los
  `tool_result` de una vuelta van en UN solo mensaje de usuario;
- lo que no pasa `validar` sale con el texto fijo del servidor, no del modelo;
- toda cifra de la respuesta tiene que figurar en lo que devolvieron las
  herramientas de ESA consulta (o en la pregunta).
"""
from __future__ import annotations

import json
import os
import re
import time
import unicodedata

MAX_VUELTAS = 6
MAX_TOKENS = 4000
TIMEOUT_S = 60
TIEMPO_TOTAL_S = 120
RESULTADO_HERRAMIENTA_MAX = 24000      # caracteres de un tool_result

PREGUNTA_MIN, PREGUNTA_MAX = 3, 300
RESPUESTA_MAX = 900

PUNTOS = ("recomendada", "tarea", "mapa")
RESULTADOS = ("respondida", "fija", "error")

TEXTO_FIJO = ("No pude responder eso con los datos del tablero. Probá con otra pregunta "
              "o mirá la ficha de la tarea.")
TEXTO_ERROR = ("No pude consultar al asistente en este momento. Probá de nuevo en un rato: "
               "el tablero y los controles siguen funcionando.")

PATRON_CODIGO = r"\b[A-Z]{2,4}-\d{2}\b"
# Códigos de la Mesa (HI0001, PE0007, AR000123): letras y dígitos pegados. No hay lista cerrada de
# ellos, así que se exige que aparezcan TAL CUAL en lo que devolvieron las herramientas o en la pregunta:
# como número suelto, uno inventado (HI0003) pasaba si «3» salía en cualquier otra parte.
PATRON_REF_MESA = r"\b[A-Z]{2}\d{4,6}\b"

_cliente = None


class PreguntaInvalida(ValueError):
    """La pregunta no cumple el largo o quedó vacía tras limpiarla."""


class ErrorHerramienta(Exception):
    """Lo que una herramienta le dice al modelo cuando no puede dar lo pedido
    (código inexistente, algo que no se puede proponer): vuelve como
    `tool_result` con `is_error`, nunca como una excepción."""


# ---------------------------------------------------------------- cliente
def usar_cliente(cliente) -> None:
    """Inyecta el cliente (los tests le ponen uno falso; None lo borra)."""
    global _cliente
    _cliente = cliente


def cliente():
    global _cliente
    if _cliente is None and os.getenv("ANTHROPIC_API_KEY"):
        from anthropic import Anthropic
        _cliente = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=1)
    return _cliente


def estado() -> tuple[bool, bool]:
    """`(disponible, simulado)`. `MOCK_EXTRACTOR=1` prende el modo simulado
    aunque no haya clave; sin clave ni mock, apagado."""
    if os.getenv("MOCK_EXTRACTOR") == "1":
        return True, True
    return cliente() is not None, False


# ---------------------------------------------------------------- texto
def limpiar(texto) -> str:
    """NFKC, sin caracteres de control ni invisibles, espacios colapsados."""
    t = unicodedata.normalize("NFKC", texto)
    t = "".join(" " if c.isspace() else ("" if unicodedata.category(c) in ("Cc", "Cf", "Cs", "Co", "Cn") else c)
                for c in t)
    return " ".join(t.split())


def normalizar_pregunta(texto) -> str:
    """La pregunta lista para usarse: de 3 a 300 caracteres DESPUÉS de limpiar."""
    if not isinstance(texto, str):
        raise PreguntaInvalida("Escribí tu pregunta.")
    if len(texto) > PREGUNTA_MAX * 20:           # antes de recorrerlo: un cuerpo de MB no cuesta CPU
        raise PreguntaInvalida(f"La pregunta pasa de {PREGUNTA_MAX} caracteres.")
    t = limpiar(texto)
    if len(t) < PREGUNTA_MIN:
        raise PreguntaInvalida("La pregunta es muy corta.")
    if len(t) > PREGUNTA_MAX:
        raise PreguntaInvalida(f"La pregunta pasa de {PREGUNTA_MAX} caracteres.")
    return t


_ANGULOS = str.maketrans({"<": "\u2039", ">": "\u203a", "〈": "\u2039", "〉": "\u203a",
                          "⟨": "\u2039", "⟩": "\u203a", "﹤": "\u2039", "﹥": "\u203a"})


def armar_mensaje(punto: str, codigo: str, pregunta: str) -> str:
    """El mensaje del usuario: el punto desde el que se pregunta y la pregunta
    dentro de marcas, que no pueden cerrarse desde adentro."""
    segura = unicodedata.normalize("NFKC", pregunta).translate(_ANGULOS)
    donde = {"recomendada": "el paso recomendado del tablero",
             "tarea": f"la tarea {codigo}",
             "mapa": f"la tarea {codigo}, vista en el mapa de dependencias"}.get(punto, "el tablero")
    return (f"Punto de la pregunta: {donde}.\n"
            "<pregunta_del_usuario>\n" + segura + "\n</pregunta_del_usuario>")


# ---------------------------------------------------------------- validación
_URL = re.compile(
    r"(https?:|ftp:|www\.|://"
    # cualquier `palabra.tld` con forma de dominio: TLD de 2 a 24 letras en MINUSCULA (una frase normal con el
    # punto pegado a la palabra siguiente, «hecha.La siguiente», arranca esa palabra con mayuscula), o los
    # TLD de siempre en cualquier caso (EJEMPLO.COM).
    r"|\b[a-z0-9][a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?-i:[a-z]{2,24})\b"
    r"|\b[a-z0-9][a-z0-9-]*\.(?:com|net|org|gob|gov|edu|info|biz|io|ar|app|me|co|xyz|ly|ru|cn|es|mx|cl|uy|br|tk)\b"
    r"|[\w.+-]+@[\w-]+\.\w|(?<!\w)@\w)", re.I)
_MARCAS = re.compile(r"[*#`|~<>\[\]{}\\]")
# Un numero: miles con punto o coma (1.234, 1.234.567, 1,234) con decimales opcionales, decimal con coma o punto, o entero.
_NUMERO = re.compile(r"\d+(?:[.,]\d{3})+(?!\d)(?:[.,]\d+)?|\d+[.,]\d+|\d+")
_ESPACIOS_DE_MILES = re.compile(r"(?<=\d)[\u2009\u202f\u00a0](?=\d{3}(?!\d))")
_GUIONES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d"), "-")


def forma_invalida(texto: str) -> str:
    """Motivo si el texto tiene una forma que no corresponde a una respuesta de
    esta pantalla (enlace, mail, marcas de formato, invisibles); '' si está bien."""
    if any(unicodedata.category(c) in ("Cf", "Co", "Cs", "Cn", "Zl", "Zp")
           or (unicodedata.category(c) == "Cc" and c != "\n") for c in texto):
        return "caracteres invisibles o de control"
    if _URL.search(unicodedata.normalize("NFKC", texto)):
        return "enlaces o direcciones"
    if _MARCAS.search(texto):
        return "marcas de formato"
    return ""


def _ascii(digitos: str) -> str:
    return "".join(str(unicodedata.digit(c, 0)) if not c.isascii() else c for c in digitos)


def _canon(entero: str, frac: str = "") -> str:
    e = entero.lstrip("0") or "0"
    f = frac.rstrip("0")
    return f"{e}.{f}" if f else e


def _candidatos(token: str) -> set:
    """Las lecturas posibles de un numero, canonicas: «1.234» es 1234 o 1,234; «12,5» es 12.5."""
    t = _ascii(token)
    seps = [c for c in t if c in ".,"]
    if not seps:
        return {_canon(t)}
    partes = re.split(r"[.,]", t)
    ultimo = partes[-1]
    if len(set(seps)) == 1 and len(seps) == 1:
        a, b = partes
        if len(b) == 3:                                  # 1.234: miles o decimal
            return {_canon(a + b), _canon(a, b)}
        return {_canon(a, b)}
    if len(set(seps)) == 1:                              # 1.234.567: solo miles
        return {_canon("".join(partes))}
    return {_canon("".join(partes[:-1]), ultimo)}        # 1.234,56


def _tokens(texto: str) -> list:
    t = _ESPACIOS_DE_MILES.sub(".", texto)
    return _NUMERO.findall(unicodedata.normalize("NFKC", t))


def _numeros(texto: str) -> set:
    """Todo lo que las herramientas (o la pregunta) dicen como numero, entero y por pedazos."""
    out = set()
    for tok in _tokens(texto):
        out |= _candidatos(tok)
        out |= {_canon(_ascii(p)) for p in re.split(r"[.,]", tok)}
    return out


def _cifra_inventada(texto: str, permitidos: set) -> str:
    """El primer numero de 2 o mas digitos que no sale de lo permitido, o ''."""
    for tok in _tokens(texto):
        if sum(c.isdigit() for c in tok) >= 2 and not (_candidatos(tok) & permitidos):
            return tok
    return ""


def validar(texto, *, visto: str = "", pregunta: str = "", codigos_validos=(),
            patron_codigo: str = PATRON_CODIGO, maximo: int = RESPUESTA_MAX) -> dict:
    """Decide si el texto final del modelo se muestra. Puro.
    `visto`: todo lo que devolvieron las herramientas de ESTA consulta (texto).
    Devuelve `{"ok": bool, "motivo": str, "texto": str, "codigos": [...]}`."""
    def no(motivo):
        return {"ok": False, "motivo": motivo, "texto": TEXTO_FIJO, "codigos": []}
    if not isinstance(texto, str):
        return no("el modelo no contestó en texto")
    t = texto.strip()
    if not t:
        return no("respuesta vacía")
    if len(t) > maximo:
        return no("respuesta demasiado larga")
    if (m := forma_invalida(t)):
        return no(m)
    validos = set(codigos_validos)
    codigos = []
    # Los codigos se buscan en MAYUSCULAS y con guion ASCII: `zzz-07` y `ZZZ\u201107` tampoco pasan.
    for c in re.findall(patron_codigo, unicodedata.normalize("NFKC", t).translate(_GUIONES).upper()):
        if c not in validos:
            return no(f"nombra una tarea que no existe ({c})")
        if c not in codigos:
            codigos.append(c)
    normal = unicodedata.normalize("NFKC", t).translate(_GUIONES).upper()
    conocido = unicodedata.normalize("NFKC", f"{visto} {pregunta}").upper()
    for ref in re.findall(PATRON_REF_MESA, normal):
        if ref not in conocido:
            return no(f"nombra un código de la Mesa que no salió de las herramientas ({ref})")
    sin_codigos = re.sub(patron_codigo, " ", normal)
    if (n := _cifra_inventada(sin_codigos, _numeros(visto) | _numeros(pregunta))):
        return no(f"cifra que no sale de las herramientas ({n})")
    return {"ok": True, "motivo": "", "texto": t, "codigos": codigos}


# ---------------------------------------------------------------- llamada
def _entero(x) -> int:
    try:
        return max(0, int(x or 0))
    except (TypeError, ValueError):
        return 0


class _Uso:
    """Suma los tokens de TODAS las vueltas: una consulta es una fila de UsoIA."""
    def __init__(self, modelo: str):
        self.modelo = modelo
        self.entrada = self.salida = self.cache_lectura = self.cache_escritura = 0
        self.llamadas = 0
        self.inicio = time.perf_counter()

    def sumar(self, msg) -> None:
        u = getattr(msg, "usage", None)
        self.llamadas += 1
        self.entrada += _entero(getattr(u, "input_tokens", 0))
        self.salida += _entero(getattr(u, "output_tokens", 0))
        self.cache_lectura += _entero(getattr(u, "cache_read_input_tokens", 0))
        self.cache_escritura += _entero(getattr(u, "cache_creation_input_tokens", 0))

    def como_dict(self):
        if not self.llamadas:
            return None
        return {"modelo": self.modelo, "tokens_entrada": self.entrada, "tokens_salida": self.salida,
                "tokens_cache_lectura": self.cache_lectura, "tokens_cache_escritura": self.cache_escritura,
                "duracion_ms": int((time.perf_counter() - self.inicio) * 1000)}


class _Corrida:
    """Lo que pasó en UNA consulta: lo que devolvieron las herramientas y la propuesta."""
    def __init__(self, herramientas: dict):
        self.herramientas = herramientas
        self.visto: list[str] = []
        self.propuesta = None

    def ejecutar(self, nombre: str, args) -> tuple[str, bool]:
        """`(contenido, es_error)` de una herramienta. Nunca levanta."""
        if nombre not in self.herramientas:
            return f"No existe la herramienta {nombre}.", True
        if not isinstance(args, dict):
            return "Los argumentos tienen que ser un objeto.", True
        try:
            r = self.herramientas[nombre][1](**args) if args else self.herramientas[nombre][1]()
        except ErrorHerramienta as e:
            texto = str(e) or "No se pudo."
            self.visto.append(texto)
            return texto, True
        except TypeError:
            return "Los argumentos no son los que pide la herramienta.", True
        except Exception as e:     # noqa: BLE001 - una herramienta rota no tumba la consulta
            print(f"[xsii-ia] la herramienta {nombre} falló ({type(e).__name__}: {e})")
            return "No se pudo leer eso ahora.", True
        if isinstance(r, dict) and "_propuesta" in r:
            r = dict(r)
            propuesta = r.pop("_propuesta")
            if self.propuesta is None and isinstance(propuesta, dict):
                self.propuesta = propuesta
        texto = json.dumps(r, ensure_ascii=False, default=str)
        if len(texto) > RESULTADO_HERRAMIENTA_MAX:
            texto = texto[:RESULTADO_HERRAMIENTA_MAX]
        self.visto.append(texto)
        return texto, False


def _definiciones(herramientas: dict) -> list:
    """Las herramientas para la API, con esquema estricto. La marca de caché va
    en la última: el sistema y las herramientas son estables entre consultas."""
    tools = [{"name": n, "description": e.get("description", ""), "strict": True,
              "input_schema": e["input_schema"]} for n, (e, _f) in herramientas.items()]
    if tools:
        tools[-1]["cache_control"] = {"type": "ephemeral"}
    return tools


def _propuesta_valida(corrida, pregunta, codigos_validos, patron_codigo):
    """La propuesta de reclamo pasa por las MISMAS reglas que la respuesta (forma,
    cifras, codigos): se vuelve una tarjeta que lee el sindicato. Si no pasa se
    descarta, y la respuesta puede seguir."""
    p = corrida.propuesta
    if not isinstance(p, dict):
        return None
    visto = "\n".join(corrida.visto)
    for campo, tope in (("titulo", 120), ("texto", 1000)):
        v = validar(p.get(campo), visto=visto, pregunta=pregunta, codigos_validos=codigos_validos,
                    patron_codigo=patron_codigo, maximo=tope)
        if not v["ok"]:
            print(f"[xsii-ia] propuesta descartada ({campo}: {v['motivo']})")
            return None
    return p


def _salida(resultado, texto, motivo, corrida, uso, vueltas, modelo, simulado, codigos=(), propuesta=None) -> dict:
    return {"resultado": resultado, "texto": texto, "motivo": motivo, "codigos": list(codigos),
            "propuesta": propuesta if resultado == "respondida" else None,
            "uso": uso.como_dict() if uso else None, "vueltas": vueltas, "modelo": modelo,
            "simulado": simulado}


def consultar(*, modelo: str, sistema: str, punto: str, codigo: str, pregunta: str, herramientas: dict,
              codigos_validos, simular=None, opciones: dict | None = None,
              patron_codigo: str = PATRON_CODIGO) -> dict:
    """Una pregunta ya normalizada -> `{resultado, texto, motivo, codigos,
    propuesta, uso, vueltas, modelo, simulado}`. Nunca levanta: un fallo de la
    API es resultado `error`. `uso` es el consumo a registrar (None si no hubo
    llamada). No toca la base.

    `simular(punto, codigo, pregunta, llamar)` arma el texto en modo simulado
    llamando a las MISMAS herramientas con `llamar(nombre, args)`."""
    corrida = _Corrida(herramientas)
    disponible, simulado = estado()
    if simulado:
        def llamar(nombre, args=None):
            contenido, error = corrida.ejecutar(nombre, args or {})
            if error:
                raise ErrorHerramienta(contenido)
            return json.loads(contenido)
        try:
            texto = simular(punto, codigo, pregunta, llamar) if simular else None
        except ErrorHerramienta:
            texto = None
        v = validar(texto, visto="\n".join(corrida.visto), pregunta=pregunta,
                    codigos_validos=codigos_validos, patron_codigo=patron_codigo)
        prop = _propuesta_valida(corrida, pregunta, codigos_validos, patron_codigo) if v["ok"] else None
        return _salida("respondida" if v["ok"] else "fija", v["texto"], v["motivo"], corrida, None, 0,
                       "simulado", True, v["codigos"], prop)
    cli = cliente()
    uso = _Uso(modelo)
    if cli is None or not disponible:
        return _salida("error", TEXTO_ERROR, "sin cliente", corrida, None, 0, modelo, False)

    def fija(motivo, vueltas):
        return _salida("fija", TEXTO_FIJO, motivo, corrida, uso, vueltas, modelo, False)
    mensajes = [{"role": "user", "content": armar_mensaje(punto, codigo, pregunta)}]
    system = [{"type": "text", "text": sistema, "cache_control": {"type": "ephemeral"}}]
    tools = _definiciones(herramientas)
    inicio = time.perf_counter()
    vueltas = 0
    try:
        while vueltas < MAX_VUELTAS:
            restante = TIEMPO_TOTAL_S - (time.perf_counter() - inicio)
            if restante <= 1:
                return fija("se pasó del tiempo máximo", vueltas)
            vueltas += 1
            kwargs = {"model": modelo, "max_tokens": MAX_TOKENS, "timeout": min(TIMEOUT_S, restante),
                      "system": system, "messages": mensajes, "tool_choice": {"type": "auto"},
                      **(opciones or {})}
            if tools:
                kwargs["tools"] = tools
            msg = cli.messages.create(**kwargs)
            uso.sumar(msg)
            parada = getattr(msg, "stop_reason", None)          # SIEMPRE antes del contenido
            if parada == "refusal":
                return fija("el modelo declinó", vueltas)
            if parada == "max_tokens":
                return fija("la respuesta se cortó", vueltas)
            contenido = list(getattr(msg, "content", None) or [])
            if parada == "tool_use":
                usos = [b for b in contenido if getattr(b, "type", "") == "tool_use"]
                if not usos:
                    return fija("pidió una herramienta sin llamarla", vueltas)
                resultados = []
                for b in usos:
                    texto, error = corrida.ejecutar(getattr(b, "name", ""), getattr(b, "input", None))
                    r = {"type": "tool_result", "tool_use_id": b.id, "content": texto}
                    if error:
                        r["is_error"] = True
                    resultados.append(r)
                mensajes.append({"role": "assistant", "content": msg.content})   # el contenido ENTERO
                mensajes.append({"role": "user", "content": resultados})          # todos juntos, UN mensaje
                continue
            if parada != "end_turn":
                return fija(f"terminó por {parada}", vueltas)
            final = " ".join(x for x in (str(getattr(b, "text", "") or "").strip() for b in contenido
                                         if getattr(b, "type", "") == "text") if x)
            v = validar(final, visto="\n".join(corrida.visto), pregunta=pregunta,
                        codigos_validos=codigos_validos, patron_codigo=patron_codigo)
            prop = _propuesta_valida(corrida, pregunta, codigos_validos, patron_codigo) if v["ok"] else None
            return _salida("respondida" if v["ok"] else "fija", v["texto"], v["motivo"], corrida, uso, vueltas,
                           modelo, False, v["codigos"], prop)
        return fija("se agotaron las vueltas", vueltas)
    except Exception as e:          # noqa: BLE001 - red, saldo, tiempo, 4xx/5xx: se informa, no se esconde
        print(f"[xsii-ia] la API falló ({type(e).__name__}: {e})")
        return _salida("error", TEXTO_ERROR, f"la API falló ({type(e).__name__})", corrida, uso, vueltas,
                       modelo, False)
