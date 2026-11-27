"""Tarea asistida EST-01: cargar las seccionales (y Sede Central) desde una
planilla CSV. Contrato: docs/xsii/API.md, «Bloque 3».

`leer` es PURA (sin base, sin red): clasifica cada fila y calcula qué se
escribiría; la comparten el ensayo y la carga, así que lo que el ensayo muestra
es exactamente lo que la carga escribe. `ensayar` y `cargar` solo agregan la
lectura de las seccionales que ya tiene el sindicato (y, en la carga, la
escritura, SIN commit: lo hace la ruta, todo o nada).

No se geocodifica nada: ningún servicio externo. Una fila sin coordenadas se
carga igual, marcada «sin ubicar» (X21); coordenadas de la planilla quedan con
precisión `manual` (X23).
"""

from __future__ import annotations

import csv
import io
import math
import re
import unicodedata

from sqlmodel import select

import geo
import listas

from .base import ErrorAsistida, huella

NOMBRE_ARCHIVO = "modelo-seccionales.csv"
TOPE_FILAS = 500
TOPE_BYTES = 1024 * 1024
LARGO_NOMBRE = 120
# Argentina continental (X-contrato): afuera de esto, la coordenada es un error.
LAT_RANGO = (-56.0, -21.0)
LON_RANGO = (-74.0, -53.0)

DOMICILIO = ("calle", "numero", "piso_depto", "localidad", "provincia", "codigo_postal")
CONTACTO = {"telefono": 40, "whatsapp": 40, "mail": 200, "horario_atencion": 300}
CAMPOS_COMPARABLES = ("ve_todas", *DOMICILIO, "direccion_texto", "latitud", "longitud",
                      "precision_geo", *CONTACTO)

_RE_MAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SI = {"si", "s", "1", "true", "verdadero", "x", "yes", "y"}
_NO = {"", "no", "n", "0", "false", "falso"}
_NOMBRES_DE_SEDE = {"sede_central", "casa_central"}

# (clave, rótulo, obligatoria, ejemplo, ayuda). Un alias más por columna: lo
# que las planillas del sindicato suelen llamar distinto.
COLUMNAS = (
    ("nombre", "Nombre", True, "Seccional Rosario",
     "Cómo se llama la seccional. Es lo único obligatorio y no puede repetirse."),
    ("sede_central", "Es Sede Central", False, "no",
     "«sí» en la fila de Sede Central: sus usuarios ven todas las seccionales."),
    ("provincia", "Provincia", False, "Santa Fe", "Provincia del domicilio."),
    ("localidad", "Localidad", False, "Rosario", "Ciudad o localidad del domicilio."),
    ("calle", "Calle", False, "Córdoba", "Calle, sin el número."),
    ("numero", "Número", False, "1234", "Altura de la calle."),
    ("piso_depto", "Piso o depto", False, "3° B", "Piso o departamento, si tiene."),
    ("codigo_postal", "Código postal", False, "2000", "Código postal, si lo tienen."),
    ("latitud", "Latitud", False, "-32,9468",
     "Latitud en grados decimales. Si falta, la seccional queda «sin ubicar»."),
    ("longitud", "Longitud", False, "-60,6393",
     "Longitud en grados decimales. Va junto con la latitud."),
    ("telefono", "Teléfono", False, "341 555-0100", "Teléfono de atención."),
    ("whatsapp", "WhatsApp", False, "341 155-550100", "WhatsApp de atención."),
    ("mail", "Mail", False, "rosario@sindicato.example", "Mail de atención."),
    ("horario", "Horario de atención", False, "Lunes a viernes de 9 a 17",
     "Días y horas de atención."),
)
_ALIAS = {"horario": ("horario_atencion", "horarios"), "sede_central": ("sede",)}

