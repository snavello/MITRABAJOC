"""El servicio de geocodificación (geo.py), SIN salir a la red.

Todo pedido de geo.py pasa por `geo._pedir_json`, y estos tests lo
reemplazan por respuestas simuladas copiadas de las de verdad (Georef y
Nominatim, consultadas el 2026-09-12 para armarlas). Así se prueba lo que
importa -- qué precisión sale de cada respuesta, qué pasa cuando una API no
contesta, que la caché ahorre el pedido -- sin gastar el presupuesto de 1
pedido por segundo de Nominatim ni depender de que dos servicios ajenos
estén arriba para que la suite pase.

Correr con: .venv/bin/python -m pytest test_geo_servicio.py -q
"""
import db
import geo


# ------------------------------------------------------ respuestas simuladas

# Copiadas de las respuestas reales, recortadas a los campos que geo.py lee.
PROV_SANTA_FE = {"provincias": [{"id": "82", "nombre": "Santa Fe",
                                 "centroide": {"lat": -30.7088, "lon": -60.9506}}]}
LOC_ROSARIO = {"localidades": [{"id": "82084270", "nombre": "Rosario",
                                "centroide": {"lat": -32.9472, "lon": -60.6331},
                                "provincia": {"id": "82", "nombre": "Santa Fe"}}]}
# place_rank 30 + addresstype house = la puerta. Esto es `exacta`.
NOMINATIM_PUERTA = [{
    "lat": "-32.9473381", "lon": "-60.6368931", "place_rank": 30,
    "addresstype": "house", "type": "house",
    "display_name": "850, Peatonal San Martín, Rosario, Santa Fe, 2000, Argentina",
    "address": {"postcode": "2000", "city": "Rosario"},
}]
# Una calle entera, sin altura: place_rank 26. Esto NO puede ser `exacta`.
NOMINATIM_CALLE = [{
    "lat": "-32.9500000", "lon": "-60.6400000", "place_rank": 26,
    "addresstype": "road", "type": "residential",
    "display_name": "San Martín, Rosario, Santa Fe, Argentina",
    "address": {"city": "Rosario"},
}]


class RedSimulada:
    """Reemplaza geo._pedir_json y anota cada URL pedida.

    Anotar las URLs es la única forma de verificar que la caché AHORRA el
    pedido: si solo se mirara el resultado, una caché que no cachea nada
    devolvería lo mismo y el test pasaría igual."""

    def __init__(self, provincias=PROV_SANTA_FE, localidades=LOC_ROSARIO,
                 nominatim=NOMINATIM_PUERTA):
        self.provincias, self.localidades, self.nominatim = provincias, localidades, nominatim
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        if "/provincias" in url:
            return self.provincias
        if "/localidades" in url:
            return self.localidades
        if "nominatim" in url:
            return self.nominatim
        return None

    @property
    def pedidos_a_nominatim(self):
        return [u for u in self.urls if "nominatim" in u]


def _con_red(monkeypatch, red):
    monkeypatch.setattr(geo, "_pedir_json", red)
    # El candado de 1/s dormiría de verdad entre pedidos simulados y haría
    # que la suite tarde un segundo por test sin ganar nada: lo que se
    # verifica de la tasa es que exista, no que time.sleep funcione.
    monkeypatch.setattr(geo, "_esperar_turno", lambda: None)
    return red


# ------------------------------------------------------------------- puro

def test_armar_direccion_texto_completa():
    texto = geo.armar_direccion_texto({
        "calle": "San Martín", "numero": "850", "piso_depto": "3 B",
        "localidad": "Rosario", "provincia": "Santa Fe", "codigo_postal": "2000"})
    assert texto == "San Martín 850, 3 B, Rosario, Santa Fe (CP 2000)"
    print("OK  test_armar_direccion_texto_completa")


