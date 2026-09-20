# XSANDERS Security Kit (XSK) — El método

Este archivo es **genérico**: no menciona ningún sistema en particular. Es lo
que se extrae cuando XSK pasa a repositorio propio. Lo específico de cada
sistema evaluado vive en `proyectos/<nombre>/`.

XSK es un método para llevar un sistema a un estado de seguridad
**verificado** antes de exponerlo a usuarios reales, y para mantenerlo ahí. Se
ejecuta con un agente de código (Claude Code) como brazo: revisa el código,
corre análisis estático, ataca el entorno de prueba, configura el perímetro y
lleva el registro. La persona decide alcance, acepta riesgos y aprueba
correcciones.

## Principios

1. **Todo test se conecta a un activo.** Se testea lo que el modelo de
   amenazas dice que está en juego, no lo que una lista genérica trae. Un
   test que no protege ningún activo del sistema no entra al alcance.
2. **Hechos, no derivados.** El registro guarda probabilidad, daño y
   complejidad; el riesgo y el ranking se calculan al mostrarlos. Cambiar la
   escala no reescribe la historia.
3. **Nada se borra.** Un hallazgo cambia de estado; nunca desaparece. Un
   riesgo aceptado se acepta con motivo y firma.
4. **Cada corrección deja un test.** Si no hay test de regresión, la
   corrección no está cerrada.
5. **Lo que no se puede probar no se afirma.** Resistir un DDoS real no se
   prueba desde una máquina: se delega al perímetro y se verifica que el
   perímetro esté configurado. El informe dice eso, no "resiste DDoS".
6. **El kit no es un arma cargada.** Credenciales y tokens en variables de
   entorno, nunca en el registro. Los hallazgos abiertos se tratan como
   confidenciales.
7. **Estándares desde el día uno.** Cada test y cada hallazgo referencian
   OWASP Top 10 (2021), ASVS 4.0 y CWE. Agregarlo después es el trabajo que
   nadie hace.

## Las diez etapas

### Etapa 0 — Configuración
Qué necesita el método para correr sobre este sistema: URLs de los entornos
de prueba, cuentas de cada rol para atacar, acceso a la infraestructura
(API del hosting, DNS, perímetro), acceso al repositorio y a la
observabilidad. Sale `configuracion.md` con **qué se necesita, qué se tiene,
qué falta y dónde vive cada cosa** (los valores sensibles, en `.env`; el
archivo solo nombra la variable).

### Etapa 1 — Relevamiento
Qué es el sistema, para quién, qué datos maneja, quién lo opera, qué
regulación lo alcanza. Se hace **preguntando a la persona, de a una**, y
leyendo la documentación del proyecto. Sale `relevamiento.md` con la lista
de **activos** (qué vale la pena robar, alterar o tirar abajo) y de
**actores** (roles legítimos y atacantes plausibles).

### Etapa 2 — Mapeo y modelo de amenazas
La superficie técnica **generada desde el código**, no de memoria: rutas y
métodos, qué autenticación exige cada una, cookies, archivos que se suben y
cómo se sirven, llamadas a servicios externos, secretos que el sistema lee,
dependencias, dónde corre. Sale `mapa.md`. Sobre eso, el modelo de amenazas
(STRIDE por componente o por activo): para cada activo, quién lo querría,
por dónde entraría y qué pasaría. Sale `amenazas.md`.

### Etapa 3 — Alcance
Qué ejes entran en **esta iteración** y por qué (lo que bloquea salir a
producción primero). El alcance es por ejes, no por tests sueltos. Sale
`alcance.md` con la iteración numerada.

### Etapa 4 — Herramientas
Para cada test del catálogo, con qué se corre: skill de revisión de código,
análisis estático (dependencias, secretos, patrones), test dinámico contra el
entorno, verificación de configuración por API, o revisión manual. Se anota
en el propio test del catálogo. Las herramientas se instalan y se prueban
antes de empezar la batería.

### Etapa 5 — Ejecución
La batería se corre **por eje y en pasos**. Cada corrida deja un archivo en
`corridas/` con fecha, eje, entorno, y por test: pasó / falló / no aplica /
error, con la evidencia. Un test que falla abre un hallazgo (o reabre uno).