OPCIONES = (
    {"clave": "actualizar_existentes", "rotulo": "Actualizar las que ya existen",
     "ayuda": "Si una seccional de la planilla ya está cargada (mismo nombre), le actualiza el domicilio y "
              "el contacto con lo que traiga la planilla. Nunca borra nada ni le saca el alcance sobre todo el sindicato.",
     "defecto": False},
    {"clave": "sede_por_nombre", "rotulo": "Marcar Sede Central por el nombre",
     "ayuda": "Si una fila se llama «Sede Central» o «Casa Central» y no la marcaste, la marca como Sede Central.",
     "defecto": True},
)


# ------------------------------------------------------------------ describir

def _columna_json(c) -> dict:
    return {"clave": c[0], "rotulo": c[1], "obligatoria": c[2], "ejemplo": c[3], "ayuda": c[4]}


def modelo_csv() -> str:
    """La planilla para completar: cabecera con las claves y dos filas de
    ejemplo. Punto y coma y decimales con coma, que es lo que Excel en
    castellano abre y guarda sin pelear."""
    salida = io.StringIO()
    w = csv.writer(salida, delimiter=";", lineterminator="\n")
    w.writerow([c[0] for c in COLUMNAS])
    w.writerow(["Sede Central", "sí", "Ciudad Autónoma de Buenos Aires", "Ciudad Autónoma de Buenos Aires",
                "Avenida de Mayo", "1500", "", "1085", "-34,6091", "-58,3896", "11 5555-0100",
                "11 5555-0101", "sede@sindicato.example", "Lunes a viernes de 9 a 17"])
    w.writerow(["Seccional Rosario", "no", "Santa Fe", "Rosario", "Córdoba", "1234", "", "2000", "-32,9468",
                "-60,6393", "341 555-0100", "", "rosario@sindicato.example", "Lunes a viernes de 9 a 17"])
    return "﻿" + salida.getvalue()


def describir() -> dict:
    return {
        "titulo": "Seccionales y Sede Central desde una planilla",
        "que_voy_a_hacer": [
            "Leo la planilla y te muestro, fila por fila, qué cargaría y qué no: en el ensayo no se guarda nada.",
            "Si estás de acuerdo, cargo las seccionales de una vez, controlo el resultado y dejo registrado quién lo hizo.",
        ],
        "insumo": "lista_seccionales",
        "columnas": [_columna_json(c) for c in COLUMNAS],
        "modelo_csv": modelo_csv(),
        "opciones": [dict(o) for o in OPCIONES],
    }


def normalizar_opciones(opciones) -> dict:
    """Las opciones completas, con su defecto. Una opción que no es verdadero o
    falso es un error del pedido (400); una clave desconocida se ignora."""
    if opciones is None:
        opciones = {}
    if not isinstance(opciones, dict):
        raise ErrorAsistida(400, "Las opciones tienen que ser un objeto.")
    salida = {}
    for o in OPCIONES:
        valor = opciones.get(o["clave"], o["defecto"])
        if not isinstance(valor, bool):
            raise ErrorAsistida(400, f"La opción «{o['rotulo']}» tiene que ser verdadero o falso.")
        salida[o["clave"]] = valor
    return salida


# ------------------------------------------------------------------ lectura

def _limpiar(valor) -> str:
    """El texto de una celda sin caracteres de control ni invisibles; los
    espacios raros pasan a espacio común y se recortan los bordes. Lo que
    empieza con = + - @ se deja tal cual (no es una planilla de salida)."""
    salida = []
    for c in str(valor or ""):
        cat = unicodedata.category(c)
        if cat == "Zs":
            salida.append(" ")
        elif cat in ("Cc", "Cf", "Cs", "Zl", "Zp") or c in "⠀ᅟᅠㅤﾠ":
            continue
        else:
            salida.append(c)
    return re.sub(r" {2,}", " ", "".join(salida)).strip()


