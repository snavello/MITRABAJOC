# -*- coding: utf-8 -*-
"""Laboratorio de modelos (Herramientas de /entornos, 2026-10-29).

El banco de pruebas de /plataforma compara modelos de Anthropic con la clave
de la plataforma. Este laboratorio es lo mismo pero AISLADO de la app real y
abierto a otros proveedores: lee el mismo archivo con cualquier combinación
de modelos (Claude, Kimi de Moonshot, Qwen de Alibaba...) y muestra lado a
lado qué leyó cada uno, cuánto tardó y cuánto costó; cada corrida queda
guardada como un *ensayo* para comparar después con números y no con
impresiones.

Reglas:
- **Mismo prompt para todos.** El sistema y el esquema son los de
  `extractor.py`, sin adaptar: si un modelo necesita otro prompt para leer
  un recibo, eso es parte de lo que se mide, no algo que el laboratorio
  tape.
- **No toca la app.** Ninguna ruta de trabajador, sindicato ni plataforma
  importa este módulo. Lo único compartido es `extractor` (prompt, imagen,
  parseo, comparación) y `precios_ia` (precios de Anthropic).
- **Cada proveedor con su clave, por variable de entorno** (`variable` en
  el catálogo). Sin la variable, el modelo se muestra pero no se puede
  elegir, y la pantalla dice qué variable falta. La clave nunca sale al
  navegador.
- **Los proveedores que no son Anthropic hablan el formato OpenAI** (`/chat/
  completions` con la imagen como data URL): OpenAI, Moonshot y Alibaba lo
  exponen así y es el que más proveedores comparten. Un proveedor nuevo es
  una entrada en `data/laboratorio_modelos.json`, no código; sus dialectos
  también (`extra`, `quitar`, `tope_salida`).
- **Un ensayo no guarda identidad**: nombre, CUIL y legajo del recibo se
  borran antes de guardar (`sin_identidad`). Lo que se compara son
  importes, códigos y clasificaciones.
- **Los precios son de lista y van con fecha de lectura**, como en
  `precios_ia.py`: un precio sin fecha no se audita.

Puro salvo la llamada HTTP (`_post`, aislada para simularla en los tests).
No importa `db`.
"""
import base64
import copy
import json
import os
import statistics
import time
from pathlib import Path

import httpx

import cuit

import extractor
import precios_ia
from extractor import ErrorLectura

ARCHIVO = Path(__file__).resolve().parent / "data" / "laboratorio_modelos.json"
HERRAMIENTA = "laboratorio"
TIPOS = ("recibo", "aportes")
# Un modelo abierto servido desde Asia puede tardar bastante más que Claude;
# el navegador espera a todos en paralelo, así que el techo es generoso.
TIEMPO_MAXIMO_S = 180
# Ante un 429 (límite de pedidos del proveedor) se reintenta hasta tantas veces.
REINTENTOS_429 = 2


def _espera_429(r, intento: int) -> float:
    try:
        return min(float(r.headers.get("Retry-After", "")), 30.0)
    except (TypeError, ValueError):
        return 3.0 * (intento + 1)
ANTHROPIC = "anthropic"


class ErrorProveedor(Exception):
    """La API del proveedor no contestó 200 (clave inválida, sin saldo,
    modelo inexistente, límite de uso) o no se pudo llegar. No lleva `uso`:
    un pedido rechazado no se cobra."""


# ---------------------------------------------------------------- catálogo
def catalogo() -> dict:
    try:
        return json.loads(ARCHIVO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"leido": "", "proveedores": []}


def _proveedor_anthropic() -> dict:
    """Anthropic no está en el JSON del laboratorio: sus modelos y precios
    salen de `precios_ia`, que es la única lista que la app mantiene. Así
    el laboratorio no puede tener un precio distinto del panel."""
    cat = precios_ia.catalogo()
    return {
        "id": ANTHROPIC, "nombre": "Anthropic (Claude)", "estilo": "anthropic",
        "variable": "ANTHROPIC_API_KEY", "sitio": "https://platform.claude.com",
        "leido": cat.get("leido", ""), "fuente": cat.get("fuente", ""),
        "nota": "La misma clave y los mismos precios que la app. Las lecturas de "
                "estos modelos se registran en Uso de IA de /plataforma como «prueba».",
        "modelos": [dict(m, vision=True) for m in cat.get("modelos", [])],
    }


