# Plan general de implementación: qué quedó afuera y qué cambió

Bloque 6 de `PLAN_IMPLEMENTACION.md` (decisión I9). El documento nuevo es
`docs/implementacion/plan-general.html` (copia publicada:
`recursos/colm3na-plan-general-implementacion.html`, 12 hojas A4). Regla del
dueño: ante la duda o contradicción vale el documento más nuevo. Orden de las
fuentes, de la más nueva a la más vieja: Documento integrador, cap. 8 (13 nov
2026) > plan de La Bancaria v0.2 y guía de la reunión (11 oct 2026) > Plan
Maestro (6-7 sep 2026) > «Implementación en el sindicato» (4 sep 2026).

## 1. De «Implementación en el sindicato» (4 sep 2026)

**Quedó afuera**
- Las cinco etapas y la preparación numeradas S0 a S13: las reemplazan las seis
  fases del plan v0.2 (más nuevo).
- Los 66 ítems del checklist y los formularios F1 a F10 con su guardado en el
  navegador: los reemplaza la Mesa de implementación (tarjetas, carpetas de
  entrada y salida, aprobaciones). Los formularios por tema siguen siendo el kit
  de relevamiento de la fase 0, pero se responden y se archivan en la Mesa.
- Todo el bloque del bot conversacional (contrato de integración, JWT, niveles 1
  y 2, hitos S1 a S12, formulario F9): el bot lo desarrolla un tercero y no es
  parte de Colm3na hoy; no se presenta como existente. Lo que existe son las
  «Consultas sobre el convenio» (módulo opt-in, en piloto), que el plan nuevo
  lista como «Después».
- La «oleada 2» con Trámites y Empleadores y la «oleada 3» con el bot: el plan
  v0.2 (más nuevo) pone Trámites, Beneficios y Encuestas en el piloto y deja solo
  Empleadores y Consultas sobre el convenio para después.
- «Soporte Mi Trabajo» como trámite interno del sistema: las consultas y errores
  de la implementación van como tarjetas de la Mesa.
- El anexo interno (cuentas, entornos, costos) y la mención de «Mi Trabajo» como
  nombre del producto: la plataforma se llama Colm3na.
- Pestaña Bot, tiempos de soporte con números («críticas en 1 día hábil») y la
  lista larga de indicadores con metas de cierre en S13 (adopción ≥ 40 %, uso
  ≥ 1 recibo por mes, conceptos ≥ 90 %, etc.): el plan v0.2 trae seis
  indicadores de piloto y el integrador dice que las metas se acuerdan con cada
  sindicato.

**Cambió**
- Duración: de 13 semanas cerradas a «semanas de referencia» (el integrador dice
  que fechas, tamaño del piloto y metas se acuerdan con el sindicato). Se conserva
  el calendario del v0.2 solo como referencia (entorno de prueba en la semana 4,
  piloto de la 7 a la 12, implementación total desde la 13).
- Grupo piloto: de 30 a 50 trabajadores en dos seccionales a «un grupo chico que
  se amplía» (el v0.2 habla de unos 50 y hasta 500 o 1.000; el tamaño lo define
  cada sindicato).
- Primer contacto con el sindicato: del «kick-off» de la semana 1 a una reunión
  estratégica con autoridades en la semana 0 (guía de reunión v0.2, Anexo A) y un
  lanzamiento en la semana 1.
- Gobernanza y ritmo (semanal de 45 minutos, demostración quincenal, tres tipos de
  pedido de cambio, decisiones con fecha y quién decidió) se conservan casi igual;
  el registro de decisiones pasa a ser tarjetas de tipo Aprobación y Aviso.

## 2. Del Plan Maestro (6-7 sep 2026)

Es un documento interno de dirección de empresa. Quedó afuera casi todo, por
empresario o por desactualizado:
- Todo lo societario y económico: las dos empresas, quién firma el contrato,
  la cuota del SaaS, el plazo de 24 meses, la cota de recibos por mes, el reparto,
  las horas de cada persona, la facturación, las adendas con precio y los
  controles económicos. **Sin costos ni decisiones empresarias** (regla I9).
- Los nombres de las personas y su matriz de responsabilidades por persona: queda
  solo la matriz por rol del integrador (8.3).