def test_armar_direccion_texto_tolera_huecos():
    # Solo localidad y provincia: información útil, no una cadena con comas
    # sueltas ("", ", , Rosario") que es lo que sale de un join ingenuo.
    assert geo.armar_direccion_texto(
        {"localidad": "Rosario", "provincia": "Santa Fe"}) == "Rosario, Santa Fe"
    assert geo.armar_direccion_texto({"calle": "San Martín"}) == "San Martín"
    assert geo.armar_direccion_texto({}) == ""
    assert geo.armar_direccion_texto({"calle": "  ", "numero": " "}) == ""
    print("OK  test_armar_direccion_texto_tolera_huecos")


def test_clave_cache_normaliza():
    # Si la clave no normalizara, la caché no ahorraría nada: nadie escribe
    # dos veces la misma dirección igual.
    a = geo.clave_cache("Santa Fe", "Rosario", "San Martín", "850")
    b = geo.clave_cache("santa  fe", "ROSARIO", "san martin", " 850 ")
    assert a == b == "santa fe|rosario|san martin|850"
    print("OK  test_clave_cache_normaliza")


def test_coordenadas_validas_rechaza_lo_que_se_cuela():
    assert geo.coordenadas_validas(-32.94, -60.63)
    assert geo.coordenadas_validas("-32.94", "-60.63")      # llegan como texto del navegador
    assert not geo.coordenadas_validas(0, 0)                # Golfo de Guinea: JS que falló
    assert not geo.coordenadas_validas(None, None)
    assert not geo.coordenadas_validas("", "")
    assert not geo.coordenadas_validas(91, 0)
    assert not geo.coordenadas_validas(-32.94, 181)
    assert not geo.coordenadas_validas("ahí nomás", "-60.63")
    print("OK  test_coordenadas_validas_rechaza_lo_que_se_cuela")


def test_distancia_km():
    # CABA -> Rosario en línea recta son ~275 km.
    d = geo.distancia_km(-34.6144, -58.4458, -32.9472, -60.6331)
    assert 270 < d < 280, d
    assert geo.distancia_km(-34.6, -58.4, -34.6, -58.4) == 0.0
    assert geo.distancia_km(None, None, -32.9, -60.6) is None
    print("OK  test_distancia_km")


def test_normalizar_precision_es_fail_closed():
    for valor in geo.PRECISIONES:
        assert geo.normalizar_precision(valor) == valor
    # Un POST armado a mano no puede meter una precisión inventada.
    assert geo.normalizar_precision("exactísima") == "sin_geo"
    assert geo.normalizar_precision("") == "sin_geo"
    assert geo.normalizar_precision(None) == "sin_geo"
    print("OK  test_normalizar_precision_es_fail_closed")


def test_vencido():
    import fechas
    from datetime import timedelta
    ahora = fechas.ahora()
    fresco = ahora.strftime("%Y-%m-%d %H:%M")
    viejo = (ahora - timedelta(days=geo.TTL_CACHE_DIAS + 1)).strftime("%Y-%m-%d %H:%M")
    assert not geo.vencido(fresco, ahora)
    assert geo.vencido(viejo, ahora)
    # Un sello ilegible se toma como vencido: volver a preguntar es barato,
    # servir algo de fecha desconocida no.
    assert geo.vencido("", ahora)
    assert geo.vencido("el martes", ahora)
    print("OK  test_vencido")


# ------------------------------------------------ candidatos y precisiones

def test_candidato_exacto(monkeypatch):
    _con_red(monkeypatch, RedSimulada())
    r = geo.normalizar_direccion("Santa Fe", "Rosario", "San Martín", "850",
                                 usar_cache=False)
    assert r["aviso"] == ""
    assert len(r["candidatos"]) == 1
    c = r["candidatos"][0]
    assert c["precision"] == "exacta"
    assert (round(c["lat"], 4), round(c["lon"], 4)) == (-32.9473, -60.6369)
    # El CP lo trae Nominatim: el formulario lo completa gratis.
    assert c["codigo_postal"] == "2000"
    assert c["direccion_texto"] == "San Martín 850, Rosario, Santa Fe (CP 2000)"
    # Georef devuelve el nombre oficial, que es el que se guarda.
    assert r["provincia"] == "Santa Fe" and r["localidad"] == "Rosario"
    print("OK  test_candidato_exacto")