def _leer_csv(contenido: bytes):
    """`(cabecera, [(linea, celdas)])`. Rechaza (400) lo que no sirve para nada."""
    if not contenido or not contenido.strip():
        raise ErrorAsistida(400, "El archivo está vacío.")
    if len(contenido) > TOPE_BYTES:
        raise ErrorAsistida(400, "El archivo pesa más de 1 MB: partilo en dos.")
    if b"\x00" in contenido or contenido[:2] == b"PK":
        raise ErrorAsistida(400, "No pude leer el archivo: tiene que ser un CSV (si es de Excel, guardalo como "
                                 "«CSV» o bajá el modelo).")
    texto = listas._decodificar(contenido)
    lector = csv.reader(io.StringIO(texto), delimiter=listas._dialecto(texto))
    cabecera, filas = None, []
    try:
        for celdas in lector:
            if not any(str(x).strip() for x in celdas):
                continue
            if cabecera is None:
                cabecera = celdas
                continue
            if len(filas) >= TOPE_FILAS:
                raise ErrorAsistida(400, f"La planilla tiene más de {TOPE_FILAS} filas: partila en varias.")
            filas.append((lector.line_num, celdas))
    except csv.Error:
        raise ErrorAsistida(400, "No pude leer el archivo: el CSV está mal formado.")
    if cabecera is None:
        raise ErrorAsistida(400, "El archivo está vacío.")
    return cabecera, filas


def _posiciones(cabecera):
    """`({clave: índice}, [rótulos ignorados])`. La cabecera se reconoce por clave
    o por rótulo, sin mirar mayúsculas, acentos ni espacios."""
    planas = [listas._plano(h) for h in cabecera]
    posicion, usadas = {}, set()
    for clave, rotulo, *_ in COLUMNAS:
        candidatos = {clave, listas._plano(rotulo), *(_ALIAS.get(clave, ()))}
        idx = next((i for i, h in enumerate(planas) if h in candidatos and i not in usadas), None)
        if idx is not None:
            posicion[clave] = idx
            usadas.add(idx)
    if "nombre" not in posicion:
        raise ErrorAsistida(400, "Falta la columna «nombre» en la cabecera de la planilla.")
    ignoradas = [_limpiar(h) for i, h in enumerate(cabecera) if i not in usadas and str(h).strip()]
    return posicion, ignoradas


def _decimal(texto: str):
    """Un número con coma o punto decimal; None si no se entiende."""
    t = texto.strip().replace(",", ".")
    if not re.fullmatch(r"[+-]?\d+(\.\d+)?", t):
        return None
    valor = float(t)
    return valor if math.isfinite(valor) else None


def _clave_nombre(nombre: str) -> str:
    return listas._plano(nombre)


def _celda(celdas, posicion, clave) -> str:
    i = posicion.get(clave)
    return _limpiar(celdas[i]) if i is not None and i < len(celdas) else ""