- Los once hitos con fechas calendario (14 sep a 11 dic 2026): caducos, y el plan
  nuevo no fija fechas.
- El traspaso del desarrollo, el crecimiento del equipo y la titularidad de las
  cuentas técnicas (GitHub, Render, Claude, dominio, marca): interno, tiene su
  propio instructivo de montaje.
- Horas externas, revisión de seguridad externa como hito, tareas semana a semana.

**Se rescató:** el principio de gradualidad (ninguna puerta de fase exige tener
todas las definiciones a una fecha; entregables y pruebas son graduales y
consensuados) y la idea de puertas de fase con aceptación del sindicato.

## 3. Del plan v0.2 de La Bancaria y la guía de reunión (11 oct 2026)

Es la base del documento nuevo. Se generalizó: «La Bancaria» pasa a «el
sindicato», «CCT 18/75» a «el convenio», «bancos» a «empleadores». No se copió:
- Las fechas y la nota de calendario de noviembre y diciembre: quedó como una
  frase genérica sobre aguinaldo y receso.
- La lista de qué se implementa quedó igual salvo dos cambios: Consultas sobre el
  convenio pasó de «Piloto» a «Después» (es módulo opt-in en piloto y el
  integrador no la cuenta entre lo que se prepara para el piloto), y «Avisos y trámites con los empleadores» sigue en «Después».
- La guía de reunión se incorporó entera como Anexo A (orden del día, qué se busca
  acordar, tabla de funcionalidades, qué hace cada parte después). La tabla de
  «datos disponibles» se unificó con la de datos para el alta de la hoja 9.

**Se agregó** (no estaba en v0.2): la Mesa de implementación como herramienta de
seguimiento (hoja 8); el alta del sindicato con clave inicial transitoria y primer
ingreso obligatorio; la cláusula de confidencialidad; los cuatro niveles de
verificación de identidad; el orden de configuración de la fase 3 y el cuidado
por configuración mal cargada (integrador 8.4); la columna «Qué se entrega» por
fase.

## 4. Del Documento integrador, cap. 8 (13 nov 2026)

Es la fuente que más pesa. Sus puntos vigentes se respetaron: sin precios ni
costos; fechas y metas «se acuerdan con el sindicato»; La Bancaria «en preparación». No se copió el estado de seguridad ni
las capturas, que son del integrador.

## 5. Las cinco diferencias más importantes

1. Hay un solo plan genérico de seis fases; las cinco etapas de septiembre y los
   hitos con fecha del Plan Maestro desaparecen.
2. El seguimiento ya no es un checklist en el navegador con 66 tareas y
   formularios F1 a F10: es la Mesa de implementación, con aprobaciones
   registradas y carpetas.
3. El bot conversacional sale completo (no existe como parte de Colm3na).
4. Todo lo económico, societario, de cuentas técnicas y de personas del Plan
   Maestro queda fuera.
5. Las semanas son orientativas y el tamaño del piloto lo define cada sindicato.

## 6. Dudas que no se resolvieron con la regla del más nuevo

- **Semanas de referencia.** El v0.2 (20 semanas con implementación total desde
  la 13) y el integrador («unas 13 semanas», sin fechas fijas) no coinciden. Se
  usó el calendario del v0.2, marcado como referencia. A confirmar con el dueño.
- **Metas de los indicadores.** El v0.2 trae números (70 %, 50 %, 90 %, 80 %,
  50 %) y el integrador dice que se acuerdan. Se mantuvieron los del v0.2 como
  «punto de partida» en una columna aparte.
- **La Mesa como existente.** `PLAN_IMPLEMENTACION.md` la define pero se construye
  en otros bloques. El documento la nombra como la herramienta de seguimiento, tal
  como se pidió; si sale a un sindicato antes de que esté desplegada hay que
  revisar las hojas 1, 4 a 8 y 12 (a «verificar contra Pruebas»).
- **Canal de mail.** La Mesa avisa por mail; hoy el canal está configurado en
  Pruebas pero migrando a cuentas corporativas, y el captcha falta. El documento
  no promete avisos con fecha.
- **Piloto de Consultas sobre el convenio.** Se dejó en «Después» por prudencia;
  si el sindicato lo quiere en el piloto, es una decisión del plan v1.

## Hitos propuestos

