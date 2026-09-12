# Robots E2E (Playwright)

Pruebas de punta a punta contra la app REAL: servidor corriendo, Postgres de
Docker, el JavaScript del frontend ejecutándose y sesiones de verdad. Es lo
más cercano a una persona usando la aplicación.

Viven acá y no en la raíz a propósito: la suite unitaria (`test_*.py`) corre
contra una base Postgres descartable que arma conftest.py; estos, además,
necesitan la app levantada.

## Antes de correrlos

```
docker compose up -d
uvicorn main:app --reload
python cargar_lote_sindicato.py --sindicato "AEFIP"   # una sola vez
```

Instalación (una vez por máquina): `pip install -r requirements-dev.txt` y
`playwright install chromium`.

## Cómo correrlos

| Objetivo | Comando |
|---|---|
| Todos, rápido y sin ventana | `.venv/Scripts/python.exe -m pytest e2e/ -q` |
| **Verlo en vivo** (abre el navegador) | `.venv/Scripts/python.exe -m pytest e2e/ --headed --slowmo 700` |
| **Grabarlo** (video + traza por actor) | `.venv/Scripts/python.exe -m pytest e2e/ --video on --tracing on --output e2e/resultados` |
| Solo un robot | agregar `e2e/test_robot_tramite_guarderia.py` |
| Grabar solo lo que falla | `--video retain-on-failure --screenshot only-on-failure` |

En vivo, cada actor ocupa media pantalla y su ventana queda fijada SIEMPRE
ENCIMA: Windows no permite que un proceso le robe el primer plano a otro, así
que `page.bring_to_front()` solo no alcanza y el robot corría invisible (ver
`e2e/ventanas.py`).

Los artefactos quedan en `e2e/resultados/` (ignorada por git: pesan MB por
corrida y se regeneran solos).

## El informe final

Cada corrida termina con un resumen en la terminal (resultado, los pasos que
dio cada robot y los datos que dejó en la app, ej. el número de expediente) y
genera `e2e/resultados/informe.html` con lo mismo en formato ficha, más los
enlaces a los videos y trazas. Con `--headed` la ficha se abre sola al final.

Un robot cuenta lo que hace con la fixture `informe`:

```python
def test_algo(page, informe):
    informe.paso("El trabajador entró a su app")        # un hito del guion
    informe.dato("Expediente generado", numero)          # algo verificable
```

Si no la usa, igual aparece en el informe con su resultado y duración; los
pasos son lo que lo hace legible para alguien que no leyó el código.

### Ver una traza (lo más útil para depurar)

```
.venv/Scripts/python.exe -m playwright show-trace e2e/resultados/<test>-<actor>-trace.zip
```

Abre el visor de Playwright: línea de tiempo paso a paso, captura de pantalla
en cada acción, el DOM navegable en cada instante, y las llamadas de red. Con
eso se ve exactamente en qué punto se rompió algo, sin volver a correr nada.

## Los robots

- `test_humo_dashboard.py` — smoke: el admin abre el Panel Sindical con datos
  vivos y el modal "Ver"; un trabajador del lote entra a su app.
- `test_robot_tramite_guarderia.py` — ciclo completo de un trámite con dos
  actores: el trabajador lo presenta, el admin responde y lo cierra, el
  trabajador ve la respuesta.

## Al escribir uno nuevo

- Pedir las páginas con la fixture `nuevo_actor("nombre")` (en `conftest.py`),
  nunca `browser.new_context()` a mano: esa fixture es la que aplica la
  grabación de video/traza a cada actor.
- Los prerequisitos de datos van en `entorno_aefip` (o una fixture nueva),
  siempre idempotentes y con `pytest.skip` explicando cómo prepararlos —
  nunca fallar críptico porque falta el lote.
- Usar `expect(...)` en vez de `sleep`: reintenta solo hasta que la condición
  se cumpla.
