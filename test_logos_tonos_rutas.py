"""Un logo a color en plataforma genera solo la otra versión; /logo/{id}?tono=."""
import os

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

import db
import main
from db import Sindicato
from sqlmodel import Session

db.crear_tablas()
client = TestClient(main.app)
client.post("/plataforma/login", data={"cuit": "20000000000", "clave": "test-plataforma"})


def _logo():
    img = Image.new("RGBA", (120, 80), (0, 0, 0, 0))
    for x in range(30, 90):
        for y in range(20, 60):
            img.putpixel((x, y), (230, 160, 20, 255))
    b = BytesIO(); img.save(b, "PNG"); return b.getvalue()


def _marca(**files):
    return client.post("/plataforma/marca", data={
        "color_primario": "#152238", "color_secundario": "#1a7a6b", "color_acento": "#b23a2e"},
        files=files, follow_redirects=False)


def test_logo_claro_arma_el_oscuro_en_blanco():
    assert _marca(logo=("logo.png", _logo(), "image/png")).status_code == 303
    assert db.marca_plataforma()["logo_oscuro"] == "auto.png"
    r = client.get("/logo-plataforma-oscuro")
    out = Image.open(BytesIO(r.content)).convert("RGBA")
    assert out.getpixel((out.width // 2, out.height // 2)) == (255, 255, 255, 255)


def test_lo_subido_a_mano_no_se_pisa():
    assert _marca(logo_oscuro=("logo.png", _logo(), "image/png")).status_code == 303
    assert db.marca_plataforma()["logo_oscuro"] == "logo.png"
    assert _marca(logo=("logo.png", _logo(), "image/png")).status_code == 303
    assert db.marca_plataforma()["logo_oscuro"] == "logo.png"


def test_ruta_de_sindicato_con_tono():
    with Session(db.engine) as s:
        sind = Sindicato(nombre="Tonos SA", logo_datos=_logo(), logo_mime="image/png", logo="logo.png",
                         color_base="#0f1b2d", color_primario="#1d4ed8", color_acento="#e5188f",
                         color_secundario="#fbbf24")
        s.add(sind); s.commit(); s.refresh(sind); sid = sind.id
    mid = lambda t: Image.open(BytesIO(client.get(f"/logo/{sid}?tono={t}").content)).convert("RGBA")
    o = mid("oscuro")
    assert o.getpixel((o.width // 2, o.height // 2)) == (0x0f, 0x1b, 0x2d, 255)
    c = mid("claro")
    assert c.getpixel((c.width // 2, c.height // 2)) == (255, 255, 255, 255)
    orig = Image.open(BytesIO(client.get(f"/logo/{sid}").content)).convert("RGBA")
    assert orig.getpixel((orig.width // 2, orig.height // 2))[:3] == (230, 160, 20)
