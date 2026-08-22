# SPRINT — Adaptación a la Reforma Laboral (Decreto 407/2026)

Especificación de trabajo para Claude Code. Se implementa por bloques, verificando
cada punto antes de avanzar. Marco normativo: Ley 27.802 (Modernización Laboral) +
Decreto 407/2026, que reglamenta el art. 140 LCT y aprueba un modelo único de recibo
(Anexo III), vigente desde el 1/6/2026.

## Contexto normativo (lo que hay que saber para implementar)

El nuevo recibo tiene CUATRO secciones obligatorias + un gráfico de torta al frente:
1. Datos identificatorios de empleador y trabajador.
2. **Contribuciones patronales y costo laboral total** (NOVEDAD). Lo que paga el
   empleador POR FUERA del neto: seguridad social, obra social, PAMI/INSSJP, ART,
   seguro de vida, cuota/aportes sindicales patronales, cámaras empresariales.
3. Remuneración bruta y deducciones (aportes DEL trabajador).
4. Remuneración neta.

DISTINCIÓN CRÍTICA que la app debe respetar:
- **Aportes del trabajador** (se descuentan del bruto): jubilación 11%, obra social
  3%, PAMI 3%, cuota sindical según convenio. Reducen el neto.
- **Contribuciones patronales** (las paga el empleador, NO se descuentan al
  trabajador): seguridad social, obra social, PAMI, ART, seguro de vida, sindical
  patronal, cámaras. NO afectan el neto del trabajador.
Confundir una contribución patronal con un aporte del trabajador produce falsos
errores de validación. Es el riesgo #1 de este sprint.

Otros datos relevantes del recibo (subsiste obligación del Dto-Ley 17.250/67):
fecha del último depósito de aportes y contribuciones, período y banco.

Tope sindical (art. 133 Ley 27.802 + Dto 407/2026): las cargas económicas de
convenio a favor de asociaciones de trabajadores (cuotas solidarias, fondos) tienen
un límite GLOBAL del 2% de las remuneraciones. Excluidas: la cuota de afiliación
sindical y beneficios exclusivos para afiliados. El tope se computa global, no puede
eludirse fragmentando conceptos.

---

# SPRINT A — Motor de lectura y validación (puntos 1, 2, 3)

Toca la cadena extractor -> validador -> semáforo. Sin decisiones de producto
pendientes. Se prueba en conjunto con FastAPI TestClient.

## Punto 1 — Extractor bi-formato (recibo clásico + recibo nuevo)
Archivo principal: extractor.py

Qué hacer:
- El extractor debe reconocer AMBOS formatos (clásico y Anexo III), porque van a
  convivir mientras las empresas se adaptan.
- Ampliar el esquema JSON de salida agregando, sin romper lo existente:
  - `formato`: "clasico" | "nuevo" (que la IA determine cuál es).
  - `contribuciones_patronales`: lista de {concepto, base, porcentaje, importe} —
    vacía en formato clásico.
  - `costo_laboral_total`: número o null.
  - `ultimo_deposito`: {fecha, periodo, banco} o null (dato del Dto-Ley 17.250/67).
  - En cada línea de `lineas[]`, agregar `tipo`: "remuneracion" | "aporte_trabajador"
    | "otro". Esto separa lo que reduce el neto de lo que no.
- Actualizar el prompt del sistema para explicar la distinción aporte vs
  contribución y las cuatro secciones del formato nuevo.

Criterios de aceptación:
- Un recibo clásico se sigue leyendo igual que antes (no regresión): `formato`=
  "clasico", `contribuciones_patronales`=[], el resto idéntico a hoy.
- Un recibo nuevo devuelve `formato`="nuevo" y puebla `contribuciones_patronales`.
- Ninguna contribución patronal aparece como `aporte_trabajador` en `lineas`.
- El JSON sigue siendo parseable y no rompe validador.py ni el preview.

## Punto 2 — Regla del tope sindical 2% en el validador
Archivos: validador.py (regla) + db.py (parámetro configurable) + panel plataforma.

Qué hacer:
- Agregar una validación que sume las cargas sindicales de convenio del recibo
  (cuota solidaria, fondos convencionales; EXCLUIR cuota de afiliación) y verifique
  que no superen el tope.
- El tope es un parámetro de PLATAFORMA (no por sindicato), default 2.0 (%),
  editable solo por el admin de plataforma. Al editarlo, mostrar una advertencia
  legal: es un límite de ley nacional; cambiarlo es bajo responsabilidad del
  operador. Guardar el valor en una tabla de configuración de plataforma.
- Si un recibo supera el tope: generar una alerta en el reporte (no un "error" de
  cálculo, sino una advertencia de posible retención en exceso), visible tanto para
  el trabajador como para el sindicato.

Criterios de aceptación:
- Con tope 2%, un recibo cuya suma de cargas sindicales de convenio dé 2.5% dispara
  la alerta; uno con 1.5% no.
- La cuota de afiliación NO se cuenta para el tope.
- El admin de plataforma puede cambiar el valor y ve la advertencia legal.
- El admin de sindicato NO puede cambiar este valor.

