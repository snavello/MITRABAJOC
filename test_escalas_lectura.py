"""La lectura de la grilla con la IA (escalas_lectura.py), con el cliente
SIMULADO: la sesión no tiene clave de la API, así que acá se prueba el
armado de los pedidos, el saneo de lo que devuelve y los fallos. La lectura
real se prueba en Pruebas (bloque 6).

Correr con: python -m pytest test_escalas_lectura.py -q
"""
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import escalas_lectura as lec
import extractor
import precios_ia

AGOSTO = json.loads((Path(__file__).parent / "data" / "grillas_bancarias" / "2026-08.json").read_text(encoding="utf-8"))
PLANTILLA = lec.plantilla_sin_importes(AGOSTO)
IMAGENES = [("AAAA", "image/png")] * 3


def _pdf(paginas=3) -> bytes:
    ims = [Image.new("RGB", (595, 842), "white") for _ in range(paginas)]
    buf = io.BytesIO()
    ims[0].save(buf, format="PDF", save_all=True, append_images=ims[1:])
    return buf.getvalue()


class Cliente:
    """Devuelve, según la herramienta pedida, lo que dice la grilla de agosto
    (con la alteración que se le indique)."""

    def __init__(self, alterar=None, parada="tool_use", error=None):
        self.llamadas = []
        self.alterar = alterar or (lambda nombre, d: d)
        self.parada, self.error = parada, error
        self.messages = self

    def create(self, **kw):
        self.llamadas.append(kw)
        if self.error:
            raise self.error
        nombre = kw["tools"][0]["name"]
        prompt = kw["messages"][0]["content"][-1]["text"]
        if nombre == "registrar_rama":
            clave = next(k for k in AGOSTO["ramas"] if f"rama {AGOSTO['ramas'][k]['nombre'].upper()}" in prompt)
            datos = {"categorias": AGOSTO["ramas"][clave]["categorias"], "notas": []}
        else:
            datos = {"periodo_impreso": "2026-08", "adicionales": AGOSTO["adicionales"],
                     "conectividad": AGOSTO["conectividad"], "roe": AGOSTO["roe"],
                     "dia_bancario": AGOSTO["dia_bancario"], "notas": []}
        datos = self.alterar(nombre + ":" + (clave if nombre == "registrar_rama" else ""), json.loads(json.dumps(datos)))
        return SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", input=datos)], stop_reason=self.parada,
            usage=SimpleNamespace(input_tokens=25000, output_tokens=1800, cache_read_input_tokens=0, cache_creation_input_tokens=0))


@pytest.fixture(autouse=True)
def _sin_cliente_real(monkeypatch):
    monkeypatch.delenv("MOCK_EXTRACTOR", raising=False)
    lec.usar_cliente(None)
    yield
    lec.usar_cliente(None)


# ---------------------------------------------------------------- default y modelo
def test_el_default_es_sonnet_5_5_del_catalogo_y_razona_asi_que_va_con_esfuerzo_bajo():
    assert lec.MODELO == "claude-sonnet-5-5" == precios_ia.default_de("grilla_salarial")
    assert precios_ia.modelo_valido(lec.MODELO)
    assert lec.MODELO in extractor.MODELOS_QUE_RAZONAN
    assert extractor._opciones(lec.MODELO) == {"output_config": {"effort": "low"}}


# ---------------------------------------------------------------- plantilla y esquemas
def test_la_plantilla_no_lleva_ningun_importe_ni_coeficiente():
    texto = json.dumps(PLANTILLA, ensure_ascii=False)
    for c in AGOSTO["ramas"]["administrativa"]["categorias"][:6]:
        assert str(c["basico"]) not in texto and str(c["coef"]) not in texto
    assert "1642764" not in texto and "163963" not in texto
    adm = PLANTILLA["ramas"]["administrativa"]["categorias"]
    assert adm[0] == {"nombre": "Inicial", "anios": 0} and len(adm) == len(AGOSTO["ramas"]["administrativa"]["categorias"])
    assert PLANTILLA["adicionales"]["titulos"] == {"secundario": None, "terciario": None, "universitario": None}


