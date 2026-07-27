"""Autodiagnóstico de la instalación de Mi Trabajo.

Ejecutar con:  python chequeo.py

Verifica, en orden, que todo lo necesario esté en su lugar. Se detiene en el
primer problema e indica qué hacer. No consume créditos de la API salvo en el
chequeo 6, que es opcional y se activa con:  python chequeo.py --api
"""
import sys
import os
import json
from pathlib import Path

VERDE = "\033[92m"
ROJO = "\033[91m"
AMAR = "\033[93m"
FIN = "\033[0m"

fallos = 0


def ok(msg):
    print(f"{VERDE}[OK]{FIN}   {msg}")


def error(msg, arreglo):
    global fallos
    fallos += 1
    print(f"{ROJO}[ERROR]{FIN} {msg}")
    print(f"        → {arreglo}")


def aviso(msg):
    print(f"{AMAR}[AVISO]{FIN} {msg}")


print("\n=== Chequeo de instalación — Mi Trabajo ===\n")

# 1. Versión de Python
print("1. Versión de Python")
v = sys.version_info
if v.major == 3 and v.minor >= 11:
    ok(f"Python {v.major}.{v.minor}.{v.micro}")
else:
    error(f"Python {v.major}.{v.minor} es muy antiguo (se necesita 3.11 o superior)",
          "Instalá una versión más nueva desde python.org")

# 2. Entorno virtual activado
print("\n2. Entorno virtual")
if sys.prefix != sys.base_prefix:
    ok("El entorno virtual está activado")
else:
    aviso("El entorno virtual NO parece estar activado.")
    print("        → Windows: .venv\\Scripts\\activate | Mac/Linux: source .venv/bin/activate")

# 3. Estructura de archivos
print("\n3. Archivos del proyecto")
esperados = [
    "main.py", "db.py", "extractor.py", "validador.py", "requirements.txt",
    "data/seed_aefip.json",
    "templates/trabajador.html", "templates/admin.html",
    "static/logo_mitrabajo.svg", "static/logo_sindicato.svg",
]
faltan = [f for f in esperados if not Path(f).exists()]
if not faltan:
    ok(f"Los {len(esperados)} archivos necesarios están presentes")
else:
    error(f"Faltan archivos: {', '.join(faltan)}",
          "Verificá que descomprimiste el ZIP completo y que estás parado en la carpeta validador-demo")

# 4. Librerías instaladas
print("\n4. Librerías de Python")
librerias = {
    "fastapi": "fastapi", "uvicorn": "uvicorn", "jinja2": "jinja2",
    "anthropic": "anthropic", "multipart": "python-multipart",
    "pdf2image": "pdf2image", "dotenv": "python-dotenv", "sqlmodel": "sqlmodel",
}
faltantes = []
for modulo, paquete in librerias.items():
    try:
        __import__(modulo)
    except ImportError:
        faltantes.append(paquete)
if not faltantes:
    ok("Todas las librerías están instaladas")
else:
    error(f"Faltan librerías: {', '.join(faltantes)}",
          "Ejecutá: pip install -r requirements.txt")

# 5. Datos de referencia
print("\n5. Datos de referencia (conceptos y fórmulas)")
try:
    seed = json.loads(Path("data/seed_aefip.json").read_text(encoding="utf-8"))
    n_con = len(seed.get("conceptos", []))
    n_for = len(seed.get("formulas", []))
    if n_con and n_for:
        ok(f"{n_con} conceptos y {n_for} fórmulas cargados")
    else:
        error("El archivo de datos está vacío o incompleto",
              "Volvé a copiar data/seed_aefip.json del ZIP original")
except FileNotFoundError:
    error("No se encuentra data/seed_aefip.json", "Copialo del ZIP original")
except json.JSONDecodeError as e:
    error(f"data/seed_aefip.json tiene un error de formato JSON (línea {e.lineno})",
          "Si lo editaste a mano, revisá comas y comillas; o volvé a copiarlo del ZIP")

