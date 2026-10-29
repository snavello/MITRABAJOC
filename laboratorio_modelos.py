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
  completions` con la imagen como data URL): Moonshot y Alibaba lo exponen
  así y es el que más proveedores comparten. Un proveedor nuevo es una
  entrada en `data/laboratorio_modelos.json`, no código.
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

import extractor
import precios_ia
from extractor import ErrorLectura

ARCHIVO = Path(__file__).resolve().parent / "data" / "laboratorio_modelos.json"
HERRAMIENTA = "laboratorio"
TIPOS = ("recibo", "aportes")
# Un modelo abierto servido desde Asia puede tardar bastante más que Claude;
# el navegador espera a todos en paralelo, así que el techo es generoso.
TIEMPO_MAXIMO_S = 180
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


def configurado(prov: dict) -> bool:
    return bool(os.getenv(prov.get("variable", "") or "", "").strip())


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
        "max_tokens": extractor.MAX_TOKENS,
        # Transcribir, no crear: la temperatura más baja que acepte el proveedor.
        "temperature": 0,
    }
    if m.get("json_mode"):
        body["response_format"] = {"type": "json_object"}
    # Parámetros propios de un proveedor (ej. apagar el razonamiento en Qwen):
    # van en el catálogo, no en el código.
    body.update(m.get("extra") or {})
    url = base_url(prov).rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {os.getenv(prov['variable'], '').strip()}",
               "Content-Type": "application/json"}
    clave_ = clave(prov["id"], m["id"])
    inicio = time.perf_counter()
    try:
        r = _post(url, headers, body)
    except httpx.HTTPError as e:
        raise ErrorProveedor(f"no se pudo llegar a {prov['nombre']}: {type(e).__name__}: {e}") from e
    ms = int((time.perf_counter() - inicio) * 1000)
    if r.status_code != 200:
        raise ErrorProveedor(f"{prov['nombre']} contestó {r.status_code}: {r.text[:300]}")
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
                                      for x in referencia[1])} for d in resumen],
            "iguales": iguales, "campos": len(resumen),
            "json": json.dumps(datos, ensure_ascii=False, indent=1),
        })
        filas.append(fila)
        leidas.append((fila["nombre"], datos))
    lineas = extractor.comparar_lineas(leidas) if tipo == "recibo" and len(leidas) > 1 else None
    distintos = sum(f["campos"] - f["iguales"] for f in filas if f.get("ok"))
    if lineas:
        distintos += lineas["distintas"]
    return {"tipo": tipo, "modelos": filas, "referencia": referencia[0] if referencia else None,
            "lineas": lineas, "distintos": distintos, "ok": sum(1 for f in filas if f.get("ok"))}


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
