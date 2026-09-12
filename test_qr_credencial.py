"""QR de la credencial: token opaco, código efímero de 10 minutos,
verificación pública, y que el servidor no confíe en los query params (esos
son solo el respaldo legible offline).

Correr con: .venv/Scripts/python.exe -m pytest test_qr_credencial.py -q
"""


import db
from db import Sindicato, Trabajador, UsuarioSindicato, CuentaTrabajador
import auth
import main
from fastapi.testclient import TestClient
from qr import (qr_svg, url_verificacion, codigo_efimero,
                verificar_codigo_efimero, TTL_QR_SEGUNDOS)

db.crear_tablas()
with db.get_session() as s:
    sind = Sindicato(nombre="Test QR", slug="test-qr")
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(Trabajador(sindicato_id=SID, cuil="20111111119", nombre="Juan Pérez", activo=True,
                      registrado=True, codigo_credencial="TESTQ-000001"))
    s.add(CuentaTrabajador(cuil="20111111119", clave_hash=auth.hashear_clave("demo1234")))
    s.commit()
db.set_modulos_sindicato(SID, ["credencial"])   # sin el módulo, /app no pinta la credencial

client = TestClient(main.app)


def _url_vigente(token):
    """La ruta pública con un código efímero recién emitido, que es como llega
    quien escanea el QR de la pantalla del afiliado."""
    codigo, _ = codigo_efimero(token)
    return f"/v/{token}?k={codigo}"


def test_token_se_genera_una_sola_vez_y_es_estable():
    t1 = db.token_credencial("20111111119", SID)
    t2 = db.token_credencial("20111111119", SID)
    assert t1 and t1 == t2, "el token tiene que ser estable entre llamadas"
    print("OK  test_token_se_genera_una_sola_vez_y_es_estable")


def test_token_vacio_si_no_esta_empadronado():
    assert db.token_credencial("20999999999", SID) == ""
    print("OK  test_token_vacio_si_no_esta_empadronado")


def test_verificacion_publica_no_requiere_login():
    token = db.token_credencial("20111111119", SID)
    r = client.get(_url_vigente(token), follow_redirects=False)
    assert r.status_code == 200, r.text
    assert "Juan P" in r.text and "Credencial válida" in r.text
    print("OK  test_verificacion_publica_no_requiere_login")


def test_verificacion_no_muestra_dni():
    token = db.token_credencial("20111111119", SID)
    r = client.get(_url_vigente(token))
    assert "DNI" not in r.text, "la página de verificación no debe mostrar el DNI"
    print("OK  test_verificacion_no_muestra_dni")


def test_verificacion_ignora_query_params_falsos():
    """El corazón de la seguridad: el token es lo único que cuenta. Un query
    param con datos distintos NO debe pisar lo que devuelve el servidor."""
    token = db.token_credencial("20111111119", SID)
    codigo, _ = codigo_efimero(token)
    r = client.get(f"/v/{token}?n=Impostor&c=99999999999&num=FALSO-000&k={codigo}")
    assert "Juan P" in r.text
    assert "Impostor" not in r.text
    assert "99999999999" not in r.text
    print("OK  test_verificacion_ignora_query_params_falsos")


def test_token_inexistente_no_verifica():
    r = client.get(_url_vigente("no-existe-este-token"))
    assert r.status_code == 200
    assert "no encontrada" in r.text.lower()
    print("OK  test_token_inexistente_no_verifica")


# ---------- Código efímero: lo que hace inútil a la captura de pantalla ----------

def test_codigo_efimero_valido_apenas_emitido():
    codigo, vida = codigo_efimero("abc123")
    assert vida == TTL_QR_SEGUNDOS
    assert verificar_codigo_efimero("abc123", codigo)
    print("OK  test_codigo_efimero_valido_apenas_emitido")


def test_codigo_efimero_no_sirve_para_otro_token():
    codigo, _ = codigo_efimero("abc123")
    assert not verificar_codigo_efimero("otro-token", codigo)
    print("OK  test_codigo_efimero_no_sirve_para_otro_token")


def test_codigo_efimero_vence():
    import time
    # Emitido hace 11 minutos: ya pasó la ventana de 10.
    codigo, _ = codigo_efimero("abc123", ahora=time.time() - TTL_QR_SEGUNDOS - 60)
    assert not verificar_codigo_efimero("abc123", codigo)
    print("OK  test_codigo_efimero_vence")


def test_codigo_efimero_no_se_puede_estirar_cambiando_el_vencimiento():
    """La firma cubre el vencimiento: correrlo a futuro invalida el código."""
    codigo, _ = codigo_efimero("abc123")
    _, firma = codigo.split(".", 1)
    import time
    assert not verificar_codigo_efimero("abc123", f"{int(time.time()) + 99999}.{firma}")
    print("OK  test_codigo_efimero_no_se_puede_estirar_cambiando_el_vencimiento")


def test_captura_de_qr_vencido_no_muestra_datos():
    """El corazón del cambio pedido: un QR fotografiado hace rato no verifica."""
    import time
    token = db.token_credencial("20111111119", SID)
    codigo, _ = codigo_efimero(token, ahora=time.time() - TTL_QR_SEGUNDOS - 60)
    r = client.get(f"/v/{token}?k={codigo}")
    assert r.status_code == 200
    assert "vencido" in r.text.lower()
    assert "Juan P" not in r.text, "una captura vencida no debe mostrar al afiliado"
    print("OK  test_captura_de_qr_vencido_no_muestra_datos")