def proveedores() -> list:
    return [_proveedor_anthropic()] + list(catalogo().get("proveedores", []))


# Claves pegadas desde la pantalla (db.claves_laboratorio); main las carga en
# cada pedido con `configurar_claves`. La variable de entorno manda.
_GUARDADAS: dict = {}


def configurar_claves(claves: dict) -> None:
    _GUARDADAS.clear()
    _GUARDADAS.update({k: v for k, v in (claves or {}).items() if v})


def clave_de(prov: dict) -> str:
    v = prov.get("variable", "") or ""
    return (os.getenv(v, "").strip() if v else "") or _GUARDADAS.get(v, "").strip()


def origen_clave(prov: dict) -> str:
    """'entorno' (variable de Render, no se edita acá), 'guardada' o ''."""
    v = prov.get("variable", "") or ""
    if v and os.getenv(v, "").strip():
        return "entorno"
    return "guardada" if _GUARDADAS.get(v, "").strip() else ""


def pista(clave: str) -> str:
    return ("····" + clave[-4:]) if len(clave) >= 8 else "····"


def configurado(prov: dict) -> bool:
    return bool(clave_de(prov))


def clave(prov_id: str, modelo_id: str) -> str:
    return f"{prov_id}:{modelo_id}"


def modelos() -> list:
    """Todos los modelos de todos los proveedores, aplanados, con su clave
    `proveedor:modelo` y si el proveedor tiene la variable cargada."""
    salida = []
    for p in proveedores():
        ok = configurado(p)
        for m in p.get("modelos", []):
            salida.append({
                **m, "clave": clave(p["id"], m["id"]), "proveedor": p["id"],
                "proveedor_nombre": p["nombre"], "configurado": ok,
                "variable": p.get("variable", ""), "precio_txt": precios_ia.precio_txt(m),
            })
    return salida


def modelo(clave_: str) -> dict | None:
    return next((m for m in modelos() if m["clave"] == clave_), None)


def proveedor(prov_id: str) -> dict | None:
    return next((p for p in proveedores() if p["id"] == prov_id), None)


def catalogo_pantalla() -> dict:
    """Lo que la página necesita para dibujar la lista: proveedores con sus
    modelos, qué variable falta, y las fechas de lectura de los precios.
    Nunca la clave."""
    provs = []
    for p in proveedores():
        provs.append({
            "id": p["id"], "nombre": p["nombre"], "configurado": configurado(p),
            "origen": origen_clave(p), "pista": pista(clave_de(p)) if configurado(p) else "",
            "editable": p["id"] != ANTHROPIC,
            "variable": p.get("variable", ""), "sitio": p.get("sitio", ""),
            "nota": p.get("nota", ""), "leido": p.get("leido", ""), "fuente": p.get("fuente", ""),
            "modelos": [{"clave": clave(p["id"], m["id"]), "id": m["id"], "nombre": m["nombre"],
                         "precio_txt": precios_ia.precio_txt(m), "contexto": m.get("contexto", ""),
                         "resumen": m.get("resumen", ""), "vision": bool(m.get("vision", True))}
                        for m in p.get("modelos", [])],
        })
    return {"proveedores": provs, "tipos": list(TIPOS)}


def costo_de(m: dict, tokens_entrada: int, tokens_salida: int) -> float | None:
    if m is None or "entrada" not in m or "salida" not in m:
        return None
    return precios_ia.costo(tokens_entrada, tokens_salida, float(m["entrada"]), float(m["salida"]))


# ---------------------------------------------------------------- la lectura
def base_url(prov: dict) -> str:
    """La del catálogo, salvo que el entorno traiga la suya (`variable_url`):
    Alibaba recomienda hoy un host con el Workspace ID adentro, que no puede
    estar escrito en un archivo versionado."""
    v = prov.get("variable_url") or ""
    return (os.getenv(v, "").strip() if v else "") or prov.get("base_url", "")


