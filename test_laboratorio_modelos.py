"""Laboratorio de modelos (Herramientas de /entornos): el banco de pruebas
aislado de la app y abierto a otros proveedores. Motor puro
(laboratorio_modelos.py), llamada OpenAI-compatible simulada y las rutas.

Correr con: python -m pytest test_laboratorio_modelos.py -q
"""
import io
import json
import os

os.environ["ENTORNO"] = "pruebas"   # antes de importar main: se lee al importar
os.environ["PIN_ENTORNOS"] = "13572468"
os.environ.pop("MOCK_EXTRACTOR", None)

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import auth
import db
import entorno
import extractor
import laboratorio_modelos as lab
import main
import precios_ia

db.crear_tablas()
API = "/api/entornos/herramientas/laboratorio"
PAGINA = "/entornos/herramientas/laboratorio-modelos"
IMAGEN = ("aGVsbG8=", "image/png")   # "hello" en base64: alcanza para armar el pedido

RECIBO = {
    "formato": "clasico", "periodo": "2026-08",
    "empleado": {"apellido_nombre": "Pérez, Ana", "cuil": "27-22222222-8", "legajo": "77",
                 "categoria": "Administrativa", "fecha_ingreso": "2020-01-01"},
    "empleador": {"nombre": "Banco de Prueba", "cuit": "30999888778"},
    "lineas": [
        {"codigo": "1", "descripcion": "Sueldo básico", "importe": 1000000, "tipo": "remuneracion",
         "seccion": "haberes", "categoria_universal": None},
        {"codigo": "2", "descripcion": "Jubilación", "importe": -110000, "tipo": "aporte_trabajador",
         "seccion": "descuentos", "categoria_universal": "jubilacion"},
    ],
    "totales_impresos": {"remuneraciones": 1000000, "descuentos": -110000, "neto": 890000},
    "confianza": "alta",
}


# ---------------------------------------------------------------- catálogo
def test_el_catalogo_tiene_forma_y_anthropic_sale_de_precios_ia():
    provs = lab.proveedores()
    assert provs[0]["id"] == lab.ANTHROPIC and provs[0]["estilo"] == "anthropic"
    assert [m["id"] for m in provs[0]["modelos"]] == [m["id"] for m in precios_ia.modelos()]
    ids = {p["id"] for p in provs}
    assert {"moonshot", "alibaba"} <= ids
    claves = [m["clave"] for m in lab.modelos()]
    assert len(claves) == len(set(claves)), "dos modelos con la misma clave proveedor:modelo"
    for p in provs:
        assert p.get("variable") and p.get("leido") and p.get("fuente"), p["id"]
        if p["estilo"] == "openai":
            assert p["base_url"].startswith("https://"), p["id"]
        for m in p["modelos"]:
            assert m.get("nombre") and float(m["entrada"]) > 0 and float(m["salida"]) > 0, (p["id"], m)
            assert m.get("vision", True) is True, f"{m['id']} no lee imágenes: no sirve en el laboratorio"
    cat = lab.catalogo_pantalla()
    assert cat["tipos"] == ["recibo", "aportes"]
    assert "Authorization" not in json.dumps(cat) and "base_url" not in json.dumps(cat), "la clave no sale al navegador"


def test_configurado_depende_de_la_variable_y_la_base_url_se_puede_pisar(monkeypatch):
    prov = lab.proveedor("alibaba")
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_BASE_URL", raising=False)
    assert not lab.configurado(prov)
    assert lab.base_url(prov) == prov["base_url"]
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-x")
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://ws123.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1")
    assert lab.configurado(prov)
    assert lab.base_url(prov).startswith("https://ws123.")
    assert lab.modelo("alibaba:qwen3.8-flash")["configurado"] is True


# ---------------------------------------------------------------- llamada OpenAI-compatible
def _respuesta(status=200, cuerpo=None, texto=None):
    r = httpx.Response(status, json=cuerpo) if cuerpo is not None else httpx.Response(status, text=texto or "")
    return r


def _ok(contenido, finish="stop", usage=None):
    return {"choices": [{"finish_reason": finish, "message": {"role": "assistant", "content": contenido,
                                                                "reasoning_content": "pensando..."}}],
            "usage": usage or {"prompt_tokens": 1200, "completion_tokens": 300}}