def _datos_de_fila(celdas, posicion) -> tuple[dict, list, list]:
    """`(datos, rechazos, dudas)` de una fila ya partida en celdas."""
    rechazos, dudas = [], []
    c = lambda k: _celda(celdas, posicion, k)          # noqa: E731
    nombre = c("nombre")
    if not nombre:
        rechazos.append("Falta el nombre.")
    elif len(nombre) > LARGO_NOMBRE:
        rechazos.append(f"El nombre tiene más de {LARGO_NOMBRE} caracteres.")
    elif not _clave_nombre(nombre):
        rechazos.append("El nombre no tiene letras ni números.")

    sede_txt = listas._plano(c("sede_central"))
    if sede_txt in _SI:
        sede, sede_explicita = True, True
    elif sede_txt in _NO:
        sede, sede_explicita = False, sede_txt != ""
    else:
        sede, sede_explicita = False, True
        dudas.append("No entendí «es Sede Central» (usá sí o no): se toma como no.")

    lat_t, lon_t = c("latitud"), c("longitud")
    lat = lon = None
    if lat_t or lon_t:
        if not lat_t or not lon_t:
            rechazos.append("Falta la latitud o la longitud: tienen que venir las dos.")
        else:
            lat, lon = _decimal(lat_t), _decimal(lon_t)
            if lat is None or lon is None:
                rechazos.append("La latitud o la longitud no se entienden (ej.: -32,9468).")
                lat = lon = None
            elif not (LAT_RANGO[0] <= lat <= LAT_RANGO[1] and LON_RANGO[0] <= lon <= LON_RANGO[1]):
                rechazos.append("Las coordenadas caen fuera de la Argentina continental.")
                lat = lon = None
    mail = c("mail")
    if mail and (len(mail) > CONTACTO["mail"] or not _RE_MAIL.match(mail)):
        rechazos.append("El mail no tiene forma de mail.")

    datos = {"nombre": nombre, "sede": sede, "sede_explicita": sede_explicita,
             "latitud": lat, "longitud": lon}
    for k in DOMICILIO:
        datos[k] = c(k)
    for k, largo in CONTACTO.items():
        datos[k] = c("horario" if k == "horario_atencion" else k)[:largo]

    if not rechazos:
        if lat is None:
            dudas.append("Sin coordenadas: queda «sin ubicar» hasta ubicarla en el mapa.")
        if not datos["provincia"] or not datos["localidad"]:
            dudas.append("Falta la provincia o la localidad.")
        if not datos["calle"] or not datos["numero"]:
            dudas.append("Falta la calle o la altura.")
    return datos, rechazos, dudas


def _float_o_none(x):
    return None if x is None else round(float(x), 6)


def _a_escribir(datos: dict, e: dict | None) -> dict:
    """Los campos de `Seccional` que se escribirían. Con `e` (la que ya existe)
    solo se devuelve lo que CAMBIA: lo vacío de la planilla no pisa lo cargado,
    `ve_todas` nunca baja y las coordenadas actuales se conservan mientras el
    domicilio no se mueva."""
    contacto = {k: datos[k] for k in CONTACTO}
    if e is None:
        dom = geo.campos_para_guardar({k: datos[k] for k in DOMICILIO}, "manual",
                                      datos["latitud"], datos["longitud"])
        return {"nombre": datos["nombre"], "ve_todas": bool(datos["sede"]), **dom, **contacto}
    mezcla = {k: datos[k] or str(e.get(k) or "") for k in DOMICILIO}
    lat, lon, precision = datos["latitud"], datos["longitud"], "manual"
    if lat is None:
        quieto = all(geo.campos_para_guardar(mezcla, "", None, None)[k] == str(e.get(k) or "") for k in DOMICILIO)
        if quieto:
            lat, lon, precision = e.get("latitud"), e.get("longitud"), e.get("precision_geo") or "manual"
    nuevo = geo.campos_para_guardar(mezcla, precision, lat, lon)
    nuevo["ve_todas"] = bool(e.get("ve_todas")) or bool(datos["sede"])
    for k in CONTACTO:
        nuevo[k] = contacto[k] or str(e.get(k) or "")
    cambios = {}
    for k in CAMPOS_COMPARABLES:
        if k in ("latitud", "longitud"):
            distinto = _float_o_none(nuevo.get(k)) != _float_o_none(e.get(k))
        else:
            distinto = nuevo.get(k) != (e.get(k) if k == "ve_todas" else (e.get(k) or ""))
        if distinto:
            cambios[k] = nuevo.get(k)
    if any(k in cambios for k in ("latitud", "longitud", "precision_geo")):
        cambios["geo_actualizado"] = nuevo.get("geo_actualizado", "")
    return cambios


def _resumen(datos: dict, accion: str, ubicada: bool) -> dict:
    """Solo textos con valor, legibles tal cual (sin booleanos ni vacíos):
    `nombre`, `direccion`, `sede_central` («Sede Central»), `ubicacion`
    («Con ubicación» / «Sin ubicar») y `accion` (crear | actualizar | sin_tocar)."""
    r = {"nombre": datos["nombre"],
         "direccion": geo.armar_direccion_texto({k: datos[k] for k in DOMICILIO}),
         "sede_central": "Sede Central" if datos["sede"] else "",
         "ubicacion": ("Con ubicación" if ubicada else "Sin ubicar") if accion else "",
         "accion": accion}
    return {k: v for k, v in r.items() if v}


