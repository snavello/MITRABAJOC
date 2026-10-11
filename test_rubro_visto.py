"""Conceptos: el rubro que sugieren los recibos leídos (db.secciones_vistas +
validador.clasificacion_vista) y el botón que confirma en ese rubro.

Caso de origen (SDN, 2026-10-11): una devolución de Ganancias ("IMP.GCIAS.
PERIODOS ANTERIORES") quedó dada de alta como haber. Si alguien la confirma
así, el catálogo queda mal para siempre. Ahora la pestaña Conceptos dice
dónde la leyó la IA ("en los recibos: descuento") y ofrece "Confirmar como
descuento"; y a un concepto ya revisado en el rubro contrario lo marca y
ofrece "Pasar a descuento".

Correr con: python -m pytest test_rubro_visto.py -q
"""
import auth
import db
import main
from db import Concepto, ReciboVerificado, Sindicato, UsuarioSindicato
from fastapi.testclient import TestClient
from sqlmodel import Session

CUIT_A = "30999888778"
CUIT_B = "30111222335"

db.crear_tablas()


def _recibo(cuit_empleador, lineas):
    return ReciboVerificado(sindicato_id=SID, cuil="20111111112", periodo="2015-02",
                            estado="OK", cuit_empleador=cuit_empleador,
                            detalle={"recibo": {"lineas": lineas}, "resultado": {}})


with db.get_session() as s:
    sind = Sindicato(nombre="AEFIP Rubros", slug="aefip-rubros", modulos_habilitados=["recibos"])
    otro = Sindicato(nombre="Otro Rubros", slug="otro-rubros", modulos_habilitados=["recibos"])
    s.add(sind); s.add(otro); s.commit(); s.refresh(sind); s.refresh(otro)
    SID, SID_OTRO = sind.id, otro.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20111111120", nombre="Admin",
                           clave_hash=auth.hashear_clave("rubros-demo"),
                           debe_cambiar_clave=False, es_super_admin=True))
    s.add(Concepto(sindicato_id=SID, codigo="433-001", nombre="IMP.GCIAS. PERIODOS ANTERIORES",
                   tipo="ingreso", remunerativo=True, alias=[], pendiente_revision=True))
    s.add(Concepto(sindicato_id=SID, codigo="161-001", nombre="IMPUESTO A LAS GANANCIAS",
                   tipo="ingreso", remunerativo=False, alias=[], pendiente_revision=False))
    s.add(Concepto(sindicato_id=SID, codigo="1-026", nombre="SUELDO BASICO",
                   tipo="ingreso", remunerativo=True, alias=[], pendiente_revision=False))
    s.add(Concepto(sindicato_id=SID, codigo="900", nombre="Ajuste del empleador A",
                   tipo="ingreso", remunerativo=True, alias=[], pendiente_revision=True,
                   cuit_empleador=CUIT_A))
    s.commit()
    s.add(_recibo(CUIT_A, [
        {"codigo": "1-026", "importe": 3451, "seccion": "haberes"},
        {"codigo": "161-001", "importe": -10274.94, "seccion": "descuentos"},
        {"codigo": "433-001", "importe": 62949.21, "seccion": "descuentos"},
        {"codigo": "900", "importe": -100, "seccion": "descuentos"},
    ]))
    s.add(_recibo(CUIT_B, [
        {"codigo": "1-026", "importe": 3451, "seccion": "Haberes"},
        {"codigo": "433-001", "importe": -500, "seccion": "descuentos"},
        {"codigo": 900, "importe": 50, "seccion": "haberes"},    # código numérico
        {"codigo": "161-001", "importe": -1},                    # lectura sin sección
        "línea rota",
    ]))
    # Un recibo ilegible y uno de otro sindicato no aportan nada.
    s.add(_recibo(CUIT_A, None))
    s.add(ReciboVerificado(sindicato_id=SID_OTRO, cuil="20111111112", periodo="2015-02",
                           cuit_empleador=CUIT_A, detalle={"recibo": {"lineas": [
                               {"codigo": "1-026", "importe": 1, "seccion": "descuentos"}]}}))
    s.commit()

cliente = TestClient(main.app)
cliente.post("/admin/login", data={"usuario": "20111111120", "clave": "rubros-demo"})


def _concepto(codigo):
    with Session(db.engine) as s:
        from sqlmodel import select
        return s.exec(select(Concepto).where(Concepto.sindicato_id == SID,
                                             Concepto.codigo == codigo)).first()


def test_secciones_vistas_cuenta_por_codigo_y_empleador_solo_del_sindicato():
    with Session(db.engine) as s:
        vistas = db.secciones_vistas(s, SID)
    assert vistas[("433-001", CUIT_A)] == {"descuentos": 1}
    assert vistas[("433-001", CUIT_B)] == {"descuentos": 1}
    assert vistas[("1-026", CUIT_A)] == {"haberes": 1}
    assert vistas[("1-026", CUIT_B)] == {"haberes": 1}     # "Haberes" normalizado
    assert vistas[("900", CUIT_B)] == {"haberes": 1}       # código numérico como texto
    # La línea sin sección no cuenta, y el recibo del otro sindicato tampoco.
    assert ("161-001", CUIT_B) not in vistas
    assert vistas[("1-026", CUIT_A)].get("descuentos") is None


def test_un_concepto_de_empleador_solo_mira_los_recibos_de_ese_cuit():
    with Session(db.engine) as s:
        vistas = db.secciones_vistas(s, SID)
    especificos = {("900", CUIT_A)}
    assert db.secciones_del_concepto(vistas, "900", CUIT_A, especificos) == {"descuentos": 1}
    # El genérico (si existiera) no cuenta los recibos del empleador que tiene el suyo.
    assert db.secciones_del_concepto(vistas, "900", None, especificos) == {"haberes": 1}
    assert db.secciones_del_concepto(vistas, "433-001", None, especificos) == {"descuentos": 2}


def test_la_pestana_conceptos_propone_el_rubro_de_los_recibos():
    html = cliente.get("/admin").text
    # Pendiente cargado como haber y leído entre los descuentos.
    assert "Confirmar como descuento" in html
    # Revisado en el rubro contrario: marcado y con el botón para pasarlo.
    assert "Pasar a descuento" in html
    assert "1 concepto(s) cargado(s) en el rubro contrario al de los recibos." in html
    assert "en los recibos: descuento" in html


def test_confirmar_en_el_rubro_propuesto():
    c = _concepto("433-001")
    r = cliente.post("/admin/concepto/confirmar",
                     data={"id": c.id, "tipo": "descuento", "remunerativo": "no"},
                     follow_redirects=False)
    assert r.status_code == 303
    c = _concepto("433-001")
    assert (c.tipo, c.remunerativo, c.pendiente_revision) == ("descuento", False, False)


def test_un_tipo_que_no_existe_no_se_guarda():
    c = _concepto("1-026")
    cliente.post("/admin/concepto/confirmar", data={"id": c.id, "tipo": "reintegro"})
    assert _concepto("1-026").tipo == "ingreso"


def test_pasar_un_revisado_al_rubro_de_los_recibos():
    c = _concepto("161-001")
    cliente.post("/admin/concepto/confirmar", data={"id": c.id, "tipo": "descuento",
                                                    "remunerativo": "no"})
    assert _concepto("161-001").tipo == "descuento"
    assert "cargado(s) en el rubro contrario" not in cliente.get("/admin").text