def _post(url: str, headers: dict, body: dict) -> httpx.Response:
    """La única salida a la red del módulo. Está sola para que los tests la
    reemplacen."""
    return httpx.post(url, headers=headers, json=body, timeout=TIEMPO_MAXIMO_S)


def _texto_de(contenido) -> str:
    """El `content` de una respuesta OpenAI puede ser un string o una lista
    de partes; algunos proveedores devuelven el razonamiento aparte
    (`reasoning_content`) y acá no interesa."""
    if isinstance(contenido, list):
        return "".join(p.get("text", "") for p in contenido if isinstance(p, dict))
    return str(contenido or "")


def _parsear_json(texto: str) -> dict:
    texto = (texto or "").strip()
    if texto.startswith("```"):
        texto = texto.split("```")[1].removeprefix("json").strip()
    return json.loads(texto)


def _leer_openai(prov: dict, m: dict, tipo: str, imagen: tuple[str, str],
                 aviso_enmascarado: bool) -> tuple[dict, dict]:
    b64, media = imagen
    if tipo == "aportes":
        system, esquema = extractor.SYSTEM_APORTES, extractor.ESQUEMA_APORTES
    else:
        system, esquema = extractor.SYSTEM, extractor.ESQUEMA
    partes = [{"type": "image_url", "image_url": {"url": f"data:{media};base64,{b64}"}},
              {"type": "text", "text": esquema}]
    if aviso_enmascarado:
        partes.append({"type": "text", "text": extractor.AVISO_ENMASCARADO})
    body = {
        "model": m["id"],
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": partes}],
        # El tope de salida se llama `max_tokens` en casi todos; OpenAI lo
        # retiró de sus modelos que razonan y exige `max_completion_tokens`
        # (`tope_salida` del proveedor en el catálogo).
        prov.get("tope_salida") or "max_tokens": extractor.MAX_TOKENS,
        # Transcribir, no crear: la temperatura más baja que acepte el proveedor.
        "temperature": 0,
    }
    if m.get("json_mode"):
        body["response_format"] = {"type": "json_object"}
    # Parámetros propios de un proveedor (ej. apagar el razonamiento en Qwen):
    # van en el catálogo, no en el código. `quitar` saca del pedido lo que un
    # proveedor rechaza aunque sea con su valor por defecto (OpenAI y la
    # temperatura en los modelos que razonan).
    body.update(m.get("extra") or {})
    for k in list(prov.get("quitar") or []) + list(m.get("quitar") or []):
        body.pop(k, None)
    url = base_url(prov).rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {clave_de(prov)}",
               "Content-Type": "application/json"}
    clave_ = clave(prov["id"], m["id"])
    inicio = time.perf_counter()
    for intento in range(REINTENTOS_429 + 1):
        try:
            r = _post(url, headers, body)
        except httpx.HTTPError as e:
            raise ErrorProveedor(f"no se pudo llegar a {prov['nombre']}: {type(e).__name__}: {e}") from e
        # Un 429 es "demasiados pedidos a la vez" (Qwen en el nivel gratis, con
        # cinco modelos en paralelo): se espera lo que pida Retry-After, o unos
        # segundos, y se vuelve a intentar un par de veces antes de rendirse.
        if r.status_code != 429 or intento == REINTENTOS_429:
            break
        time.sleep(_espera_429(r, intento))
    ms = int((time.perf_counter() - inicio) * 1000)
    if r.status_code != 200:
        raise ErrorProveedor(f"{prov['nombre']} contestó {r.status_code}: {r.text[:300]}"
                             + (" (tras reintentar por límite de pedidos)" if r.status_code == 429 else ""))
    try:
        data = r.json()
        eleccion = data["choices"][0]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise ErrorProveedor(f"{prov['nombre']} devolvió una respuesta con otra forma: {r.text[:200]}") from e
    uso_api = data.get("usage") or {}
    uso = {"modelo": clave_, "tokens_entrada": int(uso_api.get("prompt_tokens") or 0),
           "tokens_salida": int(uso_api.get("completion_tokens") or 0), "duracion_ms": ms}
    if eleccion.get("finish_reason") == "length":
        raise ErrorLectura(
            f"la respuesta se cortó en el tope de {extractor.MAX_TOKENS} tokens de salida "
            f"(el modelo devolvió {uso['tokens_salida']})", uso)
    if eleccion.get("finish_reason") == "content_filter":
        raise ErrorLectura("el proveedor filtró la respuesta (content_filter)", uso)
    texto = _texto_de((eleccion.get("message") or {}).get("content"))
    try:
        datos = _parsear_json(texto)
    except (ValueError, IndexError) as e:
        raise ErrorLectura(f"la respuesta no es un JSON válido: {e}", uso) from e
    if not isinstance(datos, dict):
        raise ErrorLectura("la respuesta es JSON pero no es un objeto", uso)
    return datos, uso


