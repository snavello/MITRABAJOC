"""achicar_imagenes.py: lo que ya estaba guardado se achica con la misma
función que lo nuevo (imagenes.achicar), una fila por transacción, y una
segunda corrida no toca nada.

Correr con: python -m pytest test_achicar_imagenes.py -q
"""
from io import BytesIO

from PIL import Image
from sqlmodel import select

import achicar_imagenes as ai
import db

db.crear_tablas()


def _png(lado, transparente=False) -> bytes:
    ruido = Image.effect_noise((200, 200), 80).convert("RGB").resize((lado, lado), Image.BICUBIC)
    if transparente:
        ruido = ruido.convert("RGBA")
        ruido.putalpha(Image.linear_gradient("L").resize((lado, lado)))
    salida = BytesIO()
    ruido.save(salida, "PNG")
    return salida.getvalue()


def _jpg(lado) -> bytes:
    salida = BytesIO()
    Image.effect_noise((lado // 4, lado // 4), 80).convert("RGB").resize((lado, lado), Image.BICUBIC).save(salida, "JPEG", quality=95)
    return salida.getvalue()


with db.get_session() as s:
    sind = db.Sindicato(nombre="Achicar", slug="achicar", color_base="#0f2240",
                        logo_datos=_png(2000, True), logo_mime="image/png")
    s.add(sind)
    cuenta = db.CuentaTrabajador(cuil="20111111112", foto_datos=_jpg(1500), foto_mime="image/jpeg")
    s.add(cuenta)
    s.commit(); s.refresh(sind)
    SID = sind.id
    noticia = db.Noticia(sindicato_id=SID, titulo="N", fecha_desde="2026-01-01", fecha_hasta="2026-12-31",
                         imagen1_datos=_jpg(2400), imagen1_mime="image/jpeg",
                         imagen1_norm=b"viejo")
    chica = db.Noticia(sindicato_id=SID, titulo="Chica", fecha_desde="2026-01-01", fecha_hasta="2026-12-31",
                       imagen1_datos=_jpg(100), imagen1_mime="image/jpeg")
    rota = db.Beneficio(sindicato_id=SID, rubro="Rota", fecha_desde="2026-01-01", fecha_hasta="2026-12-31",
                        imagen_datos=b"x" * (500 * 1024), imagen_mime="image/png")
    s.add(noticia); s.add(chica); s.add(rota); s.commit()
    NOTICIA_ID, CHICA_ID, ROTA_ID = noticia.id, chica.id, rota.id


def _estado():
    with db.get_session() as s:
        sind = s.exec(select(db.Sindicato).where(db.Sindicato.id == SID)).one()
        n = s.get(db.Noticia, NOTICIA_ID)
        c = s.get(db.Noticia, CHICA_ID)
        return {"logo": sind.logo_datos, "logo_mime": sind.logo_mime, "logo_v": db.marca_sindicato(SID)["logo_v"],
                "foto": s.exec(select(db.CuentaTrabajador).where(
                    db.CuentaTrabajador.cuil == "20111111112")).one().foto_datos,
                "n1": n.imagen1_datos, "n1_norm": n.imagen1_norm, "n1_mime": n.imagen1_mime,
                "chica": c.imagen1_datos}


def test_diagnostico_no_escribe_y_cuenta_lo_pesado():
    antes = _estado()
    filas = {f["columna"]: f for f in ai.diagnosticar(salida=lambda *_: None)}
    assert _estado() == antes
    assert filas["sindicato.logo_datos"]["sobre_objetivo"] == 1
    assert filas["noticia.imagen1_datos"]["filas"] == 2
    assert filas["noticia.imagen1_datos"]["sobre_objetivo"] == 1
    assert filas["cuentatrabajador.foto_datos"]["sobre_objetivo"] == 1


def test_ensayo_no_cambia_nada():
    antes = _estado()
    res = ai.aplicar(escribir=False, salida=lambda *_: None)
    assert res["cambiadas"] >= 3
    assert _estado() == antes


def test_aplicar_achica_y_una_segunda_corrida_no_toca_nada():
    antes = _estado()
    res = ai.aplicar(escribir=True, salida=lambda *_: None)
    assert [r[:2] for r in res["rechazadas"]] == [("beneficio.imagen_datos", ROTA_ID)]
    despues = _estado()
    logo = Image.open(BytesIO(despues["logo"]))
    assert logo.format == "WEBP" and max(logo.size) <= 512 and logo.mode == "RGBA"
    assert despues["logo_mime"] == "image/webp"
    assert despues["logo_v"] != antes["logo_v"] and despues["logo_v"] < antes["logo_v"]
    assert len(despues["foto"]) < len(antes["foto"])
    assert max(Image.open(BytesIO(despues["n1"])).size) <= 1600
    assert despues["n1_mime"] == "image/webp"
    assert despues["n1_norm"] not in (None, b"viejo")        # la normalizada se regeneró
    assert despues["chica"] == antes["chica"]                # bajo el objetivo: intacta
    with db.get_session() as s:                              # la inválida quedó como estaba
        assert len(s.get(db.Beneficio, ROTA_ID).imagen_datos) == 500 * 1024
    otra = ai.aplicar(escribir=True, salida=lambda *_: None)
    assert otra["cambiadas"] == 0
    assert _estado() == despues


def test_main_con_si_exige_quien():
    assert ai.main(["aplicar", "--si"]) == 2
