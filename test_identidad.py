"""Verificación de identidad (identidad.py): el motor, sin red y sin base.

Correr con: python -m pytest test_identidad.py -q
"""
import cuit
import identidad as idn

CUIL = "20-20279041-1"      # DNI 20279041, módulo 11 válido
DECLARADO = {"cuil": CUIL, "dni": "20279041", "nombre": "Juan Pablo", "apellido": "Pérez",
             "nacimiento": "1990-01-15", "genero": "M"}
IMG = ("imagen.jpg", b"\xff\xd8\xff", "image/jpeg")


class Falso:
    """Cliente simulado: devuelve lo configurado y anota qué se llamó."""
    def __init__(self, **resp):
        self.resp, self.llamadas = resp, []

    def _r(self, nombre, defecto):
        self.llamadas.append(nombre)
        r = self.resp.get(nombre, defecto)
        if isinstance(r, Exception):
            raise r
        return dict(r)

    def documento(self, frente, dorso=None):
        return self._r("documento", {"estado": "Approved", "alertas": [], "leido": {
            "dni": "20279041", "nombre": "JUAN PABLO", "apellido": "PEREZ",
            "nacimiento": "1990-01-15", "vencimiento": "2099-01-01"}})

    def vida(self, selfie):
        return self._r("vida", {"estado": "Approved", "puntaje": 97, "alertas": []})

    def cara(self, selfie, retrato):
        return self._r("cara", {"estado": "Approved", "puntaje": 91, "alertas": []})

    def renaper(self, declarado, selfie):
        return self._r("renaper", {"estado": "Approved", "coincidencia": "full_match", "puntaje": 100,
                                   "campos": {}, "alertas": []})


# ------------------------------------------------------------------ normas
def test_dni_del_cuil_y_fechas_y_nombres():
    assert idn.dni_del_cuil(CUIL) == "20279041"
    assert idn.dni_del_cuil("123") == ""
    assert idn.fecha_iso("15/01/1990") == "1990-01-15" and idn.fecha_iso("1990-1-5") == "1990-01-05"
    assert idn.fecha_iso("ayer") == ""
    assert idn.fecha_iso("31/02/1990") == "" and idn.fecha_iso("1990-02-30") == ""   # el día no existe
    assert idn.fecha_iso("29/02/1992") == "1992-02-29"                                  # bisiesto
    assert idn.mismo_nombre("JUAN PABLO", "Juan") and idn.mismo_nombre("Pérez", "PEREZ")
    assert not idn.mismo_nombre("Juan", "Pedro") and not idn.mismo_nombre("", "Juan")


def test_chequeos_locales_buenos_y_malos():
    assert all(c["ok"] for c in idn.chequeos_locales(DECLARADO))
    malos = {c["clave"] for c in idn.chequeos_locales({**DECLARADO, "dni": "11111111"}) if not c["ok"]}
    assert malos == {"dni_es_del_cuil"}
    malos = {c["clave"] for c in idn.chequeos_locales({**DECLARADO, "genero": "F"}) if not c["ok"]}
    assert malos == {"genero_prefijo"}                       # 20 es de varón
    assert any(c["clave"] == "cuil_valido" and not c["ok"]
               for c in idn.chequeos_locales({**DECLARADO, "cuil": "20-20279041-9"}))
    # Un DNI de 7 dígitos va con cero adelante dentro del CUIL.
    base = "2009999999"
    cuil7 = base + str(cuit.digito_verificador(base))
    d7 = idn.chequeos_locales({**DECLARADO, "cuil": cuil7, "dni": "9999999"})
    assert next(c for c in d7 if c["clave"] == "dni_es_del_cuil")["ok"]


def test_fecha_de_nacimiento_imposible_o_futura_se_avisa_claro():
    malo = {c["clave"]: c for c in idn.chequeos_locales({**DECLARADO, "nacimiento": "31/02/1990"})}
    assert not malo["nacimiento_dato"]["ok"] and "calendario" in malo["nacimiento_dato"]["detalle"]
    futura = {c["clave"]: c for c in idn.chequeos_locales({**DECLARADO, "nacimiento": "2999-01-01"})}
    assert not futura["nacimiento_plausible"]["ok"]
    assert all(c["ok"] for c in idn.chequeos_locales(DECLARADO))


# --------------------------------------------------------------- el flujo
def test_todo_en_verde_es_aprobable_y_corre_los_cinco_pasos():
    f = Falso()
    r = idn.correr(DECLARADO, IMG, IMG, None, cliente=f)
    assert r["veredicto"]["resultado"] == idn.APROBABLE
    assert f.llamadas == ["documento", "vida", "cara", "renaper"]
    assert [p["clave"] for p in r["pasos"]] == ["local", "documento", "vida", "cara", "renaper"]
    assert idn.gasto_estimado(r["pasos"]) == 4


def test_un_chequeo_local_malo_corta_sin_gastar():
    f = Falso()
    r = idn.correr({**DECLARADO, "dni": "11111111"}, IMG, IMG, cliente=f)
    assert f.llamadas == [] and r["veredicto"]["resultado"] == idn.RECHAZAR
    assert idn.gasto_estimado(r["pasos"]) == 0


