"""Enmascarado de los datos que identifican a la persona, antes de que un
recibo o un comprobante salga hacia la IA (PLAN_ENMASCARADO.md).

Este módulo es PURO: no importa `db`, no lee archivos ni llama a ninguna API.
Recibe "palabras con posición" --de dónde salgan (el texto de un PDF digital
o el OCR de una foto) es asunto de `lectores.py`-- y decide qué se tapa. Así
se prueba solo, rápido, y la regla vive en un único lugar.

Tres detectores que se suman, porque ninguno alcanza solo:

1. **Lo que ya se conoce**: el CUIL de la sesión (y el DNI, que son sus ocho
   dígitos del medio), el nombre de la persona y la razón social del
   empleador. Buscar un texto conocido es mucho más confiable que reconocer
   uno desconocido.
2. **Patrones argentinos**: un número de 11 dígitos con prefijo de CUIL/CUIT
   Y dígito verificador válido. El verificador es lo que impide tapar un
   importe que por casualidad tenga 11 cifras.
3. **Rótulos**: el valor que acompaña a "CUIL", "Apellido y nombre",
   "Legajo", "DNI", "Cuenta", "Razón social"... (en la misma frase, a la
   derecha o en la fila de abajo). Es lo que cubre al aprendizaje del admin,
   donde no hay sesión del afiliado, y a una Ñ o un acento que el OCR leyó
   mal. Cada valor se valida por su tipo antes de taparse y **un importe
   nunca se tapa**; los rótulos se ignoran dentro de la tabla de conceptos,
   donde "A CUENTA DE FUTUROS AUMENTOS" no es una cuenta bancaria.

**Se trabaja por FRASE, no por palabra**: una frase es una tira de palabras
contiguas de la misma línea. Un PDF trae "Apellido y Nombre:" como tres
palabras y el OCR puede partir "27 - 99999999 - 9" en tres cajas; mirando
palabra por palabra, ni el rótulo ni el CUIL existen. Una frase se corta en
los huecos grandes, así dos columnas vecinas no se leen como un solo número.

Después, `control_de_fuga()` revisa que no quede nada a la vista: si queda
algo, el recibo no sale.

Las coordenadas son las de la imagen de la página que se va a mandar
(píxeles, origen arriba a la izquierda), así `tapar()` las usa tal cual.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# ======================= Tipos =======================


@dataclass(frozen=True)
class Palabra:
    """Un trozo de texto con su caja en la imagen de la página. Puede ser una
    palabra o varias (el OCR a veces junta "CUIT: 30-44464097-5")."""
    texto: str
    x0: float
    y0: float
    x1: float
    y1: float
    pagina: int = 0

    @property
    def alto(self) -> float:
        return max(1.0, self.y1 - self.y0)

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass(frozen=True)
class Caja:
    """Una zona a tapar. `tipo` dice qué rótulo se pinta encima; `texto` es
    el original y NO sale del servidor (sirve para rearmar y para depurar)."""
    x0: float
    y0: float
    x1: float
    y1: float
    pagina: int
    tipo: str
    texto: str
    motivo: str  # "conocido" | "patron" | "rotulo" | "forma_juridica" | "aprendido"


@dataclass(frozen=True)
class Conocidos:
    """Lo que la app ya sabe antes de leer. Todo opcional: en el aprendizaje
    del admin no hay sesión de afiliado y solo trabajan patrones y rótulos."""
    cuil: str = ""
    nombre: str = ""
    razones_sociales: tuple[str, ...] = ()


@dataclass
class Analisis:
    cajas: list[Caja] = field(default_factory=list)
    cuiles: list[str] = field(default_factory=list)   # 11 dígitos, personas
    cuits: list[str] = field(default_factory=list)    # 11 dígitos, empresas (30/33/34)
    cuil_sesion_encontrado: bool | None = None        # None: no había CUIL de sesión
    nombre_encontrado: bool | None = None


# Rótulo que se pinta sobre cada zona, según su tipo.
ETIQUETAS = {
    "cuil": "CUIL OCULTO",
    "cuit": "CUIT OCULTO",
    "dni": "DNI OCULTO",
    "nombre": "NOMBRE OCULTO",
    "legajo": "LEGAJO OCULTO",
    "cuenta": "CUENTA OCULTA",
    "razon_social": "EMPLEADOR OCULTO",
}

# ======================= Normalización =======================


def _sin_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s or "")
                   if not unicodedata.combining(c))


def _letras(s: str) -> str:
    """Solo letras, en mayúscula y sin acentos: 'Nieves, Julia' -> 'NIEVESJULIA'."""
    return re.sub(r"[^A-Z]", "", _sin_acentos(s).upper())


def _alnum(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", _sin_acentos(s).upper())


def _norm(s: str) -> str:
    """Mayúscula, sin acentos, la puntuación como espacio y espacios simples."""
    return re.sub(r"[^A-Z0-9]+", " ", _sin_acentos(s).upper()).strip()


def _digitos(s: str) -> str:
    return re.sub(r"\D", "", s or "")


# ======================= CUIL / CUIT / DNI =======================

PREFIJOS_PERSONA = {"20", "23", "24", "25", "26", "27"}
PREFIJOS_EMPRESA = {"30", "33", "34"}
_PESOS = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)

# 11 dígitos con o sin separadores (guion, punto, barra, espacios alrededor),
# sin estar pegados a otros dígitos: "27-99999999-9", "30444640975",
# "20 - 12345678 - 3" (así lo puede partir un OCR).
_SEP = r"\s?[\-./]?\s?"
_RE_ONCE = re.compile(r"(?<!\d)\d{2}" + _SEP + r"\d{8}" + _SEP + r"\d(?!\d)")
# DNI: 7 u 8 dígitos, con o sin puntos de miles ("28.765.431", "28. 765. 431").
_RE_DNI = re.compile(r"(?<!\d)\d{1,2}\s?\.?\s?\d{3}\s?\.?\s?\d{3}(?!\d)")


def dv_valido(once: str) -> bool:
    """Dígito verificador de un CUIL/CUIT de 11 dígitos (módulo 11)."""
    if not re.fullmatch(r"\d{11}", once or ""):
        return False
    s = sum(int(d) * p for d, p in zip(once[:10], _PESOS))
    r = 11 - s % 11
    r = 0 if r == 11 else r
    return r != 10 and r == int(once[10])


def _es_persona(once: str) -> bool:
    return once[:2] in PREFIJOS_PERSONA


def _es_empresa(once: str) -> bool:
    return once[:2] in PREFIJOS_EMPRESA


def dni_de_cuil(cuil: str) -> str:
    """El DNI son los 8 dígitos del medio del CUIL, sin ceros a la izquierda."""
    d = _digitos(cuil)
    return d[2:10].lstrip("0") if len(d) == 11 else ""


# ======================= Importes =======================

# "$ 1.234,56", "1234,56", "-110.000,00", "345100.00". Lo que parece plata no
# se tapa NUNCA, venga del detector que venga.
_RE_IMPORTE = re.compile(r"^-?\$?\s*-?\d{1,3}([.\s]\d{3})*[,.]\d{2}-?$|^-?\$?\s*-?\d+[,.]\d{2}-?$")


def parece_importe(texto: str) -> bool:
    t = (texto or "").strip()
    return "$" in t or bool(_RE_IMPORTE.match(t))


# ======================= Rótulos =======================

# (tipo, expresión sobre el texto normalizado). Tienen que terminar en espacio
# o fin: "EMPLEADO" es un rótulo, "EMPLEADOR" otro, y "LEY 19032" no es "LE"
# (libreta de enrolamiento). Anclados al principio de la palabra donde
# arrancan: "CUENTA" es un rótulo, "A CUENTA DE FUTUROS AUMENTOS" no.
_ROTULOS = [
    # "CUILN": Tesseract junta "CUIL N" (N de número) en una sola palabra.
    ("cuil", r"C ?U ?I ?L( ?N[RO]?O?)?( N)?"),
    ("cuit", r"C ?U ?I ?T( ?N[RO]?O?)?( N)?( EMPLEADOR)?"),
    ("dni", r"(D ?N ?I|L ?E|L ?C|DOCUMENTO|NRO DOC|N DOC|N[RO]?O? DE DOCUMENTO"
            r"|TIPO Y NRO DE DOC(UMENTO)?|DOC(UMENTO)? NRO)( N[RO]?O?)?"),
    ("legajo", r"(NRO DE )?LEG(AJO)?( N[RO]?O?)?( N)?"),
    ("nombre", r"(APELLIDOS? Y NOMBRES?|NOMBRES? Y APELLIDOS?|APELLIDO NOMBRE|NOMBRE"
               r"|EMPLEADO|TRABAJADOR|AGENTE|BENEFICIARIO)"),
    ("cuenta", r"(SUCURSAL )?(NRO |N )?(DE )?(CUENTA|CTA|CBU|C B U)( BANCARIA)?( N[RO]?O?)?"),
    ("razon_social", r"(RAZON SOCIAL|EMPLEADOR|EMPRESA)"),
]
_ROTULOS_RE = [(t, re.compile(r"^(?:" + p + r")(?=\s|$)")) for t, p in _ROTULOS]

# Formas jurídicas que acompañan a la razón social ("S. R. L.", "SOCIEDAD ANONIMA").
_FORMAS_JURIDICAS = {
    "SA", "SRL", "SAS", "SCA", "SAU", "SOCIEDADANONIMA",
    "SOCIEDADDERESPONSABILIDADLIMITADA", "SOCIEDADANONIMASIMPLIFICADA",
    "COOPERATIVA", "COOPERATIVALIMITADA",
}

# Encabezados de la tabla de conceptos y cierre de la tabla.
_INICIO_TABLA = {"DESCRIPCION", "CONCEPTO", "CONCEPTOS", "DETALLEDELALIQUIDACION",
                 "HABERES", "DEDUCCIONES", "IMPORTE", "UNIDADES", "CANTIDAD",
                 "REMUNERATIVO", "REMUNERATIVOS"}
_FIN_TABLA = re.compile(r"^(TOTAL|NETO|SUBTOTAL)")


def valor_valido(tipo: str, texto: str) -> bool:
    """¿Este texto puede ser el valor de un rótulo de ese tipo? Es la barrera
    que impide tapar un importe o una descripción por estar al lado de un
    rótulo."""
    t = (texto or "").strip()
    if not t or parece_importe(t):
        return False
    d = _digitos(t)
    letras = _letras(t)
    if tipo in ("cuil", "cuit"):
        return len(d) == 11
    if tipo == "dni":
        return 7 <= len(d) <= 8 and len(letras) <= 3
    if tipo == "legajo":
        return len(t) <= 15 and bool(d)
    if tipo == "cuenta":
        return len(d) >= 6 and len(letras) <= 3
    if tipo == "nombre":
        return len(letras) >= 3 and not d
    if tipo == "razon_social":
        return len(letras) >= 3
    return False


# ======================= Frases =======================


def _misma_linea(a, b) -> bool:
    """Se solapan verticalmente en al menos la mitad del más bajo. Sirve para
    palabras, frases y cajas (todas tienen y0/y1)."""
    arriba = max(a.y0, b.y0)
    abajo = min(a.y1, b.y1)
    return abajo - arriba >= 0.5 * max(1.0, min(a.y1 - a.y0, b.y1 - b.y0))


@dataclass
class _Frase:
    """Palabras contiguas de una misma línea. `texto` las une con un espacio
    y `tramos[k]` dice qué caracteres de `texto` son la palabra `idx[k]`."""
    idx: list[int]
    texto: str
    tramos: list[tuple[int, int]]
    x0: float
    y0: float
    x1: float
    y1: float
    pagina: int

    @property
    def alto(self) -> float:
        return max(1.0, self.y1 - self.y0)

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    def palabras_en(self, ini: int, fin: int) -> list[int]:
        """Índices de las palabras que tocan el tramo [ini, fin) del texto."""
        return [i for i, (a, b) in zip(self.idx, self.tramos) if a < fin and b > ini]


def _frase(idx: list[int], pal: list[Palabra]) -> _Frase:
    partes, tramos, pos = [], [], 0
    for i in idx:
        t = pal[i].texto
        tramos.append((pos, pos + len(t)))
        partes.append(t)
        pos += len(t) + 1
    ps = [pal[i] for i in idx]
    return _Frase(idx, " ".join(partes), tramos, min(p.x0 for p in ps), min(p.y0 for p in ps),
                  max(p.x1 for p in ps), max(p.y1 for p in ps), ps[0].pagina)


def _frases(pal: list[Palabra]) -> list[_Frase]:
    """Agrupa en líneas y corta cada línea en los huecos grandes (más de 1,2
    veces el alto de la letra): así "CUIL: 27-...-9" es una frase y dos
    columnas de la tabla no lo son."""
    frases = []
    for pag in sorted({p.pagina for p in pal}):
        idx = sorted((i for i, p in enumerate(pal) if p.pagina == pag), key=lambda i: pal[i].cy)
        lineas: list[list[int]] = []
        for i in idx:
            for ln in lineas:
                if _misma_linea(pal[ln[-1]], pal[i]):
                    ln.append(i)
                    break
            else:
                lineas.append([i])
        for ln in lineas:
            ln.sort(key=lambda i: pal[i].x0)
            actual = [ln[0]]
            for a, b in zip(ln, ln[1:]):
                h = max(pal[a].alto, pal[b].alto)
                if pal[b].x0 - pal[a].x1 > 1.2 * h:
                    frases.append(_frase(actual, pal))
                    actual = []
                actual.append(b)
            frases.append(_frase(actual, pal))
    return frases


def _zonas_tabla(frases: list[_Frase]) -> dict[int, list[tuple[float, float]]]:
    """Por página, las franjas verticales (y0, y1) de la tabla de conceptos:
    desde la fila de su encabezado hasta la de totales. Puede haber más de
    una por página (original y duplicado en la misma hoja)."""
    zonas: dict[int, list] = {}
    for pag in sorted({f.pagina for f in frases}):
        orden = sorted((f for f in frases if f.pagina == pag), key=lambda f: (f.y0, f.x0))
        # Un título de columna es una frase que ES la palabra ("Concepto",
        # "Importe"), no una que la contiene: "RECIBO DE HABERES" es el
        # encabezado del recibo, no el de la tabla. Y hace falta una FILA de
        # títulos (dos o más en la misma línea), salvo "Detalle de la liquidación".
        titulos = [f for f in orden if _alnum(f.texto) in _INICIO_TABLA]
        inicio = None
        for f in orden:
            fila = [t for t in titulos if _misma_linea(t, f)]
            es_encabezado = f in titulos and (len(fila) >= 2 or _alnum(f.texto) == "DETALLEDELALIQUIDACION")
            if inicio is None and es_encabezado:
                inicio = f.y0
            elif inicio is not None and f.y0 > inicio + f.alto and _FIN_TABLA.match(_alnum(f.texto)):
                zonas.setdefault(pag, []).append((inicio, f.y0))
                inicio = None
        if inicio is not None:
            zonas.setdefault(pag, []).append((inicio, max(f.y1 for f in orden)))
    return zonas


def _en_tabla(f: _Frase, zonas) -> bool:
    return any(y0 <= f.cy < y1 for y0, y1 in zonas.get(f.pagina, []))


# ======================= Rótulos dentro de una frase =======================


def _rotulos_de(f: _Frase) -> list[tuple[str, int, int]]:
    """Rótulos que arrancan en alguna palabra de la frase: (tipo, inicio,
    fin) como posiciones del texto crudo de la frase."""
    encontrados = []
    for k, (a, _) in enumerate(f.tramos):
        # Texto normalizado desde esta palabra, con el mapa de vuelta al crudo.
        norm, mapa = [], []
        for j in range(k, len(f.tramos)):
            pa, pb = f.tramos[j]
            for m in re.finditer(r"[A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñºª°]+", f.texto[pa:pb]):
                if norm:
                    norm.append(" ")
                    mapa.append(pa + m.start())
                for pos, ch in enumerate(m.group()):
                    norm.append(_sin_acentos(ch).upper() or ch)
                    mapa.append(pa + m.start() + pos)
        texto = "".join(norm)
        if not texto or (encontrados and a < encontrados[-1][2]):
            continue
        for tipo, rx in _ROTULOS_RE:
            m = rx.match(texto)
            if m:
                fin = mapa[m.end() - 1] + 1
                # "Nº", ":" y similares pegados al rótulo son parte del rótulo.
                while fin < len(f.texto) and f.texto[fin] in ":.º°ª#":
                    fin += 1
                encontrados.append((tipo, a, fin))
                break
    return encontrados


# ======================= Análisis =======================


def _tokens_nombre(nombre: str) -> list[str]:
    return [t for t in (_letras(x) for x in re.split(r"[\s,;]+", nombre or "")) if len(t) >= 3]


def _nombre_en(texto: str, tokens: list[str]) -> bool:
    """¿La palabra es parte del nombre conocido? Tokens de 4+ letras como
    subcadena (el OCR junta "NIEVES,JULIA" en una sola caja); los cortos
    (PAZ, RUIZ) solo si la palabra es exactamente ese token."""
    letras = _letras(texto)
    if not letras:
        return False
    return any((len(t) >= 4 and t in letras) or (len(t) < 4 and letras == t) for t in tokens)


def _tramos_razon(f: _Frase, razones: list[str]) -> list[list[int]]:
    """Tiras de palabras consecutivas cuyo texto junto es parte de una razón
    social conocida y mide 6+ caracteres ("LOS ANDES" solo no alcanza, pero
    "DISTRIBUIDORA LOS ANDES S. R. L." entero sí)."""
    salida = []
    k = 0
    while k < len(f.idx):
        mejor = None
        junto = ""
        for j in range(k, len(f.idx)):
            a, b = f.tramos[j]
            junto += _alnum(f.texto[a:b])
            if not junto or not any(junto in r for r in razones):
                break
            if len(junto) >= 6:
                mejor = j
        # Una palabra suelta que CONTIENE la razón (el OCR la juntó con otra).
        a, b = f.tramos[k]
        suelta = _alnum(f.texto[a:b])
        if mejor is None and len(suelta) >= 6 and any(r in suelta for r in razones):
            mejor = k
        if mejor is not None:
            salida.append(f.idx[k:mejor + 1])
            k = mejor + 1
        else:
            k += 1
    return salida


def _tramos_forma_juridica(f: _Frase) -> list[list[int]]:
    salida = []
    for k in range(len(f.idx)):
        junto = ""
        for j in range(k, len(f.idx)):
            a, b = f.tramos[j]
            if _digitos(f.texto[a:b]):
                break
            junto += _letras(f.texto[a:b])
            if junto in _FORMAS_JURIDICAS and (j + 1 == len(f.idx) or
                                                junto + _letras(f.texto[slice(*f.tramos[j + 1])])
                                                not in _FORMAS_JURIDICAS):
                salida.append(f.idx[k:j + 1])
                break
    return salida


def _valor_de(f: _Frase, ini: int, fin: int) -> str:
    return f.texto[ini:fin].strip(" :.-")


def _vecina(r: _Frase, frases: list[_Frase], rotuladas: set[int], yo: int,
            tipo: str) -> int | None:
    """El valor de un rótulo que quedó solo en su frase: la frase de la
    derecha si está cerca, si no la de la fila de abajo cuyo centro queda más
    cerca del centro del rótulo -- y solo si ese valor no le queda más cerca
    a OTRO rótulo de la misma fila (encabezados en columnas: Legajo |
    Apellido y nombre | CUIL, con los valores debajo)."""
    h = r.alto
    derecha = [j for j, f in enumerate(frases)
               if j != yo and j not in rotuladas and f.pagina == r.pagina and _misma_linea(r, f)
               and f.x0 >= r.x1 - 2 and f.x0 - r.x1 <= max(8 * h, 80)]
    derecha.sort(key=lambda j: frases[j].x0)
    if derecha and valor_valido(tipo, frases[derecha[0]].texto):
        return derecha[0]
    banda = [j for j, f in enumerate(frases)
             if j not in rotuladas and f.pagina == r.pagina
             and r.y1 - 0.3 * h <= f.y0 <= r.y1 + 2.2 * h and not _misma_linea(r, f)]
    if not banda:
        return None
    # Solo la PRIMERA fila de abajo: la segunda es otra fila de rótulos o de
    # valores ajenos ("Categoria" quedaba más centrada bajo "Apellido y
    # nombre" que el nombre mismo).
    primera = min(banda, key=lambda j: frases[j].y0)
    banda = [j for j in banda if _misma_linea(frases[j], frases[primera])]
    k = min(banda, key=lambda j: abs(frases[j].cx - r.cx))
    cand = frases[k]
    if abs(cand.cx - r.cx) > max(r.x1 - r.x0, cand.x1 - cand.x0) + 4 * h:
        return None
    pares = [frases[j] for j in rotuladas if j != yo and frases[j].pagina == r.pagina
             and _misma_linea(frases[j], r)]
    if any(abs(cand.cx - o.cx) < abs(cand.cx - r.cx) for o in pares):
        return None
    return k if valor_valido(tipo, cand.texto) else None


def _identidades(f: _Frase):
    """(once, [índices de palabras]) de cada número de 11 dígitos de la frase."""
    for m in _RE_ONCE.finditer(f.texto):
        yield _digitos(m.group()), f.palabras_en(m.start(), m.end())


def _dnis(f: _Frase):
    for m in _RE_DNI.finditer(f.texto):
        yield _digitos(m.group()).lstrip("0"), f.palabras_en(m.start(), m.end())


def analizar(palabras: list[Palabra], conocidos: Conocidos | None = None) -> Analisis:
    """Decide qué se tapa. No modifica nada: devuelve las cajas y lo que leyó
    de identidad (CUILes y CUITs), que es con lo que se rearma el resultado y
    se verifica que el recibo sea de quien lo sube."""
    c = conocidos or Conocidos()
    cuil_s = _digitos(c.cuil)
    dni_s = dni_de_cuil(cuil_s)
    tokens = _tokens_nombre(c.nombre)
    razones = [_alnum(r) for r in c.razones_sociales if len(_alnum(r)) >= 6]

    res = Analisis()
    marcadas: dict[int, Caja] = {}

    def marcar(indices, tipo: str, motivo: str):
        for i in indices:
            p = palabras[i]
            if i in marcadas or parece_importe(p.texto):
                continue
            marcadas[i] = Caja(p.x0, p.y0, p.x1, p.y1, p.pagina, tipo, p.texto, motivo)

    def leido(once: str, tipo: str):
        lista = res.cuits if tipo == "cuit" else res.cuiles
        if once not in lista:
            lista.append(once)

    frases = _frases(palabras)

    # 1 y 2: lo conocido y los patrones.
    for f in frases:
        for once, idx in _identidades(f):
            conocido = bool(cuil_s) and once == cuil_s
            if conocido or (dv_valido(once) and (_es_persona(once) or _es_empresa(once))):
                tipo = "cuit" if _es_empresa(once) else "cuil"
                marcar(idx, tipo, "conocido" if conocido else "patron")
                leido(once, tipo)
        if dni_s:
            for dni, idx in _dnis(f):
                if dni == dni_s:
                    marcar(idx, "dni", "conocido")
        if razones:
            for idx in _tramos_razon(f, razones):
                marcar(idx, "razon_social", "conocido")
        for idx in _tramos_forma_juridica(f):
            marcar(idx, "razon_social", "forma_juridica")
    if tokens:
        for i, p in enumerate(palabras):
            if _nombre_en(p.texto, tokens):
                marcar([i], "nombre", "conocido")

    # 3: rótulos, fuera de la tabla de conceptos.
    zonas = _zonas_tabla(frases)
    rotulos = {j: _rotulos_de(f) for j, f in enumerate(frases) if not _en_tabla(f, zonas)}
    rotulos = {j: r for j, r in rotulos.items() if r}
    for j, lista in rotulos.items():
        f = frases[j]
        for n, (tipo, _ini, fin) in enumerate(lista):
            hasta = lista[n + 1][1] if n + 1 < len(lista) else len(f.texto)
            valor = _valor_de(f, fin, hasta)
            if valor:
                if valor_valido(tipo, valor):
                    idx = f.palabras_en(fin, hasta)
                    marcar(idx, tipo, "rotulo")
                    if tipo in ("cuil", "cuit"):
                        leido(_digitos(valor), tipo)
                continue
            # Rótulo solo: el valor está en otra frase. Solo para el último
            # rótulo de la frase (los anteriores tienen el siguiente al lado).
            if n + 1 < len(lista):
                continue
            k = _vecina(f, frases, set(rotulos), j, tipo)
            if k is not None:
                marcar(frases[k].idx, tipo, "rotulo")
                if tipo in ("cuil", "cuit"):
                    leido(_digitos(frases[k].texto), tipo)

    # 4: razón social sin rótulo. Una frase sin números que lleva una forma
    # jurídica ("DISTRIBUIDORA LOS ANDES S.R.L.") es la razón social entera;
    # si la forma jurídica está sola en su línea ("SOCIEDAD ANONIMA"), la
    # razón social es la línea de arriba.
    for f in frases:
        formas = _tramos_forma_juridica(f)
        if not formas or _digitos(f.texto):
            continue
        if len(formas[0]) < len(f.idx):
            marcar(f.idx, "razon_social", "forma_juridica")
            continue
        arriba = [g for g in frases if g.pagina == f.pagina and g is not f
                  and f.y0 - 2.5 * f.alto <= g.y1 <= f.y0 + 0.3 * f.alto
                  and min(f.x1, g.x1) - max(f.x0, g.x0) > 0 and not _digitos(g.texto)]
        if arriba:
            marcar(max(arriba, key=lambda g: g.y1).idx, "razon_social", "forma_juridica")

    # 5: lo que se tapó por rótulo o por forma jurídica se APRENDE y se busca
    # en el resto del documento: el nombre se repite al pie, para la firma, y
    # la razón social en el logo. Es lo que cubre al aprendizaje del admin,
    # donde no hay nada conocido de antemano.
    aprendido_nombre = _tokens_nombre(" ".join(k.texto for k in marcadas.values()
                                               if k.tipo == "nombre" and k.motivo == "rotulo"))
    aprendido_nombre = [t for t in aprendido_nombre if t not in tokens and len(t) >= 4]
    aprendidas_razones = {_alnum(" ".join(palabras[i].texto for i in f.idx if i in marcadas
                                          and marcadas[i].tipo == "razon_social"))
                          for f in frases}
    aprendidas_razones = [r for r in aprendidas_razones
                          if len(r) >= 8 and r not in _FORMAS_JURIDICAS and r not in razones]
    if aprendido_nombre:
        for i, p in enumerate(palabras):
            if _nombre_en(p.texto, aprendido_nombre):
                marcar([i], "nombre", "aprendido")
    if aprendidas_razones:
        for f in frases:
            for idx in _tramos_razon(f, aprendidas_razones):
                marcar(idx, "razon_social", "aprendido")

    res.cajas = sorted(marcadas.values(), key=lambda k: (k.pagina, k.y0, k.x0))
    res.cuil_sesion_encontrado = (cuil_s in res.cuiles) if cuil_s else None
    res.nombre_encontrado = any(k.tipo == "nombre" for k in res.cajas) if tokens else None
    return res


def pertenece(analisis: Analisis, cuil_sesion: str) -> bool | None:
    """¿El documento es de quien lo sube? True: su CUIL está. False: hay otro
    CUIL de persona y el suyo no. None: no se leyó ningún CUIL (foto mala,
    recorte) -- lo decide quien llama, según la política del plan (§6)."""
    cuil = _digitos(cuil_sesion)
    if cuil in analisis.cuiles:
        return True
    return False if analisis.cuiles else None


def control_de_fuga(palabras: list[Palabra], cajas: list[Caja],
                    conocidos: Conocidos | None = None) -> list[str]:
    """Lo que quedaría a la vista después de tapar. Lista vacía = se puede
    mandar. Vuelve a buscar por su cuenta (sin mirar cómo se decidió cada
    caja) el CUIL, el DNI, el nombre y la razón social conocidos y cualquier
    CUIL o CUIT con verificador válido, y reclama si alguna palabra de esas
    no quedó debajo de una caja."""
    c = conocidos or Conocidos()
    cuil_s = _digitos(c.cuil)
    dni_s = dni_de_cuil(cuil_s)
    tokens = _tokens_nombre(c.nombre)
    razones = [_alnum(r) for r in c.razones_sociales if len(_alnum(r)) >= 6]

    def cubierta(i: int) -> bool:
        p = palabras[i]
        return any(k.pagina == p.pagina and k.x0 <= p.cx <= k.x1 and k.y0 <= p.cy <= k.y1
                   for k in cajas)

    fugas = []

    def revisar(idx, motivo):
        visibles = [i for i in idx if not cubierta(i) and not parece_importe(palabras[i].texto)]
        if visibles:
            fugas.append(f"página {palabras[visibles[0]].pagina + 1}: {motivo}")

    for f in _frases(palabras):
        for once, idx in _identidades(f):
            if (cuil_s and once == cuil_s) or (dv_valido(once) and (_es_persona(once) or _es_empresa(once))):
                revisar(idx, "CUIL/CUIT")
        if dni_s:
            for dni, idx in _dnis(f):
                if dni == dni_s:
                    revisar(idx, "DNI")
        if razones:
            for idx in _tramos_razon(f, razones):
                revisar(idx, "razón social")
    if tokens:
        for i, p in enumerate(palabras):
            if _nombre_en(p.texto, tokens):
                revisar([i], "nombre")
    return fugas


# ======================= Tapar =======================


def tapar(imagen, cajas: list[Caja], margen: int = 3):
    """Devuelve una COPIA de la imagen (PIL) con las cajas cubiertas por un
    rótulo gris claro ("CUIL OCULTO"). Palabras vecinas del mismo tipo se
    cubren con un solo rótulo. No es un rectángulo negro a propósito: la IA
    lo leería como una tachadura y dispararía la alerta de adulteración, y un
    campo que dice qué había deja al modelo devolver `null` en vez de
    inventar. Las cajas tienen que ser todas de la misma página."""
    from PIL import ImageDraw, ImageFont

    img = imagen.convert("RGB").copy()
    dib = ImageDraw.Draw(img)
    for k in _unir(cajas):
        x0, y0 = max(0, k.x0 - margen), max(0, k.y0 - margen)
        x1, y1 = min(img.width, k.x1 + margen), min(img.height, k.y1 + margen)
        dib.rectangle([x0, y0, x1, y1], fill=(232, 232, 232), outline=(110, 110, 110), width=1)
        alto_max = max(9, int((y1 - y0) * 0.6))
        # El rótulo completo si entra con letra legible (9 px o más); si no
        # (un legajo de cuatro cifras), "OCULTO" a secas; si tampoco, nada.
        for etiqueta in (ETIQUETAS.get(k.tipo, "DATO OCULTO"), "OCULTO"):
            alto = alto_max
            fuente = ImageFont.load_default(size=alto)
            while alto > 9 and dib.textlength(etiqueta, font=fuente) > (x1 - x0) - 4:
                alto -= 1
                fuente = ImageFont.load_default(size=alto)
            if dib.textlength(etiqueta, font=fuente) <= (x1 - x0) - 4:
                break
        else:
            continue
        ancho = dib.textlength(etiqueta, font=fuente)
        dib.text(((x0 + x1 - ancho) / 2, (y0 + y1 - alto) / 2), etiqueta,
                 fill=(60, 60, 60), font=fuente)
    return img


def _unir(cajas: list[Caja]) -> list[Caja]:
    """Junta cajas del mismo tipo que están en la misma línea y pegadas
    ("GONZÁLEZ" "PEÑA," "MARÍA" "JOSÉ" -> un solo NOMBRE OCULTO)."""
    salida: list[Caja] = []
    for k in sorted(cajas, key=lambda c: (c.pagina, c.tipo, round(c.y0), c.x0)):
        if salida:
            u = salida[-1]
            alto = max(u.y1 - u.y0, k.y1 - k.y0, 1)
            if (u.pagina == k.pagina and u.tipo == k.tipo and _misma_linea(u, k)
                    and k.x0 - u.x1 <= 1.2 * alto):
                salida[-1] = Caja(u.x0, min(u.y0, k.y0), max(u.x1, k.x1), max(u.y1, k.y1),
                                  u.pagina, u.tipo, f"{u.texto} {k.texto}", u.motivo)
                continue
        salida.append(k)
    return salida