def test_calle_sin_altura_no_es_exacta(monkeypatch):
    # Una calle de veinte cuadras ubicada en su punto medio no es la puerta
    # de la seccional. Si esto dijera "exacta", nadie arrastraría el globo.
    _con_red(monkeypatch, RedSimulada(nominatim=NOMINATIM_CALLE))
    r = geo.normalizar_direccion("Santa Fe", "Rosario", "San Martín", "850",
                                 usar_cache=False)
    assert r["candidatos"][0]["precision"] == "aproximada"
    print("OK  test_calle_sin_altura_no_es_exacta")


def test_fallback_al_centroide_de_la_localidad(monkeypatch):
    # Nominatim no encontró nada. Tener la ciudad es mejor que no tener
    # nada: el mapa abre en el lugar correcto y arrastrar es un gesto.
    _con_red(monkeypatch, RedSimulada(nominatim=[]))
    r = geo.normalizar_direccion("Santa Fe", "Rosario", "Calle Inexistente", "9999",
                                 usar_cache=False)
    assert len(r["candidatos"]) == 1
    c = r["candidatos"][0]
    assert c["precision"] == "aproximada"
    assert (round(c["lat"], 4), round(c["lon"], 4)) == (-32.9472, -60.6331)
    assert "arrastralo" in r["aviso"]
    print("OK  test_fallback_al_centroide_de_la_localidad")


def test_sin_calle_devuelve_el_centroide(monkeypatch):
    # Cargar solo provincia y localidad es un caso legítimo: la seccional
    # queda `aproximada` y alguien la ajusta después.
    red = _con_red(monkeypatch, RedSimulada())
    r = geo.normalizar_direccion("Santa Fe", "Rosario", "", "", usar_cache=False)
    assert r["candidatos"][0]["precision"] == "aproximada"
    # Sin calle no hay nada que preguntarle a Nominatim: no se lo molesta.
    assert red.pedidos_a_nominatim == []
    print("OK  test_sin_calle_devuelve_el_centroide")


# ---------------------------------------------------- fallos que no bloquean

def test_georef_caido_no_revienta(monkeypatch):
    # Las dos APIs devuelven None (caídas). El alta TIENE que poder seguir.
    _con_red(monkeypatch, lambda url: None)
    r = geo.normalizar_direccion("Santa Fe", "Rosario", "San Martín", "850",
                                 usar_cache=False)
    assert r["candidatos"] == []
    assert "guardar igual" in r["aviso"]
    print("OK  test_georef_caido_no_revienta")


def test_provincia_inexistente_avisa(monkeypatch):
    _con_red(monkeypatch, RedSimulada(provincias={"provincias": []}))
    r = geo.normalizar_direccion("Santa Fé del Norte", "Rosario", "San Martín", "850",
                                 usar_cache=False)
    assert r["candidatos"] == []
    assert r["aviso"]
    print("OK  test_provincia_inexistente_avisa")


def test_localidad_que_georef_no_conoce_no_corta(monkeypatch):
    """El caso CABA, que apareció probando contra las APIs de verdad.

    En Ciudad Autónoma de Buenos Aires las "localidades" de Georef son los 49
    BARRIOS (Constitución, Retiro, Recoleta...), así que nadie que escriba
    una dirección porteña va a tipear una localidad que resuelva. Y sin
    embargo Nominatim encuentra "Av. Independencia 1200" sin problema. La
    primera versión cortaba con un error y dejaba toda la Capital imposible
    de georreferenciar.
    """
    red = _con_red(monkeypatch, RedSimulada(localidades={"localidades": []}))
    r = geo.normalizar_direccion("Ciudad Autónoma de Buenos Aires",
                                 "Ciudad Autónoma de Buenos Aires",
                                 "Av. Independencia", "1200", usar_cache=False)
    assert r["candidatos"], "sin localidad canónica igual tiene que buscar la calle"
    assert r["candidatos"][0]["precision"] == "exacta"
    assert red.pedidos_a_nominatim, "se le tiene que preguntar a Nominatim igual"
    # Se conserva lo que la persona escribió como localidad.
    assert r["localidad"] == "Ciudad Autónoma de Buenos Aires"
    print("OK  test_localidad_que_georef_no_conoce_no_corta")