def test_los_esquemas_son_cerrados_y_aceptan_nulos():
    h = lec.herramienta_rama("Administrativa")
    esq = h["input_schema"]
    assert h["strict"] and esq["additionalProperties"] is False and set(esq["required"]) == {"categorias", "notas"}
    cat = esq["properties"]["categorias"]["items"]
    assert set(cat["required"]) == {"nombre", "anios", "coef", "basico", "conformado", "basico_parcial", "conformado_parcial"}
    # D28: la lectura parcial es un texto NO anulable (no suma uniones al esquema estricto).
    assert cat["properties"]["basico_parcial"]["type"] == "string" and cat["properties"]["conformado_parcial"]["type"] == "string"
    assert {"type": "null"} in cat["properties"]["basico"]["anyOf"]
    r = lec.herramienta_resto(PLANTILLA)["input_schema"]
    adic = r["properties"]["adicionales"]
    claves = adic["items"]["properties"]["clave"]["enum"]
    assert "funcion_cajero" in claves and "titulos.universitario" in claves
    assert {c.split(".", 1)[1] for c in claves if c.startswith("zona_patagonica.")} == set(AGOSTO["adicionales"]["zona_patagonica"])
    assert adic["items"]["additionalProperties"] is False
    assert json.dumps(r)                      # serializable


def test_el_prompt_lista_los_nombres_en_orden_y_pide_null_ante_la_duda():
    p = lec.prompt_rama("maestranza", PLANTILLA)
    nombres = [c["nombre"] for c in AGOSTO["ramas"]["maestranza"]["categorias"]]
    assert p.index(nombres[0]) < p.index(nombres[-1]) and "MAESTRANZA" in p and "null" in p
    assert "NUNCA" in lec.SISTEMA and "null" in lec.SISTEMA
    assert "Día del Bancario" in lec.SISTEMA          # las tablas parecidas no son básicos


# ---------------------------------------------------------------- lectura
def test_una_lectura_reproduce_la_grilla_y_hace_una_llamada_por_seccion():
    cli = Cliente()
    lec.usar_cliente(cli)
    l = lec.leer_una_vez(IMAGENES, PLANTILLA, lec.MODELO)
    assert len(cli.llamadas) == 4
    esperado = {k: AGOSTO[k] for k in ("ramas", "adicionales", "conectividad", "roe", "dia_bancario")}
    assert l["contenido"] == esperado
    assert l["periodo_impreso"] == "2026-08" and l["notas"] == []
    assert len(l["usos"]) == 4 and l["usos"][0]["tokens_entrada"] == 25000
    for kw in cli.llamadas:
        assert kw["model"] == lec.MODELO and kw["max_tokens"] == lec.MAX_TOKENS
        assert kw["output_config"] == {"effort": "low"}
        # Nunca forzada: Sonnet 5.5 rechaza tool_choice "any"/"tool" con un 400 (bloque 6, 2026-11-16).
        assert kw["tool_choice"] == {"type": "auto"} and len(kw["tools"]) == 1
        contenido = kw["messages"][0]["content"]
        assert sum(1 for b in contenido if b["type"] == "image") == 3          # todas las páginas, en cada llamada
        assert len(kw["messages"]) == 1                                        # ninguna ve la lectura anterior


def test_se_lee_dos_veces_en_llamadas_independientes():
    cli = Cliente()
    lec.usar_cliente(cli)
    lecturas = lec.leer(_pdf(3), PLANTILLA, lec.MODELO)
    assert len(lecturas) == 2 and len(cli.llamadas) == 8
    assert lecturas[0]["contenido"] == lecturas[1]["contenido"]
    assert all(len(kw["messages"]) == 1 for kw in cli.llamadas)


def test_un_importe_que_no_se_leyo_queda_nulo_y_un_texto_no_es_un_importe():
    def alterar(nombre, d):
        if nombre == "registrar_rama:administrativa":
            d["categorias"][5]["basico"] = None
            d["categorias"][6]["basico"] = "mil setecientos"
            d["categorias"][7]["coef"] = True
        return d
    lec.usar_cliente(Cliente(alterar))
    l = lec.leer_una_vez(IMAGENES, PLANTILLA, lec.MODELO)
    cats = l["contenido"]["ramas"]["administrativa"]["categorias"]
    assert cats[5]["basico"] is None and cats[6]["basico"] is None and cats[7]["coef"] is None
    # D29: esto es un defecto de la respuesta (retiene C1), no un comentario del modelo.
    assert any("no numérico" in n for n in l["defectos"]) and l["notas"] == []


