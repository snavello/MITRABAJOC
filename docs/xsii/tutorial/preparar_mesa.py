"""Prepara la base LOCAL para filmar el bloque 5 del tutorial (vuelta a la Mesa).
Llama a preparar.py (usuario, proyecto y tres tarjetas) y suma: los hitos semilla de La Bancaria en el proyecto
y el usuario del sindicato en la Mesa ("Carla Demo"). Imprime el JSON de preparar.py.
Con `subir`, sube como el sindicato un archivo a una tarjeta:
    preparar_mesa.py subir PID CODIGO_TARJETA ARCHIVO"""
import json
import os
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, "..", "..", ".."))
sys.path.insert(0, RAIZ)
os.environ.setdefault("ENTORNO", "local")
import db  # noqa: E402
import implementacion as im  # noqa: E402
from sqlmodel import select  # noqa: E402

if len(sys.argv) > 1 and sys.argv[1] == "subir":
    pid, cod, ruta = int(sys.argv[2]), sys.argv[3], sys.argv[4]
    with db.get_session() as s:
        t = s.exec(select(db.ImplTarjeta).where(db.ImplTarjeta.proyecto_id == pid, db.ImplTarjeta.codigo == cod)).first()
        u = s.exec(select(db.ImplUsuario).where(db.ImplUsuario.proyecto_id == pid)).first()
        a = db.impl_subir_archivo(s, pid, t.id, im.Actor(im.SINDICATO, u.id, u.nombre), os.path.basename(ruta), "text/csv",
                                  open(ruta, "rb").read())
        print(a.codigo)
    sys.exit(0)

salida = subprocess.run([sys.executable, os.path.join(AQUI, "preparar.py")], cwd=RAIZ, capture_output=True, text=True, check=True).stdout
cfg = json.loads(salida.strip().split("\n")[-1])
eq = im.Actor(im.EQUIPO, cfg["uid"], "Sofía Demo")
with db.get_session() as s:
    db.impl_usuario_alta(s, cfg["pid"], "Carla Demo", "carla.demo@ejemplo.org.ar", "tutorial-1234", eq)
    db.impl_cargar_hitos_semilla(s, cfg["pid"], eq, im.cargar_hitos_semilla())
    s.commit()
print(json.dumps(cfg))
