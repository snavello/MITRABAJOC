# XSD, XSANDERS Design Kit: el método

XSD revisa el diseño de una aplicación entera, pantalla por pantalla, y
devuelve un **informe interactivo**: la persona responsable decide cada
mejora con un clic. Con esas decisiones se arma un plan, se aplica con
agentes en paralelo y se vuelve a revisar lo tocado.

Se usó por primera vez en Colm3na el 2026-10-24/25: 61 pantallas, 8
revisores, 228 hallazgos y 144 decisiones en la primera vuelta; 4 revisores
y 42 hallazgos nuevos en la segunda; todo aplicado en cinco PR. La versión
para leer está en el Docs «Método de auditoría de diseño con revisores»
(https://claude.ai/artifact/V2phdzEfFUjZ6cQn2qHYXj). Este archivo es la
referencia para Code.

**Sirve** para llevar a un mismo nivel muchas pantallas hechas en momentos
distintos, para revisar antes de mostrar el producto, para verificar qué
quedó sin migrar después de cambiar el sistema de diseño, y para repetir la
revisión con el mismo criterio cada cierto tiempo. **No sirve** para
pantallas que todavía no existen: para eso se diseña primero (mockups) y se
audita después.

## Las piezas

| Pieza | Dónde | Qué es |
|---|---|---|
| Ficha del proyecto | `xsd/proyectos/<p>/ficha.json` | Lo único que cambia de un proyecto a otro: cómo se levanta, cómo se entra, qué variantes y vistas, qué leer. Plantilla en `plantillas/ficha.json`. |
| Inventario | `xsd/proyectos/<p>/pantallas.json` | Una entrada por pantalla: `id`, `app`, `nombre`, `url`, `rol`, `temas` (si tiene variantes), `js` (cómo llegar a una sub-pestaña sin ruta), `espera` (ms). |
| Contexto | `xsd/proyectos/<p>/contexto.md` | Qué es la app, qué NO es diseño en las capturas, decisiones que no se proponen deshacer. Va adentro del encargo. |
| Sesiones | lo que diga `sesiones.comando` | Imprime `{rol: {cookie: valor}}` recién firmadas, para una `variante` y un `quien`. Es el único código propio del proyecto. |
| Herramientas | `xsd/herramientas/` | `xsd.py` (capturar, hoja, brief, informe, decisiones, previos, encargos, avance) y `capturar.cjs`. |
| Encargos | `xsd/plantillas/` | Revisor, segunda vuelta y equipo que aplica. |
| Informe | `xsd/informe/index.html` | La página, sin librerías; los datos van en `datos.json`. |
| Avance | `xsd/mod/avance-agentes/` | Mod de Claude Code: una ventana con el plan y lo que hace cada agente. |
| Historial | `xsd/proyectos/<p>/historial.md` y `vueltaN-consolidado.json` | Qué se revisó, qué se decidió y dónde está el informe. Es lo que necesita la vuelta siguiente. |

Los archivos de trabajo (capturas, hallazgos, informe, decisiones) van en
`<trabajo>/<corrida>/` (la ficha dice dónde; `xsd-trabajo/` no se versiona).

## Fase 0: la ficha (solo la primera vez en un proyecto)

1. Leer cómo se levanta la app (README, docker-compose, scripts) y cómo se
   autentica cada rol.
2. **Inventario**: las rutas que devuelven HTML (en FastAPI, las
   `response_class=HTMLResponse`; en otros marcos, el router), las pestañas
   y sub-pestañas dentro de cada página (sus `data-*` o funciones de
   cambio) y los ingresos sin sesión. Lo interno o técnico queda afuera, y
   el informe lo dice.
3. **Sesiones**: escribir el script del proyecto. Reglas:
   - firma sesiones nuevas cada vez, porque vencen;
   - cada `quien` usa SU usuario de cada rol, porque si la variante elegida
     vive en la cuenta, dos agentes con la misma cuenta se pisan;
   - crea lo que falte solo en la base local.
4. **Contexto**: qué es la app en cinco líneas, qué no es diseño (distintivos
   de entorno, datos de prueba raros conocidos), decisiones tomadas.
5. Preguntar a la persona **solo** lo que no se puede deducir, de a una
   pregunta.

## Fase 1: capturas

```
python xsd/herramientas/xsd.py capturar --ficha F --corrida AAAA-MM-DD-v1
python xsd/herramientas/xsd.py hoja     --ficha F --corrida AAAA-MM-DD-v1
```

- Con la app levantada y datos de prueba **creíbles**: una pantalla vacía no
  se puede revisar.
- `capturar` genera sesiones nuevas para cada variante y saca escritorio y
  teléfono, página entera con tope.
- **Mirar la hoja de contacto antes de seguir.** En Colm3na, la primera
  tanda salió con todas las pestañas iguales (solo cambiaba el `#`) y con
  sesiones vencidas. La hoja lo mostró en un vistazo.

## Fase 2: revisores en paralelo

1. **Armar `grupos.json`** en la corrida: grupos de 5 a 10 pantallas, por
   app y por tema, para que el revisor vea juntas las que deberían parecerse.
   Unas 20 a 40 capturas por grupo (pantallas × variantes × vistas): con más,
   el revisor mira por encima.

   ```json
   {"G1": {"titulo": "Ingresos y empresa", "pantallas": ["pub-inicio", "emp-portada"]}}
   ```
2. `xsd.py brief` renderiza el encargo con la ficha y el contexto. Revisá
   que no quede nada entre `<…>`.
3. **Un agente por grupo, en paralelo**, cada uno con un mensaje corto: su
   grupo, sus pantallas, la ruta del brief y la de salida. El revisor no toca
   ningún archivo y la evidencia es la captura.
4. Cada revisor deja `hallazgos/<grupo>.json`, en el formato del brief.

## Fase 3: informe y decisiones

```
python xsd/herramientas/xsd.py informe --ficha F --corrida C
```

- **Publicarlo con la herramienta Artifact**:
  - `file_path` = `<corrida>/informe/index.html`;
  - `root` = `<corrida>/informe`;
  - `files` = el contenido de `informe/archivos.json` (hasta 255 archivos y
    64 MB por publicación);
  - `capabilities` = `{"db": {}, "user": {}}`;
  - `icon` = `checklist`.
- Verificar el guardado con un `ArtifactData list` de la colección
  `decisiones`: tiene que responder, aunque sea vacía.
- **Darle el link a la persona.** Ella decide de a partes: Aceptar, Dejar
  como está o Sugerir otro cambio.
- Si el informe no se puede publicar, se abre el HTML local. Las decisiones
  quedan en el navegador y la página ofrece copiarlas para pegarlas en la
  conversación.
- Cuando la persona avisa que terminó, bajar las decisiones y juntarlas con
  los hallazgos:

  ```
  ArtifactData list  url=<informe>  collection=decisiones  out_dir=<corrida>/decisiones
  python xsd/herramientas/xsd.py decisiones --ficha F --corrida C --desde <corrida>/decisiones
  ```

  Eso deja `consolidado.json`, y las notas de «cambio» salen impresas.

## Fase 4: plan y aplicación

El plan sale de las decisiones, no de los hallazgos: lo que quedó «dejar» no
entra, y «cambio» reemplaza la sugerencia por lo que escribió la persona.

1. **Separar las notas que cambian el alcance de las que ajustan un
   hallazgo.** Ejemplos de alcance: «esta pantalla quedó vieja», «este panel
   se reemplaza».
2. **Agrupar por causa y por archivo, no por pantalla.** Un componente
   compartido arreglado una vez cierra decenas de hallazgos a la vez.
3. **Ordenar**:
   - primero lo que cambia la base (migrar una pantalla, reemplazar una
     versión);
   - después, los componentes compartidos;
   - por último, lo puntual.

   Pulir una pantalla que después se migra es trabajo doble.
4. **Presentar el plan en unas diez líneas y esperar el visto bueno.**
5. **Ejecutar por bloques.**
   - **Lo compartido**: lo hace la sesión principal.
   - **Lo independiente**: lo hacen agentes en paralelo, cada uno en su
     worktree.
     - Escribir `aplicar.json` (qué prefijos o ids van a cada agente) y
       correr `xsd.py encargos`.
     - Cada agente recibe `plantillas/brief_equipo.md` completado, con sus
       archivos, su puerto y su `quien`.
     - Los archivos que tocan dos agentes a la vez se reparten por zonas, con
       bloques marcados al final de las hojas.
   - **Al terminar cada uno**, la sesión principal integra:
     - merge de la rama;
     - las migraciones encadenadas en una sola línea;
     - tests del área;
     - la versión, la bitácora y un PR por bloque o por tanda.
6. **Ventana de avance**: `xsd.py avance --bloque b1=en_curso:Nombre|detalle`
   la mantiene al día. El mod `avance-agentes` la muestra si está cargado
   (ver `LEEME.md`).

## Fase 5: segunda vuelta

1. Volver a capturar **lo tocado o migrado**, con `--solo` o con todo.
2. Armar `grupos.json` de esta vuelta (prefijo `R`) y
   `xsd.py previos --consolidado <consolidado de la vuelta anterior>`. Eso le
   da a cada revisor lo que se pidió antes, con la decisión.
3. `xsd.py brief --vuelta 2` y completar «Qué cambió desde la primera
   vuelta».
4. Lanzar los revisores. Verifican lo anterior (resuelto / sigue / parcial /
   ya no aplica) y suman lo nuevo.
5. `xsd.py informe --vuelta 2`: cada pantalla muestra arriba la verificación
   y abajo lo nuevo. Publicar como un **artifact nuevo**, así las decisiones
   no se mezclan.
6. Con las decisiones, la tanda 2. Los «parciales» entran en los encargos
   (`aplicar.json` → `parciales`).

## Al cerrar cada vuelta

- Copiar `consolidado.json` a `xsd/proyectos/<p>/vueltaN-consolidado.json`.
- Agregar una línea a `xsd/proyectos/<p>/historial.md`: fecha, alcance,
  resultado y link del informe.
- Seguir las reglas de cierre del proyecto (bitácora, historial, versión).

## Lecciones (Colm3na, 2026-10-24/25)

- **Revisar la hoja de contacto antes de largar los revisores.**
- **Datos de prueba creíbles y avisados en el contexto.** Tres revisores
  marcaron un logo de otro gremio: era un dato local.
- **Navegador en el idioma de la app**, porque si no aparecen hallazgos
  falsos. `capturar.cjs` usa el `locale` de la ficha.
- **Las decisiones tomadas van en el encargo.** Sin esa lista, los revisores
  proponen deshacerlas.
- **Lo que solo se ve en el código va «para confirmar».**
- **Un elemento fijo se ve cortado en la captura entera**, y no es un
  hallazgo: hay que decirlo en el encargo.
- **Lo que más rindió fue detectar pantallas sin migrar.** Las notas de la
  persona («formato viejo») hicieron que el primer bloque fuera migrar, no
  pulir.
- **Un usuario de prueba por agente**, generado por `quien`, porque la
  variante elegida vive en la cuenta y dos agentes se pisaban las capturas.
- **Un puerto por agente, y nunca `pkill`**: un agente bajó el servidor de
  otro.
- **Los agentes que tocan el mismo archivo se reparten por zonas**, con
  bloques marcados al final de las hojas. Al integrar, los conflictos de
  «los dos agregaron al final» se resuelven quedándose con los dos.
- **Las migraciones de agentes paralelos nacen con el mismo
  `down_revision`.** Al integrar se encadenan en una línea, y en la base
  local compartida se hace `stamp` de las columnas que los agentes agregaron
  a mano.
- **Un test que lee «desde mi bloque hasta el final de la hoja» se rompe al
  integrar.** Que lea hasta el bloque siguiente.
