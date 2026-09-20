"""/api/leer corta ANTES de devolver nada cuando el recibo no es del CUIL
logueado.

El chequeo ya existía en /api/validar (ver test_cuil_bloqueo_ruta.py), pero
ahí llegaba tarde para lo que importa: /api/leer devolvía el recibo entero y
la pantalla de confirmar le mostraba a quien subió el archivo el nombre, el
CUIL, el empleador y todos los importes de OTRA persona. Recién al confirmar
aparecía el bloqueo. Encontrado por Sd el 2026-09-14 subiendo un recibo ajeno
con una sesión propia: "leyó todo y me mostró, debió fallar antes".

La llamada a la IA no se puede evitar -- el CUIL del recibo recién se conoce
después de leerlo --, así que el costo se registra igual. Lo que no sale de
la ruta es el contenido.

Correr con: .venv/Scripts/python.exe -m pytest test_cuil_leer_ajeno.py -q
"""
import os

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
import auth
from db import Sindicato, Trabajador, ReciboSospechoso, UsoIA
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()
with db.get_session() as s:
    sind = Sindicato(nombre="Test Leer Ajeno", slug="test-leer-ajeno")
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(Trabajador(sindicato_id=SID, cuil="27999999999", nombre="Julia",
                      activo=True, registrado=True))
    s.commit()

client = TestClient(main.app)
client.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=SID, ident="27999999999"))
client.cookies.set("cuil_trab", "27999999999")

AJENO = "20202790411"   # el CUIL del recibo del caso real


def _recibo(cuil, alerta=None):
    return {
        "periodo": "2025-07", "empleado": {"cuil": cuil, "apellido_nombre": "Otra, Persona"},
        "empleador": {"nombre": "Talleres del Sur", "cuit": "30444640975"},
        "lineas": [{"codigo": "SUELDO", "descripcion": "Sueldo básico", "importe": 365806,
                    "tipo": "remuneracion"}],
        "totales_impresos": {"remuneraciones": 365806, "descuentos": 0, "neto": 365806},
        "contribuciones_patronales": [], "confianza": "alta",
        "alerta_adulteracion": alerta or {"detectada": False, "motivo": None},
    }


def _mockear(recibo):
    """Reemplaza la lectura por IA: los tests no gastan créditos."""
    def fake(contenido, content_type, modelo=None):
        return recibo, {"modelo": modelo or "claude-sonnet-4-6", "tokens_entrada": 100,
                        "tokens_salida": 50, "duracion_ms": 1200}
    return fake


def _leer(recibo):
    original = main.extraer
    main.extraer = _mockear(recibo)
    try:
        return client.post("/api/leer",
                           files={"archivo": ("recibo.png", b"contenido-fake", "image/png")})
    finally:
        main.extraer = original


def test_recibo_ajeno_no_devuelve_nada_del_recibo():
    r = _leer(_recibo(AJENO))
    assert r.status_code == 403, r.text
    body = r.json()
    assert body["codigo"] == "E-RECIBO-04"
    # Lo central: ni un dato del recibo ajeno puede viajar al navegador.
    crudo = r.text
    for dato in (AJENO, "Otra, Persona", "Talleres del Sur", "30444640975", "365806"):
        assert dato not in crudo, f"el recibo ajeno filtró '{dato}' en la respuesta"
    print("OK  test_recibo_ajeno_no_devuelve_nada_del_recibo")


def test_recibo_ajeno_no_menciona_la_foto():
    # El recibo se leyó perfecto: el problema es de quién es. Mandar a sacar
    # otra foto sería mentira (ver la regla en errores.py).
    r = _leer(_recibo(AJENO))
    texto = r.json()["detail"].lower()
    assert "foto" not in texto and "nítida" not in texto
    print("OK  test_recibo_ajeno_no_menciona_la_foto")