def test_documento_de_pantalla_rechaza_y_no_sigue():
    f = Falso(documento={"estado": "Declined", "alertas": ["SCREEN_CAPTURE_DETECTED"], "leido": {}})
    r = idn.correr(DECLARADO, IMG, IMG, cliente=f)
    assert f.llamadas == ["documento"]
    assert r["veredicto"]["resultado"] == idn.RECHAZAR
    assert idn.gasto_estimado(r["pasos"]) == 1


def test_el_documento_con_otro_nombre_pide_revision_pero_sigue():
    f = Falso(documento={"estado": "Approved", "alertas": [], "leido": {
        "dni": "20279041", "nombre": "PEDRO", "apellido": "GOMEZ", "nacimiento": "1990-01-15"}})
    r = idn.correr(DECLARADO, IMG, IMG, cliente=f)
    assert r["veredicto"]["resultado"] == idn.REVISAR
    assert "vida" in f.llamadas and "renaper" in f.llamadas


def test_vida_declinada_rechaza_y_renaper_no_se_paga():
    f = Falso(vida={"estado": "Declined", "puntaje": 12, "alertas": ["LIVENESS_FACE_ATTACK"]})
    r = idn.correr(DECLARADO, IMG, IMG, cliente=f)
    assert r["veredicto"]["resultado"] == idn.RECHAZAR
    assert "renaper" not in f.llamadas and "cara" not in f.llamadas


def test_renaper_no_match_rechaza_y_partial_pide_revision():
    r = idn.correr(DECLARADO, IMG, IMG, cliente=Falso(
        renaper={"estado": "Declined", "coincidencia": "no_match", "puntaje": 0, "campos": {}, "alertas": []}))
    assert r["veredicto"]["resultado"] == idn.RECHAZAR
    r = idn.correr(DECLARADO, IMG, IMG, cliente=Falso(
        renaper={"estado": "In Review", "coincidencia": "partial_match", "puntaje": 60, "campos": {}, "alertas": []}))
    assert r["veredicto"]["resultado"] == idn.REVISAR


def test_un_error_de_red_no_es_un_rechazo_de_la_persona():
    f = Falso(vida=idn.ErrorDidit(503, "saturado"))
    r = idn.correr(DECLARADO, IMG, IMG, cliente=f)
    assert r["veredicto"]["resultado"] == idn.REVISAR
    assert r["veredicto"]["estados"]["vida"] == "error"
    assert "renaper" in f.llamadas        # un error ajeno no frena los demás pasos


def test_pasos_pedidos_limita_lo_que_corre():
    f = Falso()
    r = idn.correr(DECLARADO, IMG, IMG, cliente=f, pasos_pedidos=["vida"])
    assert f.llamadas == ["vida"]
    assert r["veredicto"]["resultado"] == idn.REVISAR       # lo no corrido no se da por aprobado


def test_la_salida_no_lleva_datos_personales():
    r = idn.correr(DECLARADO, IMG, IMG, cliente=Falso())
    texto = repr(r)
    for secreto in ("20279041", "Pérez", "PEREZ", "Juan", "JUAN", "1990-01-15", "20-20279041-1", "20202790411"):
        assert secreto not in texto, secreto


# ------------------------------------------------------------ tope de gasto
def test_tope_de_intentos_por_persona_y_hora(monkeypatch):
    monkeypatch.setenv("IDENTIDAD_TOPE_INTENTOS", "2")
    idn.reiniciar_intentos()
    assert idn.tope_intentos() == 2 and idn.intentos_usados(CUIL, 1000.0) == 0
    idn.anotar_intento(CUIL, 1000.0)
    idn.anotar_intento("20-20279041-1", 1100.0)              # mismo CUIL escrito de otra forma
    assert idn.intentos_usados(CUIL, 1200.0) == 2
    assert idn.intentos_usados(CUIL, 1000.0 + 3601) == 1     # el primero ya venció
    assert idn.intentos_usados("27-22222222-8", 1200.0) == 0
    idn.reiniciar_intentos()


def test_sin_clave_esta_apagado(monkeypatch):
    monkeypatch.delenv("DIDIT_API_KEY", raising=False)
    assert not idn.configurado() and not idn.es_sandbox()
    monkeypatch.setenv("DIDIT_API_KEY", "sk_test_abc")
    assert idn.configurado() and idn.es_sandbox()


def test_el_multipart_arma_campos_y_archivos():
    cuerpo, tipo = idn._cuerpo_multipart({"a": "1"}, [("front_image", "x.jpg", b"\x00BIN", "image/jpeg")])
    limite = tipo.split("boundary=")[1]
    assert cuerpo.startswith(("--" + limite).encode()) and cuerpo.endswith(("--" + limite + "--\r\n").encode())
    assert b'name="a"\r\n\r\n1' in cuerpo and b'name="front_image"; filename="x.jpg"' in cuerpo and b"\x00BIN" in cuerpo
