"""Conftest global de la suite: fuerza SQLite en los tests sin importar lo
que tenga .env en la máquina de quien los corre.

Cada test_*.py arma su propia base temporal por archivo (os.environ["DB_PATH"]
antes de "import db") -- rápido y aislado, ver CLAUDE.md "Desarrollo local
con Postgres". Pero db.py ahora hace load_dotenv() (fix necesario para que
Alembic vea DATABASE_URL al correr standalone), así que si .env tiene
DATABASE_URL apuntando al Postgres local de desarrollo (docker-compose.yml),
db.py lo tomaría igual y los tests dejarían de estar aislados entre sí.

pytest importa conftest.py ANTES de recolectar los test_*.py de este
directorio, así que esto corre antes que cualquier "import db".
"""
import os

os.environ["DATABASE_URL"] = ""