def test_recibo_ajeno_no_guarda_el_archivo_aunque_tenga_alerta():
    # Va antes de registrar_recibo_sospechoso a propósito: de un recibo que no
    # es de quien lo sube no se guarda nada, ni el archivo.
    antes = _contar(ReciboSospechoso)
    r = _leer(_recibo(AJENO, {"detectada": True, "motivo": "el neto parece retocado"}))
    assert r.status_code == 403
    assert _contar(ReciboSospechoso) == antes
    print("OK  test_recibo_ajeno_no_guarda_el_archivo_aunque_tenga_alerta")


def test_recibo_ajeno_igual_registra_el_gasto_de_ia():
    # El CUIL se conoce DESPUÉS de leer: la llamada ya se pagó y el panel de
    # costos tiene que verla, o el total deja de ser el gasto real.
    antes = _contar(UsoIA)
    _leer(_recibo(AJENO))
    assert _contar(UsoIA) == antes + 1
    print("OK  test_recibo_ajeno_igual_registra_el_gasto_de_ia")


def test_recibo_propio_se_lee_normal():
    r = _leer(_recibo("27999999999"))
    assert r.status_code == 200, r.text
    assert r.json()["recibo"]["empleado"]["cuil"] == "27999999999"
    print("OK  test_recibo_propio_se_lee_normal")


def test_recibo_sin_cuil_legible_no_bloquea():
    # cuil_no_coincide() no afirma nada con datos incompletos: un recibo cuyo
    # CUIL la IA no pudo leer sigue el camino normal.
    r = _leer(_recibo(None))
    assert r.status_code == 200, r.text
    print("OK  test_recibo_sin_cuil_legible_no_bloquea")


def _contar(modelo):
    with Session(db.engine) as s:
        return len(s.exec(select(modelo)).all())


# ---------- El gemelo: el comprobante de aportes de ARCA ----------
# Mismo agujero y peor consecuencia: sin este corte, el comprobante de otra
# persona no solo se mostraba, se GUARDABA como semáforo propio
# (guardar_semaforo indexa por el CUIL de la sesión, no por el del
# comprobante) y seguía ahí al volver a entrar.

APORTES_BASE = {
    "desde": "10/2024", "hasta": "09/2025", "confianza": "alta",
    "meses": [{"periodo": "09/2025", "jubilacion": "pagado", "obra_social": "pagado"}],
}


def _aportes(cuil):
    return dict(APORTES_BASE, cuil=cuil)


def _leer_aportes(datos):
    original = main.extraer_aportes
    def fake(contenido, content_type, modelo=None):
        return datos, {"modelo": modelo or "claude-sonnet-4-6", "tokens_entrada": 80,
                       "tokens_salida": 40, "duracion_ms": 900}
    main.extraer_aportes = fake
    try:
        return client.post("/api/aportes",
                           files={"archivo": ("arca.png", b"contenido-fake", "image/png")})
    finally:
        main.extraer_aportes = original


def _semaforo_guardado():
    with Session(db.engine) as s:
        t = s.exec(select(Trabajador).where(Trabajador.cuil == "27999999999",
                                             Trabajador.sindicato_id == SID)).first()
        return t.semaforo_datos


def test_comprobante_ajeno_no_se_lee_ni_se_guarda():
    # semaforo_datos arranca en {} (no None): lo que importa es que esté vacío.
    assert not _semaforo_guardado(), "el test arranca sin semáforo guardado"
    r = _leer_aportes(_aportes(AJENO))
    assert r.status_code == 403, r.text
    assert r.json()["codigo"] == "E-APORTE-03"
    assert AJENO not in r.text
    assert not _semaforo_guardado(), "no puede quedar el semáforo de otra persona"
    print("OK  test_comprobante_ajeno_no_se_lee_ni_se_guarda")


def test_comprobante_propio_se_guarda():
    r = _leer_aportes(_aportes("27999999999"))
    assert r.status_code == 200, r.text
    assert _semaforo_guardado()
    print("OK  test_comprobante_propio_se_guarda")


def test_comprobante_sin_cuil_legible_no_bloquea():
    r = _leer_aportes(_aportes(None))
    assert r.status_code == 200, r.text
    print("OK  test_comprobante_sin_cuil_legible_no_bloquea")