def test_abreviaturas_se_expanden_para_consultar(monkeypatch):
    """"Bv. San Juan" en Córdoba devuelve CERO en Nominatim; "Boulevard San
    Juan" la encuentra. Medido contra la API real el 2026-09-12."""
    assert geo.expandir_abreviaturas("Bv. San Juan") == "Boulevard San Juan"
    assert geo.expandir_abreviaturas("Av Gral. Paz") == "Avenida General Paz"
    assert geo.expandir_abreviaturas("Pje. Dr. Ramos") == "Pasaje Doctor Ramos"
    # Lo que no es abreviatura no se toca.
    assert geo.expandir_abreviaturas("San Martín") == "San Martín"

    red = _con_red(monkeypatch, RedSimulada())
    geo.normalizar_direccion("Santa Fe", "Rosario", "Bv. Oroño", "1500", usar_cache=False)
    pedido = red.pedidos_a_nominatim[0]
    assert "Boulevard" in pedido, pedido
    print("OK  test_abreviaturas_se_expanden_para_consultar")


def test_abreviatura_expandida_no_se_guarda(monkeypatch):
    """Se expande para CONSULTAR, no para guardar: si el cartel de la esquina
    dice "Bv. San Juan", la dirección de la seccional dice lo mismo."""
    _con_red(monkeypatch, RedSimulada())
    r = geo.normalizar_direccion("Santa Fe", "Rosario", "Bv. Oroño", "1500",
                                 usar_cache=False)
    assert "Bv. Oroño 1500" in r["candidatos"][0]["direccion_texto"]
    print("OK  test_abreviatura_expandida_no_se_guarda")


def test_homonimo_lejano_se_descarta(monkeypatch):
    """El hallazgo más caro de la prueba en vivo: `city` de Nominatim orienta
    pero NO acota. "San Juan 430, Córdoba" devuelve calles con ese nombre en
    Morrison y en Alicia, a 200 km de Córdoba capital, y llegan primero. Sin
    el corte por radio, el admin elige un globo en otra ciudad sin tener
    forma de darse cuenta.
    """
    lejano = dict(NOMINATIM_PUERTA[0])
    lejano.update({"lat": "-32.5894456", "lon": "-62.8328545",      # Morrison, a ~200 km
                   "display_name": "430, Boulevard San Juan, Morrison, Córdoba"})
    cerca = dict(NOMINATIM_PUERTA[0])
    cerca.update({"lat": "-32.9480000", "lon": "-60.6350000",       # en Rosario
                  "display_name": "430, San Juan, Rosario, Santa Fe"})
    # El lejano llega PRIMERO, como en la respuesta real.
    _con_red(monkeypatch, RedSimulada(nominatim=[lejano, cerca]))
    r = geo.normalizar_direccion("Santa Fe", "Rosario", "San Juan", "430",
                                 usar_cache=False)
    assert len(r["candidatos"]) == 1, "el homónimo lejano no tiene que estar"
    assert "Rosario" in r["candidatos"][0]["etiqueta"]
    print("OK  test_homonimo_lejano_se_descarta")