# 6. Motor de validación (prueba real, sin API)
print("\n6. Motor de validación")
try:
    from validador import validar
    recibo_prueba = {
        "empleado": {"cuil": "20000000001"},
        "periodo": "2024-09",
        "lineas": [
            {"codigo": "1-026", "descripcion": "SUELDO BASICO GRUPO 26", "importe": 100000.0},
            {"codigo": "20-024", "descripcion": "REFRIGERIO", "importe": 20000.0},
            {"codigo": "42-001", "descripcion": "AP. PERS. JUB. ANSES", "importe": -11000.0},
            {"codigo": "288-001", "descripcion": "A.E.F.I.P. CTA. AFILIACION", "importe": -1500.0},
        ],
        "totales_impresos": None,
    }
    seed = json.loads(Path("data/seed_aefip.json").read_text(encoding="utf-8"))
    r = validar(seed["conceptos"], seed["formulas"], recibo_prueba)
    # Base remunerativa esperada = 100000 (el refrigerio no cuenta).
    # Jubilación 11% = 11000 y cuota sindical 1.5% = 1500 → ambas deben dar OK.
    jub = next((f for f in r["formulas_validadas"] if f["codigo"] == "42-001"), None)
    sind = next((f for f in r["formulas_validadas"] if f["codigo"] == "288-001"), None)
    if jub and sind and jub["ok"] and sind["ok"]:
        ok("El motor calcula correctamente (probado con un recibo de ejemplo)")
    else:
        error("El motor no calculó lo esperado en la prueba",
              "Volvé a copiar validador.py y data/seed_aefip.json del ZIP original")
except Exception as e:
    error(f"El motor de validación falló: {e}",
          "Volvé a copiar validador.py del ZIP original")

# 7. API key
print("\n7. Clave de la API de Anthropic")
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
clave = os.getenv("ANTHROPIC_API_KEY", "")
if not clave:
    error("No se encontró la clave ANTHROPIC_API_KEY",
          "Creá el archivo .env con la línea: ANTHROPIC_API_KEY=tu-clave")
elif clave.startswith("pega-tu") or clave == "tu-api-key-aca":
    error("La clave sigue siendo el texto de ejemplo",
          "Editá .env y reemplazalo por tu clave real de console.anthropic.com")
elif not clave.startswith("sk-ant-"):
    aviso("La clave no tiene el formato habitual (suele empezar con sk-ant-)")
    print("        → Verificá que la copiaste completa, sin espacios")
else:
    ok(f"Clave configurada (termina en …{clave[-4:]})")

# 8. Poppler (solo si se van a usar PDFs)
print("\n8. Poppler (necesario solo para leer PDFs)")
import shutil
if shutil.which("pdftoppm"):
    ok("Poppler está instalado: vas a poder procesar PDFs")
else:
    aviso("Poppler no está instalado: solo vas a poder usar fotos (JPG/PNG)")
    print("        → Para la demo con fotos está bien. Si querés PDFs:")
    print("          Mac: brew install poppler | Ubuntu: sudo apt install poppler-utils")

# 9. Llamada real a la API (opcional)
if "--api" in sys.argv:
    print("\n9. Conexión con la API de Anthropic (consume créditos)")
    try:
        from anthropic import Anthropic
        cliente = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        resp = cliente.messages.create(
            model="claude-sonnet-4-6", max_tokens=10,
            messages=[{"role": "user", "content": "Respondé solo: ok"}],
        )
        ok("La API responde correctamente")
    except Exception as e:
        error(f"No se pudo conectar con la API: {type(e).__name__}",
              "Verificá la clave en .env, tu conexión a internet y que tengas créditos disponibles")
else:
    print("\n9. Conexión con la API (omitida)")
    print("        → Para probarla: python chequeo.py --api")

# Resumen
print("\n" + "=" * 45)
if fallos == 0:
    print(f"{VERDE}Todo listo.{FIN} Arrancá con:  uvicorn main:app --reload")
else:
    print(f"{ROJO}{fallos} problema(s) para resolver.{FIN} Revisá los errores de arriba.")
print()
sys.exit(1 if fallos else 0)
