# FLUJO.md — Cómo se desarrolla y cómo se despliega

Una página. El detalle de la infraestructura está en
[`DESPLIEGUE_RENDER.md`](DESPLIEGUE_RENDER.md) y el porqué del modelo en
[`PLAN_ENTORNOS.md`](PLAN_ENTORNOS.md). Acá está solo el ciclo de vida de un
cambio: dónde nace, dónde se ve primero, y cómo llega a la demo.

## Los tres lugares

| Dónde | Qué corre | Quién lo ve | Cómo cambia |
|-------|-----------|-------------|-------------|
| **Tu PC** | tu rama, tu Postgres de Docker | vos | cada vez que guardás |
| **Pruebas** — mitrabajo-pruebas.onrender.com | la rama `main` | el equipo | **solo** con un push a `main` |
| **Demo** — mitrabajo.onrender.com | la rama `demo` | sindicatos e inversor | **solo** corriendo `promover_demo.py` |

Cada uno tiene su propia base de datos. Nada de lo que hagas en Pruebas
puede tocar la demo.

Para no equivocarse de entorno: **mitrabajo-pruebas.onrender.com/entornos**
lista los 8 logins (Trabajador, Sindicato, Empresa y Plataforma, en Pruebas
y en Demo) con la versión que corre en cada uno. Solo existe en Pruebas.
Debajo, **Recursos**: la documentación del proyecto (planes, guías,
videos, enlaces) en un solo lugar, con miniatura y fecha; se sube desde ahí
mismo con la clave de plataforma. Un documento que tiene que viajar con el
código (como los planes de implementación) va versionado en `recursos/` y
se declara en `recursos.SEMILLA`; el resto se sube desde la landing.

## El ciclo de una feature

**1. Programás en tu PC, en una rama.**

```bash
git checkout -b mi-feature
docker compose up -d
alembic upgrade head
uvicorn main:app --reload
```

**2. Probás en tu PC.** Los tests, uno por archivo (nunca `pytest -q`
batcheado: los módulos comparten estado de import y se contaminan):

```bash
for f in test_*.py; do .venv/Scripts/python.exe -m pytest "$f" -q || break; done
```

Si tocaste un modelo de `db.py`, la migración va en el mismo commit:

```bash
alembic revision --autogenerate -m "que cambia"
alembic upgrade head
```

**3. La mergeás a `main` y se va sola a Pruebas.**

```bash
git checkout main && git merge mi-feature && git push origin main
```

Render redeploya `mitrabajo-pruebas` en 1–2 minutos. El Pre-Deploy corre
`alembic upgrade head` solo: no hay que entrar a la Shell a migrar nada.
**La demo no se entera.**

**4. Lo mirás corriendo en Pruebas.** Esta es la única prueba que vale antes
de la demo: código real, Postgres real, migración aplicada de verdad. Se
reconoce por el distintivo ámbar abajo a la izquierda (`pruebas · vX.Y.Z`).

**5. Cuando Sd lo aprueba, se promueve a la demo.**

```bash
python promover_demo.py
```

Hace backup de la base de demo, mergea `main` en `demo`, crea el tag
`demo-AAAA-MM-DD-vX.Y.Z` y pushea. Render redeploya la demo. Con
`--solo-pr` no mergea: imprime el link del Pull Request para que Sd apruebe
(el flujo desde que haya reglas de rama).

## Las tres reglas que no se rompen

1. **Sobre `demo` no se programa nunca.** Solo recibe merges de `main`. Un
   arreglo urgente para la demo se hace en una rama desde `demo`, se mergea
   a `demo`, y enseguida `demo → main` para que no se pierda.
2. **`main` siempre va adelante de `demo`.** Así, cuando algo se promueve,
   sus migraciones ya corrieron en Pruebas y no estrenan en la demo.
3. **La versión se sube sola en el mismo commit** (`version.py`): solo
   arreglos, +1 al patch; con funcionalidad nueva, +1 al minor y el patch
   vuelve a `01` (así fue `0.27.04 -> 0.28.01`). Sube **solo la app que se
   tocó**: un cambio en la pestaña Credencial mueve `VERSION_TRABAJADOR` y
   deja Admin y Plataforma como estaban. `FECHA_VERSION` va con la fecha del
   commit. Lo decide Sd solo cuando hay duda de si el cambio cuenta como
   funcionalidad nueva.

## Cuando algo sale mal

- **Se rompió la demo**: Render → Deploys → el deploy anterior → *Rollback*.
  Es inmediato y no necesita código.
- **Se rompió Pruebas**: no es urgente, es para eso. Arreglás y pusheás a
  `main` otra vez.
- **Los datos de Pruebas quedaron sucios**: se regeneran con los scripts de
  lote, no se restauran desde demo. Ver "Regenerar los datos de Pruebas" en
  `DESPLIEGUE_RENDER.md`. Por excepción, cuando la demo tiene datos que los
  scripts no reproducen, `python clonar_demo_a_pruebas.py` la clona entera
  (solo en esa dirección, nunca al revés).
- **Un entorno nuevo aparece sin el logo de Colm3na**: falta correr
  `python cargar_marca_plataforma.py`. La marca vive en la base, no en el
  código.