def test_la_lectura_openai_arma_el_pedido_con_el_mismo_prompt_y_parsea(monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-kimi")
    capturado = {}

    def falso_post(url, headers, body):
        capturado.update(url=url, headers=headers, body=body)
        return _respuesta(cuerpo=_ok("```json\n" + json.dumps(RECIBO) + "\n```"))
    monkeypatch.setattr(lab, "_post", falso_post)
    datos, uso = lab.leer("moonshot:kimi-k3", "recibo", b"", "image/png", IMAGEN, aviso_enmascarado=True)
    assert datos["periodo"] == "2026-08"
    assert uso == {"modelo": "moonshot:kimi-k3", "tokens_entrada": 1200, "tokens_salida": 300,
                   "duracion_ms": uso["duracion_ms"]}
    assert capturado["url"] == "https://api.moonshot.ai/v1/chat/completions"
    assert capturado["headers"]["Authorization"] == "Bearer sk-kimi"
    b = capturado["body"]
    assert b["model"] == "kimi-k3" and b["max_tokens"] == extractor.MAX_TOKENS
    assert b["messages"][0] == {"role": "system", "content": extractor.SYSTEM}
    partes = b["messages"][1]["content"]
    assert partes[0]["image_url"]["url"] == "data:image/png;base64,aGVsbG8="
    assert partes[1]["text"] == extractor.ESQUEMA and partes[2]["text"] == extractor.AVISO_ENMASCARADO
    assert b["response_format"] == {"type": "json_object"}
    assert b["reasoning_effort"] == "low"          # el `extra` del catálogo, tal cual
    assert b["temperature"] == 1, "Kimi K3 rechaza con 400 cualquier temperature que no sea 1 (visto en Pruebas, 2026-10-29)"


def test_aportes_usa_el_prompt_de_aportes(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")
    capturado = {}

    def falso_post(url, headers, body):
        capturado.update(body=body)
        return _respuesta(cuerpo=_ok(json.dumps({"cuil": "20111111112", "meses": [], "confianza": "alta"})))
    monkeypatch.setattr(lab, "_post", falso_post)
    datos, _ = lab.leer("alibaba:qwen3.8-flash", "aportes", b"", "image/png", IMAGEN)
    assert datos["cuil"] == "20111111112"
    assert capturado["body"]["messages"][0]["content"] == extractor.SYSTEM_APORTES
    assert capturado["body"]["messages"][1]["content"][1]["text"] == extractor.ESQUEMA_APORTES
    assert "reasoning_effort" not in capturado["body"]


def test_lo_que_falla_se_distingue(monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-kimi")
    # Un rechazo de la API no se cobra: ErrorProveedor, sin uso.
    monkeypatch.setattr(lab, "_post", lambda u, h, b: _respuesta(401, texto='{"error":"invalid key"}'))
    with pytest.raises(lab.ErrorProveedor) as e:
        lab.leer("moonshot:kimi-k3", "recibo", b"", "image/png", IMAGEN)
    assert "401" in str(e.value) and not hasattr(e.value, "uso")
    # Una respuesta cortada SÍ se pagó: ErrorLectura con el uso adentro.
    monkeypatch.setattr(lab, "_post", lambda u, h, b: _respuesta(cuerpo=_ok('{"periodo": "2026', finish="length")))
    with pytest.raises(extractor.ErrorLectura) as e:
        lab.leer("moonshot:kimi-k3", "recibo", b"", "image/png", IMAGEN)
    assert e.value.uso["tokens_salida"] == 300 and "se cortó" in str(e.value)
    # Texto que no es JSON.
    monkeypatch.setattr(lab, "_post", lambda u, h, b: _respuesta(cuerpo=_ok("No puedo leer esto.")))
    with pytest.raises(extractor.ErrorLectura):
        lab.leer("moonshot:kimi-k3", "recibo", b"", "image/png", IMAGEN)
    # La red caída.
    def caido(u, h, b):
        raise httpx.ConnectError("boom")
    monkeypatch.setattr(lab, "_post", caido)
    with pytest.raises(lab.ErrorProveedor):
        lab.leer("moonshot:kimi-k3", "recibo", b"", "image/png", IMAGEN)
    # Sin la variable, ni se intenta.
    monkeypatch.delenv("MOONSHOT_API_KEY")
    with pytest.raises(lab.ErrorProveedor) as e:
        lab.leer("moonshot:kimi-k3", "recibo", b"", "image/png", IMAGEN)
    assert "MOONSHOT_API_KEY" in str(e.value)
    with pytest.raises(lab.ErrorProveedor):
        lab.leer("nadie:nada", "recibo", b"", "image/png", IMAGEN)


def test_anthropic_va_por_el_extractor(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    llamadas = []

    def falso_extraer(contenido, ct, modelo=None, imagen=None, aviso_enmascarado=False):
        llamadas.append((modelo, imagen, aviso_enmascarado))
        return dict(RECIBO), {"modelo": modelo, "tokens_entrada": 10, "tokens_salida": 5, "duracion_ms": 7}
    monkeypatch.setattr(extractor, "extraer", falso_extraer)
    _, uso = lab.leer("anthropic:claude-sonnet-4-6", "recibo", b"x", "image/png", IMAGEN, True)
    assert llamadas == [("claude-sonnet-4-6", IMAGEN, True)]
    assert uso["modelo"] == "claude-sonnet-4-6", "el id crudo, para que UsoIA encuentre el precio"


# ---------------------------------------------------------------- resultado
def test_sin_identidad_borra_lo_que_identifica_y_no_toca_el_resto():
    d = lab.sin_identidad("recibo", RECIBO)
    assert d["empleado"]["apellido_nombre"] is None and d["empleado"]["cuil"] is None and d["empleado"]["legajo"] is None
    assert d["empleado"]["categoria"] == "Administrativa" and d["empleador"]["cuit"] == "30999888778"
    assert d["lineas"] == RECIBO["lineas"] and RECIBO["empleado"]["cuil"] == "27-22222222-8"
    assert lab.sin_identidad("aportes", {"cuil": "20111111112", "meses": []}) == {"cuil": None, "meses": []}
    assert lab.sin_identidad("recibo", "basura") == {}


def test_armar_resultado_con_un_ok_y_un_error():
    otro = json.loads(json.dumps(RECIBO))
    otro["totales_impresos"]["neto"] = 890001          # un modelo leyó el neto distinto
    otro["lineas"][1]["categoria_universal"] = None     # y no clasificó la jubilación
    claves = ["anthropic:claude-sonnet-4-6", "moonshot:kimi-k3", "alibaba:qwen3.8-flash"]
    lecturas = [
        (RECIBO, {"modelo": "claude-sonnet-4-6", "tokens_entrada": 1000, "tokens_salida": 500, "duracion_ms": 4000}),
        lab.ErrorProveedor("Moonshot AI (Kimi) contestó 403: sin saldo"),
        (otro, {"modelo": "alibaba:qwen3.8-flash", "tokens_entrada": 2000, "tokens_salida": 600, "duracion_ms": 9000}),
    ]
    r = lab.armar_resultado("recibo", claves, lecturas)
    assert r["referencia"] == "Claude Sonnet 4.6" and r["ok"] == 2
    f0, f1, f2 = r["modelos"]
    assert f0["ok"] and f0["costo"] == pytest.approx((1000 * 3 + 500 * 15) / 1e6) and f0["iguales"] == f0["campos"]
    assert not f1["ok"] and "sin saldo" in f1["error"] and f1["costo_txt"] == "—" and f1["proveedor_nombre"] == "Moonshot AI (Kimi)"
    assert f2["ok"] and f2["costo"] == pytest.approx((2000 * 0.15 + 600 * 0.47) / 1e6)
    assert f2["iguales"] == f2["campos"] - 1
    assert [d["etiqueta"] for d in f2["resumen"] if not d["igual"]] == ["Neto"]
    assert r["lineas"]["total"] == 2 and r["lineas"]["distintas"] == 1
    assert r["distintos"] == 2
    guardado = lab.para_guardar("recibo", claves, lecturas, r)
    l0 = guardado["lecturas"][0]
    assert "json" not in l0 and l0["lectura"]["empleado"]["cuil"] is None
    assert next(d["valor"] for d in l0["resumen"] if d["etiqueta"] == "CUIL") == "(no se guarda)"
    assert next(d["valor"] for d in l0["resumen"] if d["etiqueta"] == "Neto") == "890.000,00"
    assert "lectura" not in guardado["lecturas"][1]


def test_resumen_por_modelo_acumula_y_salta_los_descartados():
    def ens(estado, lecturas):
        return {"estado": estado, "real": {"lecturas": lecturas}}
    a = {"clave": "a:x", "nombre": "X", "proveedor_nombre": "A", "ok": True, "duracion_ms": 1000, "costo": 0.01,
         "iguales": 8, "campos": 10}
    b = {"clave": "b:y", "nombre": "Y", "proveedor_nombre": "B", "ok": False, "error": "403"}
    res = lab.resumen_por_modelo([
        ens("nuevo", [a, b]),
        ens("revisado", [dict(a, duracion_ms=3000, costo=0.03, iguales=10), dict(b, ok=True, duracion_ms=500, costo=None, iguales=5, campos=10)]),
        ens("descartado", [dict(a, duracion_ms=99000, costo=9)]),
    ])
    x = next(m for m in res if m["clave"] == "a:x")
    assert x["ensayos"] == 2 and x["ok"] == 2 and x["tiempo_mediano_ms"] == 2000
    assert x["costo_promedio"] == pytest.approx(0.02) and x["coincidencia"] == 90
    y = next(m for m in res if m["clave"] == "b:y")
    assert y["ensayos"] == 2 and y["ok"] == 1 and y["costo_promedio_txt"] == "—" and y["coincidencia"] == 50
    assert lab.resumen_por_modelo([]) == []


# ---------------------------------------------------------------- rutas
def _con_plataforma(usuario="snavello"):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", id_usuario=1, ident=usuario))
    return c


def test_sin_pase_no_se_ve():
    c = TestClient(main.app)
    assert c.get(API + "/catalogo").status_code == 403
    assert c.get(API + "/ensayos").status_code == 403
    assert c.post(API + "/correr", files={"archivo": ("r.png", b"x", "image/png")}).status_code == 403
    r = c.get(PAGINA, headers={"Accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/entornos")


def test_en_la_demo_no_existe(monkeypatch):
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", False)
    c = _con_plataforma()
    for ruta in (PAGINA, API + "/catalogo", API + "/ensayos", "/entornos/herramientas/laboratorio/ensayos.csv"):
        assert c.get(ruta).status_code == 404
    assert c.post(API + "/correr", files={"archivo": ("r.png", b"x", "image/png")}).status_code == 404


def test_la_pagina_y_el_catalogo(monkeypatch):
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")
    c = _con_plataforma()
    html = c.get(PAGINA).text
    assert "Laboratorio de modelos" in html and f'const API = "{API}"' in html
    assert "modales.js" not in html and "sello_static" not in html.replace("?v=", "")
    cat = c.get(API + "/catalogo").json()
    por_id = {p["id"]: p for p in cat["proveedores"]}
    assert por_id["moonshot"]["configurado"] is False and por_id["moonshot"]["variable"] == "MOONSHOT_API_KEY"
    assert por_id["alibaba"]["configurado"] is True
    assert cat["mock"] is False and isinstance(cat["enmascarado"], bool) and isinstance(cat["resumen"], list)
    # La landing presenta la herramienta.
    land = c.get("/entornos").text
    assert PAGINA in land and "laboratorio-estado" in land


def test_un_modelo_sin_clave_se_rechaza_antes_de_gastar(monkeypatch):
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    c = _con_plataforma()
    r = c.post(API + "/correr", data={"tipo": "recibo", "modelos": ["moonshot:kimi-k3"]},
               files={"archivo": ("r.png", b"x", "image/png")})
    assert r.status_code == 422 and "MOONSHOT_API_KEY" in r.json()["detail"]
    r = c.post(API + "/correr", data={"tipo": "recibo", "modelos": ["nadie:nada"]},
               files={"archivo": ("r.png", b"x", "image/png")})
    assert r.status_code == 422
    r = c.post(API + "/correr", data={"tipo": "recibo"}, files={"archivo": ("r.png", b"x", "image/png")})
    assert r.status_code == 422 and "al menos" in r.json()["detail"]
    r = c.post(API + "/correr", data={"tipo": "otro", "modelos": ["anthropic:claude-sonnet-4-6"]},
               files={"archivo": ("r.png", b"x", "image/png")})
    assert r.status_code == 422


def test_correr_guarda_el_ensayo_sin_identidad_y_registra_solo_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-k")
    monkeypatch.setattr(main, "preparar_imagen", lambda contenido, ct: IMAGEN)

    def falso_leer(clave, tipo, contenido, ct, imagen, aviso=False):
        if clave.startswith("anthropic:"):
            return json.loads(json.dumps(RECIBO)), {"modelo": "claude-sonnet-4-6", "tokens_entrada": 1000,
                                                    "tokens_salida": 400, "duracion_ms": 3500}
        if clave.startswith("moonshot:"):
            raise lab.ErrorProveedor("Moonshot AI (Kimi) contestó 403: saldo insuficiente")
        otro = json.loads(json.dumps(RECIBO))
        otro["lineas"][0]["importe"] = 1000001
        return otro, {"modelo": clave, "tokens_entrada": 2500, "tokens_salida": 500, "duracion_ms": 12000}
    monkeypatch.setattr(lab, "leer", falso_leer)
    with Session(db.engine) as s:
        antes = len(s.exec(select(db.UsoIA).where(db.UsoIA.tipo == "prueba")).all())

    c = _con_plataforma("snavello")
    r = c.post(API + "/correr",
               data={"tipo": "recibo", "nota": "recibo de <b>prueba</b>",
                     "modelos": ["anthropic:claude-sonnet-4-6", "moonshot:kimi-k3", "alibaba:qwen3.8-flash"]},
               files={"archivo": ("recibo-agosto.pdf", b"%PDF-falso", "application/pdf")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["referencia"] == "Claude Sonnet 4.6" and d["ok"] == 2 and d["archivo"] == "recibo-agosto.pdf"
    assert d["modelos"][1]["ok"] is False and "saldo" in d["modelos"][1]["error"]
    assert d["modelos"][0]["json"] and "Pérez" in d["modelos"][0]["json"], "en la pantalla viva sí se ve todo"
    assert d["lineas"]["distintas"] == 1

    # UsoIA: solo la lectura de Anthropic, como "prueba" y con el id crudo.
    with Session(db.engine) as s:
        filas = s.exec(select(db.UsoIA).where(db.UsoIA.tipo == "prueba")).all()
    assert len(filas) == antes + 1 and filas[-1].modelo == "claude-sonnet-4-6" and filas[-1].precio_entrada == 3.0

    # El ensayo guardado: sin identidad, con los números de cada modelo.
    ens = c.get(API + "/ensayos").json()
    fila = next(e for e in ens["ensayos"] if e["id"] == d["id"])
    assert fila["quien"] == "snavello" and fila["tipo"] == "recibo" and fila["archivo"] == "recibo-agosto.pdf"
    assert fila["nota"] == "recibo de <b>prueba</b>" and fila["estado"] == "nuevo"
    assert [m["ok"] for m in fila["modelos"]] == [True, False, True]
    det = c.get(API + f"/ensayos/{d['id']}").json()
    texto = json.dumps(det, ensure_ascii=False)
    assert "Pérez" not in texto and "27-22222222-8" not in texto and "27222222228" not in texto
    assert det["real"]["lecturas"][0]["lectura"]["empleador"]["cuit"] == "30999888778"
    assert det["real"]["lecturas"][2]["costo"] == pytest.approx((2500 * 0.15 + 500 * 0.47) / 1e6)
    assert det["entrada"]["modelos"][1] == "moonshot:kimi-k3" and det["entrada"]["tapado"] is False
    assert len(ens["resumen"]) >= 3 and any(m["clave"] == "alibaba:qwen3.8-flash" for m in ens["resumen"])
    assert c.get(API + "/ensayos/999999").status_code == 404

    # Estado y CSV.
    assert c.post(API + f"/ensayos/{d['id']}/estado", json={"estado": "inventado"}).status_code == 422
    assert c.post(API + f"/ensayos/{d['id']}/estado", json={"estado": "revisado"}).json()["ok"]
    assert c.get(API + f"/ensayos/{d['id']}").json()["estado_quien"] == "snavello"
    csv = c.get("/entornos/herramientas/laboratorio/ensayos.csv")
    assert csv.status_code == 200 and "attachment" in csv.headers["content-disposition"]
    texto = csv.content.decode("utf-8-sig")
    assert "Qwen 3.8 Flash" in texto and "saldo insuficiente" in texto and "Pérez" not in texto
    assert "recibo-agosto.pdf" in texto


def test_el_mapa_funcional_clasifica_las_rutas_nuevas():
    import mapa_funcional
    datos = mapa_funcional.armar() if hasattr(mapa_funcional, "armar") else None
    if datos is None:
        pytest.skip("mapa_funcional sin armar()")
    assert not [r for r in datos.get("sin_clasificar", []) if "laboratorio" in json.dumps(r)]


def test_la_clave_se_pega_desde_la_pantalla_y_el_entorno_manda(monkeypatch):
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    db.set_clave_laboratorio("MOONSHOT_API_KEY", "")
    c = _con_plataforma()
    # Guardar: queda configurado, con pista y sin devolver la clave.
    r = c.post(API + "/claves", json={"proveedor": "moonshot", "clave": "sk-kimi-1234abcd"})
    assert r.status_code == 200 and r.json() == {"ok": True, "configurado": True, "origen": "guardada", "pista": "····abcd"}
    cat = c.get(API + "/catalogo").json()
    p = next(x for x in cat["proveedores"] if x["id"] == "moonshot")
    assert p["configurado"] and p["origen"] == "guardada" and p["pista"] == "····abcd" and p["editable"]
    assert next(x for x in cat["proveedores"] if x["id"] == "anthropic")["editable"] is False
    assert "sk-kimi-1234abcd" not in json.dumps(cat)
    # El motor la usa en la llamada.
    lab.configurar_claves(db.claves_laboratorio())
    assert lab.clave_de(lab.proveedor("moonshot")) == "sk-kimi-1234abcd"
    # La variable de entorno manda sobre la guardada.
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-render")
    assert lab.clave_de(lab.proveedor("moonshot")) == "sk-render" and lab.origen_clave(lab.proveedor("moonshot")) == "entorno"
    monkeypatch.delenv("MOONSHOT_API_KEY")
    # Quitar.
    assert c.post(API + "/claves", json={"proveedor": "moonshot", "clave": ""}).json()["configurado"] is False
    assert db.claves_laboratorio() == {}
    # Lo que no corresponde.
    assert c.post(API + "/claves", json={"proveedor": "anthropic", "clave": "sk-ant-12345678"}).status_code == 422
    assert c.post(API + "/claves", json={"proveedor": "moonshot", "clave": "corta"}).status_code == 422
    assert c.post(API + "/claves", json={"proveedor": "nadie", "clave": "sk-12345678"}).status_code == 422
    assert TestClient(main.app).post(API + "/claves", json={"proveedor": "moonshot", "clave": "sk-12345678"}).status_code == 403


def test_el_signo_se_senala_en_ambar_y_no_en_rojo():
    pos = json.loads(json.dumps(RECIBO)); neg = json.loads(json.dumps(RECIBO))
    pos["lineas"][1]["importe"] = 110000            # descuento en positivo
    pos["totales_impresos"]["descuentos"] = 110000
    r = lab.armar_resultado("recibo", ["anthropic:claude-sonnet-4-6", "alibaba:qwen3.8-flash"], [
        (neg, {"modelo": "claude-sonnet-4-6", "tokens_entrada": 1, "tokens_salida": 1, "duracion_ms": 1}),
        (pos, {"modelo": "alibaba:qwen3.8-flash", "tokens_entrada": 1, "tokens_salida": 1, "duracion_ms": 1})])
    f = r["modelos"][1]
    assert f["iguales"] == f["campos"], "el signo solo no es diferencia"
    desc = next(d for d in f["resumen"] if d["etiqueta"] == "Descuentos")
    assert desc["igual"] and desc["signo"] and desc["valor"] == "110.000,00"
    assert r["lineas"]["distintas"] == 0 and r["lineas"]["signos"] == 1
    assert r["lineas"]["filas"][1]["signo"] and r["lineas"]["filas"][1]["celdas"][1]["signo"] is True
    assert any("signo" in l for l in r["analisis"])


def test_el_analisis_dice_lo_que_implican_las_diferencias():
    otro = json.loads(json.dumps(RECIBO)); otro["totales_impresos"]["neto"] = 1; otro["lineas"][1]["categoria_universal"] = None
    r = lab.armar_resultado("recibo", ["anthropic:claude-sonnet-4-6", "alibaba:qwen3.8-flash", "moonshot:kimi-k3"], [
        (RECIBO, {"modelo": "claude-sonnet-4-6", "tokens_entrada": 1000, "tokens_salida": 500, "duracion_ms": 4000}),
        (otro, {"modelo": "alibaba:qwen3.8-flash", "tokens_entrada": 2000, "tokens_salida": 600, "duracion_ms": 9000}),
        lab.ErrorProveedor("sin saldo")])
    a = r["analisis"]
    assert 3 <= len(a) <= 6
    texto = " ".join(a)
    assert "no contestaron" in texto and "Kimi K3" in texto
    assert "Neto" in texto and "error de lectura" in texto
    assert "1 de 2 difieren" in texto and "cuota sindical" in texto
    assert "Costo:" in texto and "Tiempo:" in texto
    assert "más se aparta es Qwen 3.8 Flash" in texto
    assert lab.analisis([], None, None) == ["Ningún modelo leyó el archivo: no hay nada que comparar."]
    solo = lab.analisis([{"ok": True, "nombre": "X", "iguales": 3, "campos": 3}], None, "X")
    assert "Solo contestó X" in solo[0]


def test_correr_en_vivo_transmite_un_evento_por_modelo(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")
    monkeypatch.setattr(main, "preparar_imagen", lambda contenido, ct: IMAGEN)

    def falso_leer(clave, tipo, contenido, ct, imagen, aviso=False):
        if clave.startswith("anthropic:"):
            return json.loads(json.dumps(RECIBO)), {"modelo": "claude-sonnet-4-6", "tokens_entrada": 10, "tokens_salida": 5, "duracion_ms": 100}
        raise lab.ErrorProveedor("Alibaba contestó 429: sin cupo")
    monkeypatch.setattr(lab, "leer", falso_leer)
    c = _con_plataforma()
    r = c.post(API + "/correr-en-vivo", data={"tipo": "recibo", "modelos": ["anthropic:claude-sonnet-4-6", "alibaba:qwen3.8-flash"]},
               files={"archivo": ("r.png", b"x", "image/png")})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    eventos = [json.loads(l) for l in r.text.splitlines() if l.strip()]
    assert [e["evento"] for e in eventos] == ["inicio", "modelo", "modelo", "fin"]
    assert [m["clave"] for m in eventos[0]["modelos"]] == ["anthropic:claude-sonnet-4-6", "alibaba:qwen3.8-flash"]
    por = {e["clave"]: e for e in eventos[1:3]}
    assert por["anthropic:claude-sonnet-4-6"]["ok"] and por["anthropic:claude-sonnet-4-6"]["duracion_txt"] == "0,1 s"
    assert not por["alibaba:qwen3.8-flash"]["ok"] and "429" in por["alibaba:qwen3.8-flash"]["error"]
    fin = eventos[3]
    assert fin["id"] and fin["ok"] == 1 and fin["analisis"]
    assert c.get(API + f"/ensayos/{fin['id']}").json()["analisis"] == fin["analisis"]
    # Lo que falla antes de empezar, falla con su HTTP normal (sin modelos: 422).
    assert c.post(API + "/correr-en-vivo", data={"tipo": "recibo"}, files={"archivo": ("r.png", b"x", "image/png")}).status_code == 422


def test_un_importe_escrito_como_texto_argentino_es_el_mismo_importe():
    """Kimi K3 devolvió "2.180,00" (texto) donde Claude devolvió 2180.0: la app
    los lee igual (validador.a_numero), así que el comparador también. Y un
    importe que de verdad no se puede leer se dice, no sale como "· —"."""
    texto = json.loads(json.dumps(RECIBO))
    texto["lineas"][0]["importe"] = "2.180,00"; RECIBO_NUM = json.loads(json.dumps(RECIBO)); RECIBO_NUM["lineas"][0]["importe"] = 2180
    texto["lineas"][1]["importe"] = "-110.000,00"
    texto["totales_impresos"] = {"remuneraciones": "1.000.000,00", "descuentos": "-110.000,00", "neto": "890.000,00"}
    c = extractor.comparar_lineas([("a", RECIBO_NUM), ("b", texto)])
    assert c["distintas"] == 0 and c["signos"] == 0
    r = lab.armar_resultado("recibo", ["anthropic:claude-sonnet-4-6", "moonshot:kimi-k3"], [
        (RECIBO_NUM, {"modelo": "claude-sonnet-4-6", "tokens_entrada": 1, "tokens_salida": 1, "duracion_ms": 1}),
        (texto, {"modelo": "moonshot:kimi-k3", "tokens_entrada": 1, "tokens_salida": 1, "duracion_ms": 1})])
    assert r["modelos"][1]["iguales"] == r["modelos"][1]["campos"]
    ilegible = json.loads(json.dumps(RECIBO_NUM)); ilegible["lineas"][0]["importe"] = "dos mil"
    c = extractor.comparar_lineas([("a", RECIBO_NUM), ("b", ilegible)])
    assert c["distintas"] == 1 and c["filas"][0]["celdas"][1]["valor"].endswith("· importe ilegible")


def test_el_cuit_con_guiones_no_lleva_signo_y_el_verificador_delata_el_digito_mal_leido():
    """Caso real (SDN, 2026-10-29): la referencia leyó 33693450239, otro
    33-69345023-9 (el mismo CUIT, salía con ±) y Kimi 33-59345023-9 (un
    dígito mal leído, que además no pasa el módulo 11)."""
    def con(cuit_):
        r = json.loads(json.dumps(RECIBO)); r["empleador"]["cuit"] = cuit_; return r
    r = lab.armar_resultado("recibo", ["anthropic:claude-sonnet-4-6", "alibaba:qwen3.8-flash", "moonshot:kimi-k3"], [
        (con("33693450239"), {"modelo": "claude-sonnet-4-6", "tokens_entrada": 1, "tokens_salida": 1, "duracion_ms": 1}),
        (con("33-69345023-9"), {"modelo": "alibaba:qwen3.8-flash", "tokens_entrada": 1, "tokens_salida": 1, "duracion_ms": 1}),
        (con("33-59345023-9"), {"modelo": "moonshot:kimi-k3", "tokens_entrada": 1, "tokens_salida": 1, "duracion_ms": 1})])
    fila = lambda i: next(d for d in r["modelos"][i]["resumen"] if d["etiqueta"] == "CUIT del empleador")
    assert fila(1)["igual"] and not fila(1)["signo"] and not fila(1)["invalido"]
    assert not fila(2)["igual"] and not fila(2)["signo"] and fila(2)["invalido"]
    assert not fila(0)["invalido"]
    assert any("Kimi K3" in l and "verificador" in l for l in r["analisis"])
    # El ± sigue existiendo para lo que es signo de verdad.
    neg = json.loads(json.dumps(RECIBO)); neg["totales_impresos"]["descuentos"] = 110000
    r2 = lab.armar_resultado("recibo", ["anthropic:claude-sonnet-4-6", "moonshot:kimi-k3"], [
        (RECIBO, {"modelo": "claude-sonnet-4-6", "tokens_entrada": 1, "tokens_salida": 1, "duracion_ms": 1}),
        (neg, {"modelo": "moonshot:kimi-k3", "tokens_entrada": 1, "tokens_salida": 1, "duracion_ms": 1})])
    assert next(d for d in r2["modelos"][1]["resumen"] if d["etiqueta"] == "Descuentos")["signo"]


def test_un_modelo_que_no_vuelve_no_deja_sin_resultado_a_los_otros(monkeypatch):
    """SDN corrió cinco en paralelo, uno no terminó y no vio ninguno. Ahora el
    tope por modelo lo deja como «no terminó» y el ensayo sale con los demás."""
    import time as _t
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant"); monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")
    monkeypatch.setattr(main, "preparar_imagen", lambda contenido, ct: IMAGEN)
    monkeypatch.setattr(main, "LABORATORIO_LIMITE_S", 0.3)

    def falso_leer(clave, tipo, contenido, ct, imagen, aviso=False):
        if clave.startswith("alibaba:"):
            _t.sleep(3)
        return json.loads(json.dumps(RECIBO)), {"modelo": "claude-sonnet-4-6", "tokens_entrada": 10, "tokens_salida": 5, "duracion_ms": 100}
    monkeypatch.setattr(lab, "leer", falso_leer)
    c = _con_plataforma()
    r = c.post(API + "/correr-en-vivo", data={"tipo": "recibo", "modelos": ["anthropic:claude-sonnet-4-6", "alibaba:qwen3.8-flash"]},
               files={"archivo": ("r.png", b"x", "image/png")})
    eventos = [json.loads(l) for l in r.text.splitlines() if l.strip()]
    assert eventos[0]["corrida"] and eventos[0]["limite_s"] == 0.3
    por = {e["clave"]: e for e in eventos if e["evento"] == "modelo"}
    assert por["anthropic:claude-sonnet-4-6"]["ok"]
    assert not por["alibaba:qwen3.8-flash"]["ok"] and "no terminó" in por["alibaba:qwen3.8-flash"]["error"]
    fin = eventos[-1]
    assert fin["evento"] == "fin" and fin["ok"] == 1 and fin["modelos"][0]["ok"] and fin["id"]


def test_detener_un_modelo_desde_la_pantalla(monkeypatch):
    import time as _t
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant"); monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")
    monkeypatch.setattr(main, "preparar_imagen", lambda contenido, ct: IMAGEN)
    monkeypatch.setattr(main, "_nuevo_rid", lambda: "corrida-test")

    def falso_leer(clave, tipo, contenido, ct, imagen, aviso=False):
        if clave.startswith("alibaba:"):
            _t.sleep(3)
        return json.loads(json.dumps(RECIBO)), {"modelo": "claude-sonnet-4-6", "tokens_entrada": 10, "tokens_salida": 5, "duracion_ms": 100}
    monkeypatch.setattr(lab, "leer", falso_leer)
    c = _con_plataforma()
    # El pedido de detener llega "antes" (la corrida ya está registrada con ese id).
    main._CORRIDAS_LABORATORIO["corrida-test"] = {"alibaba:qwen3.8-flash"}
    r = c.post(API + "/correr-en-vivo", data={"tipo": "recibo", "modelos": ["anthropic:claude-sonnet-4-6", "alibaba:qwen3.8-flash"]},
               files={"archivo": ("r.png", b"x", "image/png")})
    eventos = [json.loads(l) for l in r.text.splitlines() if l.strip()]
    por = {e["clave"]: e for e in eventos if e["evento"] == "modelo"}
    assert por["anthropic:claude-sonnet-4-6"]["ok"]
    assert "detenido desde la pantalla" in por["alibaba:qwen3.8-flash"]["error"]
    assert eventos[-1]["evento"] == "fin" and eventos[-1]["ok"] == 1
    assert "corrida-test" not in main._CORRIDAS_LABORATORIO
    # La ruta de detener: 404 si la corrida no existe, 200 si está en curso.
    assert c.post(API + "/correr/nada/detener", json={"clave": "x"}).status_code == 404
    main._CORRIDAS_LABORATORIO["viva"] = set()
    assert c.post(API + "/correr/viva/detener", json={"todo": True}).json()["ok"] and main._CORRIDAS_LABORATORIO.pop("viva") == {"*"}


def test_un_429_se_reintenta_y_despues_se_rinde(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")
    monkeypatch.setattr(lab.time, "sleep", lambda s: None)
    respuestas = [httpx.Response(429, text="Throttling", headers={"Retry-After": "1"}),
                  httpx.Response(200, json=_ok(json.dumps(RECIBO)))]
    monkeypatch.setattr(lab, "_post", lambda u, h, b: respuestas.pop(0))
    datos, _ = lab.leer("alibaba:qwen3.8-flash", "recibo", b"", "image/png", IMAGEN)
    assert datos["periodo"] == "2026-08" and not respuestas
    monkeypatch.setattr(lab, "_post", lambda u, h, b: httpx.Response(429, text="Throttling"))
    with pytest.raises(lab.ErrorProveedor) as e:
        lab.leer("alibaba:qwen3.8-flash", "recibo", b"", "image/png", IMAGEN)
    assert "429" in str(e.value) and "reintentar" in str(e.value)