def leer(clave_: str, tipo: str, contenido: bytes, content_type: str,
         imagen: tuple[str, str], aviso_enmascarado: bool = False) -> tuple[dict, dict]:
    """(datos, uso) de UN modelo sobre la imagen ya preparada. `uso["modelo"]`
    es la clave `proveedor:modelo` salvo en Anthropic, donde es el id crudo:
    así la fila que va a UsoIA encuentra su precio en el catálogo de la app."""
    m = modelo(clave_)
    if m is None:
        raise ErrorProveedor(f"{clave_} no está en el catálogo del laboratorio")
    prov = proveedor(m["proveedor"])
    if not configurado(prov):
        raise ErrorProveedor(f"falta la variable {prov['variable']} en este entorno")
    if prov["estilo"] == "anthropic":
        fn = extractor.extraer_aportes if tipo == "aportes" else extractor.extraer
        return fn(contenido, content_type, m["id"], imagen=imagen, aviso_enmascarado=aviso_enmascarado)
    return _leer_openai(prov, m, tipo, imagen, aviso_enmascarado)


# ---------------------------------------------------------------- resultado
def sin_identidad(tipo: str, datos: dict) -> dict:
    """La lectura sin lo que identifica a la persona. Un ensayo compara
    importes y clasificaciones; el nombre y el CUIL no suman nada guardados."""
    d = copy.deepcopy(datos) if isinstance(datos, dict) else {}
    if tipo == "aportes":
        d["cuil"] = None
        return d
    emp = d.get("empleado")
    if isinstance(emp, dict):
        for k in ("apellido_nombre", "cuil", "legajo"):
            if k in emp:
                emp[k] = None
    return d


def _cuit_invalido(d: dict) -> bool:
    """True si el dato es un CUIL/CUIT con dígitos que no pasa el verificador."""
    if not d["etiqueta"].startswith("CUI"):
        return False
    digitos = cuit.normalizar(d.get("comparar") or d.get("valor"))
    return bool(digitos) and not cuit.es_valido(digitos)


def _etiqueta_error(e: BaseException) -> str:
    if isinstance(e, (ErrorLectura, ErrorProveedor)):
        return str(e)[:300]
    return f"{type(e).__name__}: {e}"[:300]


