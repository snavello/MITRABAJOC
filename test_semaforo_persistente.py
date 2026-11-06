"""El semáforo de aportes se guarda al calcularse (POST /api/aportes) y
sobrevive a un reload -- antes se perdía apenas se navegaba, porque nunca se
persistía (calcular_semaforo() solo devolvía el resultado, no lo guardaba en
ningún lado).

Correr con: .venv/Scripts/python.exe -m pytest test_semaforo_persistente.py -q
"""


import db
import auth
from db import Sindicato, Trabajador
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()
with db.get_session() as s:
    sind = Sindicato(nombre="Test Semaforo", slug="test-semaforo")
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(Trabajador(sindicato_id=SID, cuil="20111111119", activo=True, registrado=True))
    db.guardar_datos_personales(s, "20111111119", nombre="Juan")
    s.commit()

client = TestClient(main.app)
client.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident="20111111119"))
client.cookies.set("cuil_trab", "20111111119")

DATOS_SEMAFORO = {
    "color": "verde", "titulo": "Todo al día",
    "descripcion": "Tu empleador depositó jubilación y obra social todos los meses.",
    "total_meses": 3, "jubilacion_ok": 3, "obra_social_ok": 3,
    "cuil": "20111111119", "desde": "2026-01", "hasta": "2026-03",
    "meses": [{"jubilacion": "pagado", "obra_social": "pagado"}] * 3,
}


def test_sin_consultar_nunca_no_hay_dato_guardado():
    assert db.semaforo_guardado("20111111119", SID) is None
    print("OK  test_sin_consultar_nunca_no_hay_dato_guardado")


def test_guardar_semaforo_y_leerlo():
    db.guardar_semaforo("20111111119", SID, DATOS_SEMAFORO)
    guardado = db.semaforo_guardado("20111111119", SID)
    assert guardado["color"] == "verde"
    assert guardado["jubilacion_ok"] == 3
    assert guardado["actualizado"], "debe traer la fecha real del cálculo guardado"
    print("OK  test_guardar_semaforo_y_leerlo")


def test_app_pinta_el_semaforo_guardado_sin_volver_a_subir_nada():
    db.guardar_semaforo("20111111119", SID, DATOS_SEMAFORO)
    r = client.get("/app")
    assert r.status_code == 200
    assert "semRender(" in r.text  # se llama con el dato guardado, no semApagado()
    assert "Todo al d\\u00eda" in r.text or "Todo al día" in r.text
    print("OK  test_app_pinta_el_semaforo_guardado_sin_volver_a_subir_nada")


def test_con_semaforo_guardado_sigue_el_acceso_a_arca_y_a_la_subida():
    """Con el semáforo ya generado, el trabajador tiene que poder volver a ARCA
    y subir una captura nueva: el enlace y el input de archivo salen de
    semAcciones(), que usan tanto semApagado() como semRender()."""
    import re
    db.guardar_semaforo("20111111119", SID, DATOS_SEMAFORO)
    html = client.get("/app").text
    assert "semRender(" in html and "Todo al d" in html
    # Las acciones se arman en UN solo lugar: enlace externo seguro + input.
    m = re.search(r"function semAcciones\(.*?\n\}\n", html, re.S)
    assert m, "debe existir semAcciones()"
    acciones = m.group(0)
    assert "https://serviciossegsoc.afip.gob.ar/MisAportes/app/basica.aspx" in acciones
    assert 'target="_blank" rel="noopener"' in acciones
    assert "se abre en otra pestaña" in acciones
    assert 'type="file" id="arca-file"' in acciones
    assert 'for="arca-file"' in acciones
    # Y las dos pantallas la usan (con semáforo y sin él).
    render = re.search(r"function semRender\(d\).*?\n\}\n", html, re.S).group(0)
    apagado = re.search(r"function semApagado\(\).*?\n\}\n", html, re.S).group(0)
    assert "semAcciones(" in render and "semEnlazarArchivo()" in render
    assert "semAcciones(" in apagado and "semEnlazarArchivo()" in apagado
    assert "consultá ARCA de nuevo" in render
    assert "arca-file2" not in html
    print("OK  test_con_semaforo_guardado_sigue_el_acceso_a_arca_y_a_la_subida")


def test_api_aportes_persiste_al_calcular(monkeypatch):
    import main as m

    def fake_extraer(contenido, content_type, modelo=None):
        datos = {
            "confianza": "alta",
            "meses": [{"mes": "2026-04", "jubilacion": "pagado", "obra_social": "parcial"}],
        }
        return datos, {"modelo": "claude-sonnet-4-6", "tokens_entrada": 100,
                       "tokens_salida": 50, "duracion_ms": 1200}
    monkeypatch.setattr(m, "extraer_aportes", fake_extraer)
    r = client.post("/api/aportes", files={"archivo": ("captura.png", b"fake", "image/png")})
    assert r.status_code == 200
    guardado = db.semaforo_guardado("20111111119", SID)
    assert guardado["color"] == "amarillo"  # hay un parcial, ningún malo
    print("OK  test_api_aportes_persiste_al_calcular")


if __name__ == "__main__":
    test_sin_consultar_nunca_no_hay_dato_guardado()
    test_guardar_semaforo_y_leerlo()
    test_app_pinta_el_semaforo_guardado_sin_volver_a_subir_nada()
    test_con_semaforo_guardado_sigue_el_acceso_a_arca_y_a_la_subida()
    import types
    class _MP:
        def setattr(self, obj, name, value): setattr(obj, name, value)
    test_api_aportes_persiste_al_calcular(_MP())
    print("\nTodo OK — semáforo persistente.")