def leer(contenido: bytes, existentes: list, opciones: dict | None = None) -> dict:
    """Clasifica la planilla contra las seccionales que ya tiene el sindicato
    (`existentes`: dicts con `id`, `nombre`, `ve_todas` y el resto de los campos).
    PURA. Devuelve `{total, filas, avisos, opciones}`; cada fila trae `linea`,
    `estado` (valida | dudosa | rechazada | ya_existe), `motivos`, `resumen`, y
    para el uso interno `datos`, `existente` y `cambios`."""
    opciones = normalizar_opciones(opciones)
    cabecera, crudas = _leer_csv(contenido)
    posicion, ignoradas = _posiciones(cabecera)
    por_nombre = {_clave_nombre(e["nombre"]): e for e in existentes if _clave_nombre(e["nombre"])}
    vistos, filas, avisos = set(), [], []
    if ignoradas:
        avisos.append("Se ignoran las columnas que no conozco: " + ", ".join(f"«{x}»" for x in ignoradas) + ".")

    for linea, celdas in crudas:
        datos, rechazos, dudas = _datos_de_fila(celdas, posicion)
        clave = _clave_nombre(datos["nombre"])
        if clave and clave in vistos and not rechazos:
            rechazos.append("El nombre está repetido en la planilla (se carga la primera).")
        # Solo una fila que se carga reserva el nombre: si la primera quedó
        # rechazada, «se carga la primera» sería falso y la corregida de más
        # abajo no tendría cómo entrar.
        if clave and not rechazos:
            vistos.add(clave)
        if (not rechazos and not datos["sede"] and not datos["sede_explicita"]
                and opciones["sede_por_nombre"] and clave in _NOMBRES_DE_SEDE):
            datos["sede"] = True
            dudas.append("Se llama «Sede Central» y no estaba marcada: la marco como Sede Central.")
        fila = {"linea": linea, "estado": "", "motivos": [], "datos": datos, "existente": None, "cambios": {}}
        if rechazos:
            fila.update(estado="rechazada", motivos=rechazos, resumen=_resumen(datos, "", False))
        else:
            e = por_nombre.get(clave)
            if e is not None:
                cambios = _a_escribir(datos, e)
                actualiza = opciones["actualizar_existentes"] and bool(cambios)
                accion = "actualizar" if actualiza else "sin_tocar"
                motivo = ("Ya existe: se actualiza lo que cambió." if actualiza else
                          "Ya existe: no cambia nada." if opciones["actualizar_existentes"] else
                          "Ya existe: no se toca (tildá «Actualizar las que ya existen» para cambiarle el domicilio).")
                fila.update(estado="ya_existe", motivos=[motivo, *dudas], existente=e,
                            cambios=cambios if actualiza else {})
                ubicada = (datos["latitud"] is not None) or (e.get("latitud") is not None
                                                             and e.get("precision_geo") != "sin_geo")
                fila["resumen"] = _resumen(datos, accion, ubicada)
            else:
                fila.update(estado="dudosa" if dudas else "valida", motivos=dudas,
                            resumen=_resumen(datos, "crear", datos["latitud"] is not None))
        filas.append(fila)

    # Más de una Sede Central en la planilla: ninguna es segura.
    sedes = [f for f in filas if f["estado"] != "rechazada" and f["datos"]["sede"]]
    if len(sedes) > 1:
        for f in sedes:
            f["motivos"].append("Hay más de una fila marcada como Sede Central.")
            if f["estado"] == "valida":
                f["estado"] = "dudosa"
    ya_ve_todas = any(e.get("ve_todas") for e in existentes)
    if not ya_ve_todas and not sedes:
        avisos.append("Ninguna seccional vería todas las demás: marcá la fila de Sede Central con «sí» "
                      "(o tildá «Sus usuarios ven todas las seccionales» después, en el panel).")
    return {"total": len(filas), "filas": filas, "avisos": avisos, "opciones": opciones}


