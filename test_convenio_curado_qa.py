"""QA independiente del curado de preguntas frecuentes (PLAN_CONVENIO_ESCALAS.md D41).

Intenta romper lo que armaron los desarrolladores: siembra concurrente, ediciones
que se pisan, sello de refresco, lo que ven el afiliado y la IA, tamaño del prompt,
rutas hostiles, enlaces engañosos y una sola conexión por pedido.

Correr con: python -m pytest test_convenio_curado_qa.py -q
"""
import json
import os
import threading

os.environ["ENTORNO"] = "pruebas"
os.environ["PIN_ENTORNOS"] = "13572468"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlmodel import Session, delete, select

import auth
import consulta_convenio_ia
import convenio_faq
import db
import entorno
import main

API = "/api/entornos/herramientas/escalas"
CURADO = API + "/curado"
CONV = db.CONVENIO_BANCARIO

NUEVA = {"id": "qa-uno", "tema": "vacaciones", "pregunta": "¿Cómo se prueba esto?", "en_corto": "Así se prueba.",
         "respuesta": "El art. 48 lo regula.", "articulos": [48]}


def _vaciar():
    with Session(db.engine) as s:
        s.exec(delete(db.PreguntaFrecuenteCambio))
        s.exec(delete(db.PreguntaFrecuente))
        s.commit()


@pytest.fixture(autouse=True)
def base():
    _vaciar()
    convenio_faq.registrar(CONV, None)
    main._FAQ_SELLO["sello"] = None
    db.sembrar_preguntas()
    main._refrescar_preguntas(forzar=True)
    yield
    _vaciar()
    convenio_faq.registrar(CONV, None)
    main._FAQ_SELLO["sello"] = None


def _c(ident="snavello"):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIES_POR_ROL["plataforma"], auth.crear_sesion("plataforma", id_usuario=1, ident=ident))
    return c


def _publicas():
    return {q["id"]: q for t in convenio_faq.publico()["temas"] for q in t["preguntas"]}