def armar_resultado(tipo: str, claves: list, lecturas: list) -> dict:
    """La tabla de la pantalla y lo que se guarda, a partir de las lecturas
    tal como volvieron: `(datos, uso)` o la excepción. Puro.

    La referencia es el primer modelo que contestó, en el orden en que se
    eligieron: la pantalla lo dice. Que dos coincidan no prueba que estén
    bien; prueba que leyeron lo mismo."""
    filas, leidas, referencia = [], [], None
    for clave_, r in zip(claves, lecturas):
        m = modelo(clave_) or {"clave": clave_, "nombre": clave_, "proveedor": "", "proveedor_nombre": ""}
        fila = {"clave": clave_, "modelo": m.get("id", clave_), "nombre": m["nombre"],
                "proveedor": m["proveedor"], "proveedor_nombre": m["proveedor_nombre"],
                "precio_txt": m.get("precio_txt", "—")}
        if isinstance(r, BaseException):
            uso = getattr(r, "uso", None) or {}
            fila.update({"ok": False, "error": _etiqueta_error(r),
                         "tokens_entrada": uso.get("tokens_entrada", 0),
                         "tokens_salida": uso.get("tokens_salida", 0),
                         "duracion_ms": uso.get("duracion_ms", 0),
                         "costo": costo_de(m, uso.get("tokens_entrada", 0), uso.get("tokens_salida", 0))
                         if uso else None})
            fila["costo_txt"] = precios_ia.usd(fila["costo"])
            fila["duracion_txt"] = precios_ia.segundos(fila["duracion_ms"])
            filas.append(fila)
            continue
        datos, uso = r
        resumen = extractor.resumen_comparable(tipo, datos)
        if referencia is None:
            referencia = (fila["nombre"], resumen)
        costo = costo_de(m, uso["tokens_entrada"], uso["tokens_salida"])
        iguales = sum(1 for d in resumen
                      if any(d["etiqueta"] == x["etiqueta"] and d["comparar"] == x["comparar"]
                             for x in referencia[1]))
        fila.update({
            "ok": True, "tokens_entrada": uso["tokens_entrada"], "tokens_salida": uso["tokens_salida"],
            "duracion_ms": uso.get("duracion_ms", 0), "duracion_txt": precios_ia.segundos(uso.get("duracion_ms", 0)),
            "costo": costo, "costo_txt": precios_ia.usd(costo),
            "confianza": str(datos.get("confianza") or "—"),
            "resumen": [{"etiqueta": d["etiqueta"], "valor": d["valor"],
                         "igual": any(d["etiqueta"] == x["etiqueta"] and d["comparar"] == x["comparar"]
                                      for x in referencia[1]),
                         # Igual en valor absoluto pero escrito con otro signo: se señala.
                         # SOLO si difieren en el "-" de adelante: un CUIT con guiones
                         # contra uno sin guiones es el mismo número y no lleva ±.
                         "signo": any(d["etiqueta"] == x["etiqueta"] and d["comparar"] == x["comparar"]
                                      and d["valor"] != x["valor"]
                                      and d["valor"].lstrip("-") == x["valor"].lstrip("-")
                                      for x in referencia[1]),
                         # Un CUIL o CUIT que no pasa el módulo 11 es un dígito mal leído,
                         # aunque todos los modelos coincidan (cuit.py, única implementación).
                         "invalido": _cuit_invalido(d)}
                        for d in resumen],
            "iguales": iguales, "campos": len(resumen),
            "json": json.dumps(datos, ensure_ascii=False, indent=1),
        })
        filas.append(fila)
        leidas.append((fila["nombre"], datos))
    lineas = extractor.comparar_lineas(leidas) if tipo == "recibo" and len(leidas) > 1 else None
    distintos = sum(f["campos"] - f["iguales"] for f in filas if f.get("ok"))
    if lineas:
        distintos += lineas["distintas"]
    contra_ref = campos_contra_referencia(tipo, leidas)
    for f in filas:
        if f.get("ok"):
            for d in f["resumen"]:
                d["ref_sola"] = d["etiqueta"] in contra_ref
    return {"tipo": tipo, "modelos": filas, "referencia": referencia[0] if referencia else None,
            "lineas": lineas, "distintos": distintos, "ok": sum(1 for f in filas if f.get("ok")),
            "contra_referencia": contra_ref,
            "analisis": analisis(filas, lineas, referencia[0] if referencia else None, contra_ref)}