# ------------------------------------------------------------------ base

def _existentes(s, sid: int) -> list:
    """Las seccionales del sindicato como dicts simples (no objetos de la sesión)."""
    from db import Seccional
    campos = ("id", "nombre", "ve_todas", *DOMICILIO, "direccion_texto", "latitud", "longitud",
              "precision_geo", *CONTACTO)
    return [{k: getattr(x, k) for k in campos}
            for x in s.exec(select(Seccional).where(Seccional.sindicato_id == sid).order_by(Seccional.id)).all()]


def _publica(fila: dict) -> dict:
    return {"linea": fila["linea"], "estado": fila["estado"], "motivos": list(fila["motivos"]),
            "resumen": dict(fila["resumen"])}


def ensayar(s, sid: int, contenido: bytes, opciones: dict | None = None) -> dict:
    """El ensayo: lee la planilla y dice qué haría. No escribe nada."""
    ley = leer(contenido, _existentes(s, sid), opciones)
    filas = [_publica(f) for f in ley["filas"]]
    cuenta = {e: sum(1 for f in filas if f["estado"] == e) for e in ("valida", "dudosa", "rechazada", "ya_existe")}
    a_escribir = sum(1 for f in ley["filas"] if f["estado"] in ("valida", "dudosa")
                     or (f["estado"] == "ya_existe" and f["cambios"]))
    return {"total": ley["total"], "validas": cuenta["valida"], "dudosas": cuenta["dudosa"],
            "rechazadas": cuenta["rechazada"], "ya_existen": cuenta["ya_existe"],
            "a_escribir": a_escribir, "filas": filas, "avisos": ley["avisos"], "muestra": filas[:5],
            "opciones": ley["opciones"], "huella": huella(contenido, ley["opciones"])}


def cargar(s, sid: int, contenido: bytes, opciones: dict | None = None, dejar_afuera=()) -> dict:
    """Vuelve a leer con la MISMA función del ensayo y escribe con los modelos de
    la app. NO confirma la transacción. `dejar_afuera`: líneas dudosas que no
    entran (una línea que no es dudosa se ignora)."""
    from db import Seccional
    afuera_pedido = {int(x) for x in dejar_afuera}
    ley = leer(contenido, _existentes(s, sid), opciones)
    por_id = {x.id: x for x in s.exec(select(Seccional).where(Seccional.sindicato_id == sid)).all()}
    res = {"creadas": 0, "actualizadas": 0, "sin_tocar": 0, "afuera": 0, "rechazadas": 0, "detalle": []}

    def anotar(fila, accion):
        res["detalle"].append({"linea": fila["linea"], "nombre": fila["datos"]["nombre"], "accion": accion})

    for f in ley["filas"]:
        est = f["estado"]
        if est == "rechazada":
            res["rechazadas"] += 1
            anotar(f, "rechazada")
        elif est == "ya_existe":
            if f["cambios"]:
                sec = por_id.get(f["existente"]["id"])
                if sec is None or sec.sindicato_id != sid:        # defensa: nunca una ajena
                    res["sin_tocar"] += 1
                    anotar(f, "sin_tocar")
                    continue
                for k, v in f["cambios"].items():
                    setattr(sec, k, v)
                s.add(sec)
                res["actualizadas"] += 1
                anotar(f, "actualizada")
            else:
                res["sin_tocar"] += 1
                anotar(f, "sin_tocar")
        elif est == "dudosa" and f["linea"] in afuera_pedido:
            res["afuera"] += 1
            anotar(f, "afuera")
        else:
            s.add(Seccional(sindicato_id=sid, **_a_escribir(f["datos"], None)))
            res["creadas"] += 1
            anotar(f, "creada")
    s.flush()
    res["avisos"] = ley["avisos"]
    return res
