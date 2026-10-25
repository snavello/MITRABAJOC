"""Sesiones de XSD para Colm3na: imprime `{rol: {cookie: valor}}`.

    python xsd/proyectos/mitrabajo/sesiones.py <variante> [quien]

Es la ÚNICA pieza de XSD que depende del proyecto (la ficha la nombra en
`sesiones.comando`). Firma sesiones recién hechas para cada rol del
inventario, porque las de Colm3na vencen a los 15 minutos sin uso: se corre
antes de cada tanda de capturas.

- `variante` es el modelo de diseño (`laguna`, `noticiero`) que queda elegido
  en las cuentas que usa la captura; `base` no toca nada.
- `quien` separa a los agentes que capturan a la vez: cada uno tiene SU
  afiliado y SU operador, porque el modelo elegido vive en la cuenta de la
  persona y, si dos agentes usaran la misma, uno le cambiaría las capturas
  al otro. La empresa y el usuario de plataforma son uno solo: solo los
  toca `principal` (o el `quien` que se llame como el rol).

Toma el sindicato de `XSD_SINDICATO` (nombre) o, sin la variable, el que más
afiliados tiene en el padrón. Si el operador de un `quien` no existe, lo crea
como Super Admin de ese sindicato, con su cuenta del panel y sin clave: solo
sirve para firmar sesiones en la base local.
"""
import json
import os
import sys
import zlib
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ))
os.chdir(RAIZ)

import auth  # noqa: E402
import cuit  # noqa: E402
import db  # noqa: E402
import main  # noqa: E402
import temas  # noqa: E402
from sqlmodel import func, select  # noqa: E402


def _sindicato(s):
    nombre = os.environ.get("XSD_SINDICATO", "").strip()
    if nombre:
        sind = s.exec(select(db.Sindicato).where(db.Sindicato.nombre == nombre)).first()
        if not sind:
            sys.exit(f"No hay un sindicato llamado {nombre!r} (XSD_SINDICATO).")
        return sind
    fila = s.exec(select(db.Trabajador.sindicato_id, func.count())
                  .group_by(db.Trabajador.sindicato_id)
                  .order_by(func.count().desc())).first()
    if not fila:
        sys.exit("La base no tiene padrón: cargá la demo y un lote antes de capturar.")
    return s.get(db.Sindicato, fila[0])


def _numero(quien: str) -> int:
    return 0 if quien == "principal" else 1 + zlib.crc32(quien.encode()) % 899


def _afiliado(s, sid: int, n: int) -> str:
    """Un afiliado del padrón con cuenta y clave, distinto para cada `quien`."""
    cuiles = s.exec(select(db.Trabajador.cuil)
                    .join(db.CuentaTrabajador, db.CuentaTrabajador.cuil == db.Trabajador.cuil)
                    .where(db.Trabajador.sindicato_id == sid, db.Trabajador.activo == True,  # noqa: E712
                           db.CuentaTrabajador.clave_hash != "")
                    .order_by(db.Trabajador.cuil)).all()
    if not cuiles:
        sys.exit("El sindicato no tiene afiliados con cuenta: cargá un lote (cargar_lote_sindicato.py).")
    return cuiles[n % len(cuiles)]


def _operador(s, sid: int, n: int, quien: str) -> tuple:
    """El Super Admin de este `quien`: lo crea si falta. Devuelve su id y su CUIL."""
    numero = cuit.corregir(f"2090100{n:03d}0")
    u = s.exec(select(db.UsuarioSindicato).where(db.UsuarioSindicato.usuario == numero,
                                                  db.UsuarioSindicato.sindicato_id == sid)).first()
    if not u:
        u = db.UsuarioSindicato(usuario=numero, sindicato_id=sid, cuil=numero, nombre=f"XSD {quien}",
                                es_super_admin=True, activo=True, debe_cambiar_clave=False)
        s.add(u)
    if not s.exec(select(db.CuentaPanel).where(db.CuentaPanel.cuil == numero)).first():
        s.add(db.CuentaPanel(cuil=numero, debe_cambiar_clave=False))
    s.commit()
    s.refresh(u)
    return u.id, numero


def _empresa(s, sid: int):
    cuits = s.exec(select(db.Empleador.cuit).where(db.Empleador.sindicato_id == sid)).all()
    q = select(db.CuentaEmpleador)
    cta = s.exec(q.where(db.CuentaEmpleador.cuit.in_(cuits))).first() if cuits else None
    return cta or s.exec(q).first()


def main_():
    variante = sys.argv[1] if len(sys.argv) > 1 else "base"
    quien = sys.argv[2] if len(sys.argv) > 2 else "principal"
    tema = variante if variante in temas.TEMAS else None
    n = _numero(quien)
    with db.get_session() as s:
        sind = _sindicato(s)
        sid = sind.id
        afiliado = _afiliado(s, sid, n)
        uid, operador = _operador(s, sid, n, quien)
        emp = _empresa(s, sid)
        plat = s.exec(select(db.UsuarioPlataforma).where(db.UsuarioPlataforma.activo == True)  # noqa: E712
                      .order_by(db.UsuarioPlataforma.id)).first()
        # Valores sueltos: los objetos se desprenden al cerrar la sesión.
        nombre = sind.nombre
        emp = (emp.id, emp.cuit) if emp else None
        plat = (plat.id, plat.usuario) if plat else None
    if tema:
        db.guardar_tema_persona(afiliado, tema, "afiliado")
        db.guardar_tema_persona(operador, tema, "panel")
        if emp and quien in ("principal", "empresa"):
            db.guardar_tema_persona(emp[1], tema, "empresa")
        if plat and quien in ("principal", "plataforma"):
            db.guardar_tema_plataforma(plat[0], tema)
    sesiones = {
        "ninguno": {},
        "trabajador": {main.COOKIE_TRABAJADOR: auth.crear_sesion("trabajador", sindicato_id=0, ident=afiliado)},
        "sindicato": {main.COOKIE_SINDICATO: auth.crear_sesion("sindicato", id_usuario=uid, sindicato_id=sid)},
        "empleador": ({main.COOKIE_EMPLEADOR: auth.crear_sesion("empleador", id_usuario=emp[0], sindicato_id=0,
                                                              ident=emp[1])} if emp else {}),
        "plataforma": ({main.COOKIE_PLATAFORMA: auth.crear_sesion("plataforma", id_usuario=plat[0],
                                                                ident=plat[1])} if plat else {}),
    }
    print(json.dumps(sesiones))
    print(f"xsd: sindicato {nombre} (id {sid}), afiliado {afiliado}, operador {operador}"
          + (f", empresa {emp[1]}" if emp else ", sin empresa")
          + (f", plataforma {plat[1]}" if plat else ", sin usuario de plataforma"), file=sys.stderr)


if __name__ == "__main__":
    main_()