def test_candidatos_se_ordenan_por_cercania(monkeypatch):
    """Con varios dentro del radio, primero el más cerca del centro: es el
    que la persona buscaba nueve de cada diez veces."""
    borde = dict(NOMINATIM_PUERTA[0])
    borde.update({"lat": "-33.2000000", "lon": "-60.6300000",       # ~28 km del centro
                  "display_name": "850, San Martín, Villa Amelia, Santa Fe"})
    centro = dict(NOMINATIM_PUERTA[0])
    centro.update({"lat": "-32.9473381", "lon": "-60.6368931",      # en el centro
                   "display_name": "850, Peatonal San Martín, Rosario Centro"})
    _con_red(monkeypatch, RedSimulada(nominatim=[borde, centro]))
    r = geo.normalizar_direccion("Santa Fe", "Rosario", "San Martín", "850",
                                 usar_cache=False)
    assert len(r["candidatos"]) == 2
    assert "Rosario Centro" in r["candidatos"][0]["etiqueta"]
    # El km usado para ordenar es interno: no viaja al cliente ni se guarda.
    assert "_km" not in r["candidatos"][0]
    print("OK  test_candidatos_se_ordenan_por_cercania")


def test_nominatim_caido_cae_al_centroide(monkeypatch):
    # Georef anda, Nominatim no: se salva la localidad.
    def red(url):
        if "/provincias" in url:
            return PROV_SANTA_FE
        if "/localidades" in url:
            return LOC_ROSARIO
        return None
    _con_red(monkeypatch, red)
    r = geo.normalizar_direccion("Santa Fe", "Rosario", "San Martín", "850",
                                 usar_cache=False)
    assert len(r["candidatos"]) == 1
    assert r["candidatos"][0]["precision"] == "aproximada"
    print("OK  test_nominatim_caido_cae_al_centroide")


def test_respuesta_con_lat_basura_no_rompe(monkeypatch):
    # Una respuesta con forma válida pero contenido inservible. La API es de
    # un tercero: su salida no es un contrato (misma regla que la IA en
    # validador.a_numero).
    basura = [{"lat": "ahí", "lon": None, "place_rank": 30, "addresstype": "house",
               "display_name": "x", "address": {}}]
    _con_red(monkeypatch, RedSimulada(nominatim=basura))
    r = geo.normalizar_direccion("Santa Fe", "Rosario", "San Martín", "850",
                                 usar_cache=False)
    # Descarta el candidato ilegible y cae al centroide, sin excepción.
    assert r["candidatos"][0]["precision"] == "aproximada"
    print("OK  test_respuesta_con_lat_basura_no_rompe")


# ------------------------------------------------------------------ caché

def test_cache_ahorra_el_pedido(monkeypatch):
    red = _con_red(monkeypatch, RedSimulada())
    clave = geo.clave_cache("Santa Fe", "Rosario", "Cache Test", "100")
    db.geocache_guardar(clave, [])          # limpia una corrida anterior
    with db.get_session() as s:
        from sqlmodel import select
        fila = s.exec(select(db.GeoCache).where(
            db.GeoCache.consulta_normalizada == clave)).first()
        s.delete(fila); s.commit()

    primera = geo.normalizar_direccion("Santa Fe", "Rosario", "Cache Test", "100")
    assert primera["candidatos"] and not primera.get("de_cache")
    pedidos = len(red.urls)
    assert pedidos > 0

    segunda = geo.normalizar_direccion("Santa Fe", "Rosario", "Cache Test", "100")
    assert segunda.get("de_cache") is True
    assert segunda["candidatos"] == primera["candidatos"]
    # Lo que se verifica de verdad: NO volvió a salir a la red.
    assert len(red.urls) == pedidos
    print("OK  test_cache_ahorra_el_pedido")