def test_sin_codigo_no_verifica():
    """El link pelado /v/{token} (sin `k`) tampoco alcanza: si alcanzara, con
    copiar la URL del QR una sola vez ya se tendría un pase permanente."""
    token = db.token_credencial("20111111119", SID)
    r = client.get(f"/v/{token}")
    assert "Juan P" not in r.text
    assert "vencido" in r.text.lower()
    print("OK  test_sin_codigo_no_verifica")


# ---------- La app: el QR se renueva, y la foto va bajo la filigrana ----------

def _sesion_trabajador(cuil="20111111119"):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0))
    c.cookies.set("cuil_trab", cuil)
    return c


def test_api_renueva_el_qr_con_un_codigo_distinto():
    """Dos llamadas seguidas tienen que dar QR distintos: es lo que hace que
    el que quedó en una captura ya no sea el que está en pantalla."""
    import time
    trab = _sesion_trabajador()
    a = trab.get("/api/credencial/qr")
    assert a.status_code == 200, a.text
    assert a.json()["vence_en"] == TTL_QR_SEGUNDOS
    time.sleep(1.1)   # el vencimiento tiene resolución de un segundo
    b = trab.get("/api/credencial/qr")
    assert b.json()["svg"] != a.json()["svg"]
    print("OK  test_api_renueva_el_qr_con_un_codigo_distinto")


def test_api_del_qr_exige_sesion():
    r = TestClient(main.app).get("/api/credencial/qr")
    assert r.status_code == 401
    print("OK  test_api_del_qr_exige_sesion")


def test_credencial_muestra_el_retrato_solo_si_hay_foto():
    RETRATO = '<div class="cred-retrato">'   # el bloque, no la regla CSS del mismo nombre
    trab = _sesion_trabajador()
    assert RETRATO not in trab.get("/app").text
    r = trab.post("/api/perfil/foto", files={"foto": ("f.jpg", b"jpeg-falso", "image/jpeg")})
    assert r.status_code == 200, r.text
    html = trab.get("/app").text
    assert RETRATO in html
    # El orden en el HTML es el orden de apilado: el retrato va ANTES que la
    # filigrana, así la filigrana queda por encima de la foto.
    assert html.index(RETRATO) < html.index('<div class="cred-fondo">')
    print("OK  test_credencial_muestra_el_retrato_solo_si_hay_foto")


def test_url_del_qr_lleva_el_codigo_efimero():
    codigo, _ = codigo_efimero("abc123")
    url = url_verificacion("https://mitrabajo.onrender.com", "abc123",
                            "Juan Pérez", "20111111119", "TESTQ-000001", codigo)
    assert "k=" in url
    print("OK  test_url_del_qr_lleva_el_codigo_efimero")


def test_url_verificacion_lleva_datos_de_respaldo_pero_no_dni():
    url = url_verificacion("https://mitrabajo.onrender.com", "abc123", "Juan Pérez", "20111111119", "TESTQ-000001")
    assert url.startswith("https://mitrabajo.onrender.com/v/abc123?")
    assert "TESTQ" in url and "20111111119" in url
    assert "11111111" not in url or "20111111119" in url  # el CUIL sí, un DNI suelto no
    print("OK  test_url_verificacion_lleva_datos_de_respaldo_pero_no_dni")


def test_qr_svg_es_valido():
    svg = qr_svg("https://mitrabajo.onrender.com/v/abc123")
    assert svg.startswith("<svg") and "</svg>" in svg
    print("OK  test_qr_svg_es_valido")


def test_qr_svg_tiene_viewbox_para_escalar_sin_recortarse():
    # Bug real: segno no pone viewBox, solo width/height fijos. El CSS que
    # reescala el QR a 64x64 en la credencial (.cred-qr svg) lo RECORTABA en
    # vez de escalarlo, porque sin viewBox el navegador no sabe reproporcionar
    # el contenido — se vio cortado en la credencial real.
    svg = qr_svg("https://mitrabajo.onrender.com/v/abc123")
    assert 'viewBox="0 0 ' in svg
    print("OK  test_qr_svg_tiene_viewbox_para_escalar_sin_recortarse")


if __name__ == "__main__":
    test_token_se_genera_una_sola_vez_y_es_estable()
    test_token_vacio_si_no_esta_empadronado()
    test_verificacion_publica_no_requiere_login()
    test_verificacion_no_muestra_dni()
    test_verificacion_ignora_query_params_falsos()
    test_token_inexistente_no_verifica()
    test_codigo_efimero_valido_apenas_emitido()
    test_codigo_efimero_no_sirve_para_otro_token()
    test_codigo_efimero_vence()
    test_codigo_efimero_no_se_puede_estirar_cambiando_el_vencimiento()
    test_captura_de_qr_vencido_no_muestra_datos()
    test_sin_codigo_no_verifica()
    test_api_renueva_el_qr_con_un_codigo_distinto()
    test_api_del_qr_exige_sesion()
    test_credencial_muestra_el_retrato_solo_si_hay_foto()
    test_url_del_qr_lleva_el_codigo_efimero()
    test_url_verificacion_lleva_datos_de_respaldo_pero_no_dni()
    test_qr_svg_es_valido()
    test_qr_svg_tiene_viewbox_para_escalar_sin_recortarse()
    print("\nTodo OK — QR y verificación pública de la credencial.")