### Etapa 6 — Registro
Un archivo por hallazgo (`hallazgos/H-NNNN.md`): qué se encontró, cómo se
reproduce, qué activo compromete, qué estándar lo describe, qué se sugiere.
Numeración correlativa, nunca se reutiliza un número.

### Etapa 7 — Clasificación
Ver "Escala de riesgo". Se clasifica **cada hallazgo, por separado, con la
persona**: la probabilidad y el daño son un juicio sobre este sistema, no un
número que sale de una tabla.

### Etapa 8 — Corrección
Por orden del ranking. Una rama por hallazgo (`fix/xsk-H-NNNN`), con su test
de regresión en la suite del proyecto. El hallazgo pasa a `corregido` al
mergear y a `verificado` cuando la re-ejecución del test original pasa.
Lo que no se corrige se **acepta** explícitamente (motivo, quién, hasta
cuándo) o queda `abierto` con dueño.

### Etapa 9 — Registro continuo
Una página del sistema evaluado muestra: etapa actual, avance por eje,
ranking de expuestos no corregidos, historial de corridas, y **cómo seguir**.
Todo sale de los archivos de `proyectos/<nombre>/`. Al cerrar cada iteración
se propone la siguiente.

## Escala de riesgo

Simplificación del OWASP Risk Rating. Dos juicios de 1 a 5:

| Valor | Probabilidad (que ocurra) | Daño (si ocurre) |
|---|---|---|
| 1 | Requiere acceso privilegiado y conocimiento interno | Molestia, sin datos ni servicio afectados |
| 2 | Requiere condiciones poco comunes | Un usuario afectado, reversible |
| 3 | Un atacante motivado con herramientas comunes lo logra | Varios usuarios o un cliente afectados, reversible |
| 4 | Se puede automatizar; hay herramientas públicas | Datos sensibles expuestos o servicio caído; daño reputacional |
| 5 | Ocurre solo, o cualquiera lo hace sin esfuerzo | Datos sensibles masivos, daño legal, pérdida de clientes |

**Riesgo = probabilidad × daño** (1 a 25):

| Riesgo | Nivel | Regla |
|---|---|---|
| 15–25 | **Crítico** | Bloquea producción. Se corrige antes que cualquier otra cosa. |
| 10–14 | **Alto** | Bloquea producción. |
| 5–9 | **Medio** | Puede salir con dueño y fecha asignados. |
| 1–4 | **Bajo** | Se registra; se corrige cuando conviene o se acepta. |

**Complejidad de corrección** (1 = un cambio de configuración; 5 = rediseño)
es el segundo criterio del ranking: a igual riesgo, primero lo más fácil.

**Ranking** = hallazgos no cerrados (`abierto`, `en_correccion`), ordenados
por riesgo descendente y complejidad ascendente.

## Estados de un hallazgo

`abierto` → `en_correccion` → `corregido` → `verificado`, o `abierto` →
`aceptado`. Un `verificado` que vuelve a fallar en una corrida vuelve a
`abierto` (y el archivo lo anota: la historia importa).

## Criterio de salida a producción

- Ningún hallazgo Crítico ni Alto en `abierto` o `en_correccion`.
- Todo Medio con dueño y fecha en el archivo.
- Todo `aceptado` con motivo, quién y vencimiento de la aceptación.
- La última corrida completa de los ejes del alcance no tiene tests en
  `error` (un test que no pudo correr no es un test que pasó).
- El perímetro y la observabilidad verificados en el **mismo entorno** que
  sale a producción, no en uno parecido.

## Formato de los archivos

Todo es Markdown con una cabecera de líneas `clave: valor` entre `---`
(sin YAML real: no hace falta una dependencia para leer esto). Las claves de
cada tipo de archivo están en la plantilla correspondiente:
`catalogo/_plantilla.md`, `proyectos/<nombre>/hallazgos/_plantilla.md`,
`proyectos/<nombre>/corridas/_plantilla.md`. El motor (`motor/`) las lee y
falla nombrando la clave que falta.