## Punto 3 — Fecha de último depósito -> alerta temprana en el semáforo
Archivos: extractor.py (ya extrae `ultimo_deposito` en punto 1) + semaforo.py.

Qué hacer:
- Usar `ultimo_deposito.fecha` como señal temprana: si el último depósito declarado
  en el recibo es de varios meses atrás respecto al período del recibo, marcar una
  advertencia en el semáforo ("el recibo declara último depósito en MM/AAAA").
- Es COMPLEMENTARIO a ARCA, no lo reemplaza. Si hay datos de ARCA, ARCA manda; esto
  es una señal adicional cuando el trabajador todavía no subió el comprobante de ARCA.

Criterios de aceptación:
- Un recibo con último depósito reciente no dispara advertencia.
- Un recibo con último depósito de hace 3+ meses la dispara.
- Con datos de ARCA presentes, el semáforo sigue priorizando ARCA.

---

# SPRINT B — Trabajador y sindicato (puntos 4, 5)

M�s de producto y UI. Depende de decisiones ya tomadas (ver abajo).

## Punto 4 — Capacitación: "Entendé tu nuevo recibo de sueldo"
Archivo: templates/trabajador.html (pestaña Capacitación) + datos de contenido.

Qué hacer:
- Reemplazar el "próximamente" de Capacitación por contenido REAL, fijo de
  plataforma (igual para todos los sindicatos; es ley nacional).
- Contenido: guía breve del nuevo recibo — las 4 secciones, qué se te descuenta
  (aportes) vs qué paga el empleador (contribuciones), qué es el costo laboral, qué
  mirar para detectar problemas (neto = bruto - aportes; contribuciones no bajan tu
  neto). Tono claro para trabajador, no técnico.
- Estructura preparada para que MÁS ADELANTE cada sindicato agregue su propio
  contenido, pero por ahora SOLO el ejemplo fijo de plataforma.

Criterios de aceptación:
- La pestaña Capacitación muestra la guía, ya no "próximamente".
- El contenido es el mismo para UOM y Gastronómica (es de plataforma).

## Punto 5 — Preview con formato nuevo + envío consentido al sindicato
Archivos: preview previo al reporte (main.py + template) + flujo de envío.

Qué hacer (parte A — preview):
- Cuando `formato`="nuevo", el preview previo al reporte debe mostrar las cuatro
  secciones, incluidas las contribuciones patronales y el costo laboral total, para
  que el trabajador reconozca su recibo. Cuando es "clasico", el preview queda como
  hoy.

Qué hacer (parte B — envío al sindicato, acreditación de afiliado cotizante):
- El envío de datos del recibo al sindicato es una acción VOLUNTARIA y explícita del
  trabajador (botón "enviar a mi sindicato" o equivalente).
- Junto al botón de envío, mostrar un DISCLAIMER CORTO: que al enviar, comparte con
  su sindicato los datos de su recibo (incluida la retención de cuota sindical), que
  el sindicato puede usarlos para acreditar afiliación cotizante ante la autoridad
  (art. 21 bis, Dto 407/2026). El acto de enviar = consentimiento en contexto. NO se
  anonimiza (el dato identificado es lo que da valor a la acreditación).
- En el panel del sindicato, un reporte simple: qué afiliados enviaron recibos con
  retención de cuota a favor del sindicato, por período. Es la base para acreditar
  afiliados cotizantes.

Criterios de aceptación:
- Recibo nuevo: el preview muestra contribuciones patronales y costo laboral.
- Recibo clásico: preview sin cambios.
- El envío al sindicato solo ocurre tras acción explícita del trabajador, con el
  disclaimer visible.
- El sindicato ve el listado de envíos con retención de cuota por período.

---

# Decisiones ya tomadas (no rediscutir)
- Punto 6 (cruce declarado vs ingresado de contribuciones) NO se hace ahora: falta
  la fuente de datos del lado del sindicato.
- Consentimiento del punto 5: implícito por ser el envío voluntario y explícito;
  alcanza un disclaimer corto en cada envío. No hay pantalla de términos aparte, no
  se intercepta a usuarios existentes con un modal.
- Tope 2% (punto 2): default 2.0, configurable SOLO por plataforma, con advertencia
  legal. Es ley nacional, no convenio.
- Capacitación (punto 4): arranca con contenido fijo de plataforma; lo por-sindicato
  queda para después.
- Las reglas normativas nuevas se guardan CONFIGURABLES (no hardcodeadas), porque la
  reglamentación puede judicializarse o cambiar (la CGT ya la rechazó).

# Método
- Implementar punto por punto, en el orden A1 -> A2 -> A3 -> B4 -> B5.
- Después de cada punto: verificar con FastAPI TestClient (o lógica en Python si el
  server de prueba se reinicia), y hacer un commit con mensaje claro.
- No avanzar al siguiente punto sin que el anterior pase sus criterios de aceptación.
- Preferir cambios quirúrgicos; no reescribir módulos enteros.
