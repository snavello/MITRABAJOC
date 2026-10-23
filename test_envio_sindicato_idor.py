"""XSK H-0021: /api/reportar y /api/enviar-sindicato toman la identidad de la
SESIÓN, no del cuerpo del pedido.

Antes las dos rutas guardaban el CUIL que mandaba el navegador y marcaban como
"enviado al sindicato" cualquier recibo del sindicato cuyo id viniera en el
pedido. Un afiliado podía fabricar la prueba de afiliado cotizante a nombre de
otro, o marcar el recibo de otro (los id son consecutivos) y dejar a la vista
del sindicato su nombre, CUIL y empresa sin que lo hubiera consentido."""
import auth
import db
import main
from db import EnvioSindicato, ReciboVerificado, Reporte, Sindicato, Trabajador
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()

CUIL_A = "20202790411"   # el afiliado que usa la app
CUIL_B = "27999999994"   # otra afiliada del mismo sindicato

with db.get_session() as s:
    sind = Sindicato(nombre="Sindicato H-0021", slug="sindicato-h0021")
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    for cuil, nombre in ((CUIL_A, "Afiliado A"), (CUIL_B, "Afiliada B")):
        s.add(Trabajador(sindicato_id=SID, cuil=cuil, registrado=True, activo=True))
        db.guardar_datos_personales(s, cuil, nombre=nombre)
    s.commit()


def _cliente(cuil):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", ident=cuil))
    c.cookies.set("cuil_trab", cuil)
    return c


def _recibo(cuil):
    return {"periodo": "2026-06", "empleado": {"cuil": cuil},
            "lineas": [{"codigo": "SUELDO", "descripcion": "Sueldo básico",
                        "importe": 500000, "tipo": "remuneracion"}],
            "totales_impresos": {}}


def _verificar(c, cuil):
    r = c.post("/api/validar", json={"recibo": _recibo(cuil), "conceptos_nuevos": []})
    assert r.status_code == 200, r.text
    return r.json()


def _contar(modelo, *condiciones):
    with Session(db.engine) as s:
        q = select(modelo)
        for cond in condiciones:
            q = q.where(cond)
        return len(s.exec(q).all())


def _enviado(recibo_id):
    with Session(db.engine) as s:
        return s.get(ReciboVerificado, recibo_id).enviado_sindicato


A, B = _cliente(CUIL_A), _cliente(CUIL_B)
RES_B = _verificar(B, CUIL_B)          # un recibo verificado de B, sin enviar
ID_B = RES_B["recibo_verificado_id"]


def test_no_se_puede_marcar_el_recibo_de_otro():
    for ruta in ("/api/enviar-sindicato", "/api/reportar"):
        antes = (_contar(EnvioSindicato), _contar(Reporte))
        r = A.post(ruta, json={"recibo": _recibo(CUIL_A),
                               "resultado": {"cuil": CUIL_A, "periodo": "2026-06",
                                             "recibo_verificado_id": ID_B}})
        assert r.status_code == 403 and r.json().get("codigo") == "E-RECIBO-04", (ruta, r.text)
        assert _enviado(ID_B) is False, f"{ruta} marcó como enviado el recibo de otra persona"
        assert (_contar(EnvioSindicato), _contar(Reporte)) == antes, f"{ruta} escribió algo igual"


def test_no_se_puede_enviar_a_nombre_de_otro():
    for ruta in ("/api/enviar-sindicato", "/api/reportar"):
        antes = (_contar(EnvioSindicato), _contar(Reporte))
        # El CUIL ajeno en el resultado...
        r = A.post(ruta, json={"recibo": _recibo(CUIL_A),
                               "resultado": {"cuil": CUIL_B, "periodo": "2026-06"}})
        assert r.status_code == 403 and r.json().get("codigo") == "E-RECIBO-04", (ruta, r.text)
        # ...o en el recibo.
        r = A.post(ruta, json={"recibo": _recibo(CUIL_B),
                               "resultado": {"periodo": "2026-06"}})
        assert r.status_code == 403 and r.json().get("codigo") == "E-RECIBO-04", (ruta, r.text)
        assert (_contar(EnvioSindicato), _contar(Reporte)) == antes
    assert _contar(EnvioSindicato, EnvioSindicato.cuil == CUIL_B) == 0


def test_el_cuil_guardado_es_el_de_la_sesion_aunque_el_cuerpo_no_lo_traiga():
    r = A.post("/api/reportar", json={"periodo": "2026-06"})
    assert r.status_code == 200, r.text
    with Session(db.engine) as s:
        rep = s.exec(select(Reporte).order_by(Reporte.id.desc())).first()
        env = s.exec(select(EnvioSindicato).order_by(EnvioSindicato.id.desc())).first()
    assert rep.cuil == CUIL_A and env.cuil == CUIL_A


def test_el_envio_propio_sigue_andando():
    res = _verificar(A, CUIL_A)
    rid = res["recibo_verificado_id"]
    r = A.post("/api/enviar-sindicato", json={"recibo": _recibo(CUIL_A), "resultado": res})
    assert r.status_code == 200, r.text
    assert _enviado(rid) is True
    assert _contar(EnvioSindicato, EnvioSindicato.cuil == CUIL_A, EnvioSindicato.sindicato_id == SID) >= 1
    # Reportar el propio también.
    res2 = _verificar(A, CUIL_A)
    r = A.post("/api/reportar", json={"recibo": _recibo(CUIL_A), "resultado": res2})
    assert r.status_code == 200, r.text
    assert _enviado(res2["recibo_verificado_id"]) is True


def test_un_id_que_no_existe_tambien_se_frena():
    r = A.post("/api/enviar-sindicato", json={"recibo": _recibo(CUIL_A),
                                              "resultado": {"cuil": CUIL_A, "recibo_verificado_id": 999999}})
    assert r.status_code == 403 and r.json().get("codigo") == "E-RECIBO-04", r.text


def test_sin_sesion_no_se_escribe_nada():
    antes = _contar(EnvioSindicato)
    r = TestClient(main.app).post("/api/enviar-sindicato", json={"resultado": {"cuil": CUIL_B}})
    assert r.status_code in (400, 401, 403), r.text
    assert _contar(EnvioSindicato) == antes
