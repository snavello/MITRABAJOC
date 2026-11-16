# Convenio y escalas — pedido para Code
Fecha: 2026-11-15 · Herramienta: Chat · Origen: proyecto «Mitrabajo», chat «Convenio y escalas»
Estado: acordado
Quién: SDN

## Dónde va cada archivo

| Archivo | Destino en el repo |
|---|---|
| `PLAN_CONVENIO_ESCALAS.md` | raíz |
| `2026-11-15-convenio-escalas-maquetas.html` | `docs/chat/` |
| `2026-11-15-convenio-escalas-prompt.md` (este) | `docs/chat/` |

## Línea para BITACORA.md

```
| 2026-11-15 | Chat | Herramientas | Plan y maquetas de «Convenio y escalas» (consulta de escala vigente, convenio en fichas y actualización automática de la grilla), como Herramienta de /entornos | PLAN_CONVENIO_ESCALAS.md; docs/chat/2026-11-15-convenio-escalas-maquetas.html | SDN |
```

## Pedido (copiar y pegar en Code)

```
Vamos a construir «Convenio y escalas» como Herramienta de /entornos →
Herramientas. Todo lo acordado está en PLAN_CONVENIO_ESCALAS.md (raíz) y la
referencia visual en docs/chat/2026-11-15-convenio-escalas-maquetas.html.
Leé los dos enteros antes de hacer nada.

Tu rol es planificar y coordinar. El desarrollo y el QA los hacen agentes
Sonnet 5.5 bajo tu coordinación, en paralelo donde el plan lo permite, y quien
hace QA de un bloque no es quien lo desarrolló. Seguí «Método de trabajo» de
CLAUDE.md sin excepciones: reportes cortos y no narración, cada error
clasificado por origen (la app, los datos o la configuración) antes de tocar
código, la suite completa la corre el CI, y cerrás cada bloque con bitácora.

Orden obligatorio:

1. Bloque 0, sin escribir código: leé los archivos que lista el plan y
   presentame las brechas entre el plan y el repo. Si algo del plan contradice
   al código o a una regla de CLAUDE.md, decímelo: no lo resuelvas solo.
2. Resolvé los «Abiertos» del plan preguntándome de a UNA pregunta, con
   opciones cerradas y tu recomendación. Cada respuesta queda como decisión
   numerada en el plan.
3. Esperá mi visto bueno. Recién entonces arrancan los bloques 1 a 8.

Reglas que no se negocian (el detalle está en D1 a D12):

- Preguntá antes de decidir cualquier ambigüedad.
- No se toca /app, Tu recibo, /app/convenio, rag.py ni el resultado de la
  Calculadora bancaria. grilla_bancaria.py sigue puro.
- Es una consulta, no un control: ningún total, ninguna suma, ninguna palabra
  de control. Hay un test que lo exige.
- Toda cifra lleva su etiqueta: Publicado o Referencia.
- Una grilla se publica sola solo si pasa TODOS los controles. Ante la duda,
  queda retenida y avisa. Nunca se inventa ni se completa un importe.
- Diseño: los dos modelos (laguna y noticiero) y las dos paletas, con el skill
  diseno-mi-trabajo y revisión con XSD. La maqueta marca contenido y
  jerarquía; los colores y medidas salen de las variables del modelo.
- Sin librerías nuevas y sin servicios nuevos en Render.
- El proceso diario se prende por variable de entorno y solo en Pruebas. No
  se promueve nada a Demo en este plan.

El bloque 6 es la prueba de verdad: leé agosto de 2026 con el propio proceso
y comparala celda por celda con la transcripta a mano; después cargá
septiembre de punta a punta. Mostrame el resultado control por control. Si una
grilla queda retenida, reportá el motivo antes de corregir nada.

Al terminar cada bloque: qué se hizo, qué quedó listo, qué queda pendiente.
```
