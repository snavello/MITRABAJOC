"""Aviso de tolerancia alta en Reglas y comparación de topes con el CSV."""
import db
import auth
import main
import validador
from db import Sindicato, UsuarioSindicato, Formula
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()
with db.get_session() as s:
    sind = Sindicato(nombre="Test TolAlta", slug="test-tolalta", modulos_habilitados=["recibos"])
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20999999999", nombre="Admin",
                            clave_hash=auth.hashear_clave("test-demo"), debe_cambiar_clave=False, es_super_admin=True))
    s.commit()

client = TestClient(main.app)
client.post("/admin/login", data={"usuario": "20999999999", "clave": "test-demo"})


def _guardar(tol, target="JUBILACION"):
    return client.post("/admin/formula", data={
        "target": target, "descripcion": "Jub", "expr": "0.11 * base_remunerativa", "tolerancia": str(tol),
    }, follow_redirects=False)


def test_texto_solo_sobre_el_umbral():
    assert validador.texto_tolerancia_alta(1.0) == ""
    assert validador.texto_tolerancia_alta(validador.TOLERANCIA_AVISO) == ""
    assert "5.000" in validador.texto_tolerancia_alta(5000)


def test_guardar_alta_avisa_y_no_bloquea():
    r = _guardar(5000)
    assert r.status_code == 303 and "tolalta=" in r.headers["location"]
    with Session(db.engine) as s:
        f = s.exec(select(Formula).where(Formula.sindicato_id == SID)).first()
        assert f.tolerancia == 5000
    r2 = client.get(r.headers["location"].split("#")[0])
    assert "Tolerancia alta" in r2.text


def test_guardar_normal_no_avisa():
    r = _guardar(1.0, target="PAMI")
    assert "tolalta" not in r.headers["location"]


def test_fila_de_reglas_lleva_el_aviso():
    html = client.get("/admin").text
    assert "Tolerancia alta: una diferencia menor a $ 5.000" in html


def test_diferencias_de_topes():
    csv_ = [{"vigencia_desde": "2026-02", "tope_maximo": "100"},
            {"vigencia_desde": "2026-03", "tope_maximo": "200"},
            {"vigencia_desde": "2026-04", "tope_maximo": "300"}]
    bd = [{"vigencia_desde": "2026-02", "tope_maximo": 100.0},
          {"vigencia_desde": "2026-03", "tope_maximo": 400.0}]
    txt = " | ".join(validador.diferencias_de_topes(bd, csv_))
    assert "2026-03: la base tiene 400.00 y el CSV 200.00" in txt
    assert "2026-04: falta" in txt
    assert validador.diferencias_de_topes(csv_, csv_) == []
    assert "mayor que el de" in " | ".join(validador.diferencias_de_topes(
        [{"vigencia_desde": "a", "tope_maximo": 5}, {"vigencia_desde": "b", "tope_maximo": 4}], []))