def campos_contra_referencia(tipo: str, leidas: list) -> list:
    """Las etiquetas del resumen en las que la referencia se aparta y los
    demás (dos o más) coinciden entre sí. Puro."""
    if len(leidas) < 3:
        return []
    resumenes = [extractor.resumen_comparable(tipo, datos) for _, datos in leidas]
    ref = {d["etiqueta"]: d["comparar"] for d in resumenes[0]}
    salida = []
    for etiqueta, valor_ref in ref.items():
        otros = [next((d["comparar"] for d in r if d["etiqueta"] == etiqueta), None) for r in resumenes[1:]]
        if all(o is not None for o in otros) and len(set(otros)) == 1 and otros[0] != valor_ref:
            salida.append(etiqueta)
    return salida


# Campos del resumen que NO cambian lo que la app calcula: una lectura puede
# diferir ahí sin impacto en el sistema.
_RESUMEN_SIN_IMPACTO = {"Confianza", "Formato"}


def analisis(filas: list, lineas: dict | None, referencia: str | None,
             contra_ref: list | None = None) -> list:
    """Hasta seis líneas, en castellano, sobre qué implican las diferencias
    entre las lecturas PARA EL SISTEMA. Determinista, sin IA. La primera
    línea es el veredicto: si ninguna diferencia impacta, lo dice y listo.
    Sin análisis de precios ni de tiempos (SDN, 2026-10-29: «solo quiero cómo
    impacta en el sistema la diferencia, si no impacta nada»)."""
    ok = [f for f in filas if f.get("ok")]
    fallidos = [f for f in filas if not f.get("ok")]
    if not ok:
        return ["Ningún modelo leyó el archivo: no hay nada que comparar."]
    detenidos = [f for f in fallidos if str(f.get("error", "")).startswith("detenido")]
    fallidos = [f for f in fallidos if f not in detenidos]
    if len(ok) == 1:
        out = [f"Solo contestó {ok[0]['nombre']}: con uno solo no hay comparación. Sumá al menos el de producción."]
        if fallidos:
            out.append(f"{len(fallidos)} no contestaron ({', '.join(f['nombre'] for f in fallidos)}): "
                       "un modelo que falla en el laboratorio también falla con un afiliado esperando.")
        return out
    otros = [f for f in ok if f["nombre"] != referencia]
    contra = list(contra_ref or [])
    n_lineas_contra = (lineas or {}).get("contra_referencia", 0)

    # --- qué difiere y qué de eso impacta en lo que la app calcula
    campos = sorted({d["etiqueta"] for f in otros for d in f.get("resumen", []) if not d.get("igual")})
    campos_impacto = [c for c in campos if c not in _RESUMEN_SIN_IMPACTO]
    campos_forma = [c for c in campos if c in _RESUMEN_SIN_IMPACTO]
    filas_lineas = [fl for fl in (lineas or {}).get("filas", []) if fl.get("difiere")]
    # Una fila que difiere solo por el signo no impacta (la app usa el valor absoluto).
    filas_impacto = [fl for fl in filas_lineas
                     if any((not c["igual"]) and not c.get("signo") for c in fl["celdas"])]
    invalidos = [(f["nombre"], d["etiqueta"]) for f in ok for d in f.get("resumen", []) if d.get("invalido")]
    hay_impacto = bool(campos_impacto or filas_impacto or invalidos or fallidos)

    out = []
    if not hay_impacto:
        out.append(f"Impacto en el sistema: NINGUNO. Las {len(ok)} lecturas darían la misma validación: "
                   "mismos totales, mismo período y las líneas clasificadas igual."
                   + (" Difieren solo en " + ", ".join(campos_forma) + ", que la app no usa para calcular." if campos_forma else "")
                   + (f" {lineas['signos']} línea(s) con el signo distinto: la app toma el valor absoluto." if lineas and lineas.get("signos") else ""))
    else:
        out.append("Impacto en el sistema: SÍ. Lo que sigue es lo que cambiaría en la validación según qué modelo lea.")
    if detenidos:
        out.append(f"{len(detenidos)} detenido(s) desde la pantalla ({', '.join(f['nombre'] for f in detenidos)}): no cuentan.")
    if fallidos:
        out.append(f"{len(fallidos)} de {len(filas)} no contestaron ({', '.join(f['nombre'] for f in fallidos)}): "
                   "un modelo que falla o no termina en el laboratorio también va a fallar con un afiliado esperando.")
    if campos_impacto:
        totales = [c for c in campos_impacto if c in ("Neto", "Remuneraciones", "Descuentos", "Aportes del trabajador")]
        partes = []
        if totales:
            partes.append("un total distinto (" + ", ".join(totales) + ") es un error de lectura de alguien y la app validaría los aportes contra ese número")
        if "Período" in campos_impacto:
            partes.append("el período manda qué topes y qué grilla aplican")
        if any(c.startswith("CUI") for c in campos_impacto):
            partes.append("un CUIL/CUIT distinto cambia de quién es el recibo o contra qué empleador se valida")
        if "Líneas leídas" in campos_impacto:
            partes.append("leer más o menos líneas cambia la base de los aportes")
        if any(c in ("Desde", "Hasta", "Meses leídos", "Meses con algo impago") for c in campos_impacto):
            partes.append("en un comprobante de ARCA cambia el semáforo de aportes")
        out.append(f"{len([f for f in otros if any(not d.get('igual') and d['etiqueta'] not in _RESUMEN_SIN_IMPACTO for d in f.get('resumen', []))])} "
                   f"de {len(otros)} leyeron distinto de {referencia} en {', '.join(campos_impacto)}: " + "; ".join(partes) + ".")
    if filas_impacto:
        codigos = [fl["codigo"] or fl["descripcion"][:24] for fl in filas_impacto[:4]]
        extra = f" y {len(filas_impacto) - 4} más" if len(filas_impacto) > 4 else ""
        out.append(f"{len(filas_impacto)} línea(s) leída(s) distinto ({', '.join(codigos)}{extra}): una línea clasificada "
                   "distinto (aporte, remuneración, sección), con otro importe o que un modelo no leyó cambia la cuota "
                   "sindical, el tope del 2 % o la base de los aportes, aunque el neto coincida.")
    if (contra or n_lineas_contra) and len(otros) >= 2:
        partes = []
        if contra:
            partes.append(f"en {', '.join(contra)}")
        if n_lineas_contra:
            partes.append(f"en {n_lineas_contra} línea(s)")
        out.append(f"Ojo con la referencia: {' y '.join(partes)} los otros {len(otros)} coinciden entre sí y "
                   f"{referencia} es el único que se aparta. Ahí lo más probable es que la lectura "
                   "equivocada sea la de la referencia, no la de los demás (se marca en la tabla).")
    if invalidos:
        out.append("Dígito mal leído: " + "; ".join(f"{n} devolvió un {e} que no pasa el verificador (módulo 11)" for n, e in invalidos)
                   + ". En la app ese recibo no se validaría contra el empleador correcto.")
    if hay_impacto and lineas and lineas.get("signos"):
        out.append(f"{lineas['signos']} línea(s) difieren solo en el signo: la app usa el valor absoluto, no impacta; se señala en ámbar.")
    # Quién se aparta más: campos del resumen con impacto + líneas con impacto,
    # sin contar las filas donde la que se aparta es la referencia. En empate
    # se nombran todos; si nadie se aparta, nadie.
    pos_ok = {f["nombre"]: k for k, f in enumerate(ok)}

    def _apartamiento(f):
        resumen_ = sum(1 for d in f.get("resumen", []) if not d.get("igual") and d["etiqueta"] not in _RESUMEN_SIN_IMPACTO)
        lineas_ = 0
        if lineas and f["nombre"] in pos_ok:
            k = pos_ok[f["nombre"]]
            lineas_ = sum(1 for fila in lineas["filas"]
                          if not fila.get("ref_sola") and k < len(fila["celdas"])
                          and not fila["celdas"][k]["igual"] and not fila["celdas"][k].get("signo"))
        return resumen_, lineas_
    apart = {f["nombre"]: _apartamiento(f) for f in otros}
    tope = max((sum(v) for v in apart.values()), default=0)
    if tope > 0:
        peores = [n for n, v in apart.items() if sum(v) == tope]
        r_, l_ = apart[peores[0]]
        detalle = " y ".join(x for x in (f"{r_} campo(s) del resumen" if r_ else "",
                                        f"{l_} línea(s)" if l_ else "") if x)
        quien = (f"El que más se aparta es {peores[0]}" if len(peores) == 1
                 else "Los que más se apartan son " + ", ".join(peores[:-1]) + f" y {peores[-1]}")
        out.append(f"{quien}: {detalle} distinto(s) de {referencia}. "
                   "Con un ensayo no alcanza: treinta recibos distintos antes de sacar una conclusión.")
    return out[:7]