# ======================================================================= A. datos y concurrencia
def test_la_siembra_concurrente_no_duplica():
    _vaciar()
    resultados, errores = [], []

    def sembrar():
        try:
            resultados.append(db.sembrar_preguntas())
        except Exception as e:                                   # pragma: no cover
            errores.append(e)
    hilos = [threading.Thread(target=sembrar) for _ in range(8)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert not errores
    assert len(db.listar_preguntas(CONV)) == 151                 # ni una de más
    assert sum(resultados) == 151                                # y cada fila la insertó un solo proceso


def test_la_siembra_ignora_las_filas_de_otro_convenio_y_no_las_toca():
    _vaciar()
    with Session(db.engine) as s:
        s.add(db.PreguntaFrecuente(convenio="otro-cct", clave="solo-del-otro", tema="x", pregunta="¿?", version=7))
        s.commit()
    assert db.sembrar_preguntas() == 151                         # el otro convenio no cuenta como «ya sembrado»
    assert db.sembrar_preguntas() == 0
    assert db.listar_preguntas("otro-cct")[0]["id"] == "solo-del-otro"
    assert len(db.listar_preguntas(CONV)) == 151
    assert db.sello_preguntas("otro-cct") != db.sello_preguntas(CONV)


def test_una_siembra_a_medias_no_deja_el_convenio_a_la_mitad(monkeypatch):
    """Si algo falla en medio de la siembra, no queda ninguna fila (una sola transacción)."""
    _vaciar()
    real = db.postgresql.insert
    cuenta = {"n": 0}

    def roto(*a, **k):
        cuenta["n"] += 1
        if cuenta["n"] == 60:
            raise RuntimeError("se cayó la base")
        return real(*a, **k)
    monkeypatch.setattr(db.postgresql, "insert", roto)
    with pytest.raises(RuntimeError):
        db.sembrar_preguntas()
    monkeypatch.setattr(db.postgresql, "insert", real)
    assert db.listar_preguntas(CONV) == []
    assert db.sembrar_preguntas() == 151


def test_si_la_siembra_falla_la_app_sigue_con_el_archivo(monkeypatch):
    _vaciar()
    convenio_faq.registrar(CONV, None)
    main._FAQ_SELLO["sello"] = None

    def cae(*a, **k):
        raise RuntimeError("tabla inexistente")
    monkeypatch.setattr(db, "sembrar_preguntas", cae)
    monkeypatch.setattr(db, "sello_preguntas", cae)
    main._preguntas_al_dia()                                     # no levanta
    with pytest.raises(RuntimeError):
        main._refrescar_preguntas(forzar=True)                   # el arranque lo atrapa (try/except en _startup)
    r = _c().get(API + "/frecuentes")
    assert r.status_code == 200 and len(_publicas()) == 119      # sigue sirviendo el archivo


def test_una_tabla_vacia_se_siembra_antes_del_primer_pedido():
    """El deploy de Pruebas: la tabla nace vacía y el primer pedido ya ve las 119."""
    _vaciar()
    convenio_faq.registrar(CONV, None)
    main._FAQ_SELLO["sello"] = None
    r = _c().get(API + "/frecuentes")
    assert r.status_code == 200
    assert sum(len(t["preguntas"]) for t in r.json()["temas"]) == 119
    assert len(db.listar_preguntas(CONV)) == 151


def test_el_sello_cambia_con_cada_tipo_de_cambio():
    c = _c()
    vistos = [db.sello_preguntas()]

    def nuevo(que):
        s = db.sello_preguntas()
        assert s != vistos[-1], que
        vistos.append(s)
    assert c.post(f"{CURADO}/vac-dias", json={"en_corto": "Un texto distinto."}).status_code == 200
    nuevo("editar")
    assert c.post(f"{CURADO}/vac-dias/estado", json={"estado": "revisada"}).status_code == 200
    nuevo("revisar")
    assert c.post(f"{CURADO}/vac-dias/estado", json={"estado": "retirada", "motivo": "x"}).status_code == 200
    nuevo("retirar")
    assert c.post(CURADO, json=NUEVA).status_code == 200
    nuevo("crear")
    claves = [f["id"] for f in db.listar_preguntas(CONV, tema="vacaciones")]
    assert c.post(CURADO + "/reordenar", json={"tema": "vacaciones", "claves": list(reversed(claves))}).status_code == 200
    nuevo("reordenar")
    # y una edición que no cambia nada NO mueve el sello (no hay nada que releer)
    actual = db.obtener_pregunta("qa-uno")
    assert c.post(f"{CURADO}/qa-uno", json={"en_corto": actual["en_corto"]}).status_code == 200
    assert db.sello_preguntas() == vistos[-1]


def test_dos_procesos_ven_el_cambio_del_otro_en_el_pedido_siguiente():
    """Simula dos workers: el sello de memoria de uno queda viejo y el siguiente pedido lo refresca."""
    c = _c()
    c.get(API + "/frecuentes")
    sello_a = main._FAQ_SELLO["sello"]
    limpio, err = convenio_faq.validar_pregunta({**db.obtener_pregunta("vac-dias"), "en_corto": "Lo escribió el worker B."})
    assert not err
    db.editar_pregunta(CONV, "vac-dias", limpio, "worker-b")
    assert _publicas()["vac-dias"]["en_corto"] != "Lo escribió el worker B."   # el A todavía no se enteró
    q = next(q for t in c.get(API + "/frecuentes").json()["temas"] for q in t["preguntas"] if q["id"] == "vac-dias")
    assert q["en_corto"] == "Lo escribió el worker B." and main._FAQ_SELLO["sello"] != sello_a


def test_dos_personas_editando_la_misma_pregunta_no_se_pisan_en_silencio():
    c = _c()
    viva = db.obtener_pregunta("vac-dias")
    assert "version" in viva
    # Ana y Beto abrieron la misma versión.
    r1 = c.post(f"{CURADO}/vac-dias", json={"en_corto": "Texto de Ana.", "version": viva["version"]})
    assert r1.status_code == 200 and r1.json()["pregunta"]["version"] == viva["version"] + 1
    r2 = c.post(f"{CURADO}/vac-dias", json={"en_corto": "Texto de Beto.", "version": viva["version"]})
    assert r2.status_code == 409
    assert r2.json()["errores"][0]["codigo"] == "conflicto" and "Otra persona" in r2.json()["detail"]
    assert db.obtener_pregunta("vac-dias")["en_corto"] == "Texto de Ana."          # lo de Ana sigue
    # También al cambiar el estado con la versión vieja.
    r3 = c.post(f"{CURADO}/vac-dias/estado", json={"estado": "revisada", "version": viva["version"]})
    assert r3.status_code == 409 and db.obtener_pregunta("vac-dias")["estado"] == "sin_revisar"
    # Con la versión al día, sí; y la respuesta trae la nueva para el próximo guardado.
    v = r1.json()["pregunta"]["version"]
    r4 = c.post(f"{CURADO}/vac-dias/estado", json={"estado": "revisada", "version": v})
    assert r4.status_code == 200 and r4.json()["pregunta"]["version"] == v + 1


def test_sin_version_se_guarda_como_antes_y_una_version_basura_se_rechaza():
    c = _c()
    assert c.post(f"{CURADO}/vac-dias", json={"en_corto": "Sin versión."}).status_code == 200
    for malo in ("3", True, -1, 1.5, [1], {"v": 1}, 10 ** 12):
        r = c.post(f"{CURADO}/vac-dias", json={"en_corto": "x", "version": malo})
        assert r.status_code == 400 and r.json()["errores"][0]["campo"] == "version", malo
    assert db.obtener_pregunta("vac-dias")["en_corto"] == "Sin versión."


def test_ediciones_simultaneas_se_serializan_sin_perder_la_version():
    """Diez guardados a la vez con la misma versión: gana uno, los otros nueve reciben 409."""
    c = _c()
    v = db.obtener_pregunta("vac-dias")["version"]
    estados = []

    def guardar(i):
        estados.append(_c().post(f"{CURADO}/vac-dias", json={"en_corto": f"Texto {i}.", "version": v}).status_code)
    hilos = [threading.Thread(target=guardar, args=(i,)) for i in range(10)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert sorted(estados) == [200] + [409] * 9
    assert db.obtener_pregunta("vac-dias")["version"] == v + 1


def test_reordenar_mientras_otro_crea_no_deja_el_tema_roto():
    c = _c()
    claves = [f["id"] for f in db.listar_preguntas(CONV, tema="vacaciones")]
    assert c.post(CURADO, json=NUEVA).status_code == 200               # otra persona creó una en el tema
    r = c.post(CURADO + "/reordenar", json={"tema": "vacaciones", "claves": list(reversed(claves))})
    assert r.status_code == 400 and "todas las preguntas del tema" in r.json()["detail"]
    nuevas = [f["id"] for f in db.listar_preguntas(CONV, tema="vacaciones")]
    assert c.post(CURADO + "/reordenar", json={"tema": "vacaciones", "claves": list(reversed(nuevas))}).status_code == 200
    assert [f["id"] for f in sorted(db.listar_preguntas(CONV, tema="vacaciones"), key=lambda f: f["orden"])] == list(reversed(nuevas))


def test_un_pedido_nunca_tiene_dos_conexiones_a_la_vez():
    """Regla de la casa: una sesión de base por request. Se mide el máximo de conexiones del pool
    tomadas al mismo tiempo en cada ruta del curado, de lo público y de /preguntar."""
    c = _c()
    activo, pico = {"n": 0}, {"n": 0}
    cerrojo = threading.Lock()

    def sale(*a):
        with cerrojo:
            activo["n"] += 1
            pico["n"] = max(pico["n"], activo["n"])

    def vuelve(*a):
        with cerrojo:
            activo["n"] -= 1
    event.listen(db.engine, "checkout", sale)
    event.listen(db.engine, "checkin", vuelve)
    try:
        casos = [("get", API + "/frecuentes", None), ("get", API + "/frecuentes/curado", None), ("get", CURADO, None),
                 ("get", CURADO + "/vac-dias", None), ("get", CURADO + "/articulos", None),
                 ("post", CURADO, NUEVA), ("post", f"{CURADO}/qa-uno", {"en_corto": "Otra."}),
                 ("post", f"{CURADO}/qa-uno/estado", {"estado": "revisada"}),
                 ("post", f"{CURADO}/qa-uno/estado", {"estado": "retirada", "motivo": "x"}),
                 ("post", f"{CURADO}/qa-uno/estado", {"estado": "sin_revisar"}),
                 ("post", CURADO + "/reordenar", lambda: {"tema": "vacaciones", "claves": [f["id"] for f in db.listar_preguntas(CONV, tema="vacaciones")]}),
                 ("post", API + "/preguntar", {"pregunta": "¿Cuántos días de vacaciones tengo?"})]
        for metodo, url, cuerpo in casos:
            main._FAQ_SELLO["sello"] = None                     # fuerza el refresco dentro del pedido
            pico["n"] = 0
            cuerpo = cuerpo() if callable(cuerpo) else cuerpo
            r = getattr(c, metodo)(url, **({"json": cuerpo} if cuerpo is not None else {}))
            assert r.status_code == 200, (url, r.status_code, r.text[:200])
            assert pico["n"] <= 1, (url, pico["n"])
    finally:
        event.remove(db.engine, "checkout", sale)
        event.remove(db.engine, "checkin", vuelve)


def test_el_refresco_por_pedido_es_barato():
    """Sin cambios, cada pedido cuesta una sola consulta de agregado (el sello), no un releído."""
    c = _c()
    c.get(API + "/frecuentes")
    consultas = []

    def contar(conn, cursor, statement, *a):
        consultas.append(statement)
    event.listen(db.engine, "before_cursor_execute", contar)
    try:
        c.get(API + "/frecuentes")
    finally:
        event.remove(db.engine, "before_cursor_execute", contar)
    sobre_preguntas = [q for q in consultas if "preguntafrecuente" in q.lower()]
    assert len(sobre_preguntas) == 1 and "count" in sobre_preguntas[0].lower()


# ======================================================================= B. afiliado e IA
def test_una_retirada_no_aparece_en_ningun_lado():
    c = _c()
    ret = db.listar_preguntas(CONV, estado="retirada")[0]
    clave, texto = ret["id"], ret["pregunta"]
    # Aunque tenga contenido completo y artículos.
    assert c.post(f"{CURADO}/{clave}", json={"en_corto": "Texto único de la retirada QA."}).status_code == 200
    assert db.obtener_pregunta(clave)["estado"] == "retirada"
    c.get(API + "/frecuentes")
    assert clave not in c.get(API + "/frecuentes").text and "Texto único de la retirada QA." not in c.get(API + "/frecuentes").text
    assert clave not in c.get(API + "/frecuentes/curado").text
    for bloque in (consulta_convenio_ia.texto_frecuentes(CONV), consulta_convenio_ia._corpus(CONV),
                   json.dumps(consulta_convenio_ia.armar_sistema(CONV))):
        assert "Texto único de la retirada QA." not in bloque and f"[Frecuente {clave}]" not in bloque
    assert not convenio_faq.existe(clave)
    # La IA que cita su id: se descarta, no llega a `referencias` ni al resultado.
    v = consulta_convenio_ia.validar({"responde": True, "respuesta": "El convenio lo trata en el artículo 48.",
                                      "articulos": [48], "frecuentes": [clave, "vac-dias"]})
    assert v["frecuentes"] == ["vac-dias"]
    assert consulta_convenio_ia.referencias([48], [clave, "vac-dias"])[1] == [
        {"id": "vac-dias", "pregunta": convenio_faq.pregunta("vac-dias")["pregunta"]}]
    # Y si SOLO cita la retirada, la respuesta es la fija.
    solo = consulta_convenio_ia.validar({"responde": True, "respuesta": "Es así.", "articulos": [], "frecuentes": [clave]})
    assert solo["resultado"] != "respondida" and texto not in solo["respuesta"]


def test_preguntar_no_devuelve_referencias_a_una_retirada():
    c = _c()
    q = convenio_faq.pregunta("vac-dias")
    assert c.post(f"{CURADO}/vac-dias/estado", json={"estado": "retirada", "motivo": "x"}).status_code == 200
    r = c.post(API + "/preguntar", json={"pregunta": q["pregunta"]})
    assert r.status_code == 200
    assert "vac-dias" not in json.dumps(r.json()["frecuentes"])


def test_lo_interno_no_viaja_al_afiliado_ni_al_prompt():
    c = _c()
    r = c.post(f"{CURADO}/vac-dias", json={
        "nota_curador": "NOTA-SECRETA-QA", "inspirada_en": ["INSPIRADA-SECRETA-QA"]})
    assert r.status_code == 200
    assert c.post(f"{CURADO}/vac-dias/estado", json={"estado": "retirada", "motivo": "MOTIVO-SECRETO-QA",
                                                     "detalle": "DETALLE-SECRETO-QA"}).status_code == 200
    assert c.post(f"{CURADO}/vac-dias/estado", json={"estado": "revisada"}).status_code == 200
    c.get(API + "/frecuentes")
    pub = c.get(API + "/frecuentes").text
    sistema = json.dumps(consulta_convenio_ia.armar_sistema(CONV)) + consulta_convenio_ia._corpus(CONV)
    refs = json.dumps(consulta_convenio_ia.referencias([48], ["vac-dias"]))
    interno = db.obtener_pregunta("vac-dias")
    for secreto in ("NOTA-SECRETA-QA", "INSPIRADA-SECRETA-QA", "MOTIVO-SECRETO-QA", "DETALLE-SECRETO-QA", interno["modificada_por"] + '"',
                    "modificada_por", "revisada_por", "motivo_retiro", "nota_curador", "inspirada_en", '"version"'):
        assert secreto not in pub, secreto
    assert "NOTA-SECRETA-QA" not in sistema and "INSPIRADA-SECRETA-QA" not in sistema
    assert "NOTA-SECRETA-QA" not in refs and "snavello" not in refs
    # El equipo SÍ las ve.
    assert "NOTA-SECRETA-QA" in c.get(API + "/frecuentes/curado").text


def test_el_prompt_no_se_pasa_de_largo_aunque_se_creen_preguntas_enormes():
    """Con los topes de cada campo una pregunta pesa hasta ~14.000 caracteres; 200 de ellas no entran en el
    contexto del modelo. Hay un tope del conjunto y se avisa en lugar de romper TODA consulta."""
    c = _c()
    parrafo = "El convenio fija esta regla de trabajo para todo el personal. "
    grande = (parrafo * 100)[:4000]
    base_largo = len(consulta_convenio_ia.texto_frecuentes(CONV))
    rechazada = None
    for i in range(1, 80):
        r = c.post(CURADO, json={"id": f"gran-{i}", "tema": "vacaciones", "pregunta": f"¿Pregunta enorme {i}?",
                                 "en_corto": (parrafo * 30)[:1500], "respuesta": grande, "articulos": [48],
                                 "segun_ley": grande, "normas": [{"norma": "LCT", "articulo": "1"}], "por_banco": grande})
        if r.status_code != 200:
            rechazada = r
            break
    assert rechazada is not None, "nunca se rechazó: el prompt puede crecer sin límite"
    assert rechazada.status_code == 400 and "demasiado texto" in rechazada.json()["detail"]
    c.get(API + "/frecuentes")
    largo = len(consulta_convenio_ia.texto_frecuentes(CONV))
    assert largo <= convenio_faq.TOPE_PROMPT_CARACTERES + 5000
    total = sum(len(b["text"]) for b in consulta_convenio_ia.armar_sistema(CONV))
    assert total / 3 < 100_000        # 3 caracteres por token, pesimista, f"el prompt llegaría a ~{total // 3} tokens"
    assert largo > base_largo


def test_achicar_siempre_se_puede_aunque_el_conjunto_este_lleno(monkeypatch):
    c = _c()
    monkeypatch.setattr(convenio_faq, "TOPE_PROMPT_CARACTERES", 1000)     # todo lo existente ya está «pasado»
    r = c.post(f"{CURADO}/vac-dias", json={"en_corto": "Más corto."})
    assert r.status_code in (200, 400)
    assert c.post(CURADO, json=NUEVA).status_code == 400                   # agrandar no
    corto = {"en_corto": "x" * 5}
    antes = convenio_faq.peso_prompt(db.obtener_pregunta("vac-dias"))
    assert c.post(f"{CURADO}/vac-dias", json={**corto, "respuesta": "El art. 48.", "segun_ley": "", "por_banco": ""}).status_code == 200
    assert convenio_faq.peso_prompt(db.obtener_pregunta("vac-dias")) < antes


def test_retirar_siempre_se_puede_y_reponer_respeta_el_tope(monkeypatch):
    c = _c()
    monkeypatch.setattr(convenio_faq, "TOPE_PROMPT_CARACTERES", 1000)
    assert c.post(f"{CURADO}/vac-dias/estado", json={"estado": "retirada", "motivo": "x"}).status_code == 200
    assert c.post(f"{CURADO}/vac-dias/estado", json={"estado": "sin_revisar"}).status_code == 400


def test_tope_de_cantidad_de_preguntas(monkeypatch):
    c = _c()
    monkeypatch.setattr(convenio_faq, "TOPE_PREGUNTAS", 151)
    r = c.post(CURADO, json=NUEVA)
    assert r.status_code == 400 and "máximo" in r.json()["detail"]


@pytest.mark.parametrize("ch", ["\u00ad", "\u2066", "\u2069", "\ue000", "\ufffe", "\u180e", "\u061c", "\U000e0001", "\u2028"])
def test_caracteres_invisibles_no_entran_y_el_mensaje_dice_donde(ch):
    r = _c().post(CURADO, json={**NUEVA, "respuesta": "El texto con" + ch + "algo escondido"})
    assert r.status_code == 400, hex(ord(ch))
    msg = r.json()["errores"][0]["mensaje"]
    assert f"U+{ord(ch):04X}" in msg and "después de" in msg
    assert db.obtener_pregunta("qa-uno") is None


def test_lo_que_la_ia_siempre_rechaza_no_se_acepta_en_los_textos_visibles():
    """Enlaces, correos y marcas de formato: si el curado los acepta, la IA los rechaza siempre que los repita."""
    c = _c()
    for i, t in enumerate(("Entrá a https://sitio.com para verlo.", "Escribí a alguien@sindicato.org.ar", "Visitá www.sindicato.com.ar",
                           "Esto va en **negrita**", "Mirá [el artículo 5]", "Eso es {importante}", "Va así | y así", "Es <b>fuerte</b>")):
        for campo in ("en_corto", "respuesta", "segun_ley", "por_banco", "pregunta"):
            extra = {"normas": [{"norma": "LCT"}]} if campo == "segun_ley" else {}
            r = c.post(CURADO, json={**NUEVA, "id": f"txt-{i}-{campo}".replace("_", "-"), campo: t, **extra})
            assert r.status_code == 400, (campo, t)
            assert r.json()["errores"][0]["campo"] == campo
    assert [f for f in db.listar_preguntas(CONV) if f["id"].startswith("txt-")] == []


def test_texto_normal_con_numeros_de_ley_y_articulos_sigue_entrando():
    c = _c()
    r = c.post(CURADO, json={**NUEVA, "en_corto": "Rige la Ley 20.744 (art. 150) y el Decreto 2.289/76; son 14 días corridos.",
                             "respuesta": "El art. 48 dice que son 14 días hábiles; ver también el inciso b) del art. 12.",
                             "segun_ley": "Según la Ley 24.241, art. 9.", "normas": [{"norma": "Ley 24.241", "articulo": "9"}]})
    assert r.status_code == 200, r.text


@pytest.mark.xfail(reason="D41/QA: el curado acepta cifras que la IA trata como importes (12,50 %; 10.000 afiliados; "
                          "números de 5 cifras) y por eso NUNCA puede repetirlas: sale la respuesta fija. Falla cerrado "
                          "(seguro), pero la persona que cura no se entera. Gravedad baja; sin arreglo chico y claro, porque "
                          "validar de la IA tiene falsos positivos propios (12,50 % no es plata).", strict=False)
@pytest.mark.parametrize("texto", ["Son el 12,50 % del sueldo.", "Aplica a 10.000 afiliados.", "Son 12345 casos."])
def test_xfail_el_curado_y_la_ia_coinciden_en_que_es_un_importe(texto):
    curado_acepta = not convenio_faq.hay_importe(texto)
    ia_rechaza = bool(consulta_convenio_ia._DINERO.search(texto)) or bool(consulta_convenio_ia._DINERO_PALABRAS.search(texto))
    assert not (curado_acepta and ia_rechaza)


# ======================================================================= C. seguridad de las rutas
def _todas_las_rutas_del_curado():
    rutas = []
    for r in main.app.routes:
        p = getattr(r, "path", "")
        if p.startswith(API) and any(k in p for k in ("curado", "frecuentes", "preguntar")):
            for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
                rutas.append((m, p))
    return rutas


def _llenar(path):
    return path.replace("{clave}", "vac-dias")


def test_hay_rutas_y_ninguna_se_olvida_en_la_puerta():
    rutas = _todas_las_rutas_del_curado()
    assert len(rutas) >= 10
    anon = TestClient(main.app)
    for m, p in rutas:
        r = anon.request(m, _llenar(p), json={} if m == "POST" else None)
        assert r.status_code == 403, (m, p, r.status_code)


def test_con_pase_pasan_todas_y_en_demo_todas_son_404(monkeypatch):
    c = _c()
    for m, p in _todas_las_rutas_del_curado():
        r = c.request(m, _llenar(p), json={} if m == "POST" else None)
        assert r.status_code != 403 and r.status_code < 500, (m, p, r.status_code)
    monkeypatch.setattr(entorno, "MUESTRA_DISTINTIVO", False)
    for m, p in _todas_las_rutas_del_curado():
        r = c.request(m, _llenar(p), json={} if m == "POST" else None)
        assert r.status_code == 404, (m, p, r.status_code)
    assert c.get("/entornos/herramientas/convenio-escalas/preguntas").status_code == 404
    db_antes = db.obtener_pregunta("vac-dias")
    assert db_antes and db_antes["estado"] == "sin_revisar"


def test_con_el_pin_tambien_pasa_y_queda_registrado_quien():
    c = TestClient(main.app)
    assert c.post("/entornos/pin", data={"pin": "13572468"}, follow_redirects=False).status_code == 303
    assert c.post(f"{CURADO}/vac-dias", json={"en_corto": "Por el pin."}).status_code == 200
    assert db.historial_pregunta("vac-dias")[0]["quien"] == "pase"


CLAVES_RARAS = ["../etc/passwd", "..%2f..%2fx", "%00", "a" * 500, "VAC-DIAS", "vac_dias", "vac dias", "vac-dias;drop", "ñandú",
                "<script>alert(1)</script>", "reordenar", "estado", "nueva", "' OR 1=1 --", "-", "a--b", "%", "\\"]


@pytest.mark.parametrize("clave", CLAVES_RARAS)
def test_claves_raras_en_la_ruta_dan_404_nunca_500(clave):
    c = _c()
    for m, suf in (("get", ""), ("post", ""), ("post", "/estado")):
        r = getattr(c, m)(f"{CURADO}/{clave}{suf}", **({"json": {"estado": "revisada"}} if m == "post" else {}))
        assert r.status_code in (400, 404, 405, 422), (clave, m, suf, r.status_code)


@pytest.mark.parametrize("clave", ["Mayuscula", "con espacio", "ñandú", "a" * 61, "-uno", "uno-", "uno--dos", "../x", "", " ", "reordenar", "nueva", "estado", "articulos", "a\u0000b", "<b>x</b>"])
def test_ids_invalidos_al_crear(clave):
    r = _c().post(CURADO, json={**NUEVA, "id": clave})
    assert r.status_code == 400 and r.json()["errores"][0]["campo"] == "id"


def test_filtros_de_busqueda_hostiles_no_rompen():
    c = _c()
    for q in ("'; DROP TABLE preguntafrecuente; --", "%", "_", "\\", "\u0000", "<script>", "a" * 200, "ñ", "' OR '1'='1"):
        r = c.get(CURADO, params={"q": q})
        assert r.status_code in (200, 400), (q, r.status_code)
    assert c.get(CURADO, params={"q": "a" * 201}).status_code == 422
    assert c.get(CURADO, params={"estado": "x"}).status_code == 400
    assert c.get(CURADO, params={"tema": "no-existe"}).json()["preguntas"] == []
    assert len(db.listar_preguntas(CONV)) == 151


CUERPOS = [None, [], "texto", 5, True, {}, {"a": [[[[[[[[[[1]]]]]]]]]]}, {"articulos": [[]]}, {"normas": {"a": 1}}, {"fuentes_banco": "x"},
           {"inspirada_en": [{"x": 1}]}, {"orden": "1"}, {"estado": ["revisada"]}, {"tema": None}, {"id": None}]


def test_cuerpos_de_todo_tipo_en_cada_ruta_no_dan_500():
    c = _c()
    for cuerpo in CUERPOS:
        for url in (CURADO, f"{CURADO}/vac-dias", f"{CURADO}/vac-dias/estado", CURADO + "/reordenar"):
            r = c.post(url, content=json.dumps(cuerpo).encode(), headers={"content-type": "application/json"})
            assert r.status_code < 500, (url, cuerpo, r.status_code)
    for crudo in (b"", b"null", b"\xff\xfe", b"{", b'{"a":' * 3000 + b"1" + b"}" * 3000, b"[" * 100_000 + b"]" * 100_000):
        for url in (CURADO, f"{CURADO}/vac-dias", f"{CURADO}/vac-dias/estado", CURADO + "/reordenar"):
            r = c.post(url, content=crudo, headers={"content-type": "application/json"})
            assert r.status_code < 500, (url, crudo[:20], r.status_code)
    r = c.post(CURADO, content=b"a=b", headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code < 500
    assert db.obtener_pregunta("vac-dias")["en_corto"]


def test_un_cuerpo_de_varios_megas_se_rechaza_sin_guardar_nada():
    c = _c()
    enorme = json.dumps({**NUEVA, "respuesta": "a" * 8_000_000, "inspirada_en": ["x"] * 1_000_000}).encode()
    r = c.post(CURADO, content=enorme, headers={"content-type": "application/json"})
    assert r.status_code == 400
    assert db.obtener_pregunta("qa-uno") is None


URLS_ENGANOSAS = ["https://bien.gob.ar@malo.com/x", "https://user:clave@sitio.gob.ar/", "https://sitio.gob.ar\\@malo.com", "https://localhost/x",
                  "https://127.0.0.1/", "https://10.0.0.5/admin", "https://[::1]/", "https://", "https://a", "https://sitio", "https://exámple.com/",
                  "https://sitio.gob.ar:99999/", "https://sitio.gob.ar:abc/", "https://sitio.gob.ar/<script>", "https://sitio.gob.ar/\"onclick=x",
                  "https://sitio.gob.ar/`x", "https://-malo.com/", "https://malo..com/", "https://sitio.internal/", "https://intranet.local/",
                  "HTTPS://user@malo.com", "https://0x7f.0.0.1/", "https://2130706433/", "https://.com/", "https://sitio.123/"]


@pytest.mark.parametrize("url", URLS_ENGANOSAS)
def test_enlaces_engañosos_no_se_guardan(url):
    c = _c()
    r = c.post(CURADO, json={**NUEVA, "segun_ley": "Rige la ley.", "normas": [{"norma": "LCT", "articulo": "1", "url": url}]})
    assert r.status_code == 400, url
    r = c.post(CURADO, json={**NUEVA, "por_banco": "Acuerdo con un banco.", "fuentes_banco": [{"texto": "Nota", "url": url}]})
    assert r.status_code == 400, url
    assert db.obtener_pregunta("qa-uno") is None


@pytest.mark.parametrize("url", ["https://www.argentina.gob.ar/normativa/nacional/ley-20744", "https://servicios.infoleg.gob.ar/x?id=1#a",
                                 "https://labancaria.org/nota/2026", "https://sitio.gob.ar:8443/ruta", "https://xn--exmple-cua.com/", "HTTPS://WWW.SITIO.COM.AR/X"])
def test_enlaces_normales_si_se_guardan(url):
    r = _c().post(CURADO, json={**NUEVA, "segun_ley": "Rige la ley.", "normas": [{"norma": "LCT", "articulo": "1", "url": url}]})
    assert r.status_code == 200, (url, r.text)


def test_todos_los_enlaces_de_la_semilla_pasan_la_regla_de_hosts():
    for f in db.listar_preguntas(CONV):
        for n in f["normas"]:
            assert not n["url"] or convenio_faq.host_publico(n["url"]), (f["id"], n["url"])
        for n in f["fuentes_banco"]:
            assert not n["url"] or convenio_faq.host_publico(n["url"]), (f["id"], n["url"])


def test_xss_guardado_se_rechaza_en_lo_visible_y_en_lo_interno_viaja_como_json():
    """Un <script> en lo que ve el afiliado no entra. En lo interno (nota, motivo) puede entrar, pero solo
    sale como JSON (nunca HTML) y las pantallas lo dibujan con textContent (lo prueba el robot de pantalla)."""
    c = _c()
    xss = "<img src=x onerror=alert(1)><script>alert(2)</script>"
    for campo in ("pregunta", "en_corto", "respuesta", "segun_ley", "por_banco"):
        extra = {"normas": [{"norma": "LCT"}]} if campo == "segun_ley" else {}
        assert c.post(CURADO, json={**NUEVA, "id": "xss-" + campo.replace("_", "-"), campo: xss, **extra}).status_code == 400, campo
    r = c.post(CURADO, json={**NUEVA, "nota_curador": xss, "inspirada_en": [xss], "normas": [{"norma": xss, "articulo": xss}]})
    assert r.status_code == 200
    g = c.get(f"{CURADO}/qa-uno")
    assert g.headers["content-type"].startswith("application/json") and g.json()["pregunta"]["nota_curador"] == xss
    assert "nosniff" in {k.lower(): v for k, v in g.headers.items()}.get("x-content-type-options", "").lower()
    assert c.post(f"{CURADO}/qa-uno/estado", json={"estado": "retirada", "motivo": xss, "detalle": xss}).status_code == 200
    pagina = c.get("/entornos/herramientas/convenio-escalas/preguntas").text
    assert "onerror" not in pagina and "<script>alert" not in pagina      # los datos no viajan dentro del HTML


def test_el_afiliado_no_recibe_enlaces_que_no_sean_https():
    """Aunque alguien deje pasar algo raro por la base, lo que sale de la API publica solo trae https o vacío."""
    with Session(db.engine) as s:
        f = s.exec(select(db.PreguntaFrecuente).where(db.PreguntaFrecuente.clave == "vac-dias")).one()
        f.normas = [{"norma": "LCT", "articulo": "1", "url": "javascript:alert(1)"}]
        f.segun_ley = "Rige la ley."
        f.fuentes_banco = [{"texto": "x", "url": "data:text/html,<script>1</script>"}]
        f.version += 1
        s.add(f)
        s.commit()
    c = _c()
    j = c.get(API + "/frecuentes").json()
    q = next(q for t in j["temas"] for q in t["preguntas"] if q["id"] == "vac-dias")
    assert q["normas"][0]["url"] == "" and q["fuentes_banco"][0]["url"] == ""


# ======================================================================= migración y datos
def test_la_migracion_es_idempotente_si_las_tablas_ya_existen():
    """El upgrade() de la migración no falla ni duplica si las tablas ya estaban (las armó create_all)."""
    import importlib.util
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    ruta = os.path.join(os.path.dirname(__file__), "migrations", "versions")
    archivo = next(f for f in os.listdir(ruta) if f.startswith("d8f2b4a6c0e1"))
    spec = importlib.util.spec_from_file_location("mig_d8f2", os.path.join(ruta, archivo))
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    with db.engine.connect() as con:
        with Operations.context(MigrationContext.configure(con)):
            mig.upgrade()
            mig.upgrade()
        con.rollback()
    assert len(db.listar_preguntas(CONV)) == 151


# ======================================================================= pantalla (lo que el robot de Playwright encontró)
def test_la_pantalla_muestra_los_avisos_adentro_del_editor_y_manda_la_version():
    """En el teléfono el editor tapa toda la página y en la compu el aviso de arriba queda fuera de vista al
    apretar «Guardar» al pie: los avisos (guardado, conflicto, «Ir a la siguiente») van dentro del editor."""
    html = _c().get("/entornos/herramientas/convenio-escalas/preguntas").text
    assert 'id="editor-aviso"' in html and html.index('id="editor-aviso"') < html.index('id="acciones"')
    js = open("static/escalas_preguntas.js", encoding="utf-8").read()
    assert "editor-aviso" in js and "est.ed ? adentro : arriba" in js
    assert "cuerpo.version = ed.orig.version" in js and "'conflicto'" in js and "Traer la última versión" in js
    assert "innerHTML" not in js