def test_las_notas_de_la_ia_pasan_a_quien_controla():
    def alterar(nombre, d):
        if nombre.startswith("registrar_resto"):
            d["notas"] = ["no se ve el ROE de la última fila"]
        return d
    lec.usar_cliente(Cliente(alterar))
    assert "no se ve el ROE de la última fila" in lec.leer_una_vez(IMAGENES, PLANTILLA, lec.MODELO)["notas"]


def test_los_importes_se_redondean_a_centavos():
    def alterar(nombre, d):
        if nombre == "registrar_rama:ordenanza":
            d["categorias"][2]["basico"] = 1642764.4912345
        return d
    lec.usar_cliente(Cliente(alterar))
    cats = lec.leer_una_vez(IMAGENES, PLANTILLA, lec.MODELO)["contenido"]["ramas"]["ordenanza"]["categorias"]
    assert cats[2]["basico"] == 1642764.49


# ---------------------------------------------------------------- fallos
def test_una_respuesta_cortada_levanta_con_lo_gastado():
    lec.usar_cliente(Cliente(parada="max_tokens"))
    with pytest.raises(lec.ErrorLectura) as e:
        lec.leer_una_vez(IMAGENES, PLANTILLA, lec.MODELO)
    assert "tope" in str(e.value) and len(e.value.usos) == 1


def test_la_api_caida_levanta_error_de_lectura():
    lec.usar_cliente(Cliente(error=TimeoutError("sin respuesta")))
    with pytest.raises(lec.ErrorLectura) as e:
        lec.leer_una_vez(IMAGENES, PLANTILLA, lec.MODELO)
    assert "TimeoutError" in str(e.value)


def test_un_fallo_en_la_segunda_lectura_informa_todo_lo_gastado():
    class Falla(Cliente):
        def create(self, **kw):
            if len(self.llamadas) == 5:
                self.llamadas.append(kw)
                raise RuntimeError("500")
            return super().create(**kw)
    lec.usar_cliente(Falla())
    with pytest.raises(lec.ErrorLectura) as e:
        lec.leer(_pdf(2), PLANTILLA, lec.MODELO)
    assert len(e.value.usos) == 5            # la primera lectura (4) y la primera llamada de la segunda


def test_una_respuesta_sin_herramienta_no_sirve():
    class SinTool(Cliente):
        def create(self, **kw):
            super().create(**kw)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="no sé")], stop_reason="end_turn",
                                   usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    lec.usar_cliente(SinTool())
    with pytest.raises(lec.ErrorLectura):
        lec.leer_una_vez(IMAGENES, PLANTILLA, lec.MODELO)


def test_con_el_mock_no_se_llama_a_la_api(monkeypatch):
    monkeypatch.setenv("MOCK_EXTRACTOR", "1")
    lec.usar_cliente(Cliente())
    ok, motivo = lec.disponible()
    assert ok is False and "MOCK_EXTRACTOR" in motivo