def para_guardar(tipo: str, claves: list, lecturas: list, resultado: dict) -> dict:
    """Lo que va en `CasoHerramienta.real`: una entrada por modelo con sus
    números y su lectura SIN identidad. El `json` de la pantalla (con
    identidad) no se guarda."""
    salida = []
    for fila, r in zip(resultado["modelos"], lecturas):
        f = {k: v for k, v in fila.items() if k not in ("json", "resumen")}
        if fila.get("ok"):
            datos, _ = r
            f["lectura"] = sin_identidad(tipo, datos)
            f["resumen"] = [dict(d, valor=_tapar_valor(d)) for d in fila["resumen"]]
        salida.append(f)
    return {"lecturas": salida, "referencia": resultado["referencia"]}


_ETIQUETAS_IDENTIDAD = ("CUIL",)


def _tapar_valor(d: dict) -> str:
    return "(no se guarda)" if any(d["etiqueta"].startswith(e) for e in _ETIQUETAS_IDENTIDAD) else d["valor"]


def resumen_por_modelo(ensayos: list) -> list:
    """La comparación honesta entre modelos, sobre TODOS los ensayos
    guardados: cuántas veces se lo probó, cuántas contestó, mediana de
    tiempo, costo promedio por lectura y qué parte de los campos coincidió
    con la referencia de cada ensayo. Ordenado por cantidad de ensayos.

    `ensayos` son dicts con `real` (lo de `para_guardar`) y `estado`; los
    descartados no cuentan."""
    por = {}
    for e in ensayos:
        if e.get("estado") == "descartado":
            continue
        for f in (e.get("real") or {}).get("lecturas", []):
            a = por.setdefault(f["clave"], {"clave": f["clave"], "nombre": f["nombre"],
                                            "proveedor_nombre": f.get("proveedor_nombre", ""),
                                            "ensayos": 0, "ok": 0, "tiempos": [], "costos": [],
                                            "iguales": 0, "campos": 0})
            a["ensayos"] += 1
            if f.get("ok"):
                a["ok"] += 1
                a["tiempos"].append(f.get("duracion_ms") or 0)
                if f.get("costo") is not None:
                    a["costos"].append(f["costo"])
                a["iguales"] += f.get("iguales", 0)
                a["campos"] += f.get("campos", 0)
    salida = []
    for a in por.values():
        mediana = statistics.median(a["tiempos"]) if a["tiempos"] else 0
        costo = statistics.fmean(a["costos"]) if a["costos"] else None
        salida.append({
            "clave": a["clave"], "nombre": a["nombre"], "proveedor_nombre": a["proveedor_nombre"],
            "ensayos": a["ensayos"], "ok": a["ok"],
            "tiempo_mediano_ms": int(mediana), "tiempo_mediano_txt": precios_ia.segundos(int(mediana)),
            "costo_promedio": costo, "costo_promedio_txt": precios_ia.usd(costo),
            "coincidencia": round(100 * a["iguales"] / a["campos"]) if a["campos"] else None,
        })
    return sorted(salida, key=lambda x: (-x["ensayos"], x["nombre"]))


def imagen_data_url(imagen: tuple[str, str]) -> str:
    b64, media = imagen
    return f"data:{media};base64,{b64}"


def tamanio_imagen(imagen: tuple[str, str]) -> int:
    """Bytes de la imagen que viaja (no del base64): para decir en pantalla
    cuánto se mandó a cada proveedor."""
    try:
        return len(base64.b64decode(imagen[0]))
    except (ValueError, TypeError):
        return 0
