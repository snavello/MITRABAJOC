"""Prepara la base DESCARTABLE para filmar el tutorial «XSII para implementar La Bancaria».
Crea el sindicato La Bancaria (alta y conceptos de cargar_bancaria.py, sin el lote), un usuario de plataforma
«Sofía Demo», el proyecto «La Bancaria» de la Mesa asociado a ese sindicato con los hitos semilla, y una usuaria
del sindicato en la Mesa («Carla Demo»). Imprime un JSON con la cookie de sesión.
Con `subir`, sube como el sindicato un archivo a una tarjeta:  preparar.py subir PID CODIGO ARCHIVO
Uso: DATABASE_URL=<base descartable> .venv/bin/python docs/xsii/tutorial-bancaria/preparar.py"""
import json
import os
import sys

os.environ.setdefault("ENTORNO", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from sqlmodel import select  # noqa: E402

import auth  # noqa: E402
import db  # noqa: E402
import implementacion as im  # noqa: E402

USUARIO, NOMBRE = "sofia.demo", "Sofía Demo"

if len(sys.argv) > 1 and sys.argv[1] == "subir":
    pid, cod, ruta = int(sys.argv[2]), sys.argv[3], sys.argv[4]
    with db.get_session() as s:
        t = s.exec(select(db.ImplTarjeta).where(db.ImplTarjeta.proyecto_id == pid, db.ImplTarjeta.codigo == cod)).first()
        u = s.exec(select(db.ImplUsuario).where(db.ImplUsuario.proyecto_id == pid)).first()
        a = db.impl_subir_archivo(s, pid, t.id, im.Actor(im.SINDICATO, u.id, u.nombre), os.path.basename(ruta), "text/csv",
                                  open(ruta, "rb").read())
        print(a.codigo)
    sys.exit(0)

import cargar_bancaria  # noqa: E402  (no carga nada al importarse)

sid = cargar_bancaria.crear_sindicato()
# Un sindicato RECIÉN dado de alta: sin el catálogo de ejemplo de cargar_bancaria (solo quedan los tres aportes de ley, que
# la plataforma crea sola) y sin el administrador de demo, así las tareas muestran lo que ve quien empieza de cero.
from sqlalchemy import text  # noqa: E402
with db.get_session() as s:
    s.exec(text("DELETE FROM concepto WHERE sindicato_id = :i AND codigo NOT IN ('JUBILACION','PAMI','OBRASOCIAL')"), params={"i": sid})
    s.exec(text("DELETE FROM usuariosindicato WHERE sindicato_id = :i"), params={"i": sid})
    s.exec(text("DELETE FROM cuentapanel WHERE cuil = '20333444551'"))
    s.commit()
with db.get_session() as s:
    u = s.exec(select(db.UsuarioPlataforma).where(db.UsuarioPlataforma.usuario == USUARIO)).first()
    if not u:
        u = db.UsuarioPlataforma(usuario=USUARIO, nombre=NOMBRE, email="", clave_hash=auth.hashear_clave("xsii-tutorial-1"),
                                 activo=True, debe_cambiar_clave=False, debe_completar_datos=False)
        s.add(u)
        s.commit()
        s.refresh(u)
    uid = u.id
    eq = im.Actor(im.EQUIPO, uid, NOMBRE)
    p = db.impl_crear_proyecto(s, "La Bancaria", eq, sindicato_id=sid)
    pid = p.id
    db.impl_usuario_alta(s, pid, "Carla Demo", "carla.demo@ejemplo.org.ar", "tutorial-1234", eq)
    s.exec(text("UPDATE implusuario SET debe_cambiar_clave = FALSE WHERE proyecto_id = :p"), params={"p": pid})  # para entrar directo
    db.impl_cargar_hitos_semilla(s, pid, eq, im.cargar_hitos_semilla())
    s.commit()
cookie = auth.crear_sesion("plataforma", id_usuario=uid, ident=USUARIO)
print(json.dumps({"uid": uid, "pid": pid, "sid": sid, "cookie": cookie, "cookie_name": "sesion_plataforma"}))