def test_cache_vencida_se_vuelve_a_pedir(monkeypatch):
    red = _con_red(monkeypatch, RedSimulada())
    clave = geo.clave_cache("Santa Fe", "Rosario", "Vencida", "200")
    db.geocache_guardar(clave, [{"direccion_texto": "viejo", "lat": -32.0, "lon": -60.0,
                                 "precision": "exacta", "etiqueta": "", "localidad": "Rosario",
                                 "provincia": "Santa Fe", "codigo_postal": ""}])
    with db.get_session() as s:
        from sqlmodel import select
        fila = s.exec(select(db.GeoCache).where(
            db.GeoCache.consulta_normalizada == clave)).first()
        fila.creado = "2020-01-01 10:00"      # mucho más viejo que el TTL
        s.add(fila); s.commit()

    r = geo.normalizar_direccion("Santa Fe", "Rosario", "Vencida", "200")
    assert not r.get("de_cache")
    assert red.pedidos_a_nominatim, "una entrada vencida tiene que volver a preguntar"
    print("OK  test_cache_vencida_se_vuelve_a_pedir")


def test_cache_no_guarda_cuando_no_hubo_respuesta(monkeypatch):
    # Cachear un fallo sería peor que no cachear: 90 días diciendo "no se
    # pudo" cuando la API volvió a los dos minutos.
    _con_red(monkeypatch, lambda url: None)
    clave = geo.clave_cache("Santa Fe", "Rosario", "Nada", "300")
    geo.normalizar_direccion("Santa Fe", "Rosario", "Nada", "300")
    assert db.geocache_leer(clave) is None
    print("OK  test_cache_no_guarda_cuando_no_hubo_respuesta")


# ------------------------------------------------------------------ tope

def test_tope_por_actor():
    geo.reiniciar_topes()
    for i in range(geo.TOPE_POR_ACTOR):
        assert geo.permitir_a("20111111119"), f"el pedido {i + 1} tendría que pasar"
    assert not geo.permitir_a("20111111119"), "pasado el tope, no"
    # El tope es POR actor: otro afiliado no paga el consumo del primero.
    assert geo.permitir_a("27222222224")
    geo.reiniciar_topes()
    print("OK  test_tope_por_actor")


# ------------------------------------------------------- campos_para_guardar

def test_sin_coordenadas_no_hay_precision_que_valga():
    # Una fila que dice "exacta" con lat/lon en NULL es peor que una que
    # admite no estar ubicada.
    d = geo.campos_para_guardar({"calle": "San Martín", "numero": "850",
                                 "localidad": "Rosario", "provincia": "Santa Fe"},
                                precision="exacta", lat=None, lon=None)
    assert d["precision_geo"] == "sin_geo"
    assert d["latitud"] is None and d["longitud"] is None
    assert d["geo_actualizado"] == ""
    assert d["direccion_texto"] == "San Martín 850, Rosario, Santa Fe"
    print("OK  test_sin_coordenadas_no_hay_precision_que_valga")


def test_coordenadas_sin_precision_quedan_manual():
    d = geo.campos_para_guardar({"localidad": "Rosario", "provincia": "Santa Fe"},
                                precision="inventada", lat=-32.94, lon=-60.63)
    assert d["precision_geo"] == "manual"
    assert d["geo_actualizado"], "con coordenadas hay sello de tiempo"
    print("OK  test_coordenadas_sin_precision_quedan_manual")


def test_campos_para_guardar_recorta_y_limpia():
    d = geo.campos_para_guardar({"calle": "  x" * 300, "numero": " 850 ",
                                 "codigo_postal": "2000" * 20,
                                 "localidad": " Rosario ", "provincia": "Santa Fe"},
                                precision="manual", lat=-32.94, lon=-60.63)
    assert len(d["calle"]) <= 200 and len(d["codigo_postal"]) <= 12
    assert d["numero"] == "850" and d["localidad"] == "Rosario"
    assert len(d["direccion_texto"]) <= 400
    print("OK  test_campos_para_guardar_recorta_y_limpia")


def test_geo_actualizado_es_texto_de_buenos_aires():
    import re
    d = geo.campos_para_guardar({"localidad": "Rosario"}, "manual", -32.94, -60.63)
    # Texto "AAAA-MM-DD HH:MM", como TODOS los sellos del proyecto: un
    # datetime acá sería la única columna de tiempo con otro criterio.
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", d["geo_actualizado"])
    print("OK  test_geo_actualizado_es_texto_de_buenos_aires")