Para el plan operativo de La Bancaria en la Mesa (decisión I7: de 5 a 8 hitos por
fase, redactados de nuevo). Salen de las tareas vigentes del checklist viejo y
del plan v0.2. No se incluyen las de bot, cuentas, costos ni la preparación
interna de entornos que ya está hecha. Marca: **[T]** también puede ser una tarjeta
inicial.

### Fase 0 · Preparar
1. Reunión estratégica con las autoridades realizada y acta cargada **[T]**.
2. Plan v1 enviado con lo acordado en la reunión.
3. Espacio de La Bancaria en Pruebas con su marca, sus conceptos del CCT 18/75 y recibos de ejemplo (ya preparado: verificar y mostrar).
4. Kit de relevamiento enviado (formularios por tema, lista de documentos, modelo de planilla del padrón).
5. Borrador del acuerdo de tratamiento de datos enviado a la asesoría legal.
6. Proyecto abierto en la Mesa y usuarios del sindicato dados de alta.
7. Autoridad responsable y referente operativo nombrados.
8. Fecha del lanzamiento y convocados fijados.

### Fase 1 · Acordar
1. Lanzamiento con secretarías, sistemas, prensa y seccionales realizado.
2. Todos los referentes nombrados (técnico, convenio y liquidación, comunicación, legal, seccionales).
3. Día fijo de la reunión semanal y de la demostración quincenal.
4. Funcionalidades del piloto y de «después» acordadas.
5. Piloto definido: seccionales, empleadores, cantidad y perfil de afiliados.
6. Canal seguro y fechas de entrega del padrón acordados.
7. Forma de verificación de identidad del afiliado decidida.
8. Plan v1 aprobado por el sindicato (tarjeta de Aprobación).

### Fase 2 · Relevar
1. Taller de padrón y alta de afiliados hecho.
2. Taller de trámites y comunicación hecho, con los formularios actuales recibidos.
3. Taller de estructura hecho: seccionales con domicilio, áreas y operadores.
4. Taller de convenio y liquidación hecho: conceptos, escalas y acuerdos vigentes.
5. Lista de empleadores con CUIT recibida.
6. De 30 a 60 recibos de muestra de distintos bancos recibidos (consentimiento o anonimizados).
7. Padrón recibido y revisado, con las filas con error informadas.
8. Acuerdo de tratamiento de datos firmado.

### Fase 3 · Configurar
1. Alta del sindicato con logo, colores y módulos; primer administrador con su clave elegida.
2. Seccionales ubicadas en el mapa, áreas y usuarios con permisos cargados.
3. Padrón y listas cargados y conciliados contra los totales del sindicato.
4. Catálogo de conceptos y reglas de control con su fuente aprobado por el sindicato.
5. Escalas con vigencia cargadas, y responsable de actualizarlas en cada paritaria.
6. Al menos 20 recibos reales de 4 bancos con resultado correcto revisado a mano.
7. Primeros dos o tres trámites armados con el Asistente, publicados y probados.
8. Semana 4: el sindicato recorrió el entorno con sus datos; operadores capacitados y aceptación firmada (tarjeta de Aprobación).

### Fase 4 · Piloto
1. Configuración aceptada pasada al entorno definitivo.
2. Grupo piloto elegido (variedad de bancos) y delegados que acompañan el primer ingreso.
3. Presentación del piloto y capacitación a las seccionales piloto.
4. Primer grupo de unos 50 afiliados con acceso.
5. Mesa de ayuda del piloto y revisión semanal de recibos dudosos y conceptos nuevos en marcha.
6. Ampliación a más afiliados tras el primer grupo (500 o 1.000, a definir).
7. Dos cierres de mes cubiertos.
8. Informe de resultados presentado a las autoridades y decisión de seguir (tarjeta de Aprobación).

### Fase 5 · Implementación total
1. Orden de las oleadas de seccionales y comunicación institucional acordados.
2. Primera oleada invitada, con capacitación previa.
3. Segunda y tercera oleadas invitadas.
4. Funcionalidades que quedaron para después sumadas según prioridad.
5. Mesa de ayuda en dos niveles funcionando.
6. Primer informe mensual de indicadores presentado.
7. Guías finales y respaldo de la configuración entregados.
8. Acta de cierre y acuerdo de soporte y evolución firmados (tarjetas de Aprobación).