def test_sin_clave_no_hay_lectura(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    lec.usar_cliente(None)
    assert lec.disponible()[0] is False
    with pytest.raises(lec.ErrorLectura):
        lec.leer_una_vez(IMAGENES, PLANTILLA, lec.MODELO)


# ---------------------------------------------------------------- imágenes
def test_las_paginas_se_preparan_una_vez_con_el_tope_de_lado():
    imgs = lec.paginas_a_imagenes(_pdf(4))
    assert len(imgs) == 4 and all(m == "image/png" for _, m in imgs)
    import base64
    from PIL import Image as I
    ancho, alto = I.open(io.BytesIO(base64.b64decode(imgs[0][0]))).size
    assert max(ancho, alto) <= 2000


def test_un_pdf_roto_levanta():
    with pytest.raises(Exception):
        lec.paginas_a_imagenes(b"%PDF-1.7 roto")


def test_los_esquemas_estrictos_no_pasan_el_tope_de_parametros_que_pueden_ser_null():
    """La API rechaza con 400 un esquema estricto con más de 16 parámetros con anyOf
    (bloque 6, 2026-11-16: el de «resto» tenía 18)."""
    assert lec.uniones(lec.herramienta_resto(PLANTILLA)["input_schema"]) <= lec.LIMITE_UNIONES
    assert lec.uniones(lec.herramienta_rama("Administrativa")["input_schema"]) <= lec.LIMITE_UNIONES


def test_los_adicionales_en_filas_se_arman_igual_que_la_grilla():
    filas = []
    for k, v in AGOSTO["adicionales"].items():
        filas += ([{"clave": f"{k}.{k2}", "importe": v2} for k2, v2 in v.items()] if isinstance(v, dict)
                  else [{"clave": k, "importe": v}])
    notas = []
    r = lec.sanear_resto({"adicionales": filas}, notas)
    assert r["adicionales"] == AGOSTO["adicionales"] and notas == []
    notas = []
    r = lec.sanear_resto({"adicionales": filas + [filas[0], "x", {"clave": "titulos.terciario", "importe": None}]}, notas)
    assert r["adicionales"] == AGOSTO["adicionales"] and len(notas) == 3      # repetidos e ilegibles no pisan nada


# ---------------------------------------------------------------- D28: lectura parcial
def test_d28_los_esquemas_piden_la_lectura_parcial_como_texto_y_siguen_bajo_el_tope():
    rama = lec.herramienta_rama("Administrativa")["input_schema"]
    resto = lec.herramienta_resto(PLANTILLA)["input_schema"]
    fila = resto["properties"]["adicionales"]["items"]
    assert fila["properties"]["importe_parcial"]["type"] == "string" and "importe_parcial" in fila["required"]
    # Las uniones (parámetros con anyOf) no cambiaron: 4 en la rama y 10 en «resto», tope 16.
    assert (lec.uniones(rama), lec.uniones(resto)) == (4, 10)
    assert lec.uniones(rama) <= lec.LIMITE_UNIONES and lec.uniones(resto) <= lec.LIMITE_UNIONES
    for texto in (lec.SISTEMA, lec.prompt_rama("maestranza", PLANTILLA), lec.prompt_resto(PLANTILLA)):
        assert "?" in texto and "parcial" in texto


def test_d28_la_lectura_parcial_se_devuelve_aparte_y_no_ensucia_la_grilla():
    def alterar(nombre, d):
        if nombre == "registrar_rama:maestranza":
            d["categorias"][37]["basico"] = None
            d["categorias"][37]["basico_parcial"] = " 3.?22.194,42 "
            d["categorias"][36]["conformado_parcial"] = ""            # leyó bien: vacío, no se guarda
        if nombre.startswith("registrar_resto"):
            d["adicionales"] = [{"clave": "funcion_cajero", "importe": None, "importe_parcial": "1.?00,00"},
                                {"clave": "guarderia", "importe": 5.0, "importe_parcial": 7}]    # un número no es un texto
        return d
    lec.usar_cliente(Cliente(alterar))
    l = lec.leer_una_vez(IMAGENES, PLANTILLA, lec.MODELO)
    assert l["parciales"] == {"ramas.maestranza.categorias.37.basico": "3.?22.194,42",
                              "adicionales.funcion_cajero": "1.?00,00"}
    cat = l["contenido"]["ramas"]["maestranza"]["categorias"][37]
    assert cat["basico"] is None and "basico_parcial" not in cat            # el contenido conserva la forma de la grilla
    assert l["contenido"]["adicionales"]["funcion_cajero"] is None


def test_d28_sin_lectura_parcial_el_resultado_trae_un_dict_vacio():
    lec.usar_cliente(Cliente())
    assert lec.leer_una_vez(IMAGENES, PLANTILLA, lec.MODELO)["parciales"] == {}


def test_la_lectura_parcial_se_recorta():
    """QA de D28: un texto parcial enorme no viaja a la base ni al detalle del control."""
    assert lec._parcial("3.?22.194,42") == "3.?22.194,42"
    assert len(lec._parcial("9" * 40000)) == lec.MAX_PARCIAL and lec._parcial(5) == "" and lec._parcial("   ") == ""
